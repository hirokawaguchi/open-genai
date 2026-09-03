"""procuretech-editor の SQLite 永続化（プロジェクト/ファイルのメタデータ）。

ファイル本体は S3 互換ストレージ（`objstore.py`）に保存し、本モジュールは
プロジェクト（案件フォルダ）とファイルのメタデータ（相対パス・S3 キー・種別・
サイズ・更新時刻）のみを管理する。すべて `user_id` でスコープし、他ユーザーの
プロジェクトは参照・変更できない。

S3 キーは相対パスを埋め込まない不透明キー（`<prefix>/<user_hash>/<project_id>/
<uuid>-<name>`）とする。これによりリネーム/移動は DB の `rel_path` 更新のみで済み、
S3 側のオブジェクト移動が不要になる（複製時のみ S3 コピーを行う）。
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from . import objstore

DB_PATH = os.environ.get("EDITOR_DB_PATH", "/data/procuretech_editor.db")

_lock = threading.Lock()
_db: sqlite3.Connection | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _user_hash(user_id: str) -> str:
    return hashlib.sha256((user_id or "").encode("utf-8")).hexdigest()[:32]


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    _db = conn
    return conn


def init_db() -> None:
    db = connect()
    with _lock:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY,
              user_id TEXT NOT NULL,
              name TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS files (
              id TEXT PRIMARY KEY,
              project_id TEXT NOT NULL,
              user_id TEXT NOT NULL,
              rel_path TEXT NOT NULL,
              s3_key TEXT NOT NULL,
              kind TEXT NOT NULL,
              size INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              UNIQUE (project_id, rel_path),
              FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_projects_user ON projects(user_id);
            CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
            """
        )
        db.commit()


# --- projects -----------------------------------------------------------------


def _project_dict(row: sqlite3.Row, *, file_count: int = 0) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "file_count": file_count,
    }


def create_project(user_id: str, name: str) -> dict[str, Any]:
    db = connect()
    pid = uuid.uuid4().hex
    now = _now_iso()
    with _lock:
        db.execute(
            "INSERT INTO projects (id, user_id, name, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (pid, user_id, name, now, now),
        )
        db.commit()
    return {"id": pid, "name": name, "created_at": now, "updated_at": now, "file_count": 0}


def list_projects(user_id: str) -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        """
        SELECT p.*, (
          SELECT COUNT(*) FROM files f WHERE f.project_id = p.id
        ) AS file_count
        FROM projects p
        WHERE p.user_id = ?
        ORDER BY p.created_at DESC
        """,
        (user_id,),
    ).fetchall()
    return [_project_dict(r, file_count=r["file_count"]) for r in rows]


def get_project(project_id: str, user_id: str) -> dict[str, Any] | None:
    db = connect()
    row = db.execute(
        "SELECT * FROM projects WHERE id = ? AND user_id = ?",
        (project_id, user_id),
    ).fetchone()
    if row is None:
        return None
    cnt = db.execute(
        "SELECT COUNT(*) AS c FROM files WHERE project_id = ?", (project_id,)
    ).fetchone()["c"]
    return _project_dict(row, file_count=cnt)


def touch_project(project_id: str) -> None:
    db = connect()
    with _lock:
        db.execute(
            "UPDATE projects SET updated_at = ? WHERE id = ?",
            (_now_iso(), project_id),
        )
        db.commit()


def delete_project(project_id: str, user_id: str) -> list[str]:
    """プロジェクトを削除し、削除対象の S3 キー一覧を返す（S3 実削除は呼び出し側）。"""
    db = connect()
    proj = get_project(project_id, user_id)
    if proj is None:
        return []
    keys = [r["s3_key"] for r in db.execute(
        "SELECT s3_key FROM files WHERE project_id = ?", (project_id,)
    ).fetchall()]
    with _lock:
        db.execute(
            "DELETE FROM projects WHERE id = ? AND user_id = ?",
            (project_id, user_id),
        )
        db.commit()
    return keys


# --- files --------------------------------------------------------------------


