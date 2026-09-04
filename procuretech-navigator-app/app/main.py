"""procureTech Navigator マイクロサービス（Open GENAI exApp / 専用ページ向け）。

情報化企画書（Excel）を1冊アップロードし、4分野（項番1〜4）ごとにチャットで議論し、
書き戻しボタンで対応セルへ書き戻して更新版をダウンロードする。

- 庁内: backend が JWT 検証後、HMAC 署名付きで /sessions 等へプロキシする。
- Compose では profiles: ["procuretech"] でオプション起動する。
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from . import excel, intauth, llm, sections, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
RETENTION_DAYS = int(os.environ.get("PROCURETECH_RETENTION_DAYS", "30"))
MAX_UPLOAD_BYTES = int(os.environ.get("PROCURETECH_MAX_UPLOAD_BYTES", "10485760"))

app = FastAPI(title="Open GENAI ProcureTech Navigator App", version="0.1.0")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _verify_internal(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> tuple[JSONResponse | None, str]:
    err = _check_key(x_api_key)
    if err:
        return err, ""
    if not intauth.verify(
        x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    ):
        return (
            JSONResponse(status_code=401, content={"error": "invalid internal signature"}),
            "",
        )
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), ""
    return None, x_user_id


def _cleanup_loop() -> None:
    while True:
        try:
            store.delete_old_sessions(RETENTION_DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"[procuretech] cleanup error: {e}")
        time.sleep(3600)


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()
    try:
        n = store.delete_old_sessions(RETENTION_DAYS)
        if n:
            print(f"[procuretech] startup cleanup: deleted {n} old sessions")
    except Exception as e:  # noqa: BLE001
        print(f"[procuretech] startup cleanup error: {e}")
    t = threading.Thread(target=_cleanup_loop, name="procuretech-cleanup", daemon=True)
    t.start()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def get_config(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(
        content={
            "enabled": True,
            "sections": sections.public_sections(),
            "retention_days": RETENTION_DAYS,
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "marker_value": excel.SHEET_MARKER_VALUE,
            "llm": {"model": llm.PROCURETECH_MODEL, "base_url": llm.OPENAI_BASE_URL},
        }
    )


def _section_view(
    section: sections.Section,
    current_cells: dict[str, str],
    messages_by_section: dict[str, list[dict[str, str]]],
    outputs: dict[str, dict[str, str]],
) -> dict[str, Any]:
    out = outputs.get(section.key)
    return {
        "key": section.key,
        "title": section.title,
        "item_no": section.item_no,
        "write_cell": section.write_cell,
        "description": section.description,
        "chat_placeholder": section.chat_placeholder,
        "cell_value": current_cells.get(section.write_cell, ""),
        "messages": messages_by_section.get(section.key, []),
        "output": out["content"] if out else None,
        "finalized": out is not None,
        "finalized_at": out["updated_at"] if out else None,
    }


def _session_detail(row: Any) -> dict[str, Any]:
    session_id = row["id"]
    raw = bytes(row["current_blob"])
    try:
        current_cells = excel.read_cells(raw)
    except excel.ExcelError:
        current_cells = {c: "" for c in excel.CONTENT_CELLS}
    messages_by_section = store.get_all_messages(session_id)
    outputs = store.get_outputs(session_id)
    return {
        "id": session_id,
        "filename": row["filename"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "sections": [
            _section_view(s, current_cells, messages_by_section, outputs)
            for s in sections.SECTIONS
        ],
    }


@app.get("/sessions")
def list_sessions(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(content={"sessions": store.list_sessions(uid)})


@app.post("/sessions")
async def create_session(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    filename = (body.get("filename") or "").strip() or "systemplan.xlsx"
    if not filename.lower().endswith(".xlsx"):
        return JSONResponse(
            status_code=400,
            content={"error": "情報化企画書は .xlsx 形式でアップロードしてください。"},
        )
    content = body.get("content") or body.get("data") or ""
    try:
        raw = excel.decode_upload(str(content), max_bytes=MAX_UPLOAD_BYTES)
        excel.validate_and_read(raw)
    except excel.ExcelError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    meta = store.create_session(user_id=uid, filename=filename, raw=raw)
    row = store.get_session_row(meta["id"], uid)
    print(f"[procuretech] session created id={meta['id']} by={uid}")
    return JSONResponse(status_code=201, content=_session_detail(row))


@app.get("/sessions/{session_id}")
def get_session(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    row = store.get_session_row(session_id, uid)
    if not row:
        return JSONResponse(status_code=404, content={"error": "セッションが見つかりません"})
    return JSONResponse(content=_session_detail(row))


@app.delete("/sessions/{session_id}")
def delete_session(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not store.delete_session(session_id, uid):
        return JSONResponse(status_code=404, content={"error": "セッションが見つかりません"})
    print(f"[procuretech] session deleted id={session_id} by={uid}")
    return JSONResponse(content={"message": "セッションを削除しました"})


@app.post("/sessions/{session_id}/sections/{section_key}/clear")
def clear_section(
    session_id: str,
    section_key: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if sections.get_section(section_key) is None:
        return JSONResponse(status_code=404, content={"error": "分野が見つかりません"})
    row = store.get_session_row(session_id, uid)
    if not row:
        return JSONResponse(status_code=404, content={"error": "セッションが見つかりません"})
    store.clear_section(session_id, section_key)
    row = store.get_session_row(session_id, uid)
    return JSONResponse(content=_session_detail(row))


async def _call_llm(messages: list[dict[str, str]]) -> tuple[str | None, JSONResponse | None]:
    try:
        reply = await llm.chat(messages)
    except httpx.HTTPError as e:
        return None, JSONResponse(
            status_code=502,
            content={"error": f"LLM サービスに接続できませんでした: {e}"},
        )
    except ValueError as e:
        return None, JSONResponse(status_code=502, content={"error": str(e)})
    return reply, None


def _ndjson_line(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


async def _run_chat_turn_stream(
    *,
    session_id: str,
    uid: str,
    section: sections.Section,
    user_message: str,
) -> Response:
    """通常のチャット1ターンを NDJSON でストリーミング返却する。

    事前検証（セッション有無・Excel 読取）は同期的に行い、失敗時は通常の JSON エラーを返す。
    ストリーム完了後にユーザー発話とアシスタント応答を履歴へ保存する（書き戻しは行わない）。
    """
    row = store.get_session_row(session_id, uid)
    if not row:
        return JSONResponse(status_code=404, content={"error": "セッションが見つかりません"})
    raw = bytes(row["current_blob"])
    try:
        current_cells = excel.read_cells(raw)
    except excel.ExcelError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    history = store.get_messages(session_id, section.key)
    messages = sections.build_llm_messages(
        section, current_cells, history, extra_user=user_message
    )

    async def _gen():
        parts: list[str] = []
        try:
            async for piece in llm.chat_stream(messages):
                parts.append(piece)
                yield _ndjson_line({"event": "delta", "text": piece})
        except httpx.HTTPError as e:
            yield _ndjson_line(
                {"event": "error", "error": f"LLM サービスに接続できませんでした: {e}"}
            )
            return
        except ValueError as e:
            yield _ndjson_line({"event": "error", "error": str(e)})
            return

        reply = "".join(parts).strip()
        if not reply:
            yield _ndjson_line({"event": "error", "error": "モデルの応答本文が空です"})
            return

        store.append_message(session_id, section.key, "user", user_message)
        store.append_message(session_id, section.key, "assistant", reply)
        row2 = store.get_session_row(session_id, uid)
        yield _ndjson_line(
            {
                "event": "done",
                "reply": reply,
                "finalized": False,
                "section": _next_section_view(row2, section.key),
            }
        )

    return StreamingResponse(_gen(), media_type="application/x-ndjson")


async def _run_finalize(
    *,
    session_id: str,
    uid: str,
    section: sections.Section,
) -> JSONResponse:
    """書き戻しボタン用。項番専用の整形指示で生成し、対応セルへ書き戻す。

    トリガーワードは使わない。整形指示も生成結果も会話履歴には残さず、成果物（output）と
    更新版ブックだけを保存する。
    """
    row = store.get_session_row(session_id, uid)
    if not row:
        return JSONResponse(status_code=404, content={"error": "セッションが見つかりません"})
    raw = bytes(row["current_blob"])
    try:
        current_cells = excel.read_cells(raw)
    except excel.ExcelError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})

    history = store.get_messages(session_id, section.key)
    if not history:
        return JSONResponse(
            status_code=400,
            content={"error": "書き戻す前に、この項番でAIと対話して内容を整理してください。"},
        )
    messages = sections.build_llm_messages(
        section, current_cells, history, extra_user=section.finalize_prompt
    )
    reply, err = await _call_llm(messages)
    if err:
        return err

    try:
        new_blob = excel.write_cell(raw, section.write_cell, reply or "")
    except excel.ExcelError as e:
        return JSONResponse(status_code=500, content={"error": str(e)})
    store.save_output(session_id, section.key, reply or "", new_blob)
    print(
        f"[procuretech] finalized session={session_id} section={section.key} "
        f"cell={section.write_cell} by={uid}"
    )

    row = store.get_session_row(session_id, uid)
    return JSONResponse(
        content={
            "reply": reply,
            "finalized": True,
            "section": _next_section_view(row, section.key),
        }
    )


def _next_section_view(row: Any, section_key: str) -> dict[str, Any]:
    detail = _session_detail(row)
    for s in detail["sections"]:
        if s["key"] == section_key:
            return s
    return {}


@app.post("/sessions/{session_id}/chat")
async def chat_turn(
    session_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Response:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    section_key = (body.get("section") or "").strip()
    message = (body.get("message") or "").strip()
    section = sections.get_section(section_key)
    if section is None:
        return JSONResponse(status_code=400, content={"error": "分野の指定が不正です"})
    if not message:
        return JSONResponse(status_code=400, content={"error": "メッセージを入力してください"})
    # トリガーワードは廃止。チャットからの自動書き出しは行わず、書き戻しは /finalize のみ。
    return await _run_chat_turn_stream(
        session_id=session_id,
        uid=uid,
        section=section,
        user_message=message,
    )


@app.post("/sessions/{session_id}/finalize")
async def finalize_turn(
    session_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """書き戻しボタン用。指定項番の議論を整形し、対応セルへ書き戻す（トリガーワード不使用）。"""
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    section_key = (body.get("section") or "").strip()
    section = sections.get_section(section_key)
    if section is None:
        return JSONResponse(status_code=400, content={"error": "分野の指定が不正です"})
    return await _run_finalize(
        session_id=session_id,
        uid=uid,
        section=section,
    )


@app.get("/sessions/{session_id}/download")
def download_session(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """更新済み xlsx を base64 で返す（backend が中継し、フロントで復号 DL）。"""
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    result = store.get_current_blob(session_id, uid)
    if result is None:
        return JSONResponse(status_code=404, content={"error": "セッションが見つかりません"})
    import base64
    from datetime import datetime

    raw, _filename = result
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    out_name = f"systemplan_{stamp}.xlsx"
    return JSONResponse(
        content={
            "filename": out_name,
            "mime_type": excel.XLSX_MIME,
            "content": base64.b64encode(raw).decode("ascii"),
            "size": len(raw),
        }
    )
