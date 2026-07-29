"""構造化 RAG 用の文書・ページ・ツリー索引ストア（SQLite）。

ベクトル索引(Qdrant)とは別に、全文（ページ単位）と TOC ツリーを保持する。
同一 DB ファイル（RAG_META_DB_PATH）にテーブルを追加する。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from typing import Any

DB_PATH = os.environ.get(
    "RAG_META_DB_PATH", os.environ.get("FOLDERS_DB_PATH", "/data/rag_meta.db")
)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS docs (
              doc_id TEXT PRIMARY KEY,
              scope TEXT NOT NULL,
              source TEXT NOT NULL,
              tags TEXT NOT NULL DEFAULT '[]',
              page_count INTEGER NOT NULL DEFAULT 0,
              char_count INTEGER NOT NULL DEFAULT 0,
              truncated INTEGER NOT NULL DEFAULT 0,
              content_hash TEXT NOT NULL DEFAULT '',
              index_kind TEXT NOT NULL DEFAULT 'tree',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE(scope, source)
            )
            """
        )
        cols = {
            str(r[1]) for r in conn.execute("PRAGMA table_info(docs)").fetchall()
        }
        if "index_kind" not in cols:
            conn.execute(
                "ALTER TABLE docs ADD COLUMN index_kind TEXT NOT NULL DEFAULT 'tree'"
            )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS pages (
              doc_id TEXT NOT NULL,
              page INTEGER NOT NULL,
              text TEXT NOT NULL,
              PRIMARY KEY (doc_id, page),
              FOREIGN KEY (doc_id) REFERENCES docs(doc_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tree_nodes (
              doc_id TEXT NOT NULL,
              node_id TEXT NOT NULL,
              title TEXT NOT NULL,
              summary TEXT NOT NULL DEFAULT '',
              page_start INTEGER NOT NULL,
              page_end INTEGER NOT NULL,
              parent_id TEXT,
              sort_order INTEGER NOT NULL DEFAULT 0,
              PRIMARY KEY (doc_id, node_id),
              FOREIGN KEY (doc_id) REFERENCES docs(doc_id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_docs_scope ON docs(scope)"
        )


def _now() -> str:
    return str(int(time.time() * 1000))


def _tags_json(tags: list[str] | None) -> str:
    from . import textnorm

    return json.dumps(textnorm.normalize_tags(tags), ensure_ascii=False)


def _parse_tags(raw: str | None) -> list[str]:
    from . import textnorm

    try:
        v = json.loads(raw or "[]")
        if isinstance(v, list):
            return textnorm.normalize_tags(str(t) for t in v)
        return []
    except (json.JSONDecodeError, TypeError):
        return []


def new_doc_id() -> str:
    return str(uuid.uuid4())


def upsert_document(
    *,
    scope: str,
    source: str,
    pages: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    tags: list[str] | None = None,
    content_hash: str = "",
    truncated: bool = False,
    index_kind: str = "tree",
    doc_id: str | None = None,
) -> str:
    """文書・ページ・ツリーを一括保存する。同一 (scope, source) は置き換え。

    index_kind:
      - tree: 構造化（標準登録）。TOC ツリーあり
      - fulltext: 全文のみ（簡易／URL）。コンテキスト収まる場合の全文投入用
    """
    now = _now()
    page_count = len(pages)
    char_count = sum(len(p.get("text") or "") for p in pages)
    tags_s = _tags_json(tags)
    kind = (index_kind or "tree").strip().lower()
    if kind not in ("tree", "fulltext"):
        kind = "tree"

    with _connect() as conn:
        existing = conn.execute(
            "SELECT doc_id FROM docs WHERE scope = ? AND source = ?",
            (scope, source),
        ).fetchone()
        if existing:
            doc_id = existing["doc_id"]
            conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM tree_nodes WHERE doc_id = ?", (doc_id,))
            conn.execute(
                """
                UPDATE docs SET tags = ?, page_count = ?, char_count = ?,
                  truncated = ?, content_hash = ?, index_kind = ?, updated_at = ?
                WHERE doc_id = ?
                """,
                (
                    tags_s,
                    page_count,
                    char_count,
                    1 if truncated else 0,
                    content_hash,
                    kind,
                    now,
                    doc_id,
                ),
            )
        else:
            doc_id = doc_id or new_doc_id()
            conn.execute(
                """
                INSERT INTO docs (
                  doc_id, scope, source, tags, page_count, char_count,
                  truncated, content_hash, index_kind, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    doc_id,
                    scope,
                    source,
                    tags_s,
                    page_count,
                    char_count,
                    1 if truncated else 0,
                    content_hash,
                    kind,
                    now,
                    now,
                ),
            )

        conn.executemany(
            "INSERT INTO pages (doc_id, page, text) VALUES (?, ?, ?)",
            [(doc_id, int(p["page"]), p.get("text") or "") for p in pages],
        )
        conn.executemany(
            """
            INSERT INTO tree_nodes (
              doc_id, node_id, title, summary, page_start, page_end,
              parent_id, sort_order
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    doc_id,
                    n["node_id"],
                    n.get("title") or n["node_id"],
                    n.get("summary") or "",
                    int(n["page_start"]),
                    int(n["page_end"]),
                    n.get("parent_id"),
                    int(n.get("sort_order") or 0),
                )
                for n in nodes
            ],
        )
    return doc_id  # type: ignore[return-value]


def _normalize_doc_row(r: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    d = dict(r)
    d["tags"] = _parse_tags(d.get("tags"))
    d["truncated"] = bool(d.get("truncated"))
    d["index_kind"] = (d.get("index_kind") or "tree").strip().lower()
    if d["index_kind"] not in ("tree", "fulltext"):
        d["index_kind"] = "tree"
    return d


def list_docs(scope: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT doc_id, scope, source, tags, page_count, char_count,
                   truncated, content_hash, index_kind, created_at, updated_at
            FROM docs WHERE scope = ? ORDER BY source
            """,
            (scope,),
        ).fetchall()
    from . import textnorm

    out: list[dict[str, Any]] = []
    tag_set = set(textnorm.normalize_tags(tags))
    for r in rows:
        d = _normalize_doc_row(r)
        doc_tags = set(textnorm.normalize_tags(d.get("tags") or []))
        if tag_set and not tag_set.intersection(doc_tags):
            continue
        # 応答も NFC に揃える（LLM がコピーしても照合できる）
        d["tags"] = sorted(doc_tags) if doc_tags else []
        out.append(d)
    return out


def get_doc(doc_id: str, scope: str | None = None) -> dict[str, Any] | None:
    with _connect() as conn:
        if scope:
            r = conn.execute(
                "SELECT * FROM docs WHERE doc_id = ? AND scope = ?",
                (doc_id, scope),
            ).fetchone()
        else:
            r = conn.execute(
                "SELECT * FROM docs WHERE doc_id = ?", (doc_id,)
            ).fetchone()
    if not r:
        return None
    return _normalize_doc_row(r)


def get_doc_by_source(scope: str, source: str) -> dict[str, Any] | None:
    with _connect() as conn:
        r = conn.execute(
            "SELECT * FROM docs WHERE scope = ? AND source = ?",
            (scope, source),
        ).fetchone()
    if not r:
        return None
    return _normalize_doc_row(r)


def get_toc(doc_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT node_id, title, summary, page_start, page_end,
                   parent_id, sort_order
            FROM tree_nodes WHERE doc_id = ?
            ORDER BY sort_order, node_id
            """,
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_children(doc_id: str, parent_id: str | None) -> list[dict[str, Any]]:
    with _connect() as conn:
        if parent_id is None:
            rows = conn.execute(
                """
                SELECT node_id, title, summary, page_start, page_end,
                       parent_id, sort_order
                FROM tree_nodes
                WHERE doc_id = ? AND parent_id IS NULL
                ORDER BY sort_order, node_id
                """,
                (doc_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT node_id, title, summary, page_start, page_end,
                       parent_id, sort_order
                FROM tree_nodes
                WHERE doc_id = ? AND parent_id = ?
                ORDER BY sort_order, node_id
                """,
                (doc_id, parent_id),
            ).fetchall()
    return [dict(r) for r in rows]


def get_node(doc_id: str, node_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        r = conn.execute(
            """
            SELECT node_id, title, summary, page_start, page_end,
                   parent_id, sort_order
            FROM tree_nodes WHERE doc_id = ? AND node_id = ?
            """,
            (doc_id, node_id),
        ).fetchone()
    return dict(r) if r else None


def get_page_texts(doc_id: str, page_start: int, page_end: int) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT page, text FROM pages
            WHERE doc_id = ? AND page >= ? AND page <= ?
            ORDER BY page
            """,
            (doc_id, page_start, page_end),
        ).fetchall()
    return [dict(r) for r in rows]


def get_all_pages(doc_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT page, text FROM pages
            WHERE doc_id = ?
            ORDER BY page
            """,
            (doc_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_nodes_with_text(doc_id: str, node_ids: list[str]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for nid in node_ids:
        node = get_node(doc_id, nid)
        if not node:
            continue
        pages = get_page_texts(doc_id, node["page_start"], node["page_end"])
        text = "\n\n".join(p["text"] for p in pages if p.get("text"))
        out.append({**node, "text": text, "pages": pages})
    return out


def delete_by_source(scope: str, source: str) -> bool:
    doc = get_doc_by_source(scope, source)
    if not doc:
        return False
    with _connect() as conn:
        conn.execute("DELETE FROM docs WHERE doc_id = ?", (doc["doc_id"],))
    return True


def delete_scope(scope: str) -> int:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM docs WHERE scope = ?", (scope,))
        return cur.rowcount or 0


def set_tags(scope: str, source: str, tags: list[str]) -> bool:
    doc = get_doc_by_source(scope, source)
    if not doc:
        return False
    with _connect() as conn:
        conn.execute(
            "UPDATE docs SET tags = ?, updated_at = ? WHERE doc_id = ?",
            (_tags_json(tags), _now(), doc["doc_id"]),
        )
    return True


def rename_tag(scope: str, old: str, new: str) -> int:
    import json

    n = 0
    with _connect() as conn:
        rows = conn.execute(
            "SELECT doc_id, tags FROM docs WHERE scope = ?", (scope,)
        ).fetchall()
        for r in rows:
            try:
                tags = json.loads(r["tags"] or "[]")
            except (json.JSONDecodeError, TypeError):
                tags = []
            if old not in tags:
                continue
            nxt = [new if t == old else t for t in tags]
            seen: list[str] = []
            for t in nxt:
                if t not in seen:
                    seen.append(t)
            conn.execute(
                "UPDATE docs SET tags = ?, updated_at = ? WHERE doc_id = ?",
                (json.dumps(seen, ensure_ascii=False), _now(), r["doc_id"]),
            )
            n += 1
    return n
