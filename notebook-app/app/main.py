"""ノートブック。資料を構造化して項目・対話・ヒアリングシートにする。"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import extract, ground, harness, hermes_mcp, intauth, llm, mcp_catalog, mcp_knowledge, ocr, pii_warn, retrieve, store, structure, tools
from .agent_session import HermesUnavailable, PoolFull, SessionKey, pool as agent_pool

for parent in Path(__file__).resolve().parents:
    if (parent / "shared" / "navsheet.py").exists():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break
from shared.navsheet import NavRow, NavSheet, empty_workbook, write_workbook  # noqa: E402

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
RETENTION_DAYS = int(os.environ.get("HEARING_RETENTION_DAYS", "30"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_DOC_BYTES", str(100 * 1024 * 1024)))

app = FastAPI(title="Open GENAI Notebook", version="0.2.0")


def _hearing_xlsx_name(title: str) -> tuple[str, str]:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    safe = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", (title or "").strip()) or "無題"
    safe = safe.strip(" .")[:80]
    name = f"ヒアリングシート_{safe}_{stamp}.xlsx"
    ascii_name = f"hearing-sheet_{stamp}.xlsx"
    return name, ascii_name


def _xlsx_disposition(name: str, ascii_name: str) -> str:
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(name)}'


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _verify(
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


def _auth(request: Request) -> tuple[JSONResponse | None, str]:
    return _verify(
        request.headers.get("x-api-key"),
        request.headers.get("x-user-id"),
        request.headers.get("x-user-groups"),
        request.headers.get("x-scope"),
        request.headers.get("x-user-ts"),
        request.headers.get("x-user-sig"),
        request.headers.get("x-user-tags"),
    )


def _b64_bytes(value: Any) -> bytes:
    raw = str(value or "")
    if raw.startswith("data:") and "," in raw:
        raw = raw.split(",", 1)[1]
    return base64.b64decode(raw)


def _cleanup_loop() -> None:
    while True:
        try:
            store.delete_old_sessions(RETENTION_DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"[hearing] cleanup error: {e}")
        time.sleep(3600)


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()
    # 再起動で消えた読み取りタスクは、画面に残さない。
    store.fail_interrupted_ingests()
    t = threading.Thread(target=_cleanup_loop, name="hearing-cleanup", daemon=True)
    t.start()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def get_config(request: Request) -> JSONResponse:
    err, _uid = _auth(request)
    if err:
        return err
    return JSONResponse(
        content={
            "enabled": True,
            "accept": list(extract.accept_exts()),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "retention_days": RETENTION_DAYS,
            "llm": {
                "enabled": llm.LLM_ENABLED,
                "model": llm.PROCURETECH_MODEL,
                "base_url": llm.OPENAI_BASE_URL,
            },
            "ocr": ocr.status(),
            "tools": list(tools.ALL_TOOL_NAMES),
            "mcp": {
                "knowledge": {
                    "enabled": mcp_knowledge.enabled(),
                    "shared": True,
                    "tools": [
                        "knowledge_list_tags",
                        "knowledge_list_docs",
                        "knowledge_search",
                    ],
                },
                "catalog": [
                    {
                        "catalog_id": spec["catalog_id"],
                        "name": spec["name"],
                        "description": spec["description"],
                    }
                    for spec in mcp_catalog.CATALOG
                ],
            },
        }
    )


@app.get("/template")
def template(request: Request) -> Response:
    err, _uid = _auth(request)
    if err:
        return err
    return Response(
        content=empty_workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="hearing-sheet.xlsx"'},
    )


@app.get("/sessions")
def list_sessions(request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    return JSONResponse(content={"sessions": store.list_sessions(uid)})


@app.post("/sessions")
async def create_session(request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return JSONResponse(content=store.create_session(user_id=uid, title=str(body.get("title") or "")))


@app.get("/sessions/{session_id}")
def get_session(session_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    detail = store.get_session(session_id, uid)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.put("/sessions/{session_id}")
async def put_session(session_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    mcp_enabled: dict[str, bool] | None = None
    raw_mcps = body.get("mcps") if "mcps" in body else body.get("mcp_enabled")
    if isinstance(raw_mcps, dict):
        mcp_enabled = {str(k): bool(v) for k, v in raw_mcps.items()}
    elif isinstance(raw_mcps, list):
        mcp_enabled = {}
        for item in raw_mcps:
            if isinstance(item, dict) and item.get("id"):
                mcp_enabled[str(item["id"])] = bool(item.get("enabled", True))
    detail = store.update_session(
        session_id,
        uid,
        title=body.get("title") if "title" in body else None,
        instruction=body.get("instruction") if "instruction" in body else None,
        editor_project_id=body.get("editor_project_id")
        if "editor_project_id" in body
        else None,
        mcp_enabled=mcp_enabled,
    )
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    if not store.delete_session(session_id, uid):
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content={"ok": True})


@app.post("/sessions/{session_id}/items")
async def add_item(session_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    detail = store.add_item(session_id, uid, label=str(body.get("label") or ""))
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.patch("/sessions/{session_id}/items/{item_id}")
async def patch_item(session_id: str, item_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    cites = body.get("citations") if "citations" in body else None
    if cites is not None and not isinstance(cites, list):
        cites = []
    detail = store.update_item(
        session_id,
        uid,
        item_id,
        label=body.get("label") if "label" in body else None,
        value=body.get("value") if "value" in body else None,
        citations=cites,
    )
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.delete("/sessions/{session_id}/items/{item_id}")
def remove_item(session_id: str, item_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    detail = store.delete_item(session_id, uid, item_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.post("/sessions/{session_id}/files")
async def add_file(session_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    filename = str(body.get("filename") or "file")
    try:
        raw = _b64_bytes(body.get("content") or "")
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": "ファイルの復号に失敗しました"})
    if len(raw) > MAX_UPLOAD_BYTES:
        limit_mb = MAX_UPLOAD_BYTES // (1024 * 1024)
        return JSONResponse(
            status_code=400,
            content={"error": f"ファイルが大きすぎます。{limit_mb}MB までにしてください。"},
        )
    if not extract.allowed_name(filename):
        return JSONResponse(
            status_code=400,
            content={"error": f"未対応の形式です: {filename}"},
        )
    tenant_id = request.headers.get("x-tenant-id")
    file_id = str(uuid.uuid4())
    # 本文抽出は待たない。参考資料の件数は、読み取りが終わってから増える。
    detail = store.add_file(
        session_id,
        uid,
        filename=filename,
        raw=raw,
        error="",
        nodes=[],
        briefing={"ingest": "processing"},
        file_id=file_id,
    )
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    asyncio.create_task(_ingest_file(session_id, uid, file_id, filename, raw, tenant_id))
    return JSONResponse(content=detail)


async def _build_file_briefing(
    filename: str, pages: list[dict], tenant_id: str | None
) -> tuple[list[dict], dict]:
    """ページ本文から nodes と briefing（要約・個人情報注記つき）を作る。"""
    nodes = structure.build_nodes(pages)
    for n in nodes:
        n["source"] = filename
    briefing = structure.briefing_from_nodes(filename, nodes)
    if any(p.get("ocr") for p in pages):
        briefing["ocr"] = True
    sample = "\n".join(str(n.get("text") or "") for n in structure.sample_nodes(nodes, 6))
    briefing = await ground.enrich_briefing(filename, briefing, sample)
    briefing = pii_warn.annotate_briefing(briefing, nodes, tenant_id)
    return nodes, briefing


def _pages_have_text(pages: list[dict]) -> bool:
    return any(str(p.get("text") or "").strip() for p in pages)


async def _ingest_file(
    session_id: str,
    uid: str,
    file_id: str,
    filename: str,
    raw: bytes,
    tenant_id: str | None,
) -> None:
    """受け付けたファイルの本文抽出・OCR・要約を、応答のあとで行う。"""
    loop = asyncio.get_running_loop()
    try:
        base_pages, ocr_pending = await loop.run_in_executor(
            None, lambda: extract.extract_text_pages(filename, raw)
        )
    except extract.DocExtractError as e:
        store.update_file(session_id, uid, file_id, briefing={}, error=str(e))
        return
    except Exception as e:  # noqa: BLE001
        print(f"[notebook] 本文抽出に失敗: {e}")
        store.update_file(session_id, uid, file_id, briefing={}, error="読み取りに失敗しました")
        return

    pages = base_pages
    if ocr_pending:
        if not store.update_file(
            session_id,
            uid,
            file_id,
            briefing={"ingest": "processing", "ocr_pending": True},
            error="",
        ):
            return
        try:
            pages = await loop.run_in_executor(
                None, lambda: extract.run_ocr(filename, raw, base_pages)
            )
        except Exception as e:  # noqa: BLE001
            print(f"[notebook] OCR に失敗: {e}")
            if not _pages_have_text(base_pages):
                store.update_file(
                    session_id, uid, file_id, briefing={}, error="OCR に失敗しました"
                )
                return
            pages = base_pages

    if not _pages_have_text(pages):
        store.update_file(
            session_id,
            uid,
            file_id,
            briefing={},
            error=f"{filename} からテキストを抽出できませんでした",
        )
        return
    try:
        nodes, briefing = await _build_file_briefing(filename, pages, tenant_id)
    except Exception as e:  # noqa: BLE001
        print(f"[notebook] 要約に失敗: {e}")
        store.update_file(session_id, uid, file_id, briefing={}, error="読み取りに失敗しました")
        return
    store.update_file(session_id, uid, file_id, nodes=nodes, briefing=briefing, error="")


@app.delete("/sessions/{session_id}/files/{file_id}")
def remove_file(session_id: str, file_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    detail = store.delete_file(session_id, uid, file_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.post("/sessions/{session_id}/items/{item_id}/generate")
async def generate_item(session_id: str, item_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    if not llm.LLM_ENABLED:
        return JSONResponse(status_code=503, content={"error": "LLM が無効です"})
    detail = store.get_session(session_id, uid)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    item = next((i for i in detail["items"] if i["id"] == item_id), None)
    if not item:
        return JSONResponse(status_code=404, content={"error": "項目が見つかりません"})
    label = (item.get("label") or "").strip()
    if not label:
        return JSONResponse(status_code=400, content={"error": "項目名（設問）を入力してください"})
    try:
        answer, cites = await ground.answer_from_sources(
            session_id,
            uid,
            label,
            instruction=str(detail.get("instruction") or ""),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"error": f"生成に失敗しました: {e}"}
        )
    detail = store.update_item(
        session_id,
        uid,
        item_id,
        value=retrieve.strip_citation_marks(answer),
        citations=cites,
    )
    return JSONResponse(content=detail)


@app.post("/sessions/{session_id}/knowledge-refs")
async def add_knowledge_ref(session_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    nodes = body.get("nodes") or []
    if not isinstance(nodes, list) or not nodes:
        return JSONResponse(status_code=400, content={"error": "ノードがありません"})
    briefing = body.get("briefing") if isinstance(body.get("briefing"), dict) else {}
    detail = store.add_knowledge_ref(
        session_id,
        uid,
        scope=str(body.get("scope") or ""),
        doc_id=str(body.get("doc_id") or ""),
        source=str(body.get("source") or ""),
        title=str(body.get("title") or body.get("source") or ""),
        nodes=[n for n in nodes if isinstance(n, dict)],
        briefing=briefing,
    )
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.delete("/sessions/{session_id}/knowledge-refs/{ref_id}")
def remove_knowledge_ref(session_id: str, ref_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    detail = store.delete_knowledge_ref(session_id, uid, ref_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


@app.get("/skills")
def list_skills(request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    return JSONResponse(content={"skills": store.list_skills(uid), "tools": list(tools.ALL_TOOL_NAMES)})


@app.post("/skills")
async def create_skill(request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    names = body.get("tools")
    tool_names = [str(t) for t in names] if isinstance(names, list) else None
    skill = store.create_skill(
        uid,
        name=str(body.get("name") or ""),
        personality=str(body.get("personality") or ""),
        instructions=str(body.get("instructions") or ""),
        tool_names=tool_names,
    )
    return JSONResponse(content=skill)


@app.put("/skills/{skill_id}")
async def put_skill(skill_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    names = body.get("tools") if "tools" in body else None
    tool_names = [str(t) for t in names] if isinstance(names, list) else None
    skill = store.update_skill(
        skill_id,
        uid,
        name=str(body["name"]) if "name" in body else None,
        personality=str(body["personality"]) if "personality" in body else None,
        instructions=str(body["instructions"]) if "instructions" in body else None,
        tool_names=tool_names,
    )
    if not skill:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=skill)


@app.get("/mcps")
def list_mcps(request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    return JSONResponse(content={"mcps": store.list_mcps(uid)})


@app.post("/mcps")
async def create_mcp(request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    url = str(body.get("url") or "").strip()
    if not url:
        return JSONResponse(status_code=400, content={"error": "MCP の URL を入力してください"})
    if not url.startswith("http://") and not url.startswith("https://"):
        return JSONResponse(status_code=400, content={"error": "URL は http(s) で指定してください"})
    tools_found: list[dict[str, Any]] = []
    try:
        tools_found = await mcp_knowledge.list_tools(url)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=400,
            content={"error": f"MCP に接続できません: {e}"},
        )
    if not tools_found:
        return JSONResponse(
            status_code=400,
            content={"error": "この MCP からツール一覧を取得できませんでした"},
        )
    mcp = store.create_mcp(
        uid,
        name=str(body.get("name") or ""),
        url=url,
        prompt=str(body.get("prompt") or ""),
        description=str(body.get("description") or ""),
        tools=tools_found,
    )
    return JSONResponse(content=mcp)


@app.put("/mcps/{mcp_id}")
async def put_mcp(mcp_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    body = await request.json()
    reset_prompt = bool(body.get("reset_prompt"))
    mcp = store.update_mcp(
        mcp_id,
        uid,
        connected=body.get("connected") if "connected" in body else None,
        prompt=str(body["prompt"]) if "prompt" in body and not reset_prompt else None,
        url=str(body["url"]) if "url" in body else None,
        name=str(body["name"]) if "name" in body else None,
        description=str(body["description"]) if "description" in body else None,
        reset_prompt=reset_prompt,
    )
    if not mcp:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=mcp)


@app.delete("/mcps/{mcp_id}")
def remove_mcp(mcp_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    if not store.delete_mcp(mcp_id, uid):
        return JSONResponse(
            status_code=400,
            content={"error": "組み込みの MCP は削除できません。切り離してください。"},
        )
    return JSONResponse(content={"ok": True})


@app.delete("/skills/{skill_id}")
def remove_skill(skill_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    if not store.delete_skill(skill_id, uid):
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content={"ok": True})


@app.post("/sessions/{session_id}/chat")
async def chat(session_id: str, request: Request) -> JSONResponse:
    err, uid = _auth(request)
    if err:
        return err
    if not llm.LLM_ENABLED:
        return JSONResponse(status_code=503, content={"error": "LLM が無効です"})
    body = await request.json()
    question = str(body.get("question") or body.get("content") or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"error": "質問を入力してください"})
    detail = store.get_session(session_id, uid)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    raw_ids = body.get("source_ids")
    requested: list[str] = []
    if isinstance(raw_ids, list):
        seen: set[str] = set()
        for item in raw_ids:
            sid = str(item or "").strip()
            if sid and sid not in seen:
                seen.add(sid)
                requested.append(sid)
    scoped: list[str] | None = None
    labels: list[str] = []
    if requested:
        resolved = store.resolve_source_selection(session_id, uid, requested)
        if resolved is None:
            return JSONResponse(status_code=404, content={"error": "見つかりません"})
        kept, labels = resolved
        if not kept:
            return JSONResponse(
                status_code=400,
                content={"error": "指定した資料がこのノートにありません"},
            )
        scoped = kept
    history = list(detail.get("messages") or [])
    designated, ref_error = harness.resolve_answer_refs(question, history)
    if ref_error:
        return JSONResponse(status_code=400, content={"error": ref_error})
    store.add_message(
        session_id, uid, role="user", content=question, source_labels=labels
    )
    return await _generate_reply(
        session_id=session_id,
        uid=uid,
        request=request,
        detail=detail,
        question=question,
        history=history,
        labels=labels,
        scoped=scoped,
        designated=designated,
    )


@app.post("/sessions/{session_id}/chat/retry")
async def retry_chat(session_id: str, request: Request) -> JSONResponse:
    """直前の質問で、最後の回答だけを作り直す。質問の吹き出しは増やさない。"""
    err, uid = _auth(request)
    if err:
        return err
    if not llm.LLM_ENABLED:
        return JSONResponse(status_code=503, content={"error": "LLM が無効です"})
    detail = store.get_session(session_id, uid)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    messages = list(detail.get("messages") or [])
    if not messages or messages[-1].get("role") != "assistant":
        return JSONResponse(status_code=400, content={"error": "作り直す回答がありません"})
    user_idx = next(
        (
            i
            for i in range(len(messages) - 2, -1, -1)
            if messages[i].get("role") == "user"
        ),
        None,
    )
    if user_idx is None:
        return JSONResponse(status_code=400, content={"error": "作り直す質問がありません"})
    question = str(messages[user_idx].get("content") or "").strip()
    if not question:
        return JSONResponse(status_code=400, content={"error": "作り直す質問がありません"})
    labels = [
        str(item).strip()
        for item in (messages[user_idx].get("source_labels") or [])
        if str(item).strip()
    ]
    history = messages[:user_idx]
    designated, ref_error = harness.resolve_answer_refs(question, history)
    if ref_error:
        return JSONResponse(status_code=400, content={"error": ref_error})
    previous = messages[-1]
    if not store.delete_message(session_id, uid, str(previous.get("id") or "")):
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    response = await _generate_reply(
        session_id=session_id,
        uid=uid,
        request=request,
        detail=detail,
        question=question,
        history=history,
        labels=labels,
        scoped=None,
        designated=designated,
    )
    if response.status_code >= 400:
        store.add_message(
            session_id,
            uid,
            role="assistant",
            content=str(previous.get("content") or ""),
            citations=list(previous.get("citations") or []),
            tool_trace=list(previous.get("tool_trace") or []),
            drafts=list(previous.get("drafts") or []),
            open_editor=bool(previous.get("open_editor")),
        )
    return response


async def _generate_reply(
    *,
    session_id: str,
    uid: str,
    request: Request,
    detail: dict,
    question: str,
    history: list,
    labels: list[str],
    scoped: list[str] | None,
    designated: list,
) -> JSONResponse:
    scope = (request.headers.get("x-scope") or "").strip()
    forward = {
        key: value
        for key, value in request.headers.items()
        if key.lower().startswith("x-")
    }
    try:
        agent_pool.acquire(
            SessionKey(
                tenant=(request.headers.get("x-tenant-id") or "").strip(),
                team=scope,
                user=uid,
            )
        )
    except PoolFull as e:
        return JSONResponse(status_code=409, content={"error": str(e)})
    except HermesUnavailable as e:
        return JSONResponse(status_code=503, content={"error": str(e)})
    try:
        answer, cites, traces, drafts, open_editor = await harness.run(
            session_id=session_id,
            user_id=uid,
            scope=scope,
            question=question,
            history=history,
            instruction=str(detail.get("instruction") or ""),
            source_ids=scoped,
            source_labels=labels,
            designated_answers=designated,
            forward_headers=forward,
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"error": f"生成に失敗しました: {e}"}
        )
    detail = store.add_message(
        session_id,
        uid,
        role="assistant",
        content=answer,
        citations=cites,
        tool_trace=traces,
        drafts=drafts,
        open_editor=open_editor,
    )
    return JSONResponse(content=detail)


@app.post("/internal/mcp")
async def internal_mcp(request: Request) -> Response:
    """Hermes コンテナから、今のターンの道具だけを呼ぶ。"""
    if (request.headers.get("x-api-key") or "") != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    raw = await request.body()
    if not raw:
        return Response(status_code=202)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return JSONResponse(
            status_code=400,
            content={
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "parse error"},
            },
        )
    token = (request.headers.get("x-notebook-turn") or "").strip()
    result = await hermes_mcp.handle(payload, token)
    if result is None:
        return Response(status_code=202)
    return JSONResponse(result)


@app.get("/sessions/{session_id}/download")
def download(session_id: str, request: Request) -> Response:
    err, uid = _auth(request)
    if err:
        return err
    detail = store.get_session(session_id, uid)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    sheet = NavSheet(
        rows=[
            NavRow(
                label=i.get("label") or "",
                value=retrieve.strip_citation_marks(i.get("value") or ""),
            )
            for i in detail["items"]
        ],
        instruction=detail.get("instruction") or "",
    )
    raw = write_workbook(sheet)
    name, ascii_name = _hearing_xlsx_name(str(detail.get("title") or ""))
    return Response(
        content=raw,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _xlsx_disposition(name, ascii_name)},
    )
