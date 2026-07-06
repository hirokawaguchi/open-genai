"""Open GENAI ローカルバックエンドの永続化レイヤ。

クラウド版では DynamoDB に保存しているチャット・メッセージを、
ローカルでは SQLite で代替する。スキーマは genai-web が要求する
型（Chat / RecordedMessage）に合わせている。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any

DB_PATH = os.environ.get("DB_PATH", "/data/open-genai.db")

# 既存（userId 無し）チャットの移管先。空の場合は移管せず、どのユーザーからも
# 不可視になる（開発データのため許容）。本番移行時にメール/sub を設定する。
LEGACY_CHAT_OWNER = os.environ.get("LEGACY_CHAT_OWNER", "")

_lock = threading.Lock()


def _now() -> str:
    # フロントは createdDate を `new Date(Number(...))` で扱うためエポック(ms)文字列で返す
    return str(int(time.time() * 1000))


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS chats (
                chatId TEXT PRIMARY KEY,
                id TEXT NOT NULL,
                usecase TEXT NOT NULL DEFAULT '/chat',
                title TEXT NOT NULL DEFAULT '',
                userId TEXT NOT NULL DEFAULT '',
                createdDate TEXT NOT NULL,
                updatedDate TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                messageId TEXT PRIMARY KEY,
                chatId TEXT NOT NULL,
                id TEXT NOT NULL,
                createdDate TEXT NOT NULL,
                usecase TEXT NOT NULL DEFAULT '/chat',
                userId TEXT NOT NULL DEFAULT 'local-user',
                feedback TEXT NOT NULL DEFAULT '',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                trace TEXT,
                llmType TEXT,
                extraData TEXT,
                seq INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS system_contexts (
                systemContextId TEXT PRIMARY KEY,
                userId TEXT NOT NULL,
                systemContextTitle TEXT NOT NULL DEFAULT '',
                systemContext TEXT NOT NULL DEFAULT '',
                sharedTags TEXT NOT NULL DEFAULT '[]',
                isPublic INTEGER NOT NULL DEFAULT 0,
                createdDate TEXT NOT NULL,
                updatedDate TEXT NOT NULL
            );
            """
        )
        _migrate(conn)
        conn.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_chats_user
                ON chats(userId, updatedDate DESC);
            CREATE INDEX IF NOT EXISTS idx_messages_chat
                ON messages(chatId, seq);
            """
        )


def _migrate(conn: sqlite3.Connection) -> None:
    """既存DB（userId 列の無い chats 等）への冪等マイグレーション。"""
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(chats)").fetchall()]
    if "userId" not in cols:
        conn.execute(
            "ALTER TABLE chats ADD COLUMN userId TEXT NOT NULL DEFAULT ''"
        )
        if LEGACY_CHAT_OWNER:
            conn.execute(
                "UPDATE chats SET userId = ? WHERE userId = ''",
                (LEGACY_CHAT_OWNER,),
            )

    # system_contexts の共有タグ(ABAC)対応（加算的・後方互換）
    sc_cols = [
        r["name"] for r in conn.execute("PRAGMA table_info(system_contexts)").fetchall()
    ]
    if "sharedTags" not in sc_cols:
        conn.execute(
            "ALTER TABLE system_contexts ADD COLUMN sharedTags TEXT NOT NULL DEFAULT '[]'"
        )
    if "isPublic" not in sc_cols:
        conn.execute(
            "ALTER TABLE system_contexts ADD COLUMN isPublic INTEGER NOT NULL DEFAULT 0"
        )


def _normalize_usecase(usecase: str) -> str:
    value = (usecase or "/chat").strip()
    if not value.startswith("/"):
        value = f"/{value}"
    return value


def _resolve_chat_usecase(
    conn: sqlite3.Connection, chat_id: str, stored_usecase: str
) -> str:
    """保存済み usecase がデフォルトのとき、先頭メッセージから補完する。"""
    normalized = _normalize_usecase(stored_usecase)
    if normalized not in ("", "/chat"):
        return normalized
    row = conn.execute(
        "SELECT usecase FROM messages"
        " WHERE chatId = ? AND role != 'system'"
        " ORDER BY seq ASC LIMIT 1",
        (chat_id,),
    ).fetchone()
    if row and row["usecase"]:
        return _normalize_usecase(row["usecase"])
    return "/chat"


def create_chat(user_id: str, usecase: str = "/chat") -> dict[str, Any]:
    chat_id = str(uuid.uuid4())
    now = _now()
    normalized_usecase = _normalize_usecase(usecase)
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO chats (chatId, id, usecase, title, userId, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (chat_id, f"chat#{chat_id}", normalized_usecase, "", user_id, now, now),
        )
        row = conn.execute(
            "SELECT * FROM chats WHERE chatId = ?", (chat_id,)
        ).fetchone()
    return _row_to_chat(row)


def _chat_owner(conn: sqlite3.Connection, chat_id: str) -> str | None:
    """チャットの所有者 userId を返す。存在しなければ None。"""
    row = conn.execute(
        "SELECT userId FROM chats WHERE chatId = ?", (chat_id,)
    ).fetchone()
    return row["userId"] if row else None


def _row_to_chat(row: sqlite3.Row) -> dict[str, Any]:
    # フロントは chatId を `chat#<uuid>` 形式で扱い decomposeId で uuid を取り出す。
    # ストレージは uuid をキーに保持し、応答時に `chat#` を付与する。
    return {
        "id": row["id"],
        "chatId": f"chat#{row['chatId']}",
        "usecase": row["usecase"],
        "title": row["title"],
        "createdDate": row["createdDate"],
        "updatedDate": row["updatedDate"],
    }


def list_chats(user_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM chats WHERE userId = ? ORDER BY updatedDate DESC",
            (user_id,),
        ).fetchall()
        chats: list[dict[str, Any]] = []
        for row in rows:
            chat = _row_to_chat(row)
            resolved = _resolve_chat_usecase(conn, row["chatId"], row["usecase"])
            if resolved != row["usecase"]:
                conn.execute(
                    "UPDATE chats SET usecase = ? WHERE chatId = ?",
                    (resolved, row["chatId"]),
                )
            chat["usecase"] = resolved
            chats.append(chat)
    return chats


def find_chat(chat_id: str, user_id: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM chats WHERE chatId = ? AND userId = ?",
            (chat_id, user_id),
        ).fetchone()
        if not row:
            return None
        chat = _row_to_chat(row)
        resolved = _resolve_chat_usecase(conn, row["chatId"], row["usecase"])
        if resolved != row["usecase"]:
            conn.execute(
                "UPDATE chats SET usecase = ? WHERE chatId = ?",
                (resolved, row["chatId"]),
            )
        chat["usecase"] = resolved
        return chat


def update_title(chat_id: str, user_id: str, title: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        # 所有者のチャットのみ更新（不一致は更新されず None を返す）
        conn.execute(
            "UPDATE chats SET title = ?, updatedDate = ? WHERE chatId = ? AND userId = ?",
            (title, _now(), chat_id, user_id),
        )
        row = conn.execute(
            "SELECT * FROM chats WHERE chatId = ? AND userId = ?",
            (chat_id, user_id),
        ).fetchone()
    return _row_to_chat(row) if row else None


def delete_chat(chat_id: str, user_id: str) -> bool:
    """所有者一致時のみ削除する。削除したら True。"""
    with _lock, _connect() as conn:
        if _chat_owner(conn, chat_id) != user_id:
            return False
        conn.execute("DELETE FROM messages WHERE chatId = ?", (chat_id,))
        conn.execute("DELETE FROM chats WHERE chatId = ?", (chat_id,))
    return True


def _row_to_message(row: sqlite3.Row) -> dict[str, Any]:
    msg = {
        "id": row["id"],
        "createdDate": row["createdDate"],
        "messageId": row["messageId"],
        "usecase": row["usecase"],
        "userId": row["userId"],
        "feedback": row["feedback"],
        "role": row["role"],
        "content": row["content"],
    }
    if row["trace"]:
        msg["trace"] = row["trace"]
    if row["llmType"]:
        msg["llmType"] = row["llmType"]
    if row["extraData"]:
        try:
            msg["extraData"] = json.loads(row["extraData"])
        except json.JSONDecodeError:
            pass
    return msg


def list_messages(chat_id: str, user_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        # 所有者でないチャットのメッセージは返さない
        if _chat_owner(conn, chat_id) != user_id:
            return []
        rows = conn.execute(
            "SELECT * FROM messages WHERE chatId = ? ORDER BY seq ASC",
            (chat_id,),
        ).fetchall()
    return [_row_to_message(r) for r in rows]


def update_message_extra_data(
    chat_id: str, user_id: str, message_id: str, extra_data: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """メッセージの extraData を更新する（所有者・存在チェック付き）。"""
    with _lock, _connect() as conn:
        if _chat_owner(conn, chat_id) != user_id:
            return None
        row = conn.execute(
            "SELECT messageId FROM messages WHERE chatId = ? AND messageId = ?",
            (chat_id, message_id),
        ).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE messages SET extraData = ? WHERE chatId = ? AND messageId = ?",
            (json.dumps(extra_data, ensure_ascii=False), chat_id, message_id),
        )
        updated = conn.execute(
            "SELECT * FROM messages WHERE chatId = ? AND messageId = ?",
            (chat_id, message_id),
        ).fetchone()
    return _row_to_message(updated) if updated else None


# ---------------------------------------------------------------------------
# System contexts（保存プロンプト）— クラウドの DynamoDB を SQLite で代替
# ---------------------------------------------------------------------------
def _sc_shared_tags(row: sqlite3.Row) -> list[str]:
    try:
        val = json.loads(row["sharedTags"]) if row["sharedTags"] else []
        return [str(x) for x in val] if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _row_to_system_context(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": f"systemContext#{row['systemContextId']}",
        # フロントは decomposeId で `#` 分割するため composite で返す
        "systemContextId": f"systemContext#{row['systemContextId']}",
        "systemContextTitle": row["systemContextTitle"],
        "systemContext": row["systemContext"],
        # 共有設定(ABAC・加算的)。所有者・全体公開・共有タグ。
        "ownerUser": row["userId"],
        "sharedTags": _sc_shared_tags(row),
        "isPublic": bool(row["isPublic"]),
        "createdDate": row["createdDate"],
    }


def list_system_contexts(user_id: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
    """本人所有 ＋ 全体公開 ＋ 共有タグ一致（tags）の保存プロンプトを返す。"""
    ut = set(tags or [])
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM system_contexts ORDER BY createdDate DESC",
        ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        visible = (
            r["userId"] == user_id
            or bool(r["isPublic"])
            or bool(ut.intersection(_sc_shared_tags(r)))
        )
        if visible:
            out.append(_row_to_system_context(r))
    return out


def create_system_context(
    user_id: str,
    title: str,
    system_context: str,
    shared_tags: list[str] | None = None,
    is_public: bool = False,
) -> dict[str, Any]:
    sc_id = str(uuid.uuid4())
    now = _now()
    tags_json = json.dumps(sorted({t.strip() for t in (shared_tags or []) if t.strip()}))
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO system_contexts"
            " (systemContextId, userId, systemContextTitle, systemContext,"
            "  sharedTags, isPublic, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (sc_id, user_id, title, system_context, tags_json, 1 if is_public else 0, now, now),
        )
        row = conn.execute(
            "SELECT * FROM system_contexts WHERE systemContextId = ?", (sc_id,)
        ).fetchone()
    return _row_to_system_context(row)


def update_system_context_title(
    user_id: str, sc_id: str, title: str
) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE system_contexts SET systemContextTitle = ?, updatedDate = ?"
            " WHERE systemContextId = ? AND userId = ?",
            (title, _now(), sc_id, user_id),
        )
        row = conn.execute(
            "SELECT * FROM system_contexts WHERE systemContextId = ? AND userId = ?",
            (sc_id, user_id),
        ).fetchone()
    return _row_to_system_context(row) if row else None


def update_system_context(
    user_id: str,
    sc_id: str,
    *,
    title: str | None = None,
    system_context: str | None = None,
    shared_tags: list[str] | None = None,
    is_public: bool | None = None,
) -> dict[str, Any] | None:
    """所有者のみ更新可。指定された項目のみ変更する（本文・タイトル・共有設定）。"""
    sets: list[str] = []
    params: list[Any] = []
    if title is not None:
        sets.append("systemContextTitle = ?")
        params.append(title)
    if system_context is not None:
        sets.append("systemContext = ?")
        params.append(system_context)
    if shared_tags is not None:
        sets.append("sharedTags = ?")
        params.append(json.dumps(sorted({t.strip() for t in shared_tags if t.strip()})))
    if is_public is not None:
        sets.append("isPublic = ?")
        params.append(1 if is_public else 0)
    if not sets:
        return None
    sets.append("updatedDate = ?")
    params.append(_now())
    params.extend([sc_id, user_id])
    with _lock, _connect() as conn:
        conn.execute(
            f"UPDATE system_contexts SET {', '.join(sets)}"
            " WHERE systemContextId = ? AND userId = ?",
            tuple(params),
        )
        row = conn.execute(
            "SELECT * FROM system_contexts WHERE systemContextId = ? AND userId = ?",
            (sc_id, user_id),
        ).fetchone()
    return _row_to_system_context(row) if row else None


def delete_system_context(user_id: str, sc_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM system_contexts WHERE systemContextId = ? AND userId = ?",
            (sc_id, user_id),
        )


def create_messages(
    chat_id: str, user_id: str, messages: list[dict[str, Any]]
) -> list[dict[str, Any]] | None:
    """ToBeRecordedMessage[] を保存し RecordedMessage[] を返す。

    所有者でないチャットへの書き込みは拒否し None を返す。
    """
    recorded: list[dict[str, Any]] = []
    with _lock, _connect() as conn:
        # 所有者のチャットにのみ書き込む
        if _chat_owner(conn, chat_id) != user_id:
            return None
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS m FROM messages WHERE chatId = ?",
            (chat_id,),
        ).fetchone()
        seq = row["m"]
        for m in messages:
            seq += 1
            message_id = m.get("messageId") or str(uuid.uuid4())
            created = m.get("createdDate") or _now()
            usecase = m.get("usecase") or "/chat"
            extra = m.get("extraData")
            rec = {
                "id": f"message#{message_id}",
                "createdDate": created,
                "messageId": message_id,
                "usecase": usecase,
                "userId": user_id,
                "feedback": "",
                "role": m["role"],
                "content": m.get("content", ""),
            }
            if m.get("trace"):
                rec["trace"] = m["trace"]
            if m.get("llmType"):
                rec["llmType"] = m["llmType"]
            if extra:
                rec["extraData"] = extra
            conn.execute(
                "INSERT OR REPLACE INTO messages"
                " (messageId, chatId, id, createdDate, usecase, userId, feedback,"
                "  role, content, trace, llmType, extraData, seq)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    chat_id,
                    rec["id"],
                    created,
                    usecase,
                    user_id,
                    "",
                    m["role"],
                    m.get("content", ""),
                    m.get("trace"),
                    m.get("llmType"),
                    json.dumps(extra, ensure_ascii=False) if extra else None,
                    seq,
                ),
            )
            recorded.append(rec)
        conn.execute(
            "UPDATE chats SET updatedDate = ? WHERE chatId = ?", (_now(), chat_id)
        )
    return recorded
