"""確定後の汎用台帳。patchform の申請 DB とは別ファイルに置く。

受理前の申請は行にしない。差戻しと取下げも行にしない。
同じ申請から行は1件。担当、状態、コメントだけを書き換える。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import files

LEDGER_DB_PATH = os.environ.get("PATCHFORM_LEDGER_DB_PATH", "/data/patchform-ledger.db")

_lock = threading.RLock()
_db: sqlite3.Connection | None = None


def ledger_files_root() -> Path:
    return Path(os.environ.get("PATCHFORM_LEDGER_FILES_DIR") or "/data/ledger-files")


def reset_connection() -> None:
    global _db, LEDGER_DB_PATH
    if _db is not None:
        _db.close()
        _db = None
    LEDGER_DB_PATH = os.environ.get("PATCHFORM_LEDGER_DB_PATH", "/data/patchform-ledger.db")


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    parent = os.path.dirname(LEDGER_DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(LEDGER_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _db = conn
    _init(conn)
    return conn


def _init(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledger_rows (
          id TEXT PRIMARY KEY,
          application_id TEXT NOT NULL UNIQUE,
          procedure_id TEXT NOT NULL,
          procedure_name TEXT NOT NULL,
          confirmed_at TEXT NOT NULL,
          confirmed_by TEXT NOT NULL,
          assignee TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          snapshot_json TEXT NOT NULL,
          review_json TEXT NOT NULL DEFAULT '',
          comment TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger_events (
          id TEXT PRIMARY KEY,
          row_id TEXT NOT NULL,
          actor_user_id TEXT NOT NULL,
          action TEXT NOT NULL,
          detail TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ledger_procedure ON ledger_rows(procedure_id);
        CREATE INDEX IF NOT EXISTS idx_ledger_events ON ledger_events(row_id);
        """
    )
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _row_payload(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    try:
        snapshot = json.loads(row["snapshot_json"] or "{}")
    except json.JSONDecodeError:
        snapshot = {}
    try:
        review = json.loads(row["review_json"] or "{}")
    except json.JSONDecodeError:
        review = {}
    events = [
        {
            "id": ev["id"],
            "actor_user_id": ev["actor_user_id"],
            "action": ev["action"],
            "detail": ev["detail"],
            "created_at": ev["created_at"],
        }
        for ev in db.execute(
            "SELECT * FROM ledger_events WHERE row_id = ? ORDER BY created_at DESC",
            (row["id"],),
        ).fetchall()
    ]
    return {
        "id": row["id"],
        "application_id": row["application_id"],
        "procedure_id": row["procedure_id"],
        "procedure_name": row["procedure_name"],
        "confirmed_at": row["confirmed_at"],
        "confirmed_by": row["confirmed_by"],
        "assignee": row["assignee"],
        "status": row["status"],
        "comment": row["comment"],
        "snapshot": snapshot if isinstance(snapshot, dict) else {},
        "review": review if isinstance(review, dict) else {},
        "events": events,
        "updated_at": row["updated_at"],
    }


def row_id_for(application_id: str) -> str | None:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT id FROM ledger_rows WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        return str(row["id"]) if row else None


def _copy_files(row_id: str, copies: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    dest_dir = ledger_files_root() / row_id
    for item in copies:
        file_id = str(item.get("file_id") or "")
        name = str(item.get("filename") or file_id)
        record: dict[str, Any] = {
            "file_id": file_id,
            "name": name,
            "mime": str(item.get("mime") or ""),
            "copied": False,
        }
        form_id = str(item.get("form_id") or "")
        if file_id and form_id:
            try:
                src = files.stored_path(form_id, file_id)
            except ValueError:
                src = None
            if src is not None and src.is_file():
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / file_id
                shutil.copyfile(src, dest)
                record["copied"] = True
        out.append(record)
    return out


def open_row(
    *,
    application_id: str,
    procedure_id: str,
    procedure_name: str,
    confirmed_by: str,
    assignee: str,
    status: str,
    snapshot: dict[str, Any],
    review: dict[str, Any] | None,
    copies: list[dict[str, str]],
    confirmed_at: str,
) -> dict[str, Any]:
    """確定版から行を1件作る。既にあればそれを返す。"""
    db = connect()
    with _lock:
        existing = db.execute(
            "SELECT * FROM ledger_rows WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        if existing:
            return _row_payload(db, existing)
        row_id = str(uuid.uuid4())
        files_out = _copy_files(row_id, copies)
        body = {**snapshot, "files": files_out}
        db.execute(
            "INSERT INTO ledger_rows (id, application_id, procedure_id, procedure_name, "
            "confirmed_at, confirmed_by, assignee, status, snapshot_json, review_json, "
            "comment, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)",
            (
                row_id,
                application_id,
                procedure_id,
                procedure_name,
                confirmed_at,
                confirmed_by,
                assignee,
                status,
                json.dumps(body, ensure_ascii=False),
                json.dumps(review or {}, ensure_ascii=False),
                confirmed_at,
            ),
        )
        db.execute(
            "INSERT INTO ledger_events (id, row_id, actor_user_id, action, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), row_id, confirmed_by, "行を作った", status, confirmed_at),
        )
        db.commit()
        row = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        return _row_payload(db, row)


def list_rows(*, procedure_id: str | None = None) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        if procedure_id:
            rows = db.execute(
                "SELECT * FROM ledger_rows WHERE procedure_id = ? ORDER BY confirmed_at DESC",
                (procedure_id,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM ledger_rows ORDER BY confirmed_at DESC"
            ).fetchall()
        return [_row_payload(db, row) for row in rows]


def get_row(row_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        return _row_payload(db, row) if row else None


def file_path(row_id: str, file_id: str) -> Path | None:
    if not files._UUID_RE.match(row_id or "") or not files._UUID_RE.match(file_id or ""):
        return None
    row = get_row(row_id)
    if row is None:
        return None
    files_out = (row.get("snapshot") or {}).get("files") or []
    known = {str(item.get("file_id") or "") for item in files_out if item.get("copied")}
    if file_id not in known:
        return None
    try:
        path = ledger_files_root() / row_id / file_id
    except Exception:
        return None
    if not path.is_file():
        return None
    return path


def update_row(
    *,
    row_id: str,
    actor_user_id: str,
    assignee: str | None = None,
    status: str | None = None,
    comment: str | None = None,
    allowed_statuses: list[str],
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        if not row:
            return None, "台帳の行が見つかりません"
        sets: list[str] = []
        params: list[Any] = []
        events: list[tuple[str, str]] = []
        if assignee is not None:
            text = assignee.strip()[:80]
            if text != row["assignee"]:
                sets.append("assignee = ?")
                params.append(text)
                events.append(("担当を変えた", text or "未設定"))
        if status is not None:
            text = status.strip()
            if text not in allowed_statuses:
                return None, "その状態はこの手続きにありません"
            if text != row["status"]:
                sets.append("status = ?")
                params.append(text)
                events.append(("状態を変えた", text))
        if comment is not None:
            text = comment.strip()[:500]
            if text != row["comment"]:
                sets.append("comment = ?")
                params.append(text)
                events.append(("コメントを書いた", text))
        if not sets:
            return _row_payload(db, row), None
        now = _now()
        sets.append("updated_at = ?")
        params.append(now)
        params.append(row_id)
        db.execute(f"UPDATE ledger_rows SET {', '.join(sets)} WHERE id = ?", params)
        for action, detail in events:
            db.execute(
                "INSERT INTO ledger_events (id, row_id, actor_user_id, action, detail, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), row_id, actor_user_id, action, detail, now),
            )
        db.commit()
        saved = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        return _row_payload(db, saved), None
