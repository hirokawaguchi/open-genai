"""タグレジストリ（スコープ内のタグ定義）。

ドキュメント付与タグとは別に、「空のタグ」も持てるようにする。
同一 DB（RAG_META_DB_PATH）に保存する。
"""

from __future__ import annotations

import os
import sqlite3
import time
from typing import Any

try:  # パッケージとして読み込まれた場合（本番アプリ）
    from . import textnorm
except ImportError:  # 単体モジュールとして読み込まれた場合（テスト）
    import textnorm

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
            """
            CREATE TABLE IF NOT EXISTS tags (
              scope TEXT NOT NULL,
              tag TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              PRIMARY KEY (scope, tag)
            )
            """
        )


def _now() -> str:
    return str(int(time.time() * 1000))


def ensure_tags(scope: str, tags: list[str]) -> list[str]:
    """タグをレジストリに登録（既存は無視）。正規化済みタグ一覧を返す。"""
    cleaned = textnorm.normalize_tags(tags)
    if not cleaned:
        return []
    now = _now()
    with _connect() as conn:
        for name in cleaned:
            conn.execute(
                """
                INSERT INTO tags (scope, tag, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(scope, tag) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (scope, name, now, now),
            )
    return cleaned


def create_tag(scope: str, tag: str) -> str:
    name = textnorm.normalize_tag(tag)
    if not name:
        raise ValueError("タグ名が空です")
    ensure_tags(scope, [name])
    return name


def list_tags(scope: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT tag, created_at, updated_at FROM tags WHERE scope = ? ORDER BY tag",
            (scope,),
        ).fetchall()
    return [dict(r) for r in rows]


def rename_tag(scope: str, old: str, new: str) -> None:
    old_n = textnorm.normalize_tag(old)
    new_n = textnorm.normalize_tag(new)
    if not old_n or not new_n:
        raise ValueError("タグ名が空です")
    if old_n == new_n:
        return
    now = _now()
    with _connect() as conn:
        exists = conn.execute(
            "SELECT 1 FROM tags WHERE scope = ? AND tag = ?", (scope, old_n)
        ).fetchone()
        if not exists:
            raise ValueError(f"タグ「{old_n}」は存在しません")
        conflict = conn.execute(
            "SELECT 1 FROM tags WHERE scope = ? AND tag = ?", (scope, new_n)
        ).fetchone()
        if conflict:
            raise ValueError(f"タグ「{new_n}」は既に存在します")
        conn.execute(
            "UPDATE tags SET tag = ?, updated_at = ? WHERE scope = ? AND tag = ?",
            (new_n, now, scope, old_n),
        )


def delete_tag(scope: str, tag: str) -> None:
    name = (tag or "").strip()
    if not name:
        raise ValueError("タグ名が空です")
    with _connect() as conn:
        cur = conn.execute(
            "DELETE FROM tags WHERE scope = ? AND tag = ?", (scope, name)
        )
        if (cur.rowcount or 0) == 0:
            raise ValueError(f"タグ「{name}」は存在しません")


def delete_scope(scope: str) -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM tags WHERE scope = ?", (scope,))
        return cur.rowcount or 0
