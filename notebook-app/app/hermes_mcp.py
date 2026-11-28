"""Hermes からノートの道具を呼ぶための、短い MCP。

ターンごとにトークンを発行し、そのトークンのヘッダが付いた呼び出しだけを受ける。
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import tools


@dataclass
class Turn:
    ctx: tools.ToolContext
    allowed: list[str]
    extras: list[dict[str, Any]] = field(default_factory=list)


_turns: dict[str, Turn] = {}


def open_turn(
    ctx: tools.ToolContext,
    allowed: list[str],
    extras: list[dict[str, Any]] | None = None,
) -> str:
    token = uuid.uuid4().hex
    _turns[token] = Turn(ctx=ctx, allowed=list(allowed), extras=list(extras or []))
    return token


def close_turn(token: str) -> None:
    _turns.pop(token, None)


def _tool_list(turn: Turn) -> list[dict[str, Any]]:
    specs = tools.openai_tools(turn.allowed, turn.extras)
    listed: list[dict[str, Any]] = []
    for spec in specs:
        fn = spec.get("function") if isinstance(spec, dict) else None
        if not isinstance(fn, dict):
            continue
        name = str(fn.get("name") or "").strip()
        if not name:
            continue
        params = fn.get("parameters") if isinstance(fn.get("parameters"), dict) else {}
        if not params:
            params = {"type": "object", "properties": {}}
        listed.append(
            {
                "name": name,
                "description": str(fn.get("description") or name),
                "inputSchema": params,
            }
        )
    return listed


async def handle(payload: Any, token: str) -> dict[str, Any] | None:
    """JSON-RPC を1件処理する。通知なら None。"""
    if not isinstance(payload, dict):
        return _error(None, -32600, "invalid request")
    method = str(payload.get("method") or "")
    req_id = payload.get("id")
    if "id" not in payload:
        return None
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    if method == "initialize":
        version = str(params.get("protocolVersion") or "2025-06-18")
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "notebook", "version": "0.2.0"},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    turn = _turns.get(token)
    if turn is None:
        return _error(req_id, -32001, "この対話はもう終わっています")
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": _tool_list(turn)}}
    if method == "tools/call":
        name = str(params.get("name") or "").strip()
        if name not in turn.allowed:
            return _error(req_id, -32602, f"このノートでは {name} を使えません")
        raw_args = params.get("arguments")
        text = await tools.dispatch(name, raw_args, turn.ctx)
        is_error = False
        try:
            parsed = json.loads(text)
            is_error = isinstance(parsed, dict) and bool(parsed.get("error"))
        except (TypeError, ValueError):
            is_error = False
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "isError": is_error,
            },
        }
    return _error(req_id, -32601, f"method not found: {method}")


def _error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    }
