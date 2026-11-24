"""Web ブラウザ マイクロサービス（Open GENAI 専用ページ向け）。

- 庁内: backend が JWT 検証後、HMAC 署名付きで /sessions と /ws へプロキシ
- Chromium はコンテナ内で起動し、画面だけを WebSocket で返す
- 出口は公開 IP の 80/443 のみ。Cookie と履歴は利用者ごとに残す

Compose では profiles: ["browser"] でオプション起動する。
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response

from . import intauth, proxy, session

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    server = await proxy.start()
    try:
        yield
    finally:
        server.close()
        await server.wait_closed()
        await session.stop_all()


app = FastAPI(title="Open GENAI Browser App", version="0.1.0", lifespan=lifespan)


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
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"}), ""
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), ""
    return None, x_user_id


def _headers_from_ws(websocket: WebSocket) -> tuple[str | None, str]:
    h = websocket.headers
    err, user_id = _verify_internal(
        h.get("x-api-key"),
        h.get("x-user-id"),
        h.get("x-user-groups"),
        h.get("x-scope"),
        h.get("x-user-ts"),
        h.get("x-user-sig"),
        h.get("x-user-tags"),
    )
    if err:
        return err.body.decode("utf-8") if err.body else "unauthorized", ""
    return None, user_id


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _user_id = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    width, height = session.screen_size()
    return JSONResponse(
        {
            "enabled": True,
            "idle_seconds": session.IDLE_SECONDS,
            "max_sessions_per_user": session.MAX_PER_USER,
            "max_sessions": session.MAX_SESSIONS,
            "width": width,
            "height": height,
        }
    )


def _session_payload(item: session.BrowserSession) -> dict[str, Any]:
    return {
        "id": item.id,
        "width": item.width,
        "height": item.height,
    }


@app.post("/sessions")
async def create_session(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, user_id = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    try:
        item = await session.open_session(user_id)
    except session.SessionLimitError as exc:
        return JSONResponse(status_code=429, content={"error": str(exc)})
    except session.BrowserStartError as exc:
        return JSONResponse(status_code=503, content={"error": str(exc)})
    return JSONResponse({"session": _session_payload(item)})


@app.post("/sessions/{session_id}/touch")
async def touch_session(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, user_id = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not await session.touch(session_id, user_id):
        return JSONResponse(status_code=404, content={"error": "ブラウザセッションが見つかりません"})
    return JSONResponse({"ok": True})


@app.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, user_id = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    owned = await session.get_owned(session_id, user_id)
    if owned is None:
        return JSONResponse({"ok": True})
    await session.stop(session_id)
    return JSONResponse({"ok": True})


def _internal_user(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> tuple[JSONResponse | None, str]:
    return _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )


@app.get("/sessions/{session_id}/downloads")
async def list_downloads(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, user_id = _internal_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    listed = await session.list_downloads(session_id, user_id)
    if listed is None:
        return JSONResponse(status_code=404, content={"error": "ブラウザセッションが見つかりません"})
    return JSONResponse(listed)


@app.get("/sessions/{session_id}/downloads/{file_id}")
async def take_download(
    session_id: str,
    file_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Response:
    err, user_id = _internal_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    taken = await session.take_download(session_id, user_id, file_id)
    if taken is None:
        return JSONResponse(status_code=404, content={"error": "ファイルが見つかりません"})
    name, data = taken
    ascii_name = "".join(c if c.isascii() and c not in '"\\' else "_" for c in name) or "download"
    disposition = f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@app.websocket("/audio")
async def browser_audio(websocket: WebSocket) -> None:
    auth_err, user_id = _headers_from_ws(websocket)
    if auth_err or not user_id:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    try:
        raw = await websocket.receive_text()
        try:
            first = json.loads(raw)
        except json.JSONDecodeError:
            await _send_json(websocket, {"type": "error", "message": "接続パラメータが不正です"})
            await websocket.close(code=4400)
            return
        if not isinstance(first, dict):
            await _send_json(websocket, {"type": "error", "message": "接続パラメータが不正です"})
            await websocket.close(code=4400)
            return
        session_id = str(first.get("sessionId") or first.get("session_id") or "").strip()
        item = await session.get_owned(session_id, user_id)
        if item is None:
            await _send_json(websocket, {"type": "error", "message": "ブラウザセッションが見つかりません"})
            await websocket.close(code=4404)
            return
        await session.bridge_audio(item, websocket)
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        try:
            await _send_json(websocket, {"type": "error", "message": "音声の転送が切れました"})
        except Exception:  # noqa: BLE001
            pass


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


@app.websocket("/ws")
async def browser_ws(websocket: WebSocket) -> None:
    auth_err, user_id = _headers_from_ws(websocket)
    if auth_err or not user_id:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    session_id = ""
    item: session.BrowserSession | None = None
    try:
        raw = await websocket.receive_text()
        try:
            first = json.loads(raw)
        except json.JSONDecodeError:
            await _send_json(websocket, {"type": "error", "message": "接続パラメータが不正です"})
            await websocket.close(code=4400)
            return
        if not isinstance(first, dict):
            await _send_json(websocket, {"type": "error", "message": "接続パラメータが不正です"})
            await websocket.close(code=4400)
            return
        session_id = str(first.get("sessionId") or first.get("session_id") or "").strip()
        item = await session.get_owned(session_id, user_id)
        if item is None:
            await _send_json(websocket, {"type": "error", "message": "ブラウザセッションが見つかりません"})
            await websocket.close(code=4404)
            return
        await _send_json(
            websocket,
            {
                "type": "ready",
                "sessionId": item.id,
                "width": item.width,
                "height": item.height,
            },
        )
        await session.bridge(item, websocket)
        if item.reason == "idle":
            await _send_json(
                websocket,
                {"type": "error", "message": "一定時間操作がなかったため切断しました"},
            )
    except WebSocketDisconnect:
        return
    except Exception:  # noqa: BLE001
        try:
            await _send_json(websocket, {"type": "error", "message": "ブラウザの画面転送が切れました"})
        except Exception:  # noqa: BLE001
            pass
    finally:
        if session_id:
            await session.stop(session_id)
