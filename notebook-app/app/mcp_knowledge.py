"""knowledge-mcp を Dify 抜きで呼ぶ。scope は呼び出し側が固定する。"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

KNOWLEDGE_MCP_URL = (os.environ.get("KNOWLEDGE_MCP_URL") or "").strip()
REQUEST_TIMEOUT = float(os.environ.get("NOTEBOOK_MCP_TIMEOUT", "45"))


def enabled() -> bool:
    return bool(KNOWLEDGE_MCP_URL)


def _rpc_result(data: Any) -> Any:
    if not isinstance(data, dict):
        raise ValueError("MCP 応答が不正です")
    if data.get("error"):
        err = data["error"]
        if isinstance(err, dict):
            raise ValueError(str(err.get("message") or err))
        raise ValueError(str(err))
    return data.get("result")


async def _rpc(
    method: str,
    params: dict[str, Any] | None = None,
    *,
    url: str = "",
    session_id: str = "",
    req_id: int = 1,
) -> tuple[Any, str]:
    endpoint = (url or KNOWLEDGE_MCP_URL).strip()
    if not endpoint:
        raise RuntimeError("MCP URL が未設定です")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        payload["params"] = params
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(endpoint, json=payload, headers=headers)
        res.raise_for_status()
        sid = res.headers.get("mcp-session-id") or session_id
        ctype = (res.headers.get("content-type") or "").lower()
        if "text/event-stream" in ctype:
            data = _parse_sse_json(res.text)
        else:
            data = res.json()
    return _rpc_result(data), sid


def _parse_sse_json(text: str) -> dict[str, Any]:
    for line in (text or "").splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            if raw:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    return parsed
    raise ValueError("MCP SSE 応答を読めません")


async def _session(url: str = "") -> str:
    _, sid = await _rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "notebook-app", "version": "0.2"},
        },
        url=url,
        req_id=1,
    )
    try:
        await _rpc(
            "notifications/initialized",
            None,
            url=url,
            session_id=sid,
            req_id=2,
        )
    except Exception:  # noqa: BLE001
        pass
    return sid


async def list_tools(url: str) -> list[dict[str, Any]]:
    sid = await _session(url)
    result, _ = await _rpc("tools/list", {}, url=url, session_id=sid, req_id=3)
    tools = result.get("tools") if isinstance(result, dict) else None
    if not isinstance(tools, list):
        return []
    out: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        schema = item.get("inputSchema") or item.get("input_schema") or {}
        out.append(
            {
                "name": name,
                "description": str(item.get("description") or ""),
                "parameters": schema if isinstance(schema, dict) else {},
            }
        )
    return out


async def call_tool_at(url: str, name: str, arguments: dict[str, Any]) -> str:
    sid = await _session(url)
    result, _ = await _rpc(
        "tools/call",
        {"name": name, "arguments": arguments},
        url=url,
        session_id=sid,
        req_id=3,
    )
    return _tool_text(result)


async def call_tool(name: str, arguments: dict[str, Any]) -> str:
    return await call_tool_at(KNOWLEDGE_MCP_URL, name, arguments)


def _tool_text(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        content = result.get("content")
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text") or ""))
            if parts:
                return "\n".join(parts)
        if result.get("structuredContent") is not None:
            return json.dumps(result["structuredContent"], ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)
    return str(result)


def citations_from_payload(text: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return []
    cites: list[dict[str, Any]] = []
    for i, n in enumerate(nodes, start=1):
        if not isinstance(n, dict):
            continue
        source = str(n.get("source") or "ナレッジ")
        title = str(n.get("title") or "").strip()
        label = source + (f" / {title}" if title else "")
        cites.append(
            {
                "n": i,
                "display_name": f"{label}（共有ナレッジ・未ソース）",
                "text": str(n.get("text") or ""),
            }
        )
    return cites
