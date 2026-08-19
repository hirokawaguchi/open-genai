"""フォーム定義と回答の SQLite 永続化。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt

from . import crypto, files, spec

DB_PATH = os.environ.get("PATCHFORM_DB_PATH", "/data/patchform.db")
RETENTION_DAYS = int(os.environ.get("PATCHFORM_RETENTION_DAYS", "365"))
PUBLIC_ENDPOINT = (os.environ.get("PATCHFORM_PUBLIC_ENDPOINT") or "").rstrip("/")

_lock = threading.RLock()
_db: sqlite3.Connection | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def hash_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_pin(pin: str, hashed: str | None) -> bool:
    if not hashed or not pin:
        return False
    try:
        return bcrypt.checkpw(pin.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


def reset_connection() -> None:
    """テスト用。接続を閉じて次回 connect() で開き直す。"""
    global _db
    if _db is not None:
        _db.close()
        _db = None


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
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
            CREATE TABLE IF NOT EXISTS forms (
              id TEXT PRIMARY KEY,
              guest_token TEXT NOT NULL UNIQUE,
              title TEXT NOT NULL,
              description TEXT,
              status TEXT NOT NULL,
              visibility TEXT NOT NULL,
              definition_json TEXT NOT NULL,
              published_version_id TEXT,
              pin_hash TEXT,
              creator_user_id TEXT,
              creator_name TEXT,
              retention_days INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS form_versions (
              id TEXT PRIMARY KEY,
              form_id TEXT NOT NULL,
              version INTEGER NOT NULL,
              definition_json TEXT NOT NULL,
              published_at TEXT NOT NULL,
              published_by TEXT,
              FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE,
              UNIQUE(form_id, version)
            );
            CREATE TABLE IF NOT EXISTS submissions (
              id TEXT PRIMARY KEY,
              form_id TEXT NOT NULL,
              version_id TEXT,
              receipt_code TEXT NOT NULL UNIQUE,
              submitter_user_id TEXT,
              submitter_name TEXT,
              answers_json TEXT NOT NULL,
              is_draft INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE,
              FOREIGN KEY (version_id) REFERENCES form_versions(id)
            );
            CREATE TABLE IF NOT EXISTS uploaded_files (
              id TEXT PRIMARY KEY,
              form_id TEXT NOT NULL,
              submission_id TEXT,
              component_id TEXT,
              filename TEXT NOT NULL,
              mime TEXT,
              size INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE,
              FOREIGN KEY (submission_id) REFERENCES submissions(id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS audit_events (
              id TEXT PRIMARY KEY,
              form_id TEXT NOT NULL,
              submission_id TEXT,
              actor_user_id TEXT NOT NULL,
              action TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (form_id) REFERENCES forms(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_forms_creator ON forms(creator_user_id);
            CREATE INDEX IF NOT EXISTS idx_forms_guest ON forms(guest_token);
            CREATE INDEX IF NOT EXISTS idx_forms_status ON forms(status);
            CREATE INDEX IF NOT EXISTS idx_submissions_form ON submissions(form_id);
            CREATE INDEX IF NOT EXISTS idx_uploads_form ON uploaded_files(form_id);
            CREATE INDEX IF NOT EXISTS idx_audit_form ON audit_events(form_id);
            """
        )
        _ensure_columns(db)
        db.commit()


def _ensure_columns(db: sqlite3.Connection) -> None:
    wanted = (
        ("forms", "allow_draft", "INTEGER NOT NULL DEFAULT 1"),
        ("forms", "allow_multiple", "INTEGER NOT NULL DEFAULT 1"),
        ("forms", "editor_user_ids", "TEXT"),
        ("forms", "viewer_user_ids", "TEXT"),
        ("forms", "identity_mode", "TEXT NOT NULL DEFAULT 'optional'"),
        ("submissions", "withdrawn_at", "TEXT"),
        ("submissions", "withdrawn_by", "TEXT"),
    )
    for table, name, decl in wanted:
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _parse_user_ids(raw: Any) -> list[str]:
    if raw is None or raw == "":
        return []
    if isinstance(raw, list):
        items = raw
    else:
        text = str(raw)
        try:
            parsed = json.loads(text)
            items = parsed if isinstance(parsed, list) else text.replace(",", "\n").splitlines()
        except (TypeError, json.JSONDecodeError):
            items = text.replace(",", "\n").splitlines()
    out: list[str] = []
    for item in items:
        uid = str(item).strip()
        if uid and uid not in out:
            out.append(uid)
    return out


def _ids_json(raw: Any) -> str:
    return json.dumps(_parse_user_ids(raw), ensure_ascii=False)


def _row_ids(row: sqlite3.Row, key: str) -> list[str]:
    if key not in row.keys():
        return []
    return _parse_user_ids(row[key])


def _is_admin(groups: list[str] | None) -> bool:
    return "SystemAdminGroup" in (groups or [])


def _role(row: sqlite3.Row, actor_user_id: str | None, groups: list[str] | None) -> str | None:
    if not actor_user_id:
        return None
    if _is_admin(groups):
        return "admin"
    if row["creator_user_id"] == actor_user_id:
        return "owner"
    if actor_user_id in _row_ids(row, "editor_user_ids"):
        return "editor"
    if actor_user_id in _row_ids(row, "viewer_user_ids"):
        return "viewer"
    return None


def _can_edit(row: sqlite3.Row, actor_user_id: str | None, groups: list[str] | None) -> bool:
    return _role(row, actor_user_id, groups) in ("admin", "owner", "editor")


def _can_delete(row: sqlite3.Row, actor_user_id: str | None, groups: list[str] | None) -> bool:
    return _role(row, actor_user_id, groups) in ("admin", "owner")


