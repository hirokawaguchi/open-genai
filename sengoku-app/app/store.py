"""戦国国取りの SQLite 永続化（利用者につき 1 局）。"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

DB_PATH = os.environ.get("SENGOKU_DB_PATH", "/data/sengoku.db")

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
    _db = conn
    return conn


def init_db() -> None:
    db = connect()
    with _lock:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS games (
              user_id TEXT PRIMARY KEY,
              state_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            """
        )
        db.commit()


def load_game(user_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT state_json FROM games WHERE user_id = ?", (user_id,)
        ).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["state_json"])
    except (ValueError, TypeError):
        return None


def save_game(user_id: str, state: dict[str, Any]) -> None:
    db = connect()
    now = _now_iso()
    payload = json.dumps(state, ensure_ascii=False)
    with _lock:
        db.execute(
            """
            INSERT INTO games (user_id, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
              state_json = excluded.state_json,
              updated_at = excluded.updated_at
            """,
            (user_id, payload, now, now),
        )
        db.commit()


def delete_game(user_id: str) -> None:
    db = connect()
    with _lock:
        db.execute("DELETE FROM games WHERE user_id = ?", (user_id,))
        db.commit()
