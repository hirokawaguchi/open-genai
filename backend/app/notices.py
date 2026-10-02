"""利用者向けのお知らせ。

全体向けはシステム管理者、棟向けは組織棟・共有棟の管理者が書く。
個人棟の本人には投稿欄を出さない。サイト固有の文面は extra_items で足す。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Callable

DB_PATH = os.environ.get("DB_PATH", "/data/open-genai.db")
MAX_BODY = 4000

_lock = threading.Lock()
_ready = False


def extra_items(user_id: str) -> list[dict[str, Any]]:
    """サイトが差し替える。課金案内など、この表に無い文面。"""
    del user_id
    return []


_extra_items: Callable[[str], list[dict[str, Any]]] = extra_items


def set_extra_items(fn: Callable[[str], list[dict[str, Any]]]) -> None:
    global _extra_items
    _extra_items = fn


def _now() -> str:
    return str(int(time.time() * 1000))


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    global _ready
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notices (
                noticeId TEXT PRIMARY KEY,
                scope TEXT NOT NULL,
                tenantId TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                authorId TEXT NOT NULL,
                createdDate TEXT NOT NULL,
                updatedDate TEXT NOT NULL
            )
            """
        )
    _ready = True


def _ensure() -> None:
    if not _ready:
        init_db()


def _row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "noticeId": row["noticeId"],
        "scope": row["scope"],
        "tenantId": row["tenantId"],
        "body": row["body"],
        "authorId": row["authorId"],
        "createdDate": row["createdDate"],
        "updatedDate": row["updatedDate"],
        "readOnly": False,
    }


def list_visible(tenant_id: str, user_id: str) -> list[dict[str, Any]]:
    _ensure()
    tid = (tenant_id or "").strip()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM notices
            WHERE scope = 'all' OR (scope = 'tenant' AND tenantId = ?)
            ORDER BY createdDate DESC
            """,
            (tid,),
        ).fetchall()
    items = list(_extra_items(user_id) or [])
    items.extend(_row(row) for row in rows)
    return items


def create_notice(
    *,
    scope: str,
    tenant_id: str,
    body: str,
    author_id: str,
) -> dict[str, Any]:
    _ensure()
    text = (body or "").strip()
    if not text:
        raise ValueError("本文が空です")
    if len(text) > MAX_BODY:
        raise ValueError(f"本文は {MAX_BODY} 文字までです")
    if scope not in ("all", "tenant"):
        raise ValueError("scope が不正です")
    if scope == "all":
        tenant_id = ""
    elif not tenant_id:
        raise ValueError("棟が指定されていません")
    now = _now()
    notice_id = str(uuid.uuid4())
    with _lock, _connect() as conn:
        conn.execute(
            """
            INSERT INTO notices
            (noticeId, scope, tenantId, body, authorId, createdDate, updatedDate)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (notice_id, scope, tenant_id, text, author_id, now, now),
        )
        row = conn.execute(
            "SELECT * FROM notices WHERE noticeId = ?", (notice_id,)
        ).fetchone()
    return _row(row)


def get_notice(notice_id: str) -> dict[str, Any] | None:
    _ensure()
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM notices WHERE noticeId = ?", (notice_id,)
        ).fetchone()
    return _row(row) if row else None


def delete_notice(notice_id: str) -> bool:
    _ensure()
    with _lock, _connect() as conn:
        cur = conn.execute("DELETE FROM notices WHERE noticeId = ?", (notice_id,))
        return cur.rowcount > 0
