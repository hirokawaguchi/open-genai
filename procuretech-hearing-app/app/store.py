"""ナビゲーションシート作業の SQLite 永続化。"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

def _db_path() -> str:
    return os.environ.get("HEARING_DB_PATH", "/data/procuretech_hearing.db")


def _retention_days() -> int:
    return int(os.environ.get("HEARING_RETENTION_DAYS", "30"))

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    path = _db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
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
              title TEXT NOT NULL DEFAULT '',
              instruction TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS items (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              position INTEGER NOT NULL,
              label TEXT NOT NULL DEFAULT '',
              value TEXT NOT NULL DEFAULT '',
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS files (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              filename TEXT NOT NULL,
              blob BLOB NOT NULL,
              error TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL,
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_hearing_sessions_user ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS idx_hearing_items_session ON items(session_id, position);
            CREATE INDEX IF NOT EXISTS idx_hearing_files_session ON files(session_id);
            """
        )
        db.commit()


def _touch(db: sqlite3.Connection, session_id: str) -> None:
    db.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now_iso(), session_id),
    )


def create_session(*, user_id: str, title: str = "") -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = _now_iso()
    name = (title or "").strip() or "新しいシート"
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO sessions (id, user_id, title, instruction, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (session_id, user_id, name, "", now, now),
        )
        db.commit()
    return get_session(session_id, user_id) or {}


def list_sessions(user_id: str) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT id, title, created_at, updated_at FROM sessions"
            " WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _owned(session_id: str, user_id: str) -> sqlite3.Row | None:
    db = connect()
    return db.execute(
        "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()


def get_session(session_id: str, user_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = _owned(session_id, user_id)
        if not row:
            return None
        items = db.execute(
            "SELECT id, label, value, position FROM items"
            " WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
        files = db.execute(
            "SELECT id, filename, error, created_at FROM files WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    return {
        "id": row["id"],
        "title": row["title"],
        "instruction": row["instruction"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "items": [
            {"id": i["id"], "label": i["label"], "value": i["value"]} for i in items
        ],
        "files": [
            {
                "id": f["id"],
                "filename": f["filename"],
                "error": f["error"] or None,
                "created_at": f["created_at"],
            }
            for f in files
        ],
    }


def update_session(
    session_id: str,
    user_id: str,
    *,
    title: str | None = None,
    instruction: str | None = None,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return None
        if title is not None:
            db.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title.strip() or "新しいシート", session_id),
            )
        if instruction is not None:
            db.execute(
                "UPDATE sessions SET instruction = ? WHERE id = ?",
                (instruction, session_id),
            )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def delete_session(session_id: str, user_id: str) -> bool:
    db = connect()
    with _lock:
        cur = db.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        )
        db.commit()
    return cur.rowcount > 0


def add_item(session_id: str, user_id: str, *, label: str = "") -> dict[str, Any] | None:
    db = connect()
    item_id = str(uuid.uuid4())
    with _lock:
        if not _owned(session_id, user_id):
            return None
        pos = db.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 AS n FROM items WHERE session_id = ?",
            (session_id,),
        ).fetchone()["n"]
        db.execute(
            "INSERT INTO items (id, session_id, position, label, value) VALUES (?,?,?,?,?)",
            (item_id, session_id, pos, label, ""),
        )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def update_item(
    session_id: str,
    user_id: str,
    item_id: str,
    *,
    label: str | None = None,
    value: str | None = None,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return None
        row = db.execute(
            "SELECT * FROM items WHERE id = ? AND session_id = ?",
            (item_id, session_id),
        ).fetchone()
        if not row:
            return None
        next_label = row["label"] if label is None else label
        next_value = row["value"] if value is None else value
        db.execute(
            "UPDATE items SET label = ?, value = ? WHERE id = ?",
            (next_label, next_value, item_id),
        )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def delete_item(session_id: str, user_id: str, item_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return None
        db.execute(
            "DELETE FROM items WHERE id = ? AND session_id = ?",
            (item_id, session_id),
        )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def add_file(
    session_id: str, user_id: str, *, filename: str, raw: bytes, error: str = ""
) -> dict[str, Any] | None:
    db = connect()
    file_id = str(uuid.uuid4())
    with _lock:
        if not _owned(session_id, user_id):
            return None
        db.execute(
            "INSERT INTO files (id, session_id, filename, blob, error, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (file_id, session_id, filename, raw, error, _now_iso()),
        )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def delete_file(session_id: str, user_id: str, file_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return None
        db.execute(
            "DELETE FROM files WHERE id = ? AND session_id = ?",
            (file_id, session_id),
        )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def list_file_blobs(session_id: str, user_id: str) -> list[tuple[str, bytes, str]] | None:
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return None
        rows = db.execute(
            "SELECT filename, blob, error FROM files WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    return [(r["filename"], bytes(r["blob"]), r["error"] or "") for r in rows]


def delete_old_sessions(days: int | None = None) -> int:
    if days is None:
        days = _retention_days()
    from datetime import timedelta

    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    db = connect()
    with _lock:
        cur = db.execute("DELETE FROM sessions WHERE updated_at < ?", (cutoff,))
        db.commit()
    return cur.rowcount
