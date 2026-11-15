"""外部システム用の台帳トークン。

ブラウザのログインセッションとは別です。文字列は発行時に一度だけ返し、
保存するのはハッシュだけです。失効させるとその場で使えなくなります。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import threading
import time
import uuid

_lock = threading.Lock()
_ready_path: str | None = None


def _path() -> str:
    return os.environ.get("SERVICE_TOKEN_DB_PATH", "/data/service-tokens.db")


def _connect() -> sqlite3.Connection:
    global _ready_path
    path = _path()
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    if _ready_path != path:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS service_tokens (
                id TEXT PRIMARY KEY,
                token_hash TEXT NOT NULL UNIQUE,
                user_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                label TEXT NOT NULL,
                created_by TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                revoked_at INTEGER,
                last_used_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_service_tokens_tenant
                ON service_tokens(tenant_id, created_at);
            """
        )
        _ready_path = path
    return conn


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _public(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "tenantId": row["tenant_id"],
        "label": row["label"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "revokedAt": row["revoked_at"],
        "lastUsedAt": row["last_used_at"],
    }


def issue(user_id: str, tenant_id: str, label: str, created_by: str) -> tuple[str, dict]:
    secret = "ogst_" + secrets.token_urlsafe(32)
    now = int(time.time())
    row_id = str(uuid.uuid4())
    with _lock:
        conn = _connect()
        try:
            conn.execute(
                "INSERT INTO service_tokens "
                "(id, token_hash, user_id, tenant_id, label, created_by, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row_id, _hash(secret), user_id, tenant_id, label, created_by, now),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM service_tokens WHERE id = ?", (row_id,)).fetchone()
        finally:
            conn.close()
    return secret, _public(row)


def resolve(secret: str) -> dict | None:
    if not secret.startswith("ogst_"):
        return None
    now = int(time.time())
    with _lock:
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT * FROM service_tokens WHERE token_hash = ?",
                (_hash(secret),),
            ).fetchone()
            if row is None or row["revoked_at"] is not None:
                return None
            conn.execute(
                "UPDATE service_tokens SET last_used_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            conn.commit()
            public = _public(row)
            public["lastUsedAt"] = now
            return public
        finally:
            conn.close()


def list_tokens(tenant_id: str) -> list[dict]:
    with _lock:
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT * FROM service_tokens WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
            return [_public(row) for row in rows]
        finally:
            conn.close()


def revoke(token_id: str, tenant_id: str) -> bool:
    now = int(time.time())
    with _lock:
        conn = _connect()
        try:
            cur = conn.execute(
                "UPDATE service_tokens SET revoked_at = ? "
                "WHERE id = ? AND tenant_id = ? AND revoked_at IS NULL",
                (now, token_id, tenant_id),
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()
