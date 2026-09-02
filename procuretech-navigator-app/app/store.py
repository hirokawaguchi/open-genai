"""procureTech Navigator の SQLite 永続化。

ユーザーごとにセッション（＝1冊の情報化企画書 Excel）を保持し、分野別のチャット履歴と
書き戻し済みブックを管理する。他ユーザーのセッションは参照できない。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

DB_PATH = os.environ.get("PROCURETECH_DB_PATH", "/data/procuretech.db")
RETENTION_DAYS = int(os.environ.get("PROCURETECH_RETENTION_DAYS", "30"))

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _db = conn
    return conn


def init_db() -> None:
    db = connect()
    with _lock:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              filename TEXT NOT NULL,
              original_blob BLOB NOT NULL,
              current_blob BLOB NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              session_id TEXT NOT NULL,
              section TEXT NOT NULL,
              role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
              content TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS section_outputs (
              session_id TEXT NOT NULL,
              section TEXT NOT NULL,
              content TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (session_id, section),
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, section);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            """
        )
        db.commit()


def _row_to_session_meta(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "filename": row["filename"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def create_session(*, user_id: str, filename: str, raw: bytes) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = _now_iso()
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO sessions (id, user_id, filename, original_blob, current_blob, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (session_id, user_id, filename, raw, raw, now, now),
        )
        db.commit()
    return {"id": session_id, "filename": filename, "created_at": now, "updated_at": now}


def get_session_row(session_id: str, user_id: str) -> sqlite3.Row | None:
    db = connect()
    with _lock:
        return db.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()


def get_current_blob(session_id: str, user_id: str) -> tuple[bytes, str] | None:
    row = get_session_row(session_id, user_id)
    if not row:
        return None
    return bytes(row["current_blob"]), row["filename"]


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT id, filename, created_at, updated_at FROM sessions "
            "WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [_row_to_session_meta(r) for r in rows]


def get_messages(session_id: str, section: str) -> list[dict[str, str]]:
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT role, content, created_at FROM messages "
            "WHERE session_id = ? AND section = ? ORDER BY id",
            (session_id, section),
        ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        for r in rows
    ]


def get_all_messages(session_id: str) -> dict[str, list[dict[str, str]]]:
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT section, role, content, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
    out: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        out.setdefault(r["section"], []).append(
            {"role": r["role"], "content": r["content"], "created_at": r["created_at"]}
        )
    return out


def get_outputs(session_id: str) -> dict[str, dict[str, str]]:
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT section, content, updated_at FROM section_outputs WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    return {
        r["section"]: {"content": r["content"], "updated_at": r["updated_at"]} for r in rows
    }


def append_message(session_id: str, section: str, role: str, content: str) -> str:
    now = _now_iso()
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO messages (session_id, section, role, content, created_at) "
            "VALUES (?,?,?,?,?)",
            (session_id, section, role, content, now),
        )
        db.execute(
            "UPDATE sessions SET updated_at = ? WHERE id = ?", (now, session_id)
        )
        db.commit()
    return now


def clear_section(session_id: str, section: str) -> None:
    db = connect()
    with _lock:
        db.execute(
            "DELETE FROM messages WHERE session_id = ? AND section = ?",
            (session_id, section),
        )
        db.execute(
            "DELETE FROM section_outputs WHERE session_id = ? AND section = ?",
            (session_id, section),
        )
        db.commit()


def save_output(
    session_id: str, section: str, content: str, new_blob: bytes
) -> str:
    """書き戻し結果（本文 + 更新後ブック）を保存する。"""
    now = _now_iso()
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO section_outputs (session_id, section, content, updated_at) "
            "VALUES (?,?,?,?) ON CONFLICT(session_id, section) DO UPDATE SET "
            "content = excluded.content, updated_at = excluded.updated_at",
            (session_id, section, content, now),
        )
        db.execute(
            "UPDATE sessions SET current_blob = ?, updated_at = ? WHERE id = ?",
            (new_blob, now, session_id),
        )
        db.commit()
    return now


def delete_session(session_id: str, user_id: str) -> bool:
    db = connect()
    with _lock:
        cur = db.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id)
        )
        db.commit()
        return cur.rowcount > 0


def delete_old_sessions(retention_days: int | None = None) -> int:
    days = retention_days if retention_days is not None else RETENTION_DAYS
    cutoff = (
        (datetime.now(timezone.utc) - timedelta(days=days))
        .replace(microsecond=0)
        .isoformat()
    )
    db = connect()
    with _lock:
        cur = db.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        db.commit()
        return cur.rowcount
