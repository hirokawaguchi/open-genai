"""起動済み Hermes の ACP ゲートウェイへ、1ターンを渡す。"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import struct
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlparse

_OP_TEXT = 0x1
_OP_CLOSE = 0x8
_OP_PING = 0x9
_OP_PONG = 0xA


def notebook_tool_name(title: str) -> str | None:
    """画面に出す道具名。Hermes 内部の探索や呼び出し ID は捨てる。"""
    text = (title or "").strip()
    if not text or text.startswith("tool_") or text.startswith("call_"):
        return None
    tail = text.split("__")[-1] if "__" in text else text
    name = tail.split(":", 1)[0].strip()
    if not name or name.startswith("tool_") or name.startswith("call_"):
        return None
    return name


def remember_tool(traces: list[dict[str, str]], name: str, result: str) -> None:
    """同じ道具の開始と完了は、画面では1行にする。"""
    if traces and traces[-1]["name"] == name:
        if result:
            traces[-1]["result"] = result
        return
    traces.append({"name": name, "result": result})


def allow_option(options: list[dict[str, Any]]) -> str | None:
    """承認の選択肢から、一度だけ許可する id を返す。"""
    once = ""
    allow = ""
    fallback = ""
    for option in options:
        oid = str(option.get("id") or "").strip()
        if not oid:
            continue
        blob = f"{oid} {option.get('name') or ''}".lower()
        if any(word in blob for word in ("reject", "deny", "cancel", "拒否")):
            continue
        if "once" in blob:
            once = once or oid
        elif "allow" in blob or "許可" in blob:
            allow = allow or oid
        elif not fallback:
            fallback = oid
    return once or allow or fallback or None


def _mask(payload: bytes) -> tuple[bytes, bytes]:
    mask = os.urandom(4)
    return mask, bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))


def encode_text(text: str) -> bytes:
    payload = text.encode()
    mask, masked = _mask(payload)
    n = len(payload)
    header = bytearray([0x81])
    if n < 126:
        header.append(0x80 | n)
    elif n < 65536:
        header.append(0x80 | 126)
        header += struct.pack("!H", n)
    else:
        header.append(0x80 | 127)
        header += struct.pack("!Q", n)
    return bytes(header) + mask + masked


def encode_pong(payload: bytes) -> bytes:
    mask, masked = _mask(payload)
    n = len(payload)
    header = bytearray([0x8A])
    if n < 126:
        header.append(0x80 | n)
    else:
        header.append(0x80 | 126)
        header += struct.pack("!H", n)
    return bytes(header) + mask + masked


async def _read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    return await reader.readexactly(n)


async def read_frame(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    head = await _read_exact(reader, 2)
    opcode = head[0] & 0x0F
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", await _read_exact(reader, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await _read_exact(reader, 8))[0]
    mask = await _read_exact(reader, 4) if head[1] & 0x80 else b""
    data = await _read_exact(reader, length) if length else b""
    if mask:
        data = bytes(byte ^ mask[i % 4] for i, byte in enumerate(data))
    return opcode, data


def _ws_target(base_url: str, token: str) -> tuple[str, int, str]:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        raise ValueError("Hermes の宛先が空です")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = f"/ws?turn={quote(token)}"
    return host, port, path


async def _open(host: str, port: int, path: str) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
    reader, writer = await asyncio.open_connection(host, port)
    key = base64.b64encode(os.urandom(16)).decode()
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    writer.write(request.encode())
    await writer.drain()
    status = await reader.readline()
    if b" 101 " not in status:
        writer.close()
        raise ConnectionError("Hermes のゲートウェイに接続できませんでした")
    while True:
        line = await reader.readline()
        if line in (b"\r\n", b"\n", b""):
            break
    return reader, writer


async def complete(
    base_url: str,
    token: str,
    prompt: str,
    *,
    timeout: float = 600,
    on_tool: Callable[[str], None] | None = None,
) -> tuple[str, list[dict[str, str]]]:
    """1ターンを送り、応答本文とツール痕跡を返す。"""
    host, port, path = _ws_target(base_url, token)

    async def _run() -> tuple[str, list[dict[str, str]]]:
        reader, writer = await _open(host, port, path)
        parts: list[str] = []
        traces: list[dict[str, str]] = []
        try:
            ready = False
            while not ready:
                opcode, data = await read_frame(reader)
                if opcode == _OP_PING:
                    writer.write(encode_pong(data))
                    await writer.drain()
                    continue
                if opcode == _OP_CLOSE:
                    raise ConnectionError("Hermes が接続を閉じました")
                if opcode != _OP_TEXT:
                    continue
                event = json.loads(data.decode() or "{}")
                if event.get("type") == "status" and event.get("text") == "ready":
                    ready = True
                elif event.get("type") == "error":
                    raise ConnectionError(str(event.get("text") or "Hermes の準備に失敗しました"))
            writer.write(encode_text(json.dumps({"type": "prompt", "text": prompt}, ensure_ascii=False)))
            await writer.drain()
            while True:
                opcode, data = await read_frame(reader)
                if opcode == _OP_PING:
                    writer.write(encode_pong(data))
                    await writer.drain()
                    continue
                if opcode == _OP_CLOSE:
                    break
                if opcode != _OP_TEXT:
                    continue
                event = json.loads(data.decode() or "{}")
                kind = event.get("type")
                if kind == "message":
                    parts.append(str(event.get("text") or ""))
                elif kind == "tool":
                    name = notebook_tool_name(str(event.get("title") or ""))
                    if name:
                        remember_tool(
                            traces,
                            name,
                            str(event.get("output") or event.get("status") or "")[:1200],
                        )
                        if on_tool:
                            on_tool(name)
                elif kind == "permission":
                    option = allow_option(event.get("options") or [])
                    writer.write(
                        encode_text(
                            json.dumps(
                                {
                                    "type": "permission_response",
                                    "id": event.get("id"),
                                    "optionId": option,
                                },
                                ensure_ascii=False,
                            )
                        )
                    )
                    await writer.drain()
                elif kind == "error":
                    raise ConnectionError(str(event.get("text") or "Hermes が失敗しました"))
                elif kind == "done":
                    break
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
        return "".join(parts).strip(), traces

    try:
        return await asyncio.wait_for(_run(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise TimeoutError("Hermes の応答が時間内に終わりませんでした") from exc