def _file_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "rel_path": row["rel_path"],
        "s3_key": row["s3_key"],
        "kind": row["kind"],
        "size": row["size"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def build_s3_key(user_id: str, project_id: str, filename: str) -> str:
    """相対パスを埋め込まない不透明な S3 キーを採番する。"""
    safe = objstore.sanitize_filename(filename)
    return "/".join(
        [
            objstore.EDITOR_S3_PREFIX,
            _user_hash(user_id),
            project_id,
            f"{uuid.uuid4().hex}-{safe}",
        ]
    )


def list_files(project_id: str, user_id: str) -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        "SELECT * FROM files WHERE project_id = ? AND user_id = ? ORDER BY rel_path",
        (project_id, user_id),
    ).fetchall()
    return [_file_dict(r) for r in rows]


def get_file(project_id: str, user_id: str, rel_path: str) -> dict[str, Any] | None:
    db = connect()
    row = db.execute(
        "SELECT * FROM files WHERE project_id = ? AND user_id = ? AND rel_path = ?",
        (project_id, user_id, rel_path),
    ).fetchone()
    return _file_dict(row) if row else None


def get_file_by_id(file_id: str, user_id: str) -> dict[str, Any] | None:
    db = connect()
    row = db.execute(
        "SELECT * FROM files WHERE id = ? AND user_id = ?",
        (file_id, user_id),
    ).fetchone()
    return _file_dict(row) if row else None


def upsert_file(
    project_id: str,
    user_id: str,
    rel_path: str,
    *,
    kind: str,
    size: int,
    s3_key: str | None = None,
) -> dict[str, Any]:
    """rel_path 単位で作成/更新する。既存なら kind/size を更新し s3_key は維持する。"""
    db = connect()
    now = _now_iso()
    existing = get_file(project_id, user_id, rel_path)
    with _lock:
        if existing:
            db.execute(
                "UPDATE files SET kind = ?, size = ?, updated_at = ? WHERE id = ?",
                (kind, size, now, existing["id"]),
            )
            db.commit()
        else:
            fid = uuid.uuid4().hex
            key = s3_key or build_s3_key(user_id, project_id, rel_path)
            db.execute(
                "INSERT INTO files (id, project_id, user_id, rel_path, s3_key, kind, size,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (fid, project_id, user_id, rel_path, key, kind, size, now, now),
            )
            db.commit()
    # touch_project は自前で _lock を取るため、必ずロック解放後に呼ぶ（再入デッドロック防止）。
    touch_project(project_id)
    if existing:
        existing.update({"kind": kind, "size": size, "updated_at": now})
        return existing
    return {
        "id": fid,
        "project_id": project_id,
        "rel_path": rel_path,
        "s3_key": key,
        "kind": kind,
        "size": size,
        "created_at": now,
        "updated_at": now,
    }


def rename_file(
    project_id: str, user_id: str, old_rel: str, new_rel: str, *, new_kind: str | None = None
) -> dict[str, Any] | None:
    """rel_path を変更する（S3 キーは維持）。衝突時は None を返す。"""
    db = connect()
    row = get_file(project_id, user_id, old_rel)
    if row is None:
        return None
    if get_file(project_id, user_id, new_rel) is not None:
        return None
    now = _now_iso()
    kind = new_kind or row["kind"]
    with _lock:
        db.execute(
            "UPDATE files SET rel_path = ?, kind = ?, updated_at = ? WHERE id = ?",
            (new_rel, kind, now, row["id"]),
        )
        db.commit()
    touch_project(project_id)
    row.update({"rel_path": new_rel, "kind": kind, "updated_at": now})
    return row


def delete_file(project_id: str, user_id: str, rel_path: str) -> str | None:
    """ファイルを削除し、削除対象の S3 キーを返す（S3 実削除は呼び出し側）。"""
    db = connect()
    row = get_file(project_id, user_id, rel_path)
    if row is None:
        return None
    with _lock:
        db.execute("DELETE FROM files WHERE id = ?", (row["id"],))
        db.commit()
    touch_project(project_id)
    return row["s3_key"]
