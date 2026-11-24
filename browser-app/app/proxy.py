"""Chromium 専用の転送プロキシ。127.0.0.1 だけで待ち受ける。

Chromium からの HTTP と CONNECT を `egress.decide` に通し、許可した接続は
解決済みの公開 IP へ張る。パスとクエリはログに残さない。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from urllib.parse import urlsplit

from . import egress

EGRESS_PORT = int(os.environ.get("BROWSER_EGRESS_PORT", "18080"))
_MAX_HEADER = 64 * 1024


def log_decision(host: str, port: int, allowed: bool, reason: str) -> None:
    print(
        json.dumps(
            {
                "event": "browser.egress",
                "host": host,
                "port": port,
                "result": "allow" if allowed else "deny",
                "reason": reason,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


async def _read_headers(
    reader: asyncio.StreamReader,
) -> tuple[str, list[tuple[str, str]], bytes] | None:
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = await reader.read(4096)
        if not chunk:
            return None
        buf += chunk
        if len(buf) > _MAX_HEADER:
            return None
    head, rest = buf.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1", errors="replace").split("\r\n")
    if not lines or not lines[0]:
        return None
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers.append((key.strip(), value.strip()))
    return lines[0], headers, rest


def _header(headers: list[tuple[str, str]], name: str) -> str | None:
    for key, value in headers:
        if key.lower() == name.lower():
            return value
    return None


async def resolve_host(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    found: list[str] = []
    for info in infos:
        addr = info[4][0]
        if addr not in found:
            found.append(addr)
    return found


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except Exception:  # noqa: BLE001
        return
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


async def _relay(
    left_r: asyncio.StreamReader,
    left_w: asyncio.StreamWriter,
    right_r: asyncio.StreamReader,
    right_w: asyncio.StreamWriter,
) -> None:
    await asyncio.gather(_pipe(left_r, right_w), _pipe(right_r, left_w))


async def _deny(writer: asyncio.StreamWriter, status: int, reason: str) -> None:
    body = reason.encode("ascii", errors="replace")
    head = (
        f"HTTP/1.1 {status} Forbidden\r\n"
        "Content-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    writer.write(head + body)
    try:
        await writer.drain()
    except Exception:  # noqa: BLE001
        pass
    writer.close()


def _request_target(
    method: str, target: str, headers: list[tuple[str, str]]
) -> tuple[str, int, str] | None:
    if method.upper() == "CONNECT":
        parsed = egress.split_host_port(target, 443)
        if parsed is None:
            return None
        host, port = parsed
        return host, port, ""
    parts = urlsplit(target)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        host_header = _header(headers, "host")
        if not host_header:
            return None
        parsed = egress.split_host_port(host_header, 80)
        if parsed is None:
            return None
        host, port = parsed
        path = target if target.startswith("/") else "/"
        return host, port, path
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path = f"{path}?{parts.query}"
    return parts.hostname, port, path


def _origin_request(
    method: str,
    path: str,
    headers: list[tuple[str, str]],
    host: str,
    port: int,
) -> bytes:
    skip = {"proxy-connection", "proxy-authorization", "connection"}
    lines = [f"{method} {path or '/'} HTTP/1.1"]
    saw_host = False
    for key, value in headers:
        if key.lower() in skip:
            continue
        if key.lower() == "host":
            saw_host = True
        lines.append(f"{key}: {value}")
    if not saw_host:
        host_value = host if port in (80, 443) else f"{host}:{port}"
        lines.append(f"Host: {host_value}")
    lines.append("Connection: close")
    return ("\r\n".join(lines) + "\r\n\r\n").encode("iso-8859-1", errors="replace")


async def _addresses_for(host: str) -> list[str]:
    if not egress.needs_dns(host):
        return []
    return await resolve_host(host)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        try:
            head = await asyncio.wait_for(_read_headers(reader), timeout=20)
        except asyncio.TimeoutError:
            await _deny(writer, 408, "timeout")
            return
        if head is None:
            writer.close()
            return
        request, headers, rest = head
        bits = request.split(" ")
        if len(bits) < 2:
            await _deny(writer, 400, "bad-request")
            return
        method, target = bits[0], bits[1]
        located = _request_target(method, target, headers)
        if located is None:
            await _deny(writer, 400, "bad-request")
            return
        host, port, path = located
        decision = egress.decide(host, port, await _addresses_for(host))
        log_decision(host, port, decision.allowed, decision.reason)
        if not decision.allowed or not decision.connect_ip:
            await _deny(writer, 403, decision.reason)
            return
        try:
            remote_r, remote_w = await asyncio.wait_for(
                asyncio.open_connection(decision.connect_ip, port),
                timeout=15,
            )
        except (OSError, asyncio.TimeoutError):
            await _deny(writer, 502, "connect")
            return
        if method.upper() == "CONNECT":
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if rest:
                remote_w.write(rest)
            await writer.drain()
            await _relay(reader, writer, remote_r, remote_w)
            return
        remote_w.write(_origin_request(method, path, headers, host, port))
        if rest:
            remote_w.write(rest)
        await remote_w.drain()
        await _relay(reader, writer, remote_r, remote_w)
    except Exception:  # noqa: BLE001
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


async def start() -> asyncio.AbstractServer:
    return await asyncio.start_server(handle_client, "127.0.0.1", EGRESS_PORT)