def _can_view_submissions(row: sqlite3.Row, actor_user_id: str | None, groups: list[str] | None) -> bool:
    return _role(row, actor_user_id, groups) in ("admin", "owner", "editor", "viewer")


def _can_reveal(row: sqlite3.Row, actor_user_id: str | None, groups: list[str] | None) -> bool:
    return _role(row, actor_user_id, groups) in ("admin", "owner", "editor")


def _can_read(row: sqlite3.Row, actor_user_id: str | None, groups: list[str] | None) -> bool:
    if _role(row, actor_user_id, groups):
        return True
    if row["status"] == "published" and row["visibility"] in ("internal", "both"):
        return True
    return False


def _flag(row: sqlite3.Row, key: str, default: int = 1) -> int:
    if key not in row.keys() or row[key] is None:
        return default
    return 1 if int(row[key]) else 0


def _is_withdrawn(row: sqlite3.Row) -> bool:
    if "withdrawn_at" not in row.keys():
        return False
    return bool(row["withdrawn_at"])


def _has_mynumber(definition: dict[str, Any]) -> bool:
    return any(c.get("type") == "mynumber" for c in definition.get("components") or [])


def _identity_mode(row: sqlite3.Row) -> str:
    raw = ""
    if "identity_mode" in row.keys() and row["identity_mode"]:
        raw = str(row["identity_mode"])
    return raw if raw in spec.IDENTITY_MODES else "optional"


def _has_name_composite(definition: dict[str, Any]) -> bool:
    return any(c.get("type") == "user_info_composite" for c in definition.get("components") or [])


def _name_from_answers(definition: dict[str, Any], answers: dict[str, Any]) -> str:
    for comp in definition.get("components") or []:
        if comp.get("type") != "user_info_composite":
            continue
        raw = answers.get(comp["id"])
        if not isinstance(raw, dict):
            continue
        name = f"{raw.get('last_name') or ''} {raw.get('first_name') or ''}".strip()
        if name:
            return name
    return ""


def _anon_key(form_id: str, user_id: str) -> str:
    digest = hashlib.sha256(f"{form_id}:{user_id}".encode("utf-8")).hexdigest()[:32]
    return f"anon:{digest}"


def _lookup_ids(form_id: str, user_id: str | None) -> list[str]:
    if not user_id:
        return []
    return [user_id, _anon_key(form_id, user_id)]


def _respondent_label(
    definition: dict[str, Any],
    answers: dict[str, Any],
    *,
    receipt_code: str,
    submitter_name: str | None,
    submitter_user_id: str | None,
    identity_mode: str,
) -> str:
    from_form = _name_from_answers(definition, answers)
    if from_form:
        return from_form
    if identity_mode == "anonymous":
        return receipt_code
    name = (submitter_name or "").strip()
    if name:
        return name
    uid = submitter_user_id or ""
    if identity_mode == "required" and uid and not uid.startswith("anon:"):
        return uid
    return receipt_code


def _log_audit(
    db: sqlite3.Connection,
    *,
    form_id: str,
    actor_user_id: str,
    action: str,
    submission_id: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO audit_events (id, form_id, submission_id, actor_user_id, action, created_at) "
        "VALUES (?,?,?,?,?,?)",
        (str(uuid.uuid4()), form_id, submission_id, actor_user_id, action, _now_iso()),
    )


def public_url_for(guest_token: str) -> str:
    if not PUBLIC_ENDPOINT:
        return f"/public/f/{guest_token}"
    return f"{PUBLIC_ENDPOINT}/public/f/{guest_token}"


def _stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, default=str)


def _definition(row: sqlite3.Row) -> dict[str, Any]:
    try:
        data = json.loads(row["definition_json"])
    except (TypeError, json.JSONDecodeError):
        data = spec.empty_definition()
    return data if isinstance(data, dict) else spec.empty_definition()


