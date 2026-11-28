#!/usr/bin/env python3
"""ノート用の ACP ゲートウェイ。

作業ディレクトリは持たない。cwd は ACP_GATEWAY_CWD（既定 /tmp）。
接続の turn クエリに対応するノートの MCP だけを、そのセッションへ渡す。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

from aiohttp import WSMsgType, web

import acp
from acp import spawn_agent_process
from acp.core import Client
from acp.helpers import text_block
from acp.schema import HttpHeader, HttpMcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [notebook-acp] %(message)s")
log = logging.getLogger("notebook-acp")

PORT = int(os.environ.get("ACP_GATEWAY_PORT", "7799"))
WORKDIR = (os.environ.get("ACP_GATEWAY_CWD") or os.environ.get("HERMES_WORK_DIR") or "/tmp").strip() or "/tmp"
PROMPT_TIMEOUT_SEC = int(os.environ.get("ACP_GATEWAY_PROMPT_TIMEOUT", "600"))
STREAM_LIMIT = int(os.environ.get("ACP_GATEWAY_STREAM_LIMIT", str(64 * 1024 * 1024)))


def _dump(obj: Any) -> Any:
    for attr in ("model_dump", "dict"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                pass
    if isinstance(obj, (list, tuple)):
        return [_dump(item) for item in obj]
    return obj


def _tool_output_text(content: Any) -> str:
    items = _dump(content)
    if not isinstance(items, list):
        return ""
    parts: list[str] = []
    for item in items:
        it = item if isinstance(item, dict) else _dump(item)
        if not isinstance(it, dict):
            continue
        inner = it.get("content")
        text = None
        if isinstance(inner, dict):
            text = inner.get("text")
        elif isinstance(inner, str):
            text = inner
        if not text:
            text = it.get("text")
        if isinstance(text, str) and text:
            parts.append(text)
    return "\n".join(parts)


class GatewayClient(Client):
    def __init__(self, ws: web.WebSocketResponse) -> None:
        self.ws = ws
        self._send_lock = asyncio.Lock()

    async def _emit(self, payload: dict) -> None:
        async with self._send_lock:
            if not self.ws.closed:
                await self.ws.send_str(json.dumps(payload, ensure_ascii=False))

    async def session_update(self, session_id: str, update: Any, **kwargs: Any) -> None:
        data = _dump(update)
        kind = data.get("session_update") if isinstance(data, dict) else None

        def _text(block: Any) -> str:
            if isinstance(block, dict):
                return str(block.get("text") or "")
            return str(getattr(block, "text", "") or "")

        if kind == "agent_message_chunk":
            await self._emit({"type": "message", "text": _text(data.get("content"))})
        elif kind == "agent_thought_chunk":
            await self._emit({"type": "thought", "text": _text(data.get("content"))})
        elif kind in ("tool_call", "tool_call_update"):
            payload = {
                "type": "tool",
                "title": data.get("title") or data.get("tool_call_id") or "tool",
                "status": data.get("status"),
            }
            out = _tool_output_text(data.get("content"))
            if out:
                payload["output"] = out
            await self._emit(payload)

    async def request_permission(self, options: Any, session_id: str, tool_call: Any, **kwargs: Any) -> Any:
        once = ""
        allow = ""
        fallback = ""
        for option in options or []:
            dumped = _dump(option)
            oid = str(dumped.get("option_id") or dumped.get("id") or "")
            if not oid:
                continue
            blob = f"{oid} {dumped.get('name') or ''}".lower()
            if any(word in blob for word in ("reject", "deny", "cancel")):
                continue
            if "once" in blob:
                once = once or oid
            elif "allow" in blob:
                allow = allow or oid
            elif not fallback:
                fallback = oid
        chosen = once or allow or fallback
        if chosen:
            return {"outcome": {"outcome": "selected", "optionId": chosen}}
        return {"outcome": {"outcome": "cancelled"}}

    async def ext_method(self, method: str, params: dict) -> dict:
        return {}

    async def ext_notification(self, method: str, params: dict) -> None:
        return None

    async def create_terminal(self, *args: Any, **kwargs: Any) -> None:
        raise acp.RequestError(code=-32601, message="terminal not supported")

    async def read_text_file(self, *args: Any, **kwargs: Any) -> None:
        raise acp.RequestError(code=-32601, message="read_text_file not supported")

    async def write_text_file(self, *args: Any, **kwargs: Any) -> None:
        raise acp.RequestError(code=-32601, message="write_text_file not supported")


def _mcp_servers(turn: str) -> list[Any]:
    url = (os.environ.get("NOTEBOOK_MCP_URL") or "").strip()
    if not url or not turn:
        return []
    headers = [
        HttpHeader(name="x-notebook-turn", value=turn),
    ]
    api_key = (os.environ.get("NOTEBOOK_API_KEY") or "").strip()
    if api_key:
        headers.insert(0, HttpHeader(name="x-api-key", value=api_key))
    return [HttpMcpServer(type="http", name="notebook", url=url, headers=headers)]


async def health_handler(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok", "service": "notebook-acp"})


async def ws_handler(request: web.Request) -> web.WebSocketResponse:
    ws = web.WebSocketResponse(heartbeat=30, max_msg_size=0)
    await ws.prepare(request)
    client = GatewayClient(ws)
    turn = (request.query.get("turn") or "").strip()
    log.info("WS connected turn=%s", turn[:8])
    try:
        async with spawn_agent_process(
            client,
            "hermes",
            "acp",
            cwd=WORKDIR,
            transport_kwargs={"limit": STREAM_LIMIT},
        ) as (conn, _proc):
            await conn.initialize(protocol_version=acp.PROTOCOL_VERSION)
            sess = await conn.new_session(cwd=WORKDIR, mcp_servers=_mcp_servers(turn))
            await client._emit({"type": "status", "text": "ready", "session_id": sess.session_id})

            async def run_prompt(text: str) -> None:
                await client._emit({"type": "prompt_started"})
                try:
                    resp = await asyncio.wait_for(
                        conn.prompt(
                            prompt=[text_block(text)],
                            session_id=sess.session_id,
                            message_id=str(uuid.uuid4()),
                        ),
                        timeout=PROMPT_TIMEOUT_SEC,
                    )
                    dumped = _dump(resp)
                    await client._emit({"type": "done", "stop_reason": dumped.get("stop_reason")})
                except asyncio.TimeoutError:
                    await client._emit({"type": "error", "text": "prompt timeout"})
                except Exception as exc:  # noqa: BLE001
                    log.exception("prompt failed")
                    await client._emit({"type": "error", "text": f"{type(exc).__name__}: {exc}"})

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except Exception:
                        continue
                    if data.get("type") == "prompt":
                        text = str(data.get("text") or "").strip()
                        if text:
                            asyncio.create_task(run_prompt(text))
                elif msg.type == WSMsgType.ERROR:
                    break
    except Exception as exc:  # noqa: BLE001
        log.exception("gateway error")
        try:
            await client._emit({"type": "error", "text": f"gateway: {exc}"})
        except Exception:
            pass
    return ws


def main() -> None:
    os.makedirs(WORKDIR, exist_ok=True)
    app = web.Application()
    app.router.add_get("/health", health_handler)
    app.router.add_get("/ws", ws_handler)
    log.info("listening on 0.0.0.0:%d cwd=%s", PORT, WORKDIR)
    web.run_app(app, host="0.0.0.0", port=PORT, access_log=None, print=None)


if __name__ == "__main__":
    main()
