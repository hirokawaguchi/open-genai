"""RAG に取り込む URL（Web ページ）のレジストリ。

6-(26) の「URL 読み込み・自動更新」のため、取り込み対象 URL を保持し、
スケジューラが定期的に再クロールできるようにする。SQLite に別テーブルとして持つ。
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

# 旧 FOLDERS_DB_PATH からの移行を考慮しつつ、RAG_META_DB_PATH を優先。
DB_PATH = os.environ.get(
    "RAG_META_DB_PATH", os.environ.get("FOLDERS_DB_PATH", "/data/rag_meta.db")
)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS url_sources ("
            " scope TEXT NOT NULL,"
            " url TEXT NOT NULL,"
            " tags TEXT NOT NULL DEFAULT '[]',"
            " title TEXT NOT NULL DEFAULT '',"
            " contentHash TEXT NOT NULL DEFAULT '',"
            " lastFetched TEXT NOT NULL DEFAULT '',"
            " createdDate TEXT NOT NULL,"
            " updatedDate TEXT NOT NULL,"
            " PRIMARY KEY (scope, url))"
        )


def _now() -> str:
    return str(int(time.time() * 1000))


def add_url(scope: str, url: str, tags: list[str] | None = None, title: str = "") -> None:
    import json

    now = _now()
    tags_json = json.dumps(tags or [], ensure_ascii=False)
    with _connect() as conn:
        conn.execute(
            "INSERT INTO url_sources (scope, url, tags, title, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(scope, url) DO UPDATE SET tags = excluded.tags,"
            " title = excluded.title, updatedDate = excluded.updatedDate",
            (scope, url, tags_json, title, now, now),
        )


def mark_fetched(scope: str, url: str, content_hash: str, title: str = "") -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE url_sources SET contentHash = ?, lastFetched = ?, updatedDate = ?"
            + (", title = ?" if title else "")
            + " WHERE scope = ? AND url = ?",
            (
                (content_hash, _now(), _now(), title, scope, url)
                if title
                else (content_hash, _now(), _now(), scope, url)
            ),
        )


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    import json

    d = dict(r)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["tags"] = []
    return d


def list_urls(scope: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT url, tags, title, lastFetched FROM url_sources"
            " WHERE scope = ? ORDER BY url",
            (scope,),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_url(scope: str, url: str) -> dict[str, Any] | None:
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM url_sources WHERE scope = ? AND url = ?", (scope, url)
        ).fetchone()
    return _row_to_dict(r) if r else None


def delete_url(scope: str, url: str) -> None:
    with _connect() as conn:
        conn.execute(
            "DELETE FROM url_sources WHERE scope = ? AND url = ?", (scope, url)
        )


def delete_scope(scope: str) -> int:
    """指定スコープの URL 登録をすべて削除する（全消去・チーム削除時）。"""
    with _connect() as conn:
        cur = conn.execute("DELETE FROM url_sources WHERE scope = ?", (scope,))
        return cur.rowcount or 0


def reassign_scope(from_scope: str, to_scope: str) -> int:
    """URL 登録の scope を付け替える（誤登録スコープの移行用）。

    to_scope に同一 URL がある場合は from_scope 側を削除し、衝突を避ける。
    """
    if from_scope == to_scope:
        return 0
    with _connect() as conn:
        existing = {
            r["url"]
            for r in conn.execute(
                "SELECT url FROM url_sources WHERE scope = ?", (to_scope,)
            ).fetchall()
        }
        rows = conn.execute(
            "SELECT url FROM url_sources WHERE scope = ?", (from_scope,)
        ).fetchall()
        moved = 0
        for r in rows:
            url = r["url"]
            if url in existing:
                conn.execute(
                    "DELETE FROM url_sources WHERE scope = ? AND url = ?",
                    (from_scope, url),
                )
            else:
                conn.execute(
                    "UPDATE url_sources SET scope = ? WHERE scope = ? AND url = ?",
                    (to_scope, from_scope, url),
                )
                moved += 1
        return moved


def scope_urls(scope: str) -> list[dict[str, Any]]:
    """指定スコープの全カラム付き URL 行（当該チームの再クロール用）。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM url_sources WHERE scope = ?", (scope,)
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def all_urls() -> list[dict[str, Any]]:
    """全スコープの登録 URL（スケジューラの再クロール用）。"""
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM url_sources").fetchall()
    return [_row_to_dict(r) for r in rows]
