"""ノート作業の SQLite 永続化。"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
import json
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
            CREATE TABLE IF NOT EXISTS source_refs (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              scope TEXT NOT NULL,
              doc_id TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL DEFAULT '',
              briefing TEXT NOT NULL DEFAULT '',
              nodes TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_hearing_refs_session ON source_refs(session_id);
            CREATE TABLE IF NOT EXISTS messages (
              id TEXT PRIMARY KEY,
              session_id TEXT NOT NULL,
              role TEXT NOT NULL,
              content TEXT NOT NULL DEFAULT '',
              citations TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_hearing_messages_session ON messages(session_id, created_at);
            """
        )
        cols = {r[1] for r in db.execute("PRAGMA table_info(files)").fetchall()}
        if "briefing" not in cols:
            db.execute("ALTER TABLE files ADD COLUMN briefing TEXT NOT NULL DEFAULT ''")
        if "nodes" not in cols:
            db.execute("ALTER TABLE files ADD COLUMN nodes TEXT NOT NULL DEFAULT '[]'")
        item_cols = {r[1] for r in db.execute("PRAGMA table_info(items)").fetchall()}
        if "citations" not in item_cols:
            db.execute("ALTER TABLE items ADD COLUMN citations TEXT NOT NULL DEFAULT '[]'")
        db.commit()


def _touch(db: sqlite3.Connection, session_id: str) -> None:
    db.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now_iso(), session_id),
    )