def _row_to_form(row: sqlite3.Row, *, include_definition: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "guest_token": row["guest_token"],
        "title": row["title"],
        "description": row["description"],
        "status": row["status"],
        "visibility": row["visibility"],
        "has_pin": bool(row["pin_hash"]),
        "creator_user_id": row["creator_user_id"],
        "creator_name": row["creator_name"],
        "retention_days": row["retention_days"],
        "published_version_id": row["published_version_id"],
        "allow_draft": bool(_flag(row, "allow_draft")),
        "allow_multiple": bool(_flag(row, "allow_multiple")),
        "identity_mode": _identity_mode(row),
        "editor_user_ids": _row_ids(row, "editor_user_ids"),
        "viewer_user_ids": _row_ids(row, "viewer_user_ids"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "public_url": public_url_for(row["guest_token"]),
    }
    if include_definition:
        out["definition"] = _definition(row)
    return out


def list_forms_for_user(user_id: str, *, actor_groups: list[str] | None = None) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        rows = db.execute("SELECT * FROM forms ORDER BY updated_at DESC").fetchall()
        submitted = {
            r["form_id"]
            for r in db.execute(
                "SELECT DISTINCT form_id FROM submissions WHERE submitter_user_id = ?",
                (user_id,),
            ).fetchall()
        }
        admin = _is_admin(actor_groups)
        out: list[dict[str, Any]] = []
        for row in rows:
            role = _role(row, user_id, actor_groups)
            open_to_staff = row["status"] == "published" and row["visibility"] in (
                "internal",
                "both",
            )
            if not (admin or role or row["id"] in submitted or open_to_staff):
                continue
            item = _row_to_form(row, include_definition=False)
            item["role"] = role or "respondent"
            item["can_edit"] = role in ("admin", "owner", "editor")
            item["can_view_submissions"] = role in ("admin", "owner", "editor", "viewer")
            out.append(item)
        return out


def get_form(
    form_id: str | None = None,
    *,
    guest_token: str | None = None,
    actor_user_id: str | None = None,
    actor_groups: list[str] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if guest_token:
            row = db.execute(
                "SELECT * FROM forms WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None
        out = _row_to_form(row)
        out["submission_count"] = db.execute(
            "SELECT COUNT(*) AS n FROM submissions WHERE form_id = ? AND is_draft = 0 "
            "AND (withdrawn_at IS NULL OR withdrawn_at = '')",
            (row["id"],),
        ).fetchone()["n"]
        out["withdrawn_count"] = db.execute(
            "SELECT COUNT(*) AS n FROM submissions WHERE form_id = ? AND is_draft = 0 "
            "AND withdrawn_at IS NOT NULL AND withdrawn_at != ''",
            (row["id"],),
        ).fetchone()["n"]
        out["draft_differs"] = False
        published_def: dict[str, Any] | None = None
        if row["published_version_id"]:
            ver = db.execute(
                "SELECT version, published_at, definition_json FROM form_versions WHERE id = ?",
                (row["published_version_id"],),
            ).fetchone()
            if ver:
                out["published_version"] = ver["version"]
                out["published_at"] = ver["published_at"]
                try:
                    parsed = json.loads(ver["definition_json"])
                    published_def = parsed if isinstance(parsed, dict) else None
                except (TypeError, json.JSONDecodeError):
                    published_def = None
                out["draft_differs"] = _stable_json(_definition(row)) != _stable_json(
                    published_def or {}
                )
        current_def = out.get("definition") if isinstance(out.get("definition"), dict) else _definition(row)
        fill_def = published_def or current_def
        out["fill_definition"] = fill_def
        out["has_mynumber"] = _has_mynumber(current_def) or _has_mynumber(fill_def or {})
        out["has_name_composite"] = _has_name_composite(fill_def or current_def)
        role = _role(row, actor_user_id, actor_groups)
        submitted = False
        has_draft = False
        lookup = _lookup_ids(row["id"], actor_user_id)
        if lookup:
            placeholders = ",".join("?" * len(lookup))
            mine = db.execute(
                f"SELECT is_draft, withdrawn_at FROM submissions WHERE form_id = ? AND submitter_user_id IN ({placeholders}) "
                "ORDER BY is_draft ASC, updated_at DESC",
                (row["id"], *lookup),
            ).fetchall()
            submitted = any(int(r["is_draft"] or 0) == 0 and not _is_withdrawn(r) for r in mine)
            has_draft = any(int(r["is_draft"] or 0) == 1 for r in mine)
        out["role"] = role
        out["can_read"] = (
            bool(role)
            or _can_read(row, actor_user_id, actor_groups)
            or submitted
            or has_draft
        )
        out["can_edit"] = _can_edit(row, actor_user_id, actor_groups)
        out["can_delete"] = _can_delete(row, actor_user_id, actor_groups)
        out["can_view_submissions"] = _can_view_submissions(row, actor_user_id, actor_groups)
        out["can_reveal"] = _can_reveal(row, actor_user_id, actor_groups) and out["has_mynumber"]
        out["my_submitted"] = submitted
        out["my_has_draft"] = has_draft
        if actor_user_id and not out["can_edit"] and fill_def:
            out["definition"] = fill_def
            out["draft_differs"] = False
        return out


def create_form(
    *,
    title: str,
    description: str | None,
    creator_user_id: str,
    creator_name: str | None,
    visibility: str = "internal",
    definition: dict[str, Any] | None = None,
    pin: str | None = None,
    retention_days: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if visibility not in spec.VISIBILITIES:
        return None, "公開範囲が不正です"
    pin_err = spec.validate_pin(pin)
    if pin_err:
        return None, pin_err
    base = definition or spec.empty_definition(title, description or "")
    if not (base.get("metadata") or {}).get("title"):
        base = dict(base)
        base["metadata"] = {
            **(base.get("metadata") or {}),
            "title": title,
            "description": description or "",
        }
    normalized, err = spec.validate_definition(base, visibility=visibility)
    if err or normalized is None:
        return None, err
    form_id = str(uuid.uuid4())
    guest_token = secrets.token_urlsafe(24)
    now = _now_iso()
    days = retention_days if retention_days is not None else RETENTION_DAYS
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO forms (id, guest_token, title, description, status, visibility, "
            "definition_json, published_version_id, pin_hash, creator_user_id, creator_name, "
            "retention_days, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                form_id,
                guest_token,
                title,
                description,
                "draft",
                visibility,
                json.dumps(normalized, ensure_ascii=False),
                None,
                hash_pin(pin) if pin else None,
                creator_user_id,
                creator_name,
                days,
                now,
                now,
            ),
        )
        db.commit()
    detail = get_form(form_id, actor_user_id=creator_user_id)
    assert detail is not None
    return detail, None


def update_form(
    form_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    title: str | None = None,
    description: str | None = None,
    visibility: str | None = None,
    definition: dict[str, Any] | None = None,
    pin: str | None = None,
    retention_days: int | None = None,
    allow_draft: bool | None = None,
    allow_multiple: bool | None = None,
    editor_user_ids: list[str] | str | None = None,
    viewer_user_ids: list[str] | str | None = None,
    identity_mode: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if not _can_edit(row, actor_user_id, actor_groups):
            return None, "このフォームを編集する権限がありません"
        if row["status"] in ("archived",):
            return None, "アーカイブ済みのフォームは編集できません"
        new_title = title if title is not None else row["title"]
        new_desc = description if description is not None else row["description"]
        new_vis = visibility if visibility is not None else row["visibility"]
        if new_vis not in spec.VISIBILITIES:
            return None, "公開範囲が不正です"
        if not str(new_title or "").strip():
            return None, "タイトルは必須です"
        current = _definition(row)
        next_def = definition if definition is not None else current
        if not (next_def.get("metadata") or {}).get("title"):
            next_def = dict(next_def)
            next_def["metadata"] = {
                **(next_def.get("metadata") or {}),
                "title": new_title,
                "description": new_desc or "",
            }
        normalized, err = spec.validate_definition(next_def, visibility=new_vis)
        if err or normalized is None:
            return None, err
        pin_hash = row["pin_hash"]
        if pin is not None:
            if pin == "":
                pin_hash = None
            else:
                pin_err = spec.validate_pin(pin)
                if pin_err:
                    return None, pin_err
                pin_hash = hash_pin(pin)
        days = retention_days if retention_days is not None else row["retention_days"]
        if (editor_user_ids is not None or viewer_user_ids is not None) and _role(
            row, actor_user_id, actor_groups
        ) not in ("owner", "admin"):
            return None, "共同編集者の変更は作成者のみです"
        next_draft = _flag(row, "allow_draft") if allow_draft is None else (1 if allow_draft else 0)
        next_multi = (
            _flag(row, "allow_multiple") if allow_multiple is None else (1 if allow_multiple else 0)
        )
        next_editors = (
            _ids_json(editor_user_ids)
            if editor_user_ids is not None
            else (row["editor_user_ids"] if "editor_user_ids" in row.keys() else "[]")
        )
        next_viewers = (
            _ids_json(viewer_user_ids)
            if viewer_user_ids is not None
            else (row["viewer_user_ids"] if "viewer_user_ids" in row.keys() else "[]")
        )
        next_identity = _identity_mode(row)
        if identity_mode is not None:
            if identity_mode not in spec.IDENTITY_MODES:
                return None, "回答者の扱いが不正です"
            next_identity = identity_mode
        db.execute(
            "UPDATE forms SET title = ?, description = ?, visibility = ?, definition_json = ?, "
            "pin_hash = ?, retention_days = ?, allow_draft = ?, allow_multiple = ?, "
            "editor_user_ids = ?, viewer_user_ids = ?, identity_mode = ?, updated_at = ? WHERE id = ?",
            (
                new_title.strip(),
                new_desc,
                new_vis,
                json.dumps(normalized, ensure_ascii=False),
                pin_hash,
                days,
                next_draft,
                next_multi,
                next_editors,
                next_viewers,
                next_identity,
                _now_iso(),
                form_id,
            ),
        )
        db.commit()
    return get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups), None


def set_status(
    form_id: str,
    *,
    actor_user_id: str,
    status: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if status not in spec.STATUSES:
        return None, "状態が不正です"
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if not _can_edit(row, actor_user_id, actor_groups):
            return None, "このフォームを変更する権限がありません"
        version_id = row["published_version_id"]
        if status == "published":
            definition = _definition(row)
            normalized, err = spec.validate_definition(
                definition, visibility=row["visibility"]
            )
            if err or normalized is None:
                return None, err
            if not normalized["components"]:
                return None, "部品が無いフォームは公開できません"
            next_ver = db.execute(
                "SELECT COALESCE(MAX(version), 0) + 1 AS n FROM form_versions WHERE form_id = ?",
                (form_id,),
            ).fetchone()["n"]
            version_id = str(uuid.uuid4())
            now = _now_iso()
            db.execute(
                "INSERT INTO form_versions (id, form_id, version, definition_json, "
                "published_at, published_by) VALUES (?,?,?,?,?,?)",
                (
                    version_id,
                    form_id,
                    next_ver,
                    json.dumps(normalized, ensure_ascii=False),
                    now,
                    actor_user_id,
                ),
            )
        db.execute(
            "UPDATE forms SET status = ?, published_version_id = ?, updated_at = ? WHERE id = ?",
            (status, version_id, _now_iso(), form_id),
        )
        db.commit()
    return get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups), None


def delete_form(
    form_id: str, *, actor_user_id: str, actor_groups: list[str] | None = None
) -> str | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return "フォームが見つかりません"
        if not _can_delete(row, actor_user_id, actor_groups):
            return "このフォームを削除する権限がありません"
        db.execute("DELETE FROM forms WHERE id = ?", (form_id,))
        db.commit()
    files.remove_form_dir(form_id)
    return None


def published_definition(form_id: str) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row or not row["published_version_id"]:
            return None
        ver = db.execute(
            "SELECT definition_json FROM form_versions WHERE id = ?",
            (row["published_version_id"],),
        ).fetchone()
        if not ver:
            return None
        try:
            data = json.loads(ver["definition_json"])
        except (TypeError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None


def _published_row_writable(
    row: sqlite3.Row,
    *,
    guest: bool,
    pin: str | None,
    actor_user_id: str | None,
) -> str | None:
    if row["status"] != "published":
        return "このフォームは現在受け付けていません"
    if guest and row["visibility"] == "internal":
        return "このフォームは外部公開されていません"
    if not guest and row["visibility"] == "public" and not actor_user_id:
        return "このフォームは庁内からは回答できません"
    if guest and row["pin_hash"]:
        if not pin or not verify_pin(pin, row["pin_hash"]):
            return "暗証番号が正しくありません"
    return None


def save_upload(
    *,
    form_id: str | None = None,
    guest_token: str | None = None,
    filename: str,
    data: str,
    kind: str = "file",
    pin: str | None = None,
    actor_user_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if kind not in ("file", "signature"):
        return None, "添付の種類が不正です"
    name = files.safe_filename(filename)
    try:
        blob, mime = files.decode_upload(data, filename=name, kind=kind)
    except ValueError as e:
        return None, str(e)
    db = connect()
    with _lock:
        if guest_token:
            row = db.execute(
                "SELECT * FROM forms WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        access = _published_row_writable(
            row, guest=bool(guest_token), pin=pin, actor_user_id=actor_user_id
        )
        if access:
            return None, access
        file_id = str(uuid.uuid4())
        files.write_blob(row["id"], file_id, blob)
        now = _now_iso()
        db.execute(
            "INSERT INTO uploaded_files (id, form_id, submission_id, component_id, "
            "filename, mime, size, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (file_id, row["id"], None, None, name, mime, len(blob), now),
        )
        db.commit()
        return {
            "file_id": file_id,
            "filename": name,
            "mime": mime,
            "size": len(blob),
        }, None


def get_stored_file(
    form_id: str,
    file_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        form = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not form:
            return None, "フォームが見つかりません"
        if not _can_view_submissions(form, actor_user_id, actor_groups):
            return None, "添付を閲覧する権限がありません"
        row = db.execute(
            "SELECT * FROM uploaded_files WHERE id = ? AND form_id = ?",
            (file_id, form_id),
        ).fetchone()
        if not row:
            return None, "添付ファイルが見つかりません"
        try:
            path = files.stored_path(form_id, file_id)
        except ValueError:
            return None, "添付ファイルが見つかりません"
        if not path.is_file():
            return None, "添付ファイルが見つかりません"
        return {
            "filename": row["filename"],
            "mime": row["mime"] or "application/octet-stream",
            "path": str(path),
            "size": row["size"],
        }, None


def _bind_uploaded_files(
    db: sqlite3.Connection,
    form_id: str,
    submission_id: str,
    definition: dict[str, Any],
    answers: dict[str, Any],
) -> str | None:
    for comp in definition.get("components") or []:
        if comp.get("type") not in ("file", "signature_pad"):
            continue
        raw = answers.get(comp["id"])
        if not isinstance(raw, dict):
            continue
        file_id = str(raw.get("file_id") or "").strip()
        if not file_id:
            continue
        row = db.execute(
            "SELECT id, submission_id FROM uploaded_files WHERE id = ? AND form_id = ?",
            (file_id, form_id),
        ).fetchone()
        if not row:
            return f"{comp.get('label') or '添付'}のファイルが見つかりません"
        if row["submission_id"] and row["submission_id"] != submission_id:
            return f"{comp.get('label') or '添付'}のファイルはすでに使われています"
        try:
            path = files.stored_path(form_id, file_id)
        except ValueError:
            return f"{comp.get('label') or '添付'}のファイルが見つかりません"
        if not path.is_file():
            return f"{comp.get('label') or '添付'}のファイルが見つかりません"
        db.execute(
            "UPDATE uploaded_files SET submission_id = ?, component_id = ? WHERE id = ?",
            (submission_id, comp["id"], file_id),
        )
    return None


def public_form(guest_token: str, *, pin: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM forms WHERE guest_token = ?", (guest_token,)
        ).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if row["visibility"] == "internal":
            return None, "このフォームは外部公開されていません"
        if row["status"] != "published":
            return None, "このフォームは現在受け付けていません"
        if row["pin_hash"]:
            if not pin:
                return {
                    "requires_pin": True,
                    "title": row["title"],
                    "description": row["description"],
                }, None
            if not verify_pin(pin, row["pin_hash"]):
                return None, "暗証番号が正しくありません"
        ver = None
        if row["published_version_id"]:
            ver = db.execute(
                "SELECT definition_json FROM form_versions WHERE id = ?",
                (row["published_version_id"],),
            ).fetchone()
        definition = json.loads(ver["definition_json"]) if ver else _definition(row)
        return {
            "title": row["title"],
            "description": row["description"],
            "status": row["status"],
            "visibility": row["visibility"],
            "requires_pin": False,
            "allow_draft": bool(_flag(row, "allow_draft")),
            "allow_multiple": bool(_flag(row, "allow_multiple")),
            "identity_mode": _identity_mode(row),
            "has_name_composite": _has_name_composite(definition if isinstance(definition, dict) else {}),
            "definition": definition,
        }, None


def _find_draft(
    db: sqlite3.Connection,
    form_id: str,
    *,
    submitter_user_id: str | None,
    resume_token: str | None,
) -> sqlite3.Row | None:
    if resume_token:
        found = db.execute(
            "SELECT * FROM submissions WHERE form_id = ? AND receipt_code = ?",
            (form_id, resume_token),
        ).fetchone()
        return found
    lookup = _lookup_ids(form_id, submitter_user_id)
    if not lookup:
        return None
    placeholders = ",".join("?" * len(lookup))
    return db.execute(
        f"SELECT * FROM submissions WHERE form_id = ? AND is_draft = 1 "
        f"AND submitter_user_id IN ({placeholders}) ORDER BY updated_at DESC",
        (form_id, *lookup),
    ).fetchone()


def _resolve_identity(
    row: sqlite3.Row,
    definition: dict[str, Any],
    answers: dict[str, Any],
    *,
    guest: bool,
    submitter_user_id: str | None,
    submitter_name: str | None,
    is_draft: bool,
) -> tuple[str | None, str | None, str | None]:
    mode = _identity_mode(row)
    from_form = _name_from_answers(definition, answers)
    typed = (submitter_name or "").strip() or None
    if mode == "anonymous":
        stored_id = _anon_key(row["id"], submitter_user_id) if submitter_user_id else None
        return stored_id, None, None
    if mode == "required":
        if guest:
            name = typed or from_form
            if not is_draft and not name:
                return None, None, "氏名を入力してください"
            return None, name, None
        if not submitter_user_id:
            return None, None, "回答者を特定できません"
        return submitter_user_id, typed or from_form or submitter_user_id, None
    name = typed or from_form
    if guest:
        return None, name, None
    if name:
        return submitter_user_id, name, None
    stored_id = _anon_key(row["id"], submitter_user_id) if submitter_user_id else None
    return stored_id, None, None


def submit_answers(
    *,
    form_id: str | None = None,
    guest_token: str | None = None,
    answers: dict[str, Any],
    submitter_user_id: str | None,
    submitter_name: str | None,
    pin: str | None = None,
    is_draft: bool = False,
    resume_token: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        if guest_token:
            row = db.execute(
                "SELECT * FROM forms WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        access = _published_row_writable(
            row,
            guest=bool(guest_token),
            pin=pin,
            actor_user_id=submitter_user_id,
        )
        if access:
            return None, access
        if is_draft and not _flag(row, "allow_draft"):
            return None, "このフォームは下書き保存できません"
        definition = None
        version_id = row["published_version_id"]
        if version_id:
            ver = db.execute(
                "SELECT definition_json FROM form_versions WHERE id = ?",
                (version_id,),
            ).fetchone()
            if ver:
                definition = json.loads(ver["definition_json"])
        if definition is None:
            definition = _definition(row)
        existing = _find_draft(
            db, row["id"], submitter_user_id=submitter_user_id, resume_token=resume_token
        )
        if resume_token and not existing:
            return None, "再開用の下書きが見つかりません"
        if existing and not existing["is_draft"]:
            if is_draft:
                return None, "この控えはすでに提出済みです"
            if not _flag(row, "allow_multiple"):
                return None, "このフォームにはすでに回答しています"
            existing = None
        if (
            existing
            and submitter_user_id
            and existing["submitter_user_id"]
            and existing["submitter_user_id"] not in _lookup_ids(row["id"], submitter_user_id)
        ):
            return None, "この下書きを更新する権限がありません"
        cleaned, err = spec.validate_answers(definition, answers, partial=is_draft)
        if err or cleaned is None:
            return None, err
        stored_id, stored_name, ident_err = _resolve_identity(
            row,
            definition,
            cleaned,
            guest=bool(guest_token),
            submitter_user_id=submitter_user_id,
            submitter_name=submitter_name,
            is_draft=is_draft,
        )
        if ident_err:
            return None, ident_err
        if not is_draft and not _flag(row, "allow_multiple"):
            keys = _lookup_ids(row["id"], submitter_user_id)
            if stored_id and stored_id not in keys:
                keys.append(stored_id)
            if keys:
                placeholders = ",".join("?" * len(keys))
                prior = db.execute(
                    f"SELECT id FROM submissions WHERE form_id = ? AND is_draft = 0 "
                    f"AND (withdrawn_at IS NULL OR withdrawn_at = '') "
                    f"AND submitter_user_id IN ({placeholders})",
                    (row["id"], *keys),
                ).fetchone()
                if prior and (not existing or prior["id"] != existing["id"]):
                    return None, "このフォームにはすでに回答しています"
        cleaned = crypto.protect_answers(definition, cleaned)
        now = _now_iso()
        if existing:
            sid = existing["id"]
            receipt = existing["receipt_code"]
            db.execute(
                "UPDATE submissions SET version_id = ?, submitter_user_id = ?, submitter_name = ?, "
                "answers_json = ?, is_draft = ?, updated_at = ? WHERE id = ?",
                (
                    version_id,
                    stored_id,
                    stored_name,
                    json.dumps(cleaned, ensure_ascii=False),
                    1 if is_draft else 0,
                    now,
                    sid,
                ),
            )
        else:
            sid = str(uuid.uuid4())
            receipt = secrets.token_urlsafe(10)
            db.execute(
                "INSERT INTO submissions (id, form_id, version_id, receipt_code, "
                "submitter_user_id, submitter_name, answers_json, is_draft, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    row["id"],
                    version_id,
                    receipt,
                    stored_id,
                    stored_name,
                    json.dumps(cleaned, ensure_ascii=False),
                    1 if is_draft else 0,
                    now,
                    now,
                ),
            )
        bind_err = _bind_uploaded_files(db, row["id"], sid, definition, cleaned)
        if bind_err:
            db.rollback()
            return None, bind_err
        db.commit()
    return {
        "id": sid,
        "receipt_code": receipt,
        "is_draft": is_draft,
        "message": "下書きを保存しました" if is_draft else "回答を受け付けました",
    }, None


def get_draft(
    *,
    form_id: str | None = None,
    guest_token: str | None = None,
    submitter_user_id: str | None = None,
    resume_token: str | None = None,
    pin: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        if guest_token:
            row = db.execute(
                "SELECT * FROM forms WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        access = _published_row_writable(
            row,
            guest=bool(guest_token),
            pin=pin,
            actor_user_id=submitter_user_id,
        )
        if access:
            return None, access
        found = _find_draft(
            db, row["id"], submitter_user_id=submitter_user_id, resume_token=resume_token
        )
        if not found or not found["is_draft"]:
            return {"answers": {}, "receipt_code": None, "submitter_name": None}, None
        definition = None
        if found["version_id"]:
            ver = db.execute(
                "SELECT definition_json FROM form_versions WHERE id = ?",
                (found["version_id"],),
            ).fetchone()
            if ver:
                try:
                    definition = json.loads(ver["definition_json"])
                except (TypeError, json.JSONDecodeError):
                    definition = None
        if definition is None:
            definition = _definition(row)
        try:
            answers = json.loads(found["answers_json"])
        except (TypeError, json.JSONDecodeError):
            answers = {}
        return {
            "receipt_code": found["receipt_code"],
            "submitter_name": found["submitter_name"],
            "answers": crypto.reveal_answers(definition, answers, mask=False),
            "updated_at": found["updated_at"],
        }, None


def list_submissions(
    form_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    mask: bool = True,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if not _can_view_submissions(row, actor_user_id, actor_groups):
            return None, "回答を閲覧する権限がありません"
        fallback = published_definition(form_id) or _definition(row)
        rows = db.execute(
            "SELECT s.id, s.receipt_code, s.submitter_user_id, s.submitter_name, "
            "s.answers_json, s.created_at, s.version_id, s.withdrawn_at, s.withdrawn_by, "
            "v.version AS form_version, v.published_at, v.definition_json "
            "FROM submissions s "
            "LEFT JOIN form_versions v ON v.id = s.version_id "
            "WHERE s.form_id = ? AND s.is_draft = 0 "
            "ORDER BY s.created_at DESC, s.rowid DESC",
            (form_id,),
        ).fetchall()
        out = []
        for r in rows:
            try:
                answers = json.loads(r["answers_json"])
            except (TypeError, json.JSONDecodeError):
                answers = {}
            definition = fallback
            if r["definition_json"]:
                try:
                    parsed = json.loads(r["definition_json"])
                    if isinstance(parsed, dict):
                        definition = parsed
                except (TypeError, json.JSONDecodeError):
                    pass
            answers = crypto.reveal_answers(definition, answers, mask=mask)
            mode = _identity_mode(row)
            uid = r["submitter_user_id"]
            hide_id = mode == "anonymous" or str(uid or "").startswith("anon:")
            out.append(
                {
                    "id": r["id"],
                    "receipt_code": r["receipt_code"],
                    "submitter_user_id": None if hide_id else uid,
                    "submitter_name": None if mode == "anonymous" else r["submitter_name"],
                    "respondent_label": _respondent_label(
                        definition,
                        answers,
                        receipt_code=r["receipt_code"],
                        submitter_name=r["submitter_name"],
                        submitter_user_id=uid,
                        identity_mode=mode,
                    ),
                    "answers": answers,
                    "created_at": r["created_at"],
                    "version_id": r["version_id"],
                    "form_version": r["form_version"],
                    "published_at": r["published_at"],
                    "withdrawn": _is_withdrawn(r),
                    "withdrawn_at": r["withdrawn_at"] if "withdrawn_at" in r.keys() else None,
                    "withdrawn_by": r["withdrawn_by"] if "withdrawn_by" in r.keys() else None,
                    "definition": definition,
                }
            )
        return out, None


def set_withdrawn(
    *,
    form_id: str | None = None,
    submission_id: str | None = None,
    guest_token: str | None = None,
    receipt_code: str | None = None,
    pin: str | None = None,
    actor_user_id: str | None = None,
    actor_groups: list[str] | None = None,
    withdrawn: bool,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        if guest_token:
            form = db.execute(
                "SELECT * FROM forms WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            form = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not form:
            return None, "フォームが見つかりません"
        if guest_token:
            if form["visibility"] == "internal":
                return None, "このフォームは外部公開されていません"
            if form["pin_hash"]:
                if not pin or not verify_pin(pin, form["pin_hash"]):
                    return None, "暗証番号が正しくありません"
            if not receipt_code:
                return None, "控え番号を入力してください"
            sub = db.execute(
                "SELECT * FROM submissions WHERE form_id = ? AND receipt_code = ? AND is_draft = 0",
                (form["id"], receipt_code.strip()),
            ).fetchone()
        else:
            if not _can_view_submissions(form, actor_user_id, actor_groups):
                return None, "回答を取り下げる権限がありません"
            sub = db.execute(
                "SELECT * FROM submissions WHERE id = ? AND form_id = ? AND is_draft = 0",
                (submission_id, form["id"]),
            ).fetchone()
        if not sub:
            return None, "回答が見つかりません"
        already = _is_withdrawn(sub)
        if withdrawn and already:
            return None, "この回答はすでに取り下げられています"
        if not withdrawn and not already:
            return None, "この回答は取り下げられていません"
        if guest_token and not withdrawn:
            return None, "取下げの取消は庁内から行ってください"
        now = _now_iso()
        db.execute(
            "UPDATE submissions SET withdrawn_at = ?, withdrawn_by = ?, updated_at = ? WHERE id = ?",
            (
                now if withdrawn else None,
                (actor_user_id or "guest") if withdrawn else None,
                now,
                sub["id"],
            ),
        )
        db.commit()
    return {
        "id": sub["id"],
        "receipt_code": sub["receipt_code"],
        "withdrawn": withdrawn,
        "message": "回答を取り下げました" if withdrawn else "取下げを取り消しました",
    }, None


def _union_answer_components(
    items: list[dict[str, Any]],
    fallback: dict[str, Any],
) -> list[dict[str, Any]]:
    """回答に出てきた版の部品を id でまとめる。新しい回答のラベルを優先。"""
    by_id: dict[str, dict[str, Any]] = {}
    sources = [fallback, *[item.get("definition") or {} for item in reversed(items)]]
    for definition in sources:
        for comp in definition.get("components") or []:
            if comp.get("type") in spec.DISPLAY_TYPES:
                continue
            cid = str(comp.get("id") or "")
            if cid:
                by_id[cid] = comp
    return list(by_id.values())


def export_csv(
    form_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    reveal: bool = False,
) -> tuple[str | None, str | None]:
    form = get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups)
    if not form:
        return None, "フォームが見つかりません"
    if not form.get("can_view_submissions"):
        return None, "回答を書き出す権限がありません"
    if reveal and not form.get("can_reveal"):
        return None, "個人番号を書き出す権限がありません"
    fallback = published_definition(form_id) or form["definition"]
    items, err = list_submissions(
        form_id, actor_user_id=actor_user_id, actor_groups=actor_groups, mask=not reveal
    )
    if err or items is None:
        return None, err
    comps = _union_answer_components(items, fallback)
    buf = io.StringIO()
    headers = ["receipt_code", "submitter_name", "status", "created_at", "form_version"] + [
        c["label"] for c in comps
    ]
    writer = csv.writer(buf)
    writer.writerow(headers)
    for item in items:
        answers = item.get("answers") or {}
        row = [
            item["receipt_code"],
            item.get("respondent_label") or item.get("submitter_name") or "",
            "取下げ" if item.get("withdrawn") else "受付",
            item["created_at"],
            item.get("form_version") or "",
        ]
        for c in comps:
            val = answers.get(c["id"], "")
            if isinstance(val, list):
                val = ";".join(str(v) for v in val)
            elif isinstance(val, dict):
                val = json.dumps(val, ensure_ascii=False)
            row.append(val)
        writer.writerow(row)
    if reveal:
        db = connect()
        with _lock:
            _log_audit(db, form_id=form_id, actor_user_id=actor_user_id, action="export_unmasked")
            db.commit()
    return buf.getvalue(), None


def export_jsonl(
    form_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    reveal: bool = False,
) -> tuple[str | None, str | None]:
    form = get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups)
    if not form:
        return None, "フォームが見つかりません"
    if reveal and not form.get("can_reveal"):
        return None, "個人番号を書き出す権限がありません"
    items, err = list_submissions(
        form_id, actor_user_id=actor_user_id, actor_groups=actor_groups, mask=not reveal
    )
    if err or items is None:
        return None, err
    if reveal:
        db = connect()
        with _lock:
            _log_audit(db, form_id=form_id, actor_user_id=actor_user_id, action="export_unmasked")
            db.commit()
    lines = [
        json.dumps(
            {
                "receipt_code": item["receipt_code"],
                "submitter_name": item.get("respondent_label") or item.get("submitter_name") or "",
                "respondent_label": item.get("respondent_label") or "",
                "status": "取下げ" if item.get("withdrawn") else "受付",
                "withdrawn": bool(item.get("withdrawn")),
                "created_at": item["created_at"],
                "form_version": item.get("form_version"),
                "published_at": item.get("published_at"),
                "answers": item.get("answers") or {},
            },
            ensure_ascii=False,
        )
        for item in items
    ]
    return ("\n".join(lines) + ("\n" if lines else "")), None


def reveal_submission(
    form_id: str,
    submission_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    form = get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups)
    if not form:
        return None, "フォームが見つかりません"
    if not form.get("can_reveal"):
        return None, "個人番号を表示する権限がありません"
    items, err = list_submissions(
        form_id, actor_user_id=actor_user_id, actor_groups=actor_groups, mask=False
    )
    if err or items is None:
        return None, err
    found = next((item for item in items if item["id"] == submission_id), None)
    if not found:
        return None, "回答が見つかりません"
    db = connect()
    with _lock:
        _log_audit(
            db,
            form_id=form_id,
            actor_user_id=actor_user_id,
            action="reveal",
            submission_id=submission_id,
        )
        db.commit()
    return found, None


def list_audit(
    form_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if not _can_view_submissions(row, actor_user_id, actor_groups):
            return None, "監査ログを閲覧する権限がありません"
        rows = db.execute(
            "SELECT id, form_id, submission_id, actor_user_id, action, created_at "
            "FROM audit_events WHERE form_id = ? ORDER BY created_at DESC, rowid DESC",
            (form_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "form_id": r["form_id"],
                "submission_id": r["submission_id"],
                "actor_user_id": r["actor_user_id"],
                "action": r["action"],
                "created_at": r["created_at"],
            }
            for r in rows
        ], None


def delete_old_forms(retention_days: int | None = None) -> int:
    """保持期限を過ぎたフォームを削除する。フォーム単位の retention_days を優先。"""
    default_days = retention_days if retention_days is not None else RETENTION_DAYS
    now = datetime.now(timezone.utc)
    db = connect()
    deleted = 0
    expired: list[str] = []
    with _lock:
        rows = db.execute("SELECT id, created_at, retention_days FROM forms").fetchall()
        for row in rows:
            days = row["retention_days"] or default_days
            try:
                created = datetime.fromisoformat(row["created_at"])
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            if now - created > timedelta(days=days):
                db.execute("DELETE FROM forms WHERE id = ?", (row["id"],))
                expired.append(row["id"])
                deleted += 1
        cutoff = (now - timedelta(hours=24)).replace(microsecond=0).isoformat()
        orphans = db.execute(
            "SELECT id, form_id FROM uploaded_files "
            "WHERE submission_id IS NULL AND created_at < ?",
            (cutoff,),
        ).fetchall()
        for orphan in orphans:
            files.remove_blob(orphan["form_id"], orphan["id"])
            db.execute("DELETE FROM uploaded_files WHERE id = ?", (orphan["id"],))
        db.commit()
    for form_id in expired:
        files.remove_form_dir(form_id)
    return deleted
