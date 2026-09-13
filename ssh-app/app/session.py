"""カタログ上の接続先への SSH PTY セッション。"""

from __future__ import annotations

import asyncio
import os
import time
from typing import Any

import asyncssh

from . import store

IDLE_SECONDS = int(os.environ.get("SSH_IDLE_SECONDS", "1800"))
MAX_SESSIONS = int(os.environ.get("SSH_MAX_SESSIONS_PER_USER", "2"))
CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "20"))

_sessions: dict[str, int] = {}
_lock = asyncio.Lock()


class SessionLimitError(Exception):
    pass


class HostKeyMismatchError(Exception):
    pass


class HostDisabledError(Exception):
    pass


def _key_body(value: str) -> str:
    parts = value.strip().split()
    if len(parts) >= 2:
        return f"{parts[0]} {parts[1]}"
    return value.strip()


class _KeyClient(asyncssh.SSHClient):
    def __init__(self, expected: str | None) -> None:
        self.expected = (expected or "").strip() or None
        self.learned: str | None = None
        self.mismatch = False

    def validate_host_public_key(self, host: str, addr: Any, key: asyncssh.SSHKey) -> bool:
        exported = key.export_public_key().decode().strip()
        if self.expected:
            if _key_body(exported) == _key_body(self.expected):
                return True
            self.mismatch = True
            return False
        self.learned = exported
        return True


async def acquire(user_id: str) -> None:
    async with _lock:
        n = _sessions.get(user_id, 0)
        if n >= MAX_SESSIONS:
            raise SessionLimitError()
        _sessions[user_id] = n + 1


async def release(user_id: str) -> None:
    async with _lock:
        n = _sessions.get(user_id, 0)
        if n <= 1:
            _sessions.pop(user_id, None)
        else:
            _sessions[user_id] = n - 1


async def open_connection(
    host_row: dict[str, Any],
    *,
    username: str,
    password: str,
    cols: int,
    rows: int,
) -> tuple[asyncssh.SSHClientConnection, asyncssh.SSHClientProcess, str | None]:
    if not host_row.get("enabled"):
        raise HostDisabledError()
    cols = max(20, min(int(cols or 80), 500))
    rows = max(8, min(int(rows or 25), 200))
    holder: list[_KeyClient] = []

    def factory() -> _KeyClient:
        client = _KeyClient(host_row.get("host_key") or "")
        holder.append(client)
        return client

    try:
        conn = await asyncssh.connect(
            store.resolve_connect_host(str(host_row["host"])),
            port=int(host_row["port"]),
            username=username,
            password=password,
            client_factory=factory,
            known_hosts=None,
            agent_path=None,
            client_keys=[],
            x11_forwarding=False,
            login_timeout=CONNECT_TIMEOUT,
        )
    except asyncssh.DisconnectError as e:
        if holder and holder[-1].mismatch:
            raise HostKeyMismatchError() from e
        raise
    except asyncssh.HostKeyNotVerifiable as e:
        raise HostKeyMismatchError() from e

    learned = holder[-1].learned if holder else None
    if learned:
        store.set_host_key(host_row["id"], learned)
    proc = await conn.create_process(
        term_type="xterm-256color",
        term_size=(cols, rows),
        encoding=None,
        env={
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "LC_CTYPE": "C.UTF-8",
        },
    )
    return conn, proc, learned


class IdleWatch:
    def __init__(self, seconds: int = IDLE_SECONDS) -> None:
        self.seconds = max(60, seconds)
        self._last = time.monotonic()

    def touch(self) -> None:
        self._last = time.monotonic()

    def expired(self) -> bool:
        return (time.monotonic() - self._last) > self.seconds
