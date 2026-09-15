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
              tool_trace TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_hearing_messages_session ON messages(session_id, created_at);
            CREATE TABLE IF NOT EXISTS skills (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              name TEXT NOT NULL,
              personality TEXT NOT NULL DEFAULT '',
              instructions TEXT NOT NULL DEFAULT '',
              tools TEXT NOT NULL DEFAULT '[]',
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hearing_skills_user ON skills(user_id);
            CREATE TABLE IF NOT EXISTS mcp_servers (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              catalog_id TEXT NOT NULL DEFAULT '',
              name TEXT NOT NULL,
              kind TEXT NOT NULL,
              url TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '',
              prompt TEXT NOT NULL DEFAULT '',
              tools TEXT NOT NULL DEFAULT '[]',
              connected INTEGER NOT NULL DEFAULT 1,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_hearing_mcps_user ON mcp_servers(user_id);
            CREATE TABLE IF NOT EXISTS session_mcps (
              session_id TEXT NOT NULL,
              mcp_id TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1,
              PRIMARY KEY (session_id, mcp_id),
              FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
            );
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
        msg_cols = {r[1] for r in db.execute("PRAGMA table_info(messages)").fetchall()}
        if "tool_trace" not in msg_cols:
            db.execute("ALTER TABLE messages ADD COLUMN tool_trace TEXT NOT NULL DEFAULT '[]'")
        db.commit()


def _touch(db: sqlite3.Connection, session_id: str) -> None:
    db.execute(
        "UPDATE sessions SET updated_at = ? WHERE id = ?",
        (_now_iso(), session_id),
    )


def _default_session_title(db: sqlite3.Connection, user_id: str) -> str:
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
    base = f"ノート {stamp}"
    existing = {
        str(r[0])
        for r in db.execute(
            "SELECT title FROM sessions WHERE user_id = ? AND title LIKE ?",
            (user_id, f"{base}%"),
        ).fetchall()
    }
    if base not in existing:
        return base
    n = 2
    while f"{base} ({n})" in existing:
        n += 1
    return f"{base} ({n})"


def create_session(*, user_id: str, title: str = "") -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    now = _now_iso()
    db = connect()
    with _lock:
        name = (title or "").strip() or _default_session_title(db, user_id)
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
            "SELECT id, role, content, citations, tool_trace, created_at FROM messages"
            " WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        mcps = _session_mcps_unlocked(db, session_id, user_id)
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
        "mcps": mcps,
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
    keys = m.keys()
    trace = _parse_json(m["tool_trace"] if "tool_trace" in keys else "[]", [])
    return {
        "id": m["id"],
        "role": m["role"],
        "content": m["content"],
        "citations": cites if isinstance(cites, list) else [],
        "tool_trace": trace if isinstance(trace, list) else [],
        "created_at": m["created_at"],
    }


def update_session(
    session_id: str,
    user_id: str,
    *,
    title: str | None = None,
    instruction: str | None = None,
    mcp_enabled: dict[str, bool] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = _owned(session_id, user_id)
        if not row:
            return None
        if title is not None:
            db.execute(
                "UPDATE sessions SET title = ? WHERE id = ?",
                (title.strip() or row["title"] or "無題", session_id),
            )
        if instruction is not None:
            db.execute(
                "UPDATE sessions SET instruction = ? WHERE id = ?",
                (instruction, session_id),
            )
        if mcp_enabled:
            _ensure_mcps_unlocked(db, user_id)
            for mcp_id, enabled in mcp_enabled.items():
                mid = str(mcp_id or "").strip()
                if not mid:
                    continue
                owned = db.execute(
                    "SELECT id FROM mcp_servers WHERE id = ? AND user_id = ?",
                    (mid, user_id),
                ).fetchone()
                if not owned:
                    continue
                db.execute(
                    "INSERT INTO session_mcps (session_id, mcp_id, enabled)"
                    " VALUES (?,?,?)"
                    " ON CONFLICT(session_id, mcp_id) DO UPDATE SET enabled = excluded.enabled",
                    (session_id, mid, 1 if enabled else 0),
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
    tool_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    msg_id = str(uuid.uuid4())
    with _lock:
        if not _owned(session_id, user_id):
            return None
        db.execute(
            "INSERT INTO messages (id, session_id, role, content, citations, tool_trace,"
            " created_at) VALUES (?,?,?,?,?,?,?)",
            (
                msg_id,
                session_id,
                role,
                content,
                json.dumps(citations or [], ensure_ascii=False),
                json.dumps(tool_trace or [], ensure_ascii=False),
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


_SKILL_TOOLS = (
    "search_sources",
    "list_items",
    "knowledge_list_tags",
    "knowledge_list_docs",
    "knowledge_search",
)

EXAMPLE_SKILLS: list[dict[str, Any]] = [
    {
        "name": "議事録係",
        "personality": "丁寧で正確。決定事項と未決事項を混同しない。",
        "instructions": (
            "ソースの会議内容から、決定事項・未決事項・TODO を分けて下書きする。"
            "発言に無いことは書かない。迷う箇所は〔要確認〕を付ける。"
            "見出しはマークダウンで書く。項目への転記は人が行う。"
        ),
        "tools": ["search_sources", "list_items"],
    },
    {
        "name": "進行管理担当",
        "personality": "簡潔。誰が・何を・いつまでに、だけを拾う。",
        "instructions": (
            "採用済み項目とソースからタスクを「担当・内容・期限・状態」で整理する。"
            "会議で言われていないタスクは推測で足さない。期限が無ければ未定（要確認）。"
        ),
        "tools": ["search_sources", "list_items"],
    },
    {
        "name": "秘書",
        "personality": "先回りして短い報告の材料を揃える。",
        "instructions": (
            "結論サマリー、決定と影響、課題、お願いしたい判断を短く下書きする。"
            "根拠の無い数値は要確認と書く。詳細は補足に回す。"
        ),
        "tools": ["search_sources", "list_items", "knowledge_search"],
    },
    {
        "name": "参謀",
        "personality": "冷静。楽観的な前提を見つけたら警告する。",
        "instructions": (
            "持ち越し論点と放置課題を優先度順に並べ、次回の論点案を下書きする。"
            "根拠の無い項目は入れない。楽観前提があれば確認事項を1つ添える。"
        ),
        "tools": ["search_sources", "list_items", "knowledge_list_tags", "knowledge_search"],
    },
]


def _public_skill(row: sqlite3.Row) -> dict[str, Any]:
    raw = _parse_json(row["tools"], [])
    tool_names = (
        [str(t) for t in raw if str(t) in _SKILL_TOOLS] if isinstance(raw, list) else []
    )
    return {
        "id": row["id"],
        "name": row["name"],
        "personality": row["personality"],
        "instructions": row["instructions"],
        "tools": tool_names,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_skills(user_id: str) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT * FROM skills WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
        if rows:
            return [_public_skill(r) for r in rows]
        now = _now_iso()
        for spec in EXAMPLE_SKILLS:
            db.execute(
                "INSERT INTO skills (id, user_id, name, personality, instructions, tools,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    user_id,
                    spec["name"],
                    spec["personality"],
                    spec["instructions"],
                    json.dumps(spec["tools"], ensure_ascii=False),
                    now,
                    now,
                ),
            )
        db.commit()
        rows = db.execute(
            "SELECT * FROM skills WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
    return [_public_skill(r) for r in rows]


def get_skill(skill_id: str, user_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM skills WHERE id = ? AND user_id = ?",
            (skill_id, user_id),
        ).fetchone()
    return _public_skill(row) if row else None


def create_skill(
    user_id: str,
    *,
    name: str,
    personality: str = "",
    instructions: str = "",
    tool_names: list[str] | None = None,
) -> dict[str, Any]:
    sid = str(uuid.uuid4())
    now = _now_iso()
    allowed = [t for t in (tool_names or []) if t in _SKILL_TOOLS]
    if not allowed:
        allowed = ["search_sources", "list_items"]
    title = (name or "").strip() or "無題のスキル"
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO skills (id, user_id, name, personality, instructions, tools,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                sid,
                user_id,
                title,
                (personality or "").strip(),
                (instructions or "").strip(),
                json.dumps(allowed, ensure_ascii=False),
                now,
                now,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM skills WHERE id = ?", (sid,)).fetchone()
    assert row is not None
    return _public_skill(row)


def update_skill(
    skill_id: str,
    user_id: str,
    *,
    name: str | None = None,
    personality: str | None = None,
    instructions: str | None = None,
    tool_names: list[str] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM skills WHERE id = ? AND user_id = ?",
            (skill_id, user_id),
        ).fetchone()
        if not row:
            return None
        next_name = row["name"] if name is None else ((name or "").strip() or row["name"])
        next_personality = (
            row["personality"] if personality is None else personality.strip()
        )
        next_inst = row["instructions"] if instructions is None else instructions.strip()
        if tool_names is None:
            next_tools = row["tools"]
        else:
            allowed = [t for t in tool_names if t in _SKILL_TOOLS]
            next_tools = json.dumps(
                allowed or ["search_sources", "list_items"], ensure_ascii=False
            )
        db.execute(
            "UPDATE skills SET name=?, personality=?, instructions=?, tools=?, updated_at=?"
            " WHERE id=?",
            (next_name, next_personality, next_inst, next_tools, _now_iso(), skill_id),
        )
        db.commit()
        row = db.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    return _public_skill(row) if row else None


def delete_skill(skill_id: str, user_id: str) -> bool:
    db = connect()
    with _lock:
        cur = db.execute(
            "DELETE FROM skills WHERE id = ? AND user_id = ?",
            (skill_id, user_id),
        )
        db.commit()
    return cur.rowcount > 0


def _parse_tool_specs(raw: Any) -> list[dict[str, Any]]:
    parsed = raw
    if isinstance(raw, str):
        parsed = _parse_json(raw, [])
    if not isinstance(parsed, list):
        return []
    out: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict) and item.get("name"):
            params = item.get("parameters") or item.get("inputSchema") or {}
            out.append(
                {
                    "name": str(item.get("name") or ""),
                    "description": str(item.get("description") or ""),
                    "parameters": params if isinstance(params, dict) else {},
                }
            )
        elif str(item or "").strip():
            out.append(
                {
                    "name": str(item).strip(),
                    "description": "",
                    "parameters": {"type": "object", "properties": {}},
                }
            )
    return out


def _public_mcp(row: sqlite3.Row, *, enabled: bool | None = None) -> dict[str, Any]:
    from . import mcp_catalog

    catalog_id = str(row["catalog_id"] or "")
    spec = mcp_catalog.spec_for(catalog_id)
    runtime = mcp_catalog.catalog_runtime(catalog_id) if spec else {}
    stored_prompt = str(row["prompt"] or "")
    default = (
        mcp_catalog.default_prompt(catalog_id)
        if spec
        else stored_prompt
    )
    prompt = stored_prompt or default
    if spec:
        tools = mcp_catalog.catalog_tools(catalog_id)
        tool_specs: list[dict[str, Any]] = []
        url = str(runtime.get("url") or row["url"] or "")
        available = bool(runtime.get("available"))
        builtin = True
        description = str(spec.get("description") or row["description"] or "")
        name = str(spec.get("name") or row["name"])
        kind = str(spec.get("kind") or row["kind"])
    else:
        tool_specs = _parse_tool_specs(row["tools"])
        tools = [str(t["name"]) for t in tool_specs]
        url = str(row["url"] or "")
        available = bool(url)
        builtin = False
        description = str(row["description"] or "")
        name = str(row["name"])
        kind = str(row["kind"] or "remote")
    out: dict[str, Any] = {
        "id": row["id"],
        "catalog_id": catalog_id,
        "name": name,
        "kind": kind,
        "url": url,
        "description": description,
        "prompt": prompt,
        "default_prompt": default,
        "prompt_is_default": not stored_prompt.strip() or stored_prompt == default,
        "tools": tools,
        "tool_specs": tool_specs,
        "connected": bool(row["connected"]) and available,
        "available": available,
        "builtin": builtin,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if enabled is not None:
        out["enabled"] = bool(enabled) and out["connected"]
    return out


def _ensure_mcps_unlocked(db: sqlite3.Connection, user_id: str) -> list[dict[str, Any]]:
    from . import mcp_catalog

    rows = db.execute(
        "SELECT * FROM mcp_servers WHERE user_id = ? ORDER BY created_at",
        (user_id,),
    ).fetchall()
    have = {str(r["catalog_id"]) for r in rows if r["catalog_id"]}
    now = _now_iso()
    changed = False
    for spec in mcp_catalog.CATALOG:
        cid = str(spec["catalog_id"])
        if cid in have:
            continue
        runtime = mcp_catalog.catalog_runtime(cid)
        db.execute(
            "INSERT INTO mcp_servers (id, user_id, catalog_id, name, kind, url,"
            " description, prompt, tools, connected, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()),
                user_id,
                cid,
                spec["name"],
                spec["kind"],
                str(runtime.get("url") or ""),
                spec["description"],
                "",
                json.dumps(spec["tools"], ensure_ascii=False),
                1 if runtime.get("connected_default") else 0,
                now,
                now,
            ),
        )
        changed = True
    if changed:
        db.commit()
        rows = db.execute(
            "SELECT * FROM mcp_servers WHERE user_id = ? ORDER BY created_at",
            (user_id,),
        ).fetchall()
    return [_public_mcp(r) for r in rows]


def _session_mcps_unlocked(
    db: sqlite3.Connection, session_id: str, user_id: str
) -> list[dict[str, Any]]:
    catalog = _ensure_mcps_unlocked(db, user_id)
    flags = {
        str(r["mcp_id"]): bool(r["enabled"])
        for r in db.execute(
            "SELECT mcp_id, enabled FROM session_mcps WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    }
    out: list[dict[str, Any]] = []
    for item in catalog:
        connected = bool(item.get("connected"))
        default_on = connected
        enabled = flags.get(str(item["id"]), default_on)
        row = dict(item)
        row["enabled"] = bool(enabled) and connected
        out.append(row)
    return out


def list_mcps(user_id: str) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        return _ensure_mcps_unlocked(db, user_id)


def get_mcp(mcp_id: str, user_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM mcp_servers WHERE id = ? AND user_id = ?",
            (mcp_id, user_id),
        ).fetchone()
    return _public_mcp(row) if row else None


def create_mcp(
    user_id: str,
    *,
    name: str,
    url: str,
    prompt: str = "",
    description: str = "",
    tools: list[Any] | None = None,
) -> dict[str, Any]:
    mid = str(uuid.uuid4())
    now = _now_iso()
    title = (name or "").strip() or "追加した MCP"
    endpoint = (url or "").strip()
    desc = (description or "").strip() or "追加したリモート MCP"
    stored_tools = json.dumps(tools or [], ensure_ascii=False)
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO mcp_servers (id, user_id, catalog_id, name, kind, url,"
            " description, prompt, tools, connected, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                mid,
                user_id,
                "",
                title,
                "remote",
                endpoint,
                desc,
                (prompt or "").strip(),
                stored_tools,
                1 if endpoint else 0,
                now,
                now,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM mcp_servers WHERE id = ?", (mid,)).fetchone()
    assert row is not None
    return _public_mcp(row)


def update_mcp(
    mcp_id: str,
    user_id: str,
    *,
    connected: bool | None = None,
    prompt: str | None = None,
    url: str | None = None,
    name: str | None = None,
    description: str | None = None,
    tools: list[Any] | None = None,
    reset_prompt: bool = False,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM mcp_servers WHERE id = ? AND user_id = ?",
            (mcp_id, user_id),
        ).fetchone()
        if not row:
            return None
        next_connected = row["connected"] if connected is None else (1 if connected else 0)
        if reset_prompt:
            next_prompt = ""
        elif prompt is None:
            next_prompt = row["prompt"]
        else:
            next_prompt = prompt
        next_url = row["url"] if url is None else url.strip()
        next_name = row["name"] if name is None else ((name or "").strip() or row["name"])
        next_desc = (
            row["description"] if description is None else description.strip()
        )
        next_tools = row["tools"] if tools is None else json.dumps(tools, ensure_ascii=False)
        db.execute(
            "UPDATE mcp_servers SET name=?, url=?, description=?, prompt=?, tools=?,"
            " connected=?, updated_at=? WHERE id=?",
            (
                next_name,
                next_url,
                next_desc,
                next_prompt,
                next_tools,
                next_connected,
                _now_iso(),
                mcp_id,
            ),
        )
        db.commit()
        row = db.execute("SELECT * FROM mcp_servers WHERE id = ?", (mcp_id,)).fetchone()
    return _public_mcp(row) if row else None


def delete_mcp(mcp_id: str, user_id: str) -> bool:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT catalog_id FROM mcp_servers WHERE id = ? AND user_id = ?",
            (mcp_id, user_id),
        ).fetchone()
        if not row or str(row["catalog_id"] or ""):
            return False
        cur = db.execute(
            "DELETE FROM mcp_servers WHERE id = ? AND user_id = ?",
            (mcp_id, user_id),
        )
        db.commit()
    return cur.rowcount > 0


def enabled_session_mcps(session_id: str, user_id: str) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        if not _owned(session_id, user_id):
            return []
        items = _session_mcps_unlocked(db, session_id, user_id)
    return [m for m in items if m.get("connected") and m.get("enabled")]
