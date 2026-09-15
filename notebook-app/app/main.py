"""ノートブック。資料を構造化して項目・対話・ヒアリングシートにする。"""

from __future__ import annotations

import base64
import os
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from . import extract, ground, harness, intauth, llm, mcp_catalog, mcp_knowledge, ocr, retrieve, store, structure, tools

for parent in Path(__file__).resolve().parents:
    if (parent / "shared" / "navsheet.py").exists():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break
from shared.navsheet import NavRow, NavSheet, empty_workbook, write_workbook  # noqa: E402

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
RETENTION_DAYS = int(os.environ.get("HEARING_RETENTION_DAYS", "30"))
MAX_UPLOAD_BYTES = int(os.environ.get("MAX_DOC_BYTES", str(20 * 1024 * 1024)))

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
        return JSONResponse(status_code=400, content={"error": "ファイルが大きすぎます"})
    if not extract.allowed_name(filename):
        return JSONResponse(
            status_code=400,
            content={"error": f"未対応の形式です: {filename}"},
        )
    error = ""
    nodes: list[dict] = []
    briefing: dict = {}
    try:
        pages = extract.extract_pages(filename, raw)
        nodes = structure.build_nodes(pages)
        for n in nodes:
            n["source"] = filename
        briefing = structure.briefing_from_nodes(filename, nodes)
        if any(p.get("ocr") for p in pages):
            briefing["ocr"] = True
        sample = "\n".join(str(n.get("text") or "") for n in structure.sample_nodes(nodes, 6))
        briefing = await ground.enrich_briefing(filename, briefing, sample)
    except extract.DocExtractError as e:
        error = str(e)
    detail = store.add_file(
        session_id,
        uid,
        filename=filename,
        raw=raw,
        error=error,
        nodes=nodes,
        briefing=briefing,
    )
    if not detail:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content=detail)


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
    skill = None
    skill_id = str(body.get("skill_id") or "").strip()
    if skill_id:
        skill = store.get_skill(skill_id, uid)
        if not skill:
            return JSONResponse(status_code=404, content={"error": "スキルが見つかりません"})
    history = list(detail.get("messages") or [])
    store.add_message(session_id, uid, role="user", content=question)
    scope = (request.headers.get("x-scope") or "").strip()
    try:
        answer, cites, traces = await harness.run(
            session_id=session_id,
            user_id=uid,
            scope=scope,
            question=question,
            history=history,
            instruction=str(detail.get("instruction") or ""),
            skill=skill,
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
    )
    return JSONResponse(content=detail)


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