def create_session(*, user_id: str, title: str = "") -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = _now_iso()
    name = (title or "").strip() or "新しいノート"
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
            "SELECT s.id, s.title, s.created_at, s.updated_at,"
            " (SELECT COUNT(*) FROM items i WHERE i.session_id = s.id) AS item_count,"
            " (SELECT COUNT(*) FROM items i WHERE i.session_id = s.id"
            "  AND TRIM(i.value) != '') AS filled_count"
            " FROM sessions s WHERE s.user_id = ? ORDER BY s.updated_at DESC",
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
            "SELECT id, label, value, position, citations FROM items"
            " WHERE session_id = ? ORDER BY position",
            (session_id,),
        ).fetchall()
        files = db.execute(
            "SELECT id, filename, error, created_at, briefing, nodes FROM files"
            " WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        refs = db.execute(
            "SELECT id, scope, doc_id, source, title, briefing, created_at, nodes"
            " FROM source_refs WHERE session_id = ?",
            (session_id,),
        ).fetchall()
        messages = db.execute(
            "SELECT id, role, content, citations, created_at FROM messages"
            " WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
    return {
        "id": row["id"],
        "title": row["title"],
        "instruction": row["instruction"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "items": [_public_item(i) for i in items],
        "files": [_public_file(f) for f in files],
        "knowledge_refs": [_public_ref(r) for r in refs],
        "messages": [_public_message(m) for m in messages],
    }


def _parse_json(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw or "") if raw else fallback
    except json.JSONDecodeError:
        return fallback


def _public_item(i: sqlite3.Row) -> dict[str, Any]:
    cites = _parse_json(i["citations"] if "citations" in i.keys() else "[]", [])
    return {
        "id": i["id"],
        "label": i["label"],
        "value": i["value"],
        "citations": cites if isinstance(cites, list) else [],
    }


def _public_file(f: sqlite3.Row) -> dict[str, Any]:
    nodes = _parse_json(f["nodes"] if "nodes" in f.keys() else "[]", [])
    briefing = _parse_json(f["briefing"] if "briefing" in f.keys() else "", {})
    if not isinstance(briefing, dict):
        briefing = {}
    return {
        "id": f["id"],
        "filename": f["filename"],
        "error": f["error"] or None,
        "created_at": f["created_at"],
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "briefing": briefing,
    }


def _public_ref(r: sqlite3.Row) -> dict[str, Any]:
    briefing = _parse_json(r["briefing"], {})
    if not isinstance(briefing, dict):
        briefing = {}
    nodes = _parse_json(r["nodes"] if "nodes" in r.keys() else "[]", [])
    return {
        "id": r["id"],
        "scope": r["scope"],
        "doc_id": r["doc_id"],
        "source": r["source"],
        "title": r["title"] or r["source"],
        "created_at": r["created_at"],
        "node_count": len(nodes) if isinstance(nodes, list) else 0,
        "briefing": briefing,
    }


def _public_message(m: sqlite3.Row) -> dict[str, Any]:
    cites = _parse_json(m["citations"], [])
    return {
        "id": m["id"],
        "role": m["role"],
        "content": m["content"],
        "citations": cites if isinstance(cites, list) else [],
        "created_at": m["created_at"],
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
                (title.strip() or "新しいノート", session_id),
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
    citations: list[dict[str, Any]] | None = None,
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
        if citations is None:
            next_cites = row["citations"] if "citations" in row.keys() else "[]"
        else:
            next_cites = json.dumps(citations, ensure_ascii=False)
        db.execute(
            "UPDATE items SET label = ?, value = ?, citations = ? WHERE id = ?",
            (next_label, next_value, next_cites, item_id),
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
    session_id: str,
    user_id: str,
    *,
    filename: str,
    raw: bytes,
    error: str = "",
    nodes: list[dict[str, Any]] | None = None,
    briefing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    file_id = str(uuid.uuid4())
    with _lock:
        if not _owned(session_id, user_id):
            return None
        db.execute(
            "INSERT INTO files (id, session_id, filename, blob, error, created_at,"
            " briefing, nodes) VALUES (?,?,?,?,?,?,?,?)",
            (
                file_id,
                session_id,
                filename,
                raw,
                error,
                _now_iso(),
                json.dumps(briefing or {}, ensure_ascii=False),
                json.dumps(nodes or [], ensure_ascii=False),
            ),
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


def list_material_nodes(session_id: str, user_id: str) -> list[dict[str, Any]] | None:
    """アップロードとナレッジ参照の節を、retrieve 用にフラット化する。"""
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return None
        files = db.execute(
            "SELECT filename, nodes FROM files WHERE session_id = ? AND error = ''",
            (session_id,),
        ).fetchall()
        refs = db.execute(
            "SELECT source, title, nodes FROM source_refs WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for f in files:
        for n in _parse_json(f["nodes"], []):
            if not isinstance(n, dict):
                continue
            out.append({**n, "source": f["filename"]})
    for r in refs:
        for n in _parse_json(r["nodes"], []):
            if not isinstance(n, dict):
                continue
            out.append({**n, "source": r["title"] or r["source"]})
    return out


def add_knowledge_ref(
    session_id: str,
    user_id: str,
    *,
    scope: str,
    doc_id: str,
    source: str,
    title: str,
    nodes: list[dict[str, Any]],
    briefing: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    ref_id = str(uuid.uuid4())
    with _lock:
        if not _owned(session_id, user_id):
            return None
        exists = db.execute(
            "SELECT id FROM source_refs WHERE session_id = ? AND scope = ? AND doc_id = ?",
            (session_id, scope, doc_id),
        ).fetchone()
        if exists:
            db.execute(
                "UPDATE source_refs SET source=?, title=?, briefing=?, nodes=? WHERE id=?",
                (
                    source,
                    title,
                    json.dumps(briefing or {}, ensure_ascii=False),
                    json.dumps(nodes, ensure_ascii=False),
                    exists["id"],
                ),
            )
        else:
            db.execute(
                "INSERT INTO source_refs (id, session_id, scope, doc_id, source, title,"
                " briefing, nodes, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    ref_id,
                    session_id,
                    scope,
                    doc_id,
                    source,
                    title,
                    json.dumps(briefing or {}, ensure_ascii=False),
                    json.dumps(nodes, ensure_ascii=False),
                    _now_iso(),
                ),
            )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def delete_knowledge_ref(
    session_id: str, user_id: str, ref_id: str
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return None
        db.execute(
            "DELETE FROM source_refs WHERE id = ? AND session_id = ?",
            (ref_id, session_id),
        )
        _touch(db, session_id)
        db.commit()
    return get_session(session_id, user_id)


def add_message(
    session_id: str,
    user_id: str,
    *,
    role: str,
    content: str,
    citations: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    msg_id = str(uuid.uuid4())
    with _lock:
        if not _owned(session_id, user_id):
            return None
        db.execute(
            "INSERT INTO messages (id, session_id, role, content, citations, created_at)"
            " VALUES (?,?,?,?,?,?)",
            (
                msg_id,
                session_id,
                role,
                content,
                json.dumps(citations or [], ensure_ascii=False),
                _now_iso(),
            ),
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
