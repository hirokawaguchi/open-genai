"""SSH 接続先カタログの SQLite 永続化。"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

DB_PATH = os.environ.get("SSH_DB_PATH", "/data/ssh.db")

_HOST_RE = re.compile(
    r"^(?=.{1,253}$)"
    r"(?:(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
    r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
    r"|(?:\d{1,3}\.){3}\d{1,3})$"
)
_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{1,64}$")
_NAME_RE = re.compile(r"^[^\x00-\x1f]{1,80}$")
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _parse_port(value: Any, default: int = 22) -> tuple[int | None, str | None]:
    if value is None or value == "":
        value = default
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None, "ポートは 1〜65535 の整数で指定してください"
    if port < 1 or port > 65535:
        return None, "ポートは 1〜65535 の整数で指定してください"
    return port, None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _db = conn
    return conn


def init_db() -> None:
    db = connect()
    with _lock:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS hosts (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              host TEXT NOT NULL,
              port INTEGER NOT NULL,
              default_username TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '',
              host_key TEXT NOT NULL DEFAULT '',
              enabled INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        db.commit()


def reset_connection() -> None:
    """テスト用。次の connect() で新しい DB を開く。"""
    global _db
    if _db is not None:
        _db.close()
        _db = None


def validate_host_fields(
    *,
    name: str,
    host: str,
    port: int,
    default_username: str = "",
    description: str = "",
    host_key: str = "",
) -> str | None:
    name = (name or "").strip()
    host = (host or "").strip()
    default_username = (default_username or "").strip()
    description = (description or "").strip()
    host_key = (host_key or "").strip()
    if not _NAME_RE.match(name):
        return "表示名は1〜80文字で入力してください"
    if not _HOST_RE.match(host):
        return "ホストはホスト名または IPv4 アドレスで指定してください"
    if not isinstance(port, int) or port < 1 or port > 65535:
        return "ポートは 1〜65535 の整数で指定してください"
    if default_username and not _USER_RE.match(default_username):
        return "既定ユーザー名の形式が不正です"
    if len(description) > 500:
        return "説明は500文字以内で入力してください"
    if host_key and ("\x00" in host_key or len(host_key) > 8000):
        return "ホスト鍵の形式が不正です"
    return None


def validate_username(username: str) -> str | None:
    username = (username or "").strip()
    if not _USER_RE.match(username):
        return "ユーザー名の形式が不正です"
    return None


def resolve_connect_host(host: str) -> str:
    """ssh-app コンテナ内の loopback は別コンテナへ届かないのでホスト側へ差し替える。

    同じマシンで公開しているポート（例: Wickoid の 2222）は
    host.docker.internal 経由で到達する。
    """
    normalized = (host or "").strip().lower().strip("[]")
    if normalized in _LOOPBACK_HOSTS:
        return os.environ.get("SSH_LOOPBACK_HOST", "host.docker.internal")
    return host.strip()


def _row_to_host(row: sqlite3.Row, *, include_key: bool) -> dict[str, Any]:
    item = {
        "id": row["id"],
        "name": row["name"],
        "host": row["host"],
        "port": int(row["port"]),
        "default_username": row["default_username"] or "",
        "description": row["description"] or "",
        "enabled": bool(row["enabled"]),
        "has_host_key": bool((row["host_key"] or "").strip()),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if include_key:
        item["host_key"] = row["host_key"] or ""
    return item


def list_hosts(*, include_disabled: bool, include_key: bool) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        if include_disabled:
            rows = db.execute(
                "SELECT * FROM hosts ORDER BY name COLLATE NOCASE, host"
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM hosts WHERE enabled = 1 ORDER BY name COLLATE NOCASE, host"
            ).fetchall()
    return [_row_to_host(r, include_key=include_key) for r in rows]


def get_host(host_id: str, *, include_key: bool = False) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM hosts WHERE id = ?", (host_id,)).fetchone()
    if row is None:
        return None
    return _row_to_host(row, include_key=include_key)


def create_host(payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    name = str(payload.get("name") or "").strip()
    host = str(payload.get("host") or "").strip()
    port, port_err = _parse_port(payload.get("port", 22))
    if port_err or port is None:
        return None, port_err
    default_username = str(payload.get("default_username") or "").strip()
    description = str(payload.get("description") or "").strip()
    host_key = str(payload.get("host_key") or "").strip()
    enabled = bool(payload.get("enabled", True))
    err = validate_host_fields(
        name=name,
        host=host,
        port=port,
        default_username=default_username,
        description=description,
        host_key=host_key,
    )
    if err:
        return None, err
    now = _now_iso()
    host_id = str(uuid.uuid4())
    db = connect()
    with _lock:
        db.execute(
            """
            INSERT INTO hosts (
              id, name, host, port, default_username, description, host_key,
              enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                host_id,
                name,
                host,
                port,
                default_username,
                description,
                host_key,
                1 if enabled else 0,
                now,
                now,
            ),
        )
        db.commit()
    created = get_host(host_id, include_key=True)
    return created, None


def update_host(host_id: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    current = get_host(host_id, include_key=True)
    if current is None:
        return None, "接続先が見つかりません"
    name = str(payload.get("name", current["name"]) or "").strip()
    host = str(payload.get("host", current["host"]) or "").strip()
    port, port_err = _parse_port(payload.get("port", current["port"]), current["port"])
    if port_err or port is None:
        return None, port_err
    default_username = str(
        payload.get("default_username", current["default_username"]) or ""
    ).strip()
    description = str(payload.get("description", current["description"]) or "").strip()
    if "host_key" in payload:
        host_key = str(payload.get("host_key") or "").strip()
    else:
        host_key = current.get("host_key") or ""
    enabled = bool(payload.get("enabled", current["enabled"]))
    err = validate_host_fields(
        name=name,
        host=host,
        port=port,
        default_username=default_username,
        description=description,
        host_key=host_key,
    )
    if err:
        return None, err
    db = connect()
    with _lock:
        db.execute(
            """
            UPDATE hosts SET
              name = ?, host = ?, port = ?, default_username = ?,
              description = ?, host_key = ?, enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                host,
                port,
                default_username,
                description,
                host_key,
                1 if enabled else 0,
                _now_iso(),
                host_id,
            ),
        )
        db.commit()
    return get_host(host_id, include_key=True), None


def delete_host(host_id: str) -> bool:
    db = connect()
    with _lock:
        cur = db.execute("DELETE FROM hosts WHERE id = ?", (host_id,))
        db.commit()
    return cur.rowcount > 0


def set_host_key(host_id: str, host_key: str) -> None:
    db = connect()
    with _lock:
        db.execute(
            "UPDATE hosts SET host_key = ?, updated_at = ? WHERE id = ?",
            (host_key.strip(), _now_iso(), host_id),
        )
        db.commit()
