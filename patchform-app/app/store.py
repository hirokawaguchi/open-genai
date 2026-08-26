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
from urllib.parse import urlparse

import bcrypt

from . import crypto, files, notify, procedure, spec

DB_PATH = os.environ.get("PATCHFORM_DB_PATH", "/data/patchform.db")
RETENTION_DAYS = int(os.environ.get("PATCHFORM_RETENTION_DAYS", "365"))
PUBLIC_ENDPOINT = (os.environ.get("PATCHFORM_PUBLIC_ENDPOINT") or "").rstrip("/")

_lock = threading.RLock()
_db: sqlite3.Connection | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def now_iso() -> str:
    return _now_iso()


def parse_since(value: str | None) -> tuple[datetime | None, str | None]:
    raw = (value or "").strip()
    if not raw:
        return None, None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, "since は ISO 8601 の日時で指定してください"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, None


def _parse_iso(value: str | None) -> datetime | None:
    parsed, _err = parse_since(value)
    return parsed


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
            CREATE TABLE IF NOT EXISTS procedures (
              id TEXT PRIMARY KEY,
              name TEXT NOT NULL,
              description TEXT,
              guide_form_id TEXT NOT NULL,
              mapping_json TEXT NOT NULL,
              status TEXT NOT NULL,
              creator_user_id TEXT,
              creator_name TEXT,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              FOREIGN KEY (guide_form_id) REFERENCES forms(id)
            );
            CREATE TABLE IF NOT EXISTS applications (
              id TEXT PRIMARY KEY,
              token TEXT NOT NULL UNIQUE,
              procedure_id TEXT NOT NULL,
              guide_form_id TEXT NOT NULL,
              guide_submission_id TEXT NOT NULL,
              form_ids_json TEXT NOT NULL,
              notice_json TEXT NOT NULL,
              created_at TEXT NOT NULL,
              FOREIGN KEY (procedure_id) REFERENCES procedures(id),
              FOREIGN KEY (guide_form_id) REFERENCES forms(id),
              FOREIGN KEY (guide_submission_id) REFERENCES submissions(id)
            );
            CREATE INDEX IF NOT EXISTS idx_procedures_guide ON procedures(guide_form_id);
            CREATE INDEX IF NOT EXISTS idx_procedures_status ON procedures(status);
            CREATE INDEX IF NOT EXISTS idx_applications_token ON applications(token);
            CREATE INDEX IF NOT EXISTS idx_applications_proc ON applications(procedure_id);
            """
        )
        _ensure_columns(db)
        file_moves = _migrate_legacy_receptions(db)
        db.commit()
    for old_id, new_id in file_moves:
        files.rename_form_dir(old_id, new_id)


def _ensure_columns(db: sqlite3.Connection) -> None:
    wanted = (
        ("forms", "allow_draft", "INTEGER NOT NULL DEFAULT 1"),
        ("forms", "allow_multiple", "INTEGER NOT NULL DEFAULT 1"),
        ("forms", "editor_user_ids", "TEXT"),
        ("forms", "viewer_user_ids", "TEXT"),
        ("forms", "identity_mode", "TEXT NOT NULL DEFAULT 'optional'"),
        ("forms", "source_form_id", "TEXT"),
        ("forms", "locked", "INTEGER NOT NULL DEFAULT 0"),
        ("forms", "tags", "TEXT NOT NULL DEFAULT '[]'"),
        ("submissions", "withdrawn_at", "TEXT"),
        ("submissions", "withdrawn_by", "TEXT"),
        ("submissions", "application_id", "TEXT"),
        ("submissions", "application_item_id", "TEXT"),
        ("procedures", "notify_emails_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("applications", "items_json", "TEXT NOT NULL DEFAULT '[]'"),
    )
    for table, name, decl in wanted:
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    db.execute("CREATE INDEX IF NOT EXISTS idx_forms_source ON forms(source_form_id)")


def _source_form_id(row: sqlite3.Row) -> str | None:
    if "source_form_id" not in row.keys():
        return None
    value = row["source_form_id"]
    return str(value) if value else None


def _is_reception(row: sqlite3.Row) -> bool:
    return bool(_source_form_id(row))


def _definition_id(row: sqlite3.Row) -> str:
    return _source_form_id(row) or row["id"]


def _is_locked(row: sqlite3.Row) -> bool:
    return bool(_flag(row, "locked", 0))


NAVIGATION_TAG = "ナビゲーション"
MAX_FORM_TAGS = 20
MAX_FORM_TAG_LEN = 30


def normalize_tags(raw: Any) -> tuple[list[str] | None, str | None]:
    if raw is None:
        return [], None
    if isinstance(raw, str):
        items = [part.strip() for part in raw.replace("、", ",").replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        items = [str(item).strip() for item in raw]
    else:
        return None, "タグの形式が不正です"
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not item:
            continue
        if len(item) > MAX_FORM_TAG_LEN:
            return None, f"タグは{MAX_FORM_TAG_LEN}文字以内にしてください"
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
        if len(out) > MAX_FORM_TAGS:
            return None, f"タグは{MAX_FORM_TAGS}個までです"
    return out, None


def _row_tags(row: sqlite3.Row) -> list[str]:
    if "tags" not in row.keys() or not row["tags"]:
        return []
    try:
        data = json.loads(row["tags"])
    except (TypeError, json.JSONDecodeError):
        return []
    tags, _err = normalize_tags(data if isinstance(data, list) else [])
    return tags or []


def _tags_json(tags: list[str]) -> str:
    return json.dumps(tags, ensure_ascii=False)


def _form_row(db: sqlite3.Connection, form_id: str) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()


def _as_definition_id(db: sqlite3.Connection, form_id: str) -> str | None:
    row = _form_row(db, form_id)
    return _definition_id(row) if row else None


def _published_reception_row(db: sqlite3.Connection, form_id: str) -> sqlite3.Row | None:
    row = _form_row(db, form_id)
    if not row:
        return None
    def_id = _definition_id(row)
    rec = db.execute(
        "SELECT * FROM forms WHERE source_form_id = ? AND status = 'published' "
        "ORDER BY created_at DESC",
        (def_id,),
    ).fetchone()
    if rec:
        return rec
    src = _form_row(db, def_id)
    if src and not _is_reception(src) and src["status"] == "published":
        return src
    return None


def _replace_form_id_json(raw: str | None, old_id: str, new_id: str) -> str:
    try:
        items = json.loads(raw or "[]")
    except (TypeError, json.JSONDecodeError):
        items = []
    if not isinstance(items, list):
        return raw or "[]"
    changed = [new_id if item == old_id else item for item in items]
    return json.dumps(changed, ensure_ascii=False)


def _migrate_legacy_receptions(db: sqlite3.Connection) -> list[tuple[str, str]]:
    """公開中・受付終了の定義を、同じゲスト URL の受付コピーに分ける。"""
    cols = {r[1] for r in db.execute("PRAGMA table_info(forms)").fetchall()}
    if "source_form_id" not in cols:
        return []
    rows = db.execute(
        "SELECT * FROM forms WHERE (source_form_id IS NULL OR source_form_id = '') "
        "AND status IN ('published', 'closed')"
    ).fetchall()
    moves: list[tuple[str, str]] = []
    for row in rows:
        rec_id = str(uuid.uuid4())
        old_token = row["guest_token"]
        def_token = secrets.token_urlsafe(24)
        now = _now_iso()
        db.execute(
            "UPDATE forms SET guest_token = ?, updated_at = ? WHERE id = ?",
            (def_token, now, row["id"]),
        )
        db.execute(
            "INSERT INTO forms (id, guest_token, title, description, status, visibility, "
            "definition_json, published_version_id, pin_hash, creator_user_id, creator_name, "
            "retention_days, created_at, updated_at, allow_draft, allow_multiple, "
            "editor_user_ids, viewer_user_ids, identity_mode, source_form_id, locked, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                rec_id,
                old_token,
                row["title"],
                row["description"],
                row["status"],
                row["visibility"],
                row["definition_json"],
                row["published_version_id"],
                row["pin_hash"],
                row["creator_user_id"],
                row["creator_name"],
                row["retention_days"],
                row["created_at"],
                now,
                _flag(row, "allow_draft"),
                _flag(row, "allow_multiple"),
                row["editor_user_ids"] if "editor_user_ids" in row.keys() else "[]",
                row["viewer_user_ids"] if "viewer_user_ids" in row.keys() else "[]",
                _identity_mode(row),
                row["id"],
                0,
                _tags_json(_row_tags(row)),
            ),
        )
        db.execute("UPDATE form_versions SET form_id = ? WHERE form_id = ?", (rec_id, row["id"]))
        db.execute("UPDATE submissions SET form_id = ? WHERE form_id = ?", (rec_id, row["id"]))
        db.execute("UPDATE uploaded_files SET form_id = ? WHERE form_id = ?", (rec_id, row["id"]))
        db.execute("UPDATE audit_events SET form_id = ? WHERE form_id = ?", (rec_id, row["id"]))
        db.execute(
            "UPDATE applications SET guide_form_id = ? WHERE guide_form_id = ?",
            (rec_id, row["id"]),
        )
        for app in db.execute("SELECT id, form_ids_json FROM applications").fetchall():
            next_json = _replace_form_id_json(app["form_ids_json"], row["id"], rec_id)
            if next_json != app["form_ids_json"]:
                db.execute(
                    "UPDATE applications SET form_ids_json = ? WHERE id = ?",
                    (next_json, app["id"]),
                )
        db.execute(
            "UPDATE forms SET status = 'draft', locked = 1, published_version_id = NULL, "
            "updated_at = ? WHERE id = ?",
            (now, row["id"]),
        )
        moves.append((row["id"], rec_id))
    return moves


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


def public_application_url_for(token: str) -> str:
    if not PUBLIC_ENDPOINT:
        return f"/public/p/{token}"
    return f"{PUBLIC_ENDPOINT}/public/p/{token}"


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
        "source_form_id": _source_form_id(row),
        "locked": _is_locked(row),
        "kind": "reception" if _is_reception(row) else "definition",
        "work_status": None
        if _is_reception(row)
        else ("ready" if _is_locked(row) else "editing"),
        "tags": _row_tags(row),
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
            if _is_reception(row):
                continue
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
            item["can_delete"] = role in ("admin", "owner")
            item["can_view_submissions"] = role in ("admin", "owner", "editor", "viewer")
            item["reception_count"] = db.execute(
                "SELECT COUNT(*) AS n FROM forms WHERE source_form_id = ?",
                (row["id"],),
            ).fetchone()["n"]
            item["has_opening"] = bool(
                db.execute(
                    "SELECT 1 FROM forms WHERE source_form_id = ? AND status = 'published' LIMIT 1",
                    (row["id"],),
                ).fetchone()
            )
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
        if not _is_reception(row):
            recs = db.execute(
                "SELECT * FROM forms WHERE source_form_id = ? ORDER BY created_at DESC",
                (row["id"],),
            ).fetchall()
            receptions: list[dict[str, Any]] = []
            for rec in recs:
                item = _row_to_form(rec, include_definition=False)
                item["submission_count"] = db.execute(
                    "SELECT COUNT(*) AS n FROM submissions WHERE form_id = ? AND is_draft = 0 "
                    "AND (withdrawn_at IS NULL OR withdrawn_at = '')",
                    (rec["id"],),
                ).fetchone()["n"]
                receptions.append(item)
            out["receptions"] = receptions
            if receptions:
                out["can_delete"] = False
        else:
            src = _form_row(db, row["source_form_id"])
            out["source_title"] = src["title"] if src else None
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
    tags: list[str] | str | None = None,
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
    tag_list, tag_err = normalize_tags(tags)
    if tag_err or tag_list is None:
        return None, tag_err
    form_id = str(uuid.uuid4())
    guest_token = secrets.token_urlsafe(24)
    now = _now_iso()
    days = retention_days if retention_days is not None else RETENTION_DAYS
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO forms (id, guest_token, title, description, status, visibility, "
            "definition_json, published_version_id, pin_hash, creator_user_id, creator_name, "
            "retention_days, created_at, updated_at, source_form_id, locked, tags) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                None,
                0,
                _tags_json(tag_list),
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
    tags: list[str] | str | None = None,
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
        if not _is_reception(row) and _is_locked(row):
            return None, "作成完了のフォームは部品を変えられません。作成に戻してから直してください。"
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
        if tags is not None:
            tag_list, tag_err = normalize_tags(tags)
            if tag_err or tag_list is None:
                return None, tag_err
            next_tags = _tags_json(tag_list)
        else:
            next_tags = row["tags"] if "tags" in row.keys() and row["tags"] else "[]"
        db.execute(
            "UPDATE forms SET title = ?, description = ?, visibility = ?, definition_json = ?, "
            "pin_hash = ?, retention_days = ?, allow_draft = ?, allow_multiple = ?, "
            "editor_user_ids = ?, viewer_user_ids = ?, identity_mode = ?, tags = ?, "
            "updated_at = ? WHERE id = ?",
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
                next_tags,
                _now_iso(),
                form_id,
            ),
        )
        db.commit()
    return get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups), None


def _publish_form_version(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    actor_user_id: str,
) -> tuple[str | None, str | None]:
    definition = _definition(row)
    normalized, err = spec.validate_definition(definition, visibility=row["visibility"])
    if err or normalized is None:
        return None, err
    if not normalized["components"]:
        return None, "部品が無いフォームは公開できません"
    next_ver = db.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS n FROM form_versions WHERE form_id = ?",
        (row["id"],),
    ).fetchone()["n"]
    version_id = str(uuid.uuid4())
    now = _now_iso()
    db.execute(
        "INSERT INTO form_versions (id, form_id, version, definition_json, "
        "published_at, published_by) VALUES (?,?,?,?,?,?)",
        (
            version_id,
            row["id"],
            next_ver,
            json.dumps(normalized, ensure_ascii=False),
            now,
            actor_user_id,
        ),
    )
    db.execute(
        "UPDATE forms SET status = 'published', published_version_id = ?, definition_json = ?, "
        "updated_at = ? WHERE id = ?",
        (version_id, json.dumps(normalized, ensure_ascii=False), now, row["id"]),
    )
    return version_id, None


def _insert_reception(
    db: sqlite3.Connection,
    source: sqlite3.Row,
    *,
    actor_user_id: str,
) -> tuple[str | None, str | None]:
    definition = _definition(source)
    normalized, err = spec.validate_definition(definition, visibility=source["visibility"])
    if err or normalized is None:
        return None, err
    if not normalized["components"]:
        return None, "部品が無いフォームは受付を開始できません"
    rec_id = str(uuid.uuid4())
    guest_token = secrets.token_urlsafe(24)
    now = _now_iso()
    version_id = str(uuid.uuid4())
    db.execute(
        "INSERT INTO forms (id, guest_token, title, description, status, visibility, "
        "definition_json, published_version_id, pin_hash, creator_user_id, creator_name, "
        "retention_days, created_at, updated_at, allow_draft, allow_multiple, "
        "editor_user_ids, viewer_user_ids, identity_mode, source_form_id, locked, tags) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            rec_id,
            guest_token,
            source["title"],
            source["description"],
            "published",
            source["visibility"],
            json.dumps(normalized, ensure_ascii=False),
            version_id,
            source["pin_hash"],
            source["creator_user_id"],
            source["creator_name"],
            source["retention_days"],
            now,
            now,
            _flag(source, "allow_draft"),
            _flag(source, "allow_multiple"),
            source["editor_user_ids"] if "editor_user_ids" in source.keys() else "[]",
            source["viewer_user_ids"] if "viewer_user_ids" in source.keys() else "[]",
            _identity_mode(source),
            source["id"],
            0,
            _tags_json(_row_tags(source)),
        ),
    )
    db.execute(
        "INSERT INTO form_versions (id, form_id, version, definition_json, "
        "published_at, published_by) VALUES (?,?,?,?,?,?)",
        (
            version_id,
            rec_id,
            1,
            json.dumps(normalized, ensure_ascii=False),
            now,
            actor_user_id,
        ),
    )
    db.execute(
        "UPDATE forms SET locked = 1, status = 'draft', published_version_id = NULL, "
        "updated_at = ? WHERE id = ?",
        (now, source["id"]),
    )
    return rec_id, None


def _closed_reception_row(db: sqlite3.Connection, form_id: str) -> sqlite3.Row | None:
    row = _form_row(db, form_id)
    if not row:
        return None
    source = row if not _is_reception(row) else _form_row(db, _definition_id(row))
    if not source:
        return None
    return db.execute(
        "SELECT * FROM forms WHERE source_form_id = ? AND status = 'closed' "
        "ORDER BY created_at DESC",
        (_definition_id(source),),
    ).fetchone()


def _ensure_reception(
    db: sqlite3.Connection,
    form_id: str,
    *,
    actor_user_id: str,
) -> tuple[str | None, str | None]:
    rec = _published_reception_row(db, form_id)
    if rec:
        return rec["id"], None
    row = _form_row(db, form_id)
    if not row:
        return None, "フォームが見つかりません"
    source = row if not _is_reception(row) else _form_row(db, _definition_id(row))
    if not source:
        return None, "フォームが見つかりません"
    closed = _closed_reception_row(db, form_id)
    if closed:
        db.execute(
            "UPDATE forms SET status = 'published', updated_at = ? WHERE id = ?",
            (_now_iso(), closed["id"]),
        )
        return closed["id"], None
    return _insert_reception(db, source, actor_user_id=actor_user_id)


def _close_procedure_receptions(db: sqlite3.Connection, row: sqlite3.Row) -> None:
    mapping, _err = procedure.normalize_mapping(row["mapping_json"])
    ids = [row["guide_form_id"]]
    for rule in mapping.get("rules") or []:
        ids.extend(rule.get("form_ids") or [])
    seen: set[str] = set()
    now = _now_iso()
    for fid in ids:
        if not fid or fid in seen:
            continue
        seen.add(fid)
        rec = _published_reception_row(db, fid)
        if rec:
            db.execute(
                "UPDATE forms SET status = 'closed', updated_at = ? WHERE id = ?",
                (now, rec["id"]),
            )


def set_tags(
    form_id: str,
    *,
    actor_user_id: str,
    tags: list[str] | str | None,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if not _can_edit(row, actor_user_id, actor_groups):
            return None, "このフォームを編集する権限がありません"
        if _is_reception(row):
            return None, "受付の窓口ではタグを変更できません"
        if row["status"] in ("archived",):
            return None, "ゴミ箱のフォームはタグを変更できません"
        tag_list, tag_err = normalize_tags(tags)
        if tag_err or tag_list is None:
            return None, tag_err
        db.execute(
            "UPDATE forms SET tags = ?, updated_at = ? WHERE id = ?",
            (_tags_json(tag_list), _now_iso(), form_id),
        )
        db.commit()
    return get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups), None


def set_status(
    form_id: str,
    *,
    actor_user_id: str,
    status: str,
    actor_groups: list[str] | None = None,
    locked: bool | None = None,
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
        if _is_reception(row):
            if locked is not None:
                return None, "受付の窓口では作成完了の操作はできません"
            if status == "draft":
                return None, "受付の窓口を作成中には戻せません。受付を終了してください。"
            if status == "published":
                _vid, err = _publish_form_version(db, row, actor_user_id=actor_user_id)
                if err:
                    return None, err
            elif status == "closed":
                db.execute(
                    "UPDATE forms SET status = ?, updated_at = ? WHERE id = ?",
                    (status, _now_iso(), form_id),
                )
            else:
                db.execute(
                    "UPDATE forms SET status = ?, updated_at = ? WHERE id = ?",
                    (status, _now_iso(), form_id),
                )
            db.commit()
            return get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups), None
        if status == "closed":
            return None, "作成中のフォームは受付終了できません。受付は申請受付の窓口で終了します。"
        if status == "published":
            return None, "受付は手続きを公開して開始します。"
        if status == "draft":
            next_locked = 1 if locked is True else 0
            if next_locked:
                definition = _definition(row)
                normalized, err = spec.validate_definition(
                    definition, visibility=row["visibility"]
                )
                if err or normalized is None:
                    return None, err
                if not normalized["components"]:
                    return None, "部品が無いフォームは作成完了できません"
            db.execute(
                "UPDATE forms SET status = 'draft', locked = ?, updated_at = ? WHERE id = ?",
                (next_locked, _now_iso(), form_id),
            )
            db.commit()
            return get_form(form_id, actor_user_id=actor_user_id, actor_groups=actor_groups), None
        db.execute(
            "UPDATE forms SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), form_id),
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
        if not _is_reception(row):
            child = db.execute(
                "SELECT id FROM forms WHERE source_form_id = ? LIMIT 1", (form_id,)
            ).fetchone()
            if child:
                return "受付の窓口があるため削除できません。先に窓口を終了して削除してください。"
        used_name = _procedure_using_form(db, form_id)
        if used_name:
            return used_name
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
    application_token: str | None = None,
    application_item_id: str | None = None,
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
        linked_app_id, link_err = _resolve_application_id(
            db, row["id"], application_token
        )
        if link_err:
            return None, link_err
        linked_item_id = _resolve_application_item_id(
            db, linked_app_id, row["id"], application_item_id
        )
        if existing:
            sid = existing["id"]
            receipt = existing["receipt_code"]
            db.execute(
                "UPDATE submissions SET version_id = ?, submitter_user_id = ?, submitter_name = ?, "
                "answers_json = ?, is_draft = ?, application_id = COALESCE(?, application_id), "
                "application_item_id = COALESCE(?, application_item_id), "
                "updated_at = ? WHERE id = ?",
                (
                    version_id,
                    stored_id,
                    stored_name,
                    json.dumps(cleaned, ensure_ascii=False),
                    1 if is_draft else 0,
                    linked_app_id,
                    linked_item_id,
                    now,
                    sid,
                ),
            )
        else:
            sid = str(uuid.uuid4())
            receipt = secrets.token_urlsafe(10)
            db.execute(
                "INSERT INTO submissions (id, form_id, version_id, receipt_code, "
                "submitter_user_id, submitter_name, answers_json, is_draft, "
                "application_id, application_item_id, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    row["id"],
                    version_id,
                    receipt,
                    stored_id,
                    stored_name,
                    json.dumps(cleaned, ensure_ascii=False),
                    1 if is_draft else 0,
                    linked_app_id,
                    linked_item_id,
                    now,
                    now,
                ),
            )
        bind_err = _bind_uploaded_files(db, row["id"], sid, definition, cleaned)
        if bind_err:
            db.rollback()
            return None, bind_err
        opened = None
        notify_proc = None
        if not is_draft:
            opened = _open_application_from_guide(db, row["id"], sid, cleaned)
            if opened:
                notify_proc = db.execute(
                    "SELECT name, notify_emails_json FROM procedures WHERE id = ?",
                    (opened.get("procedure_id"),),
                ).fetchone()
        db.commit()
    if opened:
        try:
            notify.notify_new_application(
                opened,
                recipients=_emails_from_row(notify_proc) if notify_proc else [],
                procedure_name=notify_proc["name"] if notify_proc else None,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[patchform] notify skipped: {exc}")
    out: dict[str, Any] = {
        "id": sid,
        "receipt_code": receipt,
        "is_draft": is_draft,
        "message": "下書きを保存しました" if is_draft else "回答を受け付けました",
    }
    if opened:
        out["application"] = opened
    return out, None


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
                if _form_used_by_procedure(db, row["id"]):
                    continue
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


def _form_used_by_procedure(db: sqlite3.Connection, form_id: str) -> bool:
    return _procedure_using_form(db, form_id) is not None


def _procedure_using_form(db: sqlite3.Connection, form_id: str) -> str | None:
    def_id = _as_definition_id(db, form_id) or form_id
    for proc in db.execute("SELECT name, guide_form_id, mapping_json FROM procedures").fetchall():
        guide_def = _as_definition_id(db, proc["guide_form_id"]) or proc["guide_form_id"]
        if guide_def == def_id or proc["guide_form_id"] == form_id:
            return f"手続き「{proc['name']}」の案内に使われているため削除できません"
        mapping, _err = procedure.normalize_mapping(proc["mapping_json"])
        for rule in mapping.get("rules") or []:
            for fid in rule.get("form_ids") or []:
                mapped_def = _as_definition_id(db, fid) or fid
                if mapped_def == def_id or fid == form_id:
                    return f"手続き「{proc['name']}」の様式に使われているため削除できません"
    return None


def _can_edit_procedure(
    row: sqlite3.Row, actor_user_id: str | None, groups: list[str] | None
) -> bool:
    if _is_admin(groups):
        return True
    return bool(actor_user_id) and row["creator_user_id"] == actor_user_id


def _guide_definition(db: sqlite3.Connection, guide_form_id: str) -> dict[str, Any] | None:
    published = published_definition(guide_form_id)
    if published:
        return published
    row = db.execute("SELECT * FROM forms WHERE id = ?", (guide_form_id,)).fetchone()
    return _definition(row) if row else None


def _row_to_procedure(
    db: sqlite3.Connection,
    row: sqlite3.Row,
    *,
    actor_user_id: str | None = None,
    actor_groups: list[str] | None = None,
) -> dict[str, Any]:
    mapping, _err = procedure.normalize_mapping(row["mapping_json"])
    guide = db.execute("SELECT * FROM forms WHERE id = ?", (row["guide_form_id"],)).fetchone()
    opening = _published_reception_row(db, row["guide_form_id"]) if guide else None
    closed = _closed_reception_row(db, row["guide_form_id"]) if guide and not opening else None
    definition = _guide_definition(db, row["guide_form_id"]) if guide else None
    opening_or_guide = opening or closed or guide
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "guide_form_id": row["guide_form_id"],
        "guide_title": guide["title"] if guide else None,
        "guide_status": opening_or_guide["status"] if opening_or_guide else None,
        "guide_guest_token": opening["guest_token"]
        if opening
        else (guide["guest_token"] if guide else None),
        "guide_public_url": public_url_for(opening["guest_token"])
        if opening
        else (public_url_for(guide["guest_token"]) if guide else None),
        "guide_reception_id": opening["id"] if opening else None,
        "guide_visibility": (opening or guide)["visibility"] if (opening or guide) else None,
        "mapping": mapping,
        "status": row["status"],
        "creator_user_id": row["creator_user_id"],
        "creator_name": row["creator_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "choice_fields": procedure.choice_fields(definition),
        "warnings": procedure.mapping_warnings(mapping, definition),
        "can_edit": _can_edit_procedure(row, actor_user_id, actor_groups),
        "notify_emails": _emails_from_row(row),
    }


def list_procedures(
    *, actor_user_id: str, actor_groups: list[str] | None = None
) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        rows = db.execute("SELECT * FROM procedures ORDER BY updated_at DESC").fetchall()
        return [
            _row_to_procedure(db, row, actor_user_id=actor_user_id, actor_groups=actor_groups)
            for row in rows
        ]


def get_procedure(
    procedure_id: str,
    *,
    actor_user_id: str | None = None,
    actor_groups: list[str] | None = None,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM procedures WHERE id = ?", (procedure_id,)).fetchone()
        if not row:
            return None
        return _row_to_procedure(
            db, row, actor_user_id=actor_user_id, actor_groups=actor_groups
        )


def _safe_origin(origin: str) -> str | None:
    parsed = urlparse((origin or "").strip())
    if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.username:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def _qr_svg(url: str) -> str:
    import qrcode
    from qrcode.image.svg import SvgPathImage

    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=2, box_size=8)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(image_factory=SvgPathImage)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def procedure_share(
    procedure_id: str,
    *,
    origin: str,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    base = _safe_origin(origin)
    if not base:
        return None, "origin が不正です"
    proc = get_procedure(
        procedure_id, actor_user_id=actor_user_id, actor_groups=actor_groups
    )
    if not proc:
        return None, "手続きが見つかりません"
    if proc["status"] != "published" or not proc.get("guide_reception_id"):
        return None, "この手続きは受付していません"
    internal_url = f"{base}/patchform/apply/{proc['id']}"
    vis = proc.get("guide_visibility")
    external_url = proc.get("guide_public_url") if vis in ("both", "public") else None
    return {
        "id": proc["id"],
        "name": proc["name"],
        "internal_url": internal_url,
        "external_url": external_url,
        "internal_qr_svg": _qr_svg(internal_url),
        "external_qr_svg": _qr_svg(external_url) if external_url else None,
    }, None


def _catalog_form(db: sqlite3.Connection, form_id: str) -> dict[str, Any] | None:
    row = db.execute(
        "SELECT id, title, status, visibility, guest_token FROM forms WHERE id = ?",
        (form_id,),
    ).fetchone()
    if not row:
        return None
    opening = _published_reception_row(db, form_id)
    shown = opening or row
    out: dict[str, Any] = {
        "id": row["id"],
        "title": row["title"],
        "status": shown["status"],
    }
    if shown["status"] == "published" and shown["visibility"] in ("both", "external"):
        out["public_url"] = public_url_for(shown["guest_token"])
    return out


def _inspect_published(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    mapping, _err = procedure.normalize_mapping(row["mapping_json"])
    definition = _guide_definition(db, row["guide_form_id"])
    fields = procedure.choice_fields(definition)
    field_by_id = {f["id"]: f for f in fields}
    forms_seen: dict[str, dict[str, Any]] = {}
    rules_out: list[dict[str, Any]] = []
    for rule in mapping.get("rules") or []:
        field = field_by_id.get(rule["component_id"])
        forms: list[dict[str, Any]] = []
        for fid in rule.get("form_ids") or []:
            item = _catalog_form(db, fid)
            if item:
                forms.append(item)
                forms_seen[fid] = item
        rules_out.append(
            {
                "component_id": rule["component_id"],
                "component_label": (field or {}).get("label") or rule["component_id"],
                "option": rule["option"],
                "forms": forms,
                "notes": rule.get("notes") or "",
                "prepare": rule.get("prepare") or [],
                "refs": rule.get("refs") or [],
            }
        )
    guide = db.execute("SELECT * FROM forms WHERE id = ?", (row["guide_form_id"],)).fetchone()
    opening = _published_reception_row(db, row["guide_form_id"]) if guide else None
    shown = opening or guide
    guide_out: dict[str, Any] | None = None
    if guide and shown:
        guide_out = {
            "id": guide["id"],
            "title": guide["title"],
            "status": shown["status"],
            "choice_fields": fields,
        }
        if shown["status"] == "published" and shown["visibility"] in ("both", "external"):
            guide_out["public_url"] = public_url_for(shown["guest_token"])
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "updated_at": row["updated_at"],
        "guide": guide_out,
        "rules": rules_out,
        "forms": list(forms_seen.values()),
        "warnings": procedure.mapping_warnings(mapping, definition),
    }


def list_published_procedures(*, query: str | None = None) -> list[dict[str, Any]]:
    needle = (query or "").strip().lower()
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT id, name, description, updated_at FROM procedures "
            "WHERE status = 'published' ORDER BY updated_at DESC"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            hay = f"{row['name']} {row['description'] or ''}".lower()
            if needle and needle not in hay:
                continue
            out.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "description": row["description"],
                    "updated_at": row["updated_at"],
                }
            )
        return out


def find_published_procedure(ref: str) -> tuple[dict[str, Any] | None, str | None]:
    key = (ref or "").strip()
    if not key:
        return None, "手続きの指定は必須です"
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM procedures WHERE id = ? AND status = 'published'", (key,)
        ).fetchone()
        if row:
            return _inspect_published(db, row), None
        rows = db.execute(
            "SELECT * FROM procedures WHERE status = 'published' ORDER BY updated_at DESC"
        ).fetchall()
        exact = [r for r in rows if r["name"] == key]
        if len(exact) == 1:
            return _inspect_published(db, exact[0]), None
        if len(exact) > 1:
            return None, "同じ名前の公開手続きが複数あります"
        lowered = key.lower()
        partial = [r for r in rows if lowered in (r["name"] or "").lower()]
        if len(partial) == 1:
            return _inspect_published(db, partial[0]), None
        if len(partial) > 1:
            names = " / ".join(r["name"] for r in partial[:5])
            return None, f"複数の手続きに当たります: {names}"
        return None, "公開中の手続きが見つかりません"


def resolve_published_bundle(
    ref: str, answers: Any
) -> tuple[dict[str, Any] | None, str | None]:
    detail, err = find_published_procedure(ref)
    if err or detail is None:
        return None, err
    fields = ((detail.get("guide") or {}).get("choice_fields") or [])
    normalized, answer_notes = procedure.normalize_answers(fields, answers)
    mapping = {
        "rules": [
            {
                "component_id": rule["component_id"],
                "option": rule["option"],
                "form_ids": [f["id"] for f in (rule.get("forms") or [])],
                "notes": rule.get("notes") or "",
                "prepare": rule.get("prepare") or [],
                "refs": rule.get("refs") or [],
            }
            for rule in (detail.get("rules") or [])
        ]
    }
    resolved = procedure.resolve_bundle(mapping, normalized)
    form_by_id = {item["id"]: item for item in (detail.get("forms") or [])}
    return {
        "procedure_id": detail["id"],
        "procedure_name": detail["name"],
        "answers": normalized,
        "answer_notes": answer_notes,
        "forms": [form_by_id[fid] for fid in resolved["form_ids"] if fid in form_by_id],
        "notes": resolved["notes"],
        "prepare": resolved["prepare"],
        "refs": resolved["refs"],
    }, None


def _emails_from_row(row: sqlite3.Row) -> list[str]:
    if "notify_emails_json" not in row.keys():
        return []
    emails, _err = notify.parse_notify_emails(row["notify_emails_json"])
    return emails or []


def _validate_mapping_forms(
    db: sqlite3.Connection, mapping: dict[str, Any], guide_form_id: str
) -> str | None:
    for rule in mapping.get("rules") or []:
        for fid in rule.get("form_ids") or []:
            if fid == guide_form_id:
                return "案内フォーム自身を様式に足すことはできません"
            form = db.execute("SELECT id FROM forms WHERE id = ?", (fid,)).fetchone()
            if not form:
                return f"様式フォームが見つかりません（{fid}）"
    return None


def create_procedure(
    *,
    name: str,
    description: str | None,
    guide_form_id: str,
    mapping: Any = None,
    notify_emails: Any = None,
    creator_user_id: str,
    creator_name: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    title = (name or "").strip()
    if not title:
        return None, "名前は必須です"
    mapping_norm, err = procedure.normalize_mapping(mapping)
    if err:
        return None, err
    emails, email_err = notify.parse_notify_emails(notify_emails)
    if email_err:
        return None, email_err
    db = connect()
    with _lock:
        guide = db.execute("SELECT * FROM forms WHERE id = ?", (guide_form_id,)).fetchone()
        if not guide:
            return None, "案内フォームが見つかりません"
        stored_guide = _definition_id(guide)
        form_err = _validate_mapping_forms(db, mapping_norm, stored_guide)
        if form_err:
            return None, form_err
        now = _now_iso()
        pid = str(uuid.uuid4())
        db.execute(
            "INSERT INTO procedures (id, name, description, guide_form_id, mapping_json, "
            "notify_emails_json, status, creator_user_id, creator_name, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid,
                title,
                (description or "").strip() or None,
                stored_guide,
                json.dumps(mapping_norm, ensure_ascii=False),
                json.dumps(emails or [], ensure_ascii=False),
                "draft",
                creator_user_id,
                creator_name,
                now,
                now,
            ),
        )
        db.commit()
    return get_procedure(pid, actor_user_id=creator_user_id), None


def create_procedure_from_draft(
    draft: dict[str, Any],
    *,
    creator_user_id: str,
    creator_name: str | None = None,
    visibility: str = "internal",
    apply_forms: bool = True,
    apply_navigation: bool = True,
    apply_notice: bool = True,
    form_keys: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """手引き候補から、選んだ様式・選択肢・案内だけを未公開で作る。"""
    name = str((draft or {}).get("name") or "").strip() or "手続き（仮）"
    apply_forms = bool(apply_forms)
    apply_navigation = bool(apply_navigation)
    apply_notice = bool(apply_notice)
    if not (apply_forms or apply_navigation or apply_notice):
        return None, "反映するものを1つ以上選んでください"

    guide_def = draft.get("guide") if isinstance(draft.get("guide"), dict) else {}
    wanted_keys = None
    if form_keys is not None:
        wanted_keys = {str(k).strip() for k in form_keys if str(k).strip()}

    selected_forms: list[dict[str, Any]] = []
    for item in draft.get("forms") or []:
        if not isinstance(item, dict) or not isinstance(item.get("definition"), dict):
            continue
        key = str(item.get("key") or "").strip()
        if wanted_keys is not None and key not in wanted_keys:
            continue
        selected_forms.append(item)

    if apply_navigation and not any(
        isinstance(c, dict) and c.get("type") in ("select", "radio", "checkbox")
        for c in (guide_def.get("components") or [])
    ):
        return None, "手続きの選択肢が読み取れていません。チェックを外すか、手作業でナビゲーションフォームを作ってください。"
    if apply_forms and not selected_forms:
        return None, "反映する様式がありません。様式を選ぶか、チェックを外してください。"
    if apply_notice and not apply_navigation and not apply_forms:
        return None, "手続きの案内には、選択肢か様式が必要です。"

    extra = []
    if draft.get("missing"):
        extra.append("文書に無し: " + " / ".join(str(x) for x in draft["missing"]))
    if draft.get("notes"):
        extra.append(str(draft["notes"]))
    desc = str(draft.get("description") or "").strip()
    if extra:
        desc = (desc + "\n\n" if desc else "") + "【確認】" + " ".join(extra)
    case_tag = name[:MAX_FORM_TAG_LEN]
    created: list[dict[str, str]] = []
    guide = None
    if apply_navigation:
        guide, err = create_form(
            title=str((guide_def.get("metadata") or {}).get("title") or f"{name}の案内"),
            description=str((guide_def.get("metadata") or {}).get("description") or "") or None,
            creator_user_id=creator_user_id,
            creator_name=creator_name,
            visibility=visibility,
            definition=guide_def,
            tags=[NAVIGATION_TAG, case_tag],
        )
        if err or guide is None:
            return None, err or "案内フォームを作れませんでした"
        created.append({"id": guide["id"], "title": guide["title"], "role": "guide"})

    key_to_id: dict[str, str] = {}
    if apply_forms:
        for item in selected_forms:
            definition = item["definition"]
            form, ferr = create_form(
                title=str((definition.get("metadata") or {}).get("title") or "様式"),
                description=str((definition.get("metadata") or {}).get("description") or "") or None,
                creator_user_id=creator_user_id,
                creator_name=creator_name,
                visibility=visibility,
                definition=definition,
                tags=[case_tag],
            )
            if ferr or form is None:
                return None, ferr or "様式フォームを作れませんでした"
            key = str(item.get("key") or form["id"])
            key_to_id[key] = form["id"]
            created.append({"id": form["id"], "title": form["title"], "role": "form"})

    detail = None
    if apply_notice:
        if guide is None:
            first = next((item for item in created if item["role"] == "form"), None)
            if first is None:
                return None, "手続きの案内には、選択肢か様式が必要です。"
            guide_id = first["id"]
            rules: list[dict[str, Any]] = []
        else:
            guide_id = guide["id"]
            rules = []
            for rule in draft.get("rules") or []:
                if not isinstance(rule, dict):
                    continue
                form_ids = [key_to_id[k] for k in (rule.get("form_keys") or []) if k in key_to_id]
                rules.append(
                    {
                        "component_id": rule.get("component_id"),
                        "option": rule.get("option"),
                        "form_ids": form_ids,
                        "notes": rule.get("notes") or "",
                        "prepare": rule.get("prepare") or [],
                        "refs": [],
                    }
                )
        detail, perr = create_procedure(
            name=name,
            description=desc or None,
            guide_form_id=guide_id,
            mapping={"rules": rules},
            creator_user_id=creator_user_id,
            creator_name=creator_name,
        )
        if perr or detail is None:
            return None, perr
        detail = {**detail, "created_forms": created}

    return {
        "procedure": detail,
        "created_forms": created,
        "applied": {
            "forms": apply_forms,
            "navigation": apply_navigation,
            "notice": apply_notice,
        },
    }, None


def update_procedure(
    procedure_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    name: str | None = None,
    description: str | None = None,
    guide_form_id: str | None = None,
    mapping: Any = None,
    notify_emails: Any = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM procedures WHERE id = ?", (procedure_id,)).fetchone()
        if not row:
            return None, "手続きが見つかりません"
        if not _can_edit_procedure(row, actor_user_id, actor_groups):
            return None, "この手続きを変更する権限がありません"
        next_name = (name if name is not None else row["name"]).strip()
        if not next_name:
            return None, "名前は必須です"
        next_desc = row["description"] if description is None else ((description or "").strip() or None)
        next_guide = guide_form_id or row["guide_form_id"]
        guide = db.execute("SELECT * FROM forms WHERE id = ?", (next_guide,)).fetchone()
        if not guide:
            return None, "案内フォームが見つかりません"
        next_guide = _definition_id(guide)
        if mapping is None:
            next_mapping, err = procedure.normalize_mapping(row["mapping_json"])
        else:
            next_mapping, err = procedure.normalize_mapping(mapping)
        if err:
            return None, err
        form_err = _validate_mapping_forms(db, next_mapping, next_guide)
        if form_err:
            return None, form_err
        if notify_emails is None:
            next_emails = _emails_from_row(row)
        else:
            next_emails, email_err = notify.parse_notify_emails(notify_emails)
            if email_err:
                return None, email_err
        db.execute(
            "UPDATE procedures SET name = ?, description = ?, guide_form_id = ?, "
            "mapping_json = ?, notify_emails_json = ?, updated_at = ? WHERE id = ?",
            (
                next_name,
                next_desc,
                next_guide,
                json.dumps(next_mapping, ensure_ascii=False),
                json.dumps(next_emails or [], ensure_ascii=False),
                _now_iso(),
                procedure_id,
            ),
        )
        db.commit()
    return get_procedure(
        procedure_id, actor_user_id=actor_user_id, actor_groups=actor_groups
    ), None


def set_procedure_status(
    procedure_id: str,
    *,
    actor_user_id: str,
    status: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if status not in ("draft", "published", "archived"):
        return None, "状態が不正です"
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM procedures WHERE id = ?", (procedure_id,)).fetchone()
        if not row:
            return None, "手続きが見つかりません"
        if not _can_edit_procedure(row, actor_user_id, actor_groups):
            return None, "この手続きを変更する権限がありません"
        if status == "archived":
            if row["status"] == "published":
                return None, "公開中の手続きはゴミ箱へ移せません。先に受付を終了してください。"
            _close_procedure_receptions(db, row)
        if status == "draft":
            _close_procedure_receptions(db, row)
        if status == "published":
            guide = _form_row(db, row["guide_form_id"])
            if not guide:
                return None, "案内フォームが見つかりません"
            guide_id, guide_err = _ensure_reception(
                db, row["guide_form_id"], actor_user_id=actor_user_id
            )
            if guide_err or not guide_id:
                return None, guide_err or "案内の受付を開始できませんでした"
            mapping, _merr = procedure.normalize_mapping(row["mapping_json"])
            for rule in mapping.get("rules") or []:
                for fid in rule.get("form_ids") or []:
                    _rid, form_err = _ensure_reception(db, fid, actor_user_id=actor_user_id)
                    if form_err:
                        return None, form_err
            guide_def = _definition_id(guide)
            for other in db.execute(
                "SELECT id, guide_form_id FROM procedures WHERE status = 'published' AND id != ?",
                (procedure_id,),
            ).fetchall():
                other_def = _as_definition_id(db, other["guide_form_id"]) or other["guide_form_id"]
                if other_def == guide_def:
                    return None, "この案内フォームは、すでに別の公開中手続きで使われています"
        db.execute(
            "UPDATE procedures SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), procedure_id),
        )
        db.commit()
    return get_procedure(
        procedure_id, actor_user_id=actor_user_id, actor_groups=actor_groups
    ), None


def delete_procedure(
    procedure_id: str, *, actor_user_id: str, actor_groups: list[str] | None = None
) -> str | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM procedures WHERE id = ?", (procedure_id,)).fetchone()
        if not row:
            return "手続きが見つかりません"
        if not _can_edit_procedure(row, actor_user_id, actor_groups):
            return "この手続きを削除する権限がありません"
        if row["status"] == "published":
            return "公開中の手続きは削除できません。先に公開を取り下げてください。"
        apps = db.execute(
            "SELECT 1 FROM applications WHERE procedure_id = ? LIMIT 1", (procedure_id,)
        ).fetchone()
        if apps:
            return "すでに申請があるため削除できません"
        db.execute("DELETE FROM procedures WHERE id = ?", (procedure_id,))
        db.commit()
    return None


def _form_progress(db: sqlite3.Connection, application_id: str, form_id: str) -> str:
    rows = db.execute(
        "SELECT is_draft, withdrawn_at FROM submissions "
        "WHERE application_id = ? AND form_id = ? ORDER BY updated_at DESC",
        (application_id, form_id),
    ).fetchall()
    has_submitted = False
    has_draft = False
    has_withdrawn = False
    for r in rows:
        withdrawn = _is_withdrawn(r)
        if r["is_draft"]:
            has_draft = True
        elif withdrawn:
            has_withdrawn = True
        else:
            has_submitted = True
    if has_submitted:
        return "submitted"
    if has_draft:
        return "draft"
    if has_withdrawn:
        return "withdrawn"
    return "none"


def _new_item(
    *,
    slot_id: str,
    title: str,
    kind: str,
    required: str = "recommended",
    cardinality: str = "one",
    form_id: str = "",
    template_file_id: str = "",
    fulfillment: str = "",
    file_id: str = "",
    file_name: str = "",
    copy_index: int = 0,
    added_by: str = "system",
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "slot_id": slot_id,
        "title": title or "",
        "kind": kind if kind in procedure.SLOT_KINDS else "yoshiki",
        "required": required if required in procedure.SLOT_REQUIRED else "recommended",
        "cardinality": cardinality if cardinality in procedure.SLOT_CARDINALITY else "one",
        "form_id": form_id or "",
        "template_file_id": template_file_id or "",
        "fulfillment": fulfillment if fulfillment in ("form", "file") else "",
        "file_id": file_id or "",
        "file_name": file_name or "",
        "copy_index": int(copy_index or 0),
        "added_by": added_by or "system",
    }


def _application_items(row: sqlite3.Row) -> list[dict[str, Any]]:
    if "items_json" not in row.keys() or not row["items_json"]:
        return []
    try:
        data = json.loads(row["items_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _items_from_form_ids(db: sqlite3.Connection, row: sqlite3.Row) -> list[dict[str, Any]]:
    """items_json を持たない旧束は、form_ids から枠アイテムに読み替える。"""
    try:
        form_ids = json.loads(row["form_ids_json"])
    except (TypeError, json.JSONDecodeError):
        form_ids = []
    if not isinstance(form_ids, list):
        form_ids = []
    items: list[dict[str, Any]] = []
    for idx, fid in enumerate(form_ids):
        form = _form_row(db, fid)
        items.append(
            _new_item(
                slot_id="" if idx == 0 else f"yoshiki:{fid}",
                title=form["title"] if form else "(削除済み)",
                kind="data" if idx == 0 else "yoshiki",
                required="required" if idx == 0 else "recommended",
                form_id=fid,
                fulfillment="form" if idx == 0 else "",
                added_by="system",
            )
        )
    return items


def _item_status(db: sqlite3.Connection, application_id: str, item: dict[str, Any]) -> str:
    if item.get("fulfillment") == "file" and item.get("file_id"):
        return "submitted"
    form_id = item.get("form_id") or ""
    if not form_id:
        return "none"
    item_id = item.get("id") or ""
    tagged = db.execute(
        "SELECT is_draft, withdrawn_at FROM submissions "
        "WHERE application_id = ? AND application_item_id = ? AND form_id = ?",
        (application_id, item_id, form_id),
    ).fetchall()
    if tagged:
        has_submitted = any(not r["is_draft"] and not _is_withdrawn(r) for r in tagged)
        has_draft = any(r["is_draft"] for r in tagged)
        if has_submitted:
            return "submitted"
        if has_draft:
            return "draft"
        return "withdrawn"
    return _form_progress(db, application_id, form_id)


_TEMPLATE_PREFIX = "template:"


def _procedure_templates(
    db: sqlite3.Connection, guide_form_id: str
) -> dict[str, dict[str, Any]]:
    """枠ごとの様式ひな型を案内フォームのバケットから引く。{slot_id: メタ}。"""
    if not guide_form_id:
        return {}
    rows = db.execute(
        "SELECT id, component_id, filename, mime, size FROM uploaded_files "
        "WHERE form_id = ? AND component_id LIKE 'template:%'",
        (guide_form_id,),
    ).fetchall()
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        slot_id = str(r["component_id"])[len(_TEMPLATE_PREFIX) :]
        out[slot_id] = {
            "file_id": r["id"],
            "filename": r["filename"],
            "mime": r["mime"] or "",
            "size": int(r["size"] or 0),
        }
    return out


def _item_payload(
    db: sqlite3.Connection,
    app_row: sqlite3.Row,
    item: dict[str, Any],
    templates: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": item.get("id"),
        "slot_id": item.get("slot_id") or "",
        "title": item.get("title") or "",
        "kind": item.get("kind") or "yoshiki",
        "required": item.get("required") or "recommended",
        "cardinality": item.get("cardinality") or "one",
        "form_id": item.get("form_id") or None,
        "fulfillment": item.get("fulfillment") or "",
        "file_id": item.get("file_id") or None,
        "file_name": item.get("file_name") or None,
        "copy_index": int(item.get("copy_index") or 0),
        "added_by": item.get("added_by") or "system",
        "guest_token": None,
        "public_url": None,
        "visibility": None,
        "can_fill_online": bool(item.get("form_id")),
        "template": (templates or {}).get(item.get("slot_id") or ""),
        "status": "none",
    }
    form_id = item.get("form_id") or ""
    if form_id:
        form = _form_row(db, form_id)
        if form:
            out["title"] = out["title"] or form["title"]
            out["guest_token"] = form["guest_token"]
            out["public_url"] = public_url_for(form["guest_token"])
            out["visibility"] = form["visibility"]
    out["status"] = _item_status(db, app_row["id"], item)
    if form_id and out["status"] == "submitted" and item.get("fulfillment") != "file":
        sub = db.execute(
            "SELECT s.answers_json, s.receipt_code, s.submitter_name, s.created_at, "
            "v.definition_json FROM submissions s "
            "LEFT JOIN form_versions v ON v.id = s.version_id "
            "WHERE s.application_id = ? AND s.form_id = ? AND s.is_draft = 0 "
            "ORDER BY s.created_at DESC",
            (app_row["id"], form_id),
        ).fetchone()
        if sub:
            try:
                answers = json.loads(sub["answers_json"])
            except (TypeError, json.JSONDecodeError):
                answers = {}
            definition = None
            if sub["definition_json"]:
                try:
                    parsed = json.loads(sub["definition_json"])
                    if isinstance(parsed, dict):
                        definition = parsed
                except (TypeError, json.JSONDecodeError):
                    definition = None
            if definition is None:
                form = _form_row(db, form_id)
                definition = _definition(form) if form else {}
            out["answers"] = crypto.reveal_answers(definition, answers, mask=True)
            out["definition"] = definition
            out["receipt_code"] = sub["receipt_code"]
            out["respondent_label"] = sub["submitter_name"]
            out["submitted_at"] = sub["created_at"]
    return out


def _application_payload(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    try:
        form_ids = json.loads(row["form_ids_json"])
    except (TypeError, json.JSONDecodeError):
        form_ids = []
    if not isinstance(form_ids, list):
        form_ids = []
    try:
        notice = json.loads(row["notice_json"])
    except (TypeError, json.JSONDecodeError):
        notice = {"notes": [], "prepare": [], "refs": []}
    proc = db.execute(
        "SELECT name, description, guide_form_id FROM procedures WHERE id = ?",
        (row["procedure_id"],),
    ).fetchone()
    forms: list[dict[str, Any]] = []
    for fid in form_ids:
        form = db.execute("SELECT * FROM forms WHERE id = ?", (fid,)).fetchone()
        if not form:
            forms.append(
                {
                    "id": fid,
                    "title": "(削除済み)",
                    "guest_token": None,
                    "public_url": None,
                    "visibility": None,
                    "status": "none",
                }
            )
            continue
        item = {
            "id": form["id"],
            "title": form["title"],
            "guest_token": form["guest_token"],
            "public_url": public_url_for(form["guest_token"]),
            "visibility": form["visibility"],
            "status": _form_progress(db, row["id"], fid),
        }
        sub = db.execute(
            "SELECT s.answers_json, s.receipt_code, s.submitter_name, s.created_at, "
            "s.withdrawn_at, v.definition_json "
            "FROM submissions s "
            "LEFT JOIN form_versions v ON v.id = s.version_id "
            "WHERE s.application_id = ? AND s.form_id = ? AND s.is_draft = 0 "
            "ORDER BY s.created_at DESC",
            (row["id"], fid),
        ).fetchone()
        if sub:
            try:
                answers = json.loads(sub["answers_json"])
            except (TypeError, json.JSONDecodeError):
                answers = {}
            definition = _definition(form)
            if sub["definition_json"]:
                try:
                    parsed = json.loads(sub["definition_json"])
                    if isinstance(parsed, dict):
                        definition = parsed
                except (TypeError, json.JSONDecodeError):
                    pass
            item["answers"] = crypto.reveal_answers(definition, answers, mask=True)
            item["definition"] = definition
            item["receipt_code"] = sub["receipt_code"]
            item["respondent_label"] = sub["submitter_name"]
            item["submitted_at"] = sub["created_at"]
        forms.append(item)
    raw_items = _application_items(row)
    if not raw_items:
        raw_items = _items_from_form_ids(db, row)
    template_bucket = proc["guide_form_id"] if proc else row["guide_form_id"]
    templates = _procedure_templates(db, template_bucket)
    items = [_item_payload(db, row, item, templates) for item in raw_items]
    stamps = [str(row["created_at"] or "")]
    for form in forms:
        submitted = form.get("submitted_at")
        if submitted:
            stamps.append(str(submitted))
    for item in items:
        submitted = item.get("submitted_at")
        if submitted:
            stamps.append(str(submitted))
    return {
        "id": row["id"],
        "token": row["token"],
        "procedure_id": row["procedure_id"],
        "procedure_name": proc["name"] if proc else "",
        "procedure_description": proc["description"] if proc else None,
        "guide_form_id": row["guide_form_id"],
        "guide_submission_id": row["guide_submission_id"],
        "form_ids": form_ids,
        "notice": notice,
        "forms": forms,
        "items": items,
        "public_url": public_application_url_for(row["token"]),
        "created_at": row["created_at"],
        "updated_at": max(stamps),
    }


def _resolve_application_id(
    db: sqlite3.Connection, form_id: str, application_token: str | None
) -> tuple[str | None, str | None]:
    token = (application_token or "").strip()
    if not token:
        return None, None
    row = db.execute("SELECT * FROM applications WHERE token = ?", (token,)).fetchone()
    if not row:
        return None, "申請束が見つかりません"
    try:
        form_ids = json.loads(row["form_ids_json"])
    except (TypeError, json.JSONDecodeError):
        form_ids = []
    item_form_ids = {
        str(it.get("form_id"))
        for it in _application_items(row)
        if it.get("form_id")
    }
    if form_id not in form_ids and form_id not in item_form_ids:
        return None, "この様式はこの申請に含まれていません"
    return row["id"], None


def _resolve_application_item_id(
    db: sqlite3.Connection,
    application_id: str | None,
    form_id: str,
    application_item_id: str | None,
) -> str | None:
    if not application_id:
        return None
    app = db.execute(
        "SELECT * FROM applications WHERE id = ?", (application_id,)
    ).fetchone()
    if not app:
        return None
    items = _application_items(app)
    wanted = (application_item_id or "").strip()
    if wanted:
        for it in items:
            if it.get("id") == wanted and (it.get("form_id") or "") == form_id:
                return wanted
    # 指定が無いときは、同じ様式の未充足アイテムを1つ選ぶ
    for it in items:
        if (it.get("form_id") or "") != form_id:
            continue
        if it.get("fulfillment") == "file":
            continue
        if _item_status(db, application_id, it) in ("none", "draft"):
            return it.get("id")
    for it in items:
        if (it.get("form_id") or "") == form_id:
            return it.get("id")
    return None


def _open_application_from_guide(
    db: sqlite3.Connection,
    form_id: str,
    submission_id: str,
    answers: dict[str, Any],
) -> dict[str, Any] | None:
    submitted = _form_row(db, form_id)
    if not submitted or submitted["status"] != "published":
        return None
    submitted_def = _definition_id(submitted)
    proc = None
    for row in db.execute(
        "SELECT * FROM procedures WHERE status = 'published'"
    ).fetchall():
        guide_def = _as_definition_id(db, row["guide_form_id"]) or row["guide_form_id"]
        if row["guide_form_id"] in (form_id, submitted_def) or guide_def == submitted_def:
            proc = row
            break
    if not proc:
        return None
    mapping, err = procedure.normalize_mapping(proc["mapping_json"])
    if err:
        return None
    resolved = procedure.resolve_bundle(mapping, answers)
    slots = procedure.resolve_slots(mapping, answers)
    reception_ids: list[str] = [submitted["id"]]
    for fid in resolved["form_ids"]:
        rec = _published_reception_row(db, fid)
        if rec and rec["id"] not in reception_ids:
            reception_ids.append(rec["id"])
    now = _now_iso()
    aid = str(uuid.uuid4())
    token = secrets.token_urlsafe(10)
    notice = {
        "notes": resolved["notes"],
        "prepare": resolved["prepare"],
        "refs": resolved["refs"],
    }
    items: list[dict[str, Any]] = [
        _new_item(
            slot_id="",
            title=submitted["title"],
            kind="data",
            required="required",
            cardinality="one",
            form_id=submitted["id"],
            fulfillment="form",
            added_by="system",
        )
    ]
    seen_forms = {submitted["id"]}
    for slot in slots["slots"]:
        if slot["kind"] == "attach":
            items.append(
                _new_item(
                    slot_id=slot["slot_id"],
                    title=slot["title"],
                    kind="attach",
                    required=slot["required"],
                    cardinality=slot["cardinality"],
                    form_id="",
                    added_by="system",
                )
            )
            continue
        rec = _published_reception_row(db, slot["form_id"])
        if not rec or rec["id"] in seen_forms:
            continue
        seen_forms.add(rec["id"])
        items.append(
            _new_item(
                slot_id=slot["slot_id"],
                title=rec["title"],
                kind="yoshiki",
                required=slot["required"],
                cardinality=slot["cardinality"],
                form_id=rec["id"],
                added_by="system",
            )
        )
    db.execute(
        "INSERT INTO applications (id, token, procedure_id, guide_form_id, "
        "guide_submission_id, form_ids_json, notice_json, items_json, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            aid,
            token,
            proc["id"],
            form_id,
            submission_id,
            json.dumps(reception_ids, ensure_ascii=False),
            json.dumps(notice, ensure_ascii=False),
            json.dumps(items, ensure_ascii=False),
            now,
        ),
    )
    db.execute(
        "UPDATE submissions SET application_id = ?, application_item_id = ? WHERE id = ?",
        (aid, items[0]["id"], submission_id),
    )
    row = db.execute("SELECT * FROM applications WHERE id = ?", (aid,)).fetchone()
    return _application_payload(db, row) if row else None


def list_inbox(
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    procedure_id: str | None = None,
) -> dict[str, Any]:
    """公開中または申請がある手続きと、届いた申請束。"""
    pid = (procedure_id or "").strip() or None
    db = connect()
    with _lock:
        app_sql = "SELECT * FROM applications"
        app_args: tuple[Any, ...] = ()
        if pid:
            app_sql += " WHERE procedure_id = ?"
            app_args = (pid,)
        app_sql += " ORDER BY created_at DESC"
        app_rows = db.execute(app_sql, app_args).fetchall()
        applications = [_application_payload(db, row) for row in app_rows]
        items: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for app in applications:
            submitted = sum(1 for f in app["forms"] if f.get("status") == "submitted")
            items.append(
                {
                    "kind": "bundle",
                    "id": app["id"],
                    "created_at": app["created_at"],
                    "title": app["procedure_name"],
                    "label": app["token"],
                    "procedure_id": app["procedure_id"],
                    "submitted": submitted,
                    "total": len(app["forms"]),
                    "public_url": app["public_url"],
                }
            )
            counts[app["procedure_id"]] = counts.get(app["procedure_id"], 0) + 1
        if not pid:
            for row in db.execute(
                "SELECT procedure_id, COUNT(*) AS n FROM applications GROUP BY procedure_id"
            ).fetchall():
                counts[row["procedure_id"]] = row["n"]
        procedures: list[dict[str, Any]] = []
        openings: list[dict[str, Any]] = []
        for proc in db.execute("SELECT * FROM procedures ORDER BY updated_at DESC").fetchall():
            if pid and proc["id"] != pid:
                continue
            n = counts.get(proc["id"], 0)
            if proc["status"] != "published" and n == 0:
                continue
            guide = db.execute("SELECT * FROM forms WHERE id = ?", (proc["guide_form_id"],)).fetchone()
            opening = _published_reception_row(db, proc["guide_form_id"])
            shown = opening or guide
            public_url = (
                public_url_for(shown["guest_token"])
                if shown
                and proc["status"] == "published"
                and shown["status"] == "published"
                and shown["visibility"] in ("both", "public")
                else None
            )
            item = {
                "id": proc["id"],
                "name": proc["name"],
                "title": proc["name"],
                "status": proc["status"],
                "guide_title": guide["title"] if guide else None,
                "public_url": public_url,
                "bundle_count": n,
                "can_edit": _can_edit_procedure(proc, actor_user_id, actor_groups),
                "updated_at": proc["updated_at"],
            }
            procedures.append(item)
            if proc["status"] == "published":
                openings.append(
                    {
                        "kind": "procedure",
                        "id": proc["id"],
                        "title": proc["name"],
                        "guide_title": guide["title"] if guide else None,
                        "public_url": public_url,
                    }
                )
        return {
            "items": items,
            "procedures": procedures,
            "openings": openings,
            "bundle_count": len(applications),
            "form_count": 0,
        }


def list_applications(
    procedure_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    since: str | None = None,
) -> tuple[list[dict[str, Any]] | None, str | None]:
    cutoff, err = parse_since(since)
    if err:
        return None, err
    db = connect()
    with _lock:
        proc = db.execute("SELECT * FROM procedures WHERE id = ?", (procedure_id,)).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        rows = db.execute(
            "SELECT * FROM applications WHERE procedure_id = ? ORDER BY created_at DESC",
            (procedure_id,),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            payload = _application_payload(db, row)
            if cutoff:
                touched = _parse_iso(str(payload.get("updated_at") or ""))
                if not touched or touched < cutoff:
                    continue
            items.append(payload)
        return items, None


def get_application(
    application_id: str | None = None,
    *,
    token: str | None = None,
    actor_user_id: str | None = None,
) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if token:
            row = db.execute("SELECT * FROM applications WHERE token = ?", (token,)).fetchone()
        else:
            row = db.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
        if not row:
            return None
        return _application_payload(db, row)


def public_application(token: str) -> tuple[dict[str, Any] | None, str | None]:
    data = get_application(token=token)
    if not data:
        return None, "申請が見つかりません"
    return data, None


def _app_row(
    db: sqlite3.Connection,
    application_id: str | None,
    token: str | None,
) -> sqlite3.Row | None:
    if token:
        return db.execute("SELECT * FROM applications WHERE token = ?", (token,)).fetchone()
    return db.execute(
        "SELECT * FROM applications WHERE id = ?", (application_id,)
    ).fetchone()


def procedure_catalog(procedure_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """手続きが持つ枠のカタログ（申請束に足せる様式・添付の種）。"""
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        mapping, err = procedure.normalize_mapping(proc["mapping_json"])
        if err:
            return None, err
        templates = _procedure_templates(db, proc["guide_form_id"])
        slots: list[dict[str, Any]] = []
        seen: set[str] = set()
        for rule in mapping.get("rules") or []:
            for fid in rule.get("form_ids") or []:
                key = f"yoshiki:{fid}"
                if key in seen:
                    continue
                seen.add(key)
                rec = _published_reception_row(db, fid) or _form_row(db, fid)
                if not rec:
                    continue
                slots.append(
                    {
                        "slot_id": key,
                        "title": rec["title"],
                        "kind": "yoshiki",
                        "form_id": rec["id"],
                        "template": templates.get(key),
                    }
                )
            for item in rule.get("prepare") or []:
                text = str(item).strip()
                if not text:
                    continue
                key = f"attach:{text}"
                if key in seen:
                    continue
                seen.add(key)
                slots.append(
                    {
                        "slot_id": key,
                        "title": text,
                        "kind": "attach",
                        "form_id": None,
                        "template": templates.get(key),
                    }
                )
        return {"procedure_id": procedure_id, "slots": slots}, None


def add_procedure_template(
    *,
    procedure_id: str,
    slot_id: str,
    filename: str,
    data: str,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """枠（slot_id）に様式ひな型を登録する。同じ枠の既存ひな型は差し替える。"""
    slot = (slot_id or "").strip()
    if not slot:
        return None, "枠が指定されていません"
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        if not _can_edit_procedure(proc, actor_user_id, actor_groups):
            return None, "この手続きを変更する権限がありません"
        name = files.safe_filename(filename)
        try:
            blob, mime = files.decode_upload(data, filename=name, kind="file")
        except ValueError as e:
            return None, str(e)
        guide_id = proc["guide_form_id"]
        comp = _TEMPLATE_PREFIX + slot
        for old in db.execute(
            "SELECT id FROM uploaded_files WHERE form_id = ? AND component_id = ?",
            (guide_id, comp),
        ).fetchall():
            files.remove_blob(guide_id, old["id"])
            db.execute("DELETE FROM uploaded_files WHERE id = ?", (old["id"],))
        file_id = str(uuid.uuid4())
        files.write_blob(guide_id, file_id, blob)
        db.execute(
            "INSERT INTO uploaded_files (id, form_id, submission_id, component_id, "
            "filename, mime, size, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (file_id, guide_id, None, comp, name, mime, len(blob), _now_iso()),
        )
        db.commit()
        return {
            "slot_id": slot,
            "file_id": file_id,
            "filename": name,
            "mime": mime,
            "size": len(blob),
        }, None


def list_procedure_templates(
    procedure_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        return {
            "procedure_id": procedure_id,
            "templates": _procedure_templates(db, proc["guide_form_id"]),
        }, None


def delete_procedure_template(
    *,
    procedure_id: str,
    file_id: str,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> str | None:
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return "手続きが見つかりません"
        if not _can_edit_procedure(proc, actor_user_id, actor_groups):
            return "この手続きを変更する権限がありません"
        guide_id = proc["guide_form_id"]
        row = db.execute(
            "SELECT id FROM uploaded_files WHERE id = ? AND form_id = ? "
            "AND component_id LIKE 'template:%'",
            (file_id, guide_id),
        ).fetchone()
        if not row:
            return "ひな型が見つかりません"
        files.remove_blob(guide_id, file_id)
        db.execute("DELETE FROM uploaded_files WHERE id = ?", (file_id,))
        db.commit()
        return None


def _template_file_at(
    db: sqlite3.Connection, guide_form_id: str, file_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    row = db.execute(
        "SELECT * FROM uploaded_files WHERE id = ? AND form_id = ? "
        "AND component_id LIKE 'template:%'",
        (file_id, guide_form_id),
    ).fetchone()
    if not row:
        return None, "ひな型が見つかりません"
    try:
        path = files.stored_path(guide_form_id, file_id)
    except ValueError:
        return None, "ひな型が見つかりません"
    if not path.is_file():
        return None, "ひな型が見つかりません"
    return {
        "filename": row["filename"],
        "mime": row["mime"] or "application/octet-stream",
        "path": str(path),
        "size": row["size"],
    }, None


def get_procedure_template_file(
    procedure_id: str, file_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT guide_form_id FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        return _template_file_at(db, proc["guide_form_id"], file_id)


def get_application_template_file(
    token: str, file_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        app = db.execute(
            "SELECT p.guide_form_id AS guide_form_id FROM applications a "
            "JOIN procedures p ON p.id = a.procedure_id WHERE a.token = ?",
            (token,),
        ).fetchone()
        if not app:
            return None, "申請が見つかりません"
        return _template_file_at(db, app["guide_form_id"], file_id)


def add_application_item(
    *,
    application_id: str | None = None,
    token: str | None = None,
    duplicate_of: str | None = None,
    form_id: str | None = None,
    slot_id: str | None = None,
    title: str | None = None,
    kind: str | None = None,
    added_by: str = "guest",
) -> tuple[dict[str, Any] | None, str | None]:
    """申請束に枠アイテムを1件足す（複製・カタログ追加・任意の添付）。"""
    db = connect()
    with _lock:
        app = _app_row(db, application_id, token)
        if not app:
            return None, "申請が見つかりません"
        items = _application_items(app)
        if not items:
            items = _items_from_form_ids(db, app)
        new_item: dict[str, Any] | None = None
        if duplicate_of:
            src = next((it for it in items if it.get("id") == duplicate_of), None)
            if not src:
                return None, "複製元のアイテムが見つかりません"
            copies = [it for it in items if it.get("slot_id") and it.get("slot_id") == src.get("slot_id")]
            new_item = _new_item(
                slot_id=src.get("slot_id") or "",
                title=src.get("title") or "",
                kind=src.get("kind") or "yoshiki",
                required="optional",
                cardinality="many",
                form_id=src.get("form_id") or "",
                template_file_id=src.get("template_file_id") or "",
                copy_index=len(copies),
                added_by=added_by,
            )
        elif form_id:
            rec = _published_reception_row(db, form_id) or _form_row(db, form_id)
            if not rec:
                return None, "様式が見つかりません"
            new_item = _new_item(
                slot_id=slot_id or f"yoshiki:{rec['id']}",
                title=title or rec["title"],
                kind=kind or "yoshiki",
                required="optional",
                cardinality="one",
                form_id=rec["id"],
                added_by=added_by,
            )
        else:
            text = (title or "").strip()
            if not text:
                return None, "足す様式か添付の名前が必要です"
            new_item = _new_item(
                slot_id=slot_id or "",
                title=text,
                kind="attach",
                required="optional",
                cardinality="one",
                form_id="",
                added_by=added_by,
            )
        items.append(new_item)
        db.execute(
            "UPDATE applications SET items_json = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), app["id"]),
        )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def _store_item_file(
    db: sqlite3.Connection, bucket_form_id: str, filename: str, data: str
) -> tuple[dict[str, Any] | None, str | None]:
    name = files.safe_filename(filename)
    try:
        blob, mime = files.decode_upload(data, filename=name, kind="file")
    except ValueError as e:
        return None, str(e)
    file_id = str(uuid.uuid4())
    files.write_blob(bucket_form_id, file_id, blob)
    db.execute(
        "INSERT INTO uploaded_files (id, form_id, submission_id, component_id, "
        "filename, mime, size, created_at) VALUES (?,?,?,?,?,?,?,?)",
        (file_id, bucket_form_id, None, None, name, mime, len(blob), _now_iso()),
    )
    return {"file_id": file_id, "filename": name, "mime": mime, "size": len(blob)}, None


def fulfill_item_with_file(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
    filename: str,
    data: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """様式・添付の枠を、記入済みファイルの添付で満たす。"""
    db = connect()
    with _lock:
        app = _app_row(db, application_id, token)
        if not app:
            return None, "申請が見つかりません"
        items = _application_items(app)
        if not items:
            items = _items_from_form_ids(db, app)
        target = next((it for it in items if it.get("id") == item_id), None)
        if not target:
            return None, "アイテムが見つかりません"
        if target.get("kind") == "data":
            return None, "この枠はオンライン記入のみです"
        bucket = target.get("form_id") or app["guide_form_id"]
        saved, err = _store_item_file(db, bucket, filename, data)
        if err or saved is None:
            return None, err
        target["fulfillment"] = "file"
        target["file_id"] = saved["file_id"]
        target["file_name"] = saved["filename"]
        target["file_bucket"] = bucket
        db.execute(
            "UPDATE applications SET items_json = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), app["id"]),
        )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def clear_item_fulfillment(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """ファイル添付を外して、未充足（またはオンライン記入）に戻す。"""
    db = connect()
    with _lock:
        app = _app_row(db, application_id, token)
        if not app:
            return None, "申請が見つかりません"
        items = _application_items(app)
        if not items:
            items = _items_from_form_ids(db, app)
        target = next((it for it in items if it.get("id") == item_id), None)
        if not target:
            return None, "アイテムが見つかりません"
        target["fulfillment"] = ""
        target["file_id"] = ""
        target["file_name"] = ""
        target.pop("file_bucket", None)
        db.execute(
            "UPDATE applications SET items_json = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), app["id"]),
        )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def _export_cell(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        return ";".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _data_item_fields(item: dict[str, Any]) -> list[tuple[str, str, Any]]:
    """記入必須（kind=data）の提出済み項目を、揃えやすいキーで返す。

    キーは様式名 + imi_type（無ければ部品ラベル）で、申請をまたいで一致させる。
    """
    if item.get("kind") != "data":
        return []
    if item.get("status") != "submitted" or item.get("fulfillment") == "file":
        return []
    answers = item.get("answers") or {}
    definition = item.get("definition") or {}
    title = item.get("title") or ""
    out: list[tuple[str, str, Any]] = []
    for comp in definition.get("components") or []:
        if comp.get("type") in spec.DISPLAY_TYPES:
            continue
        cid = str(comp.get("id") or "")
        if not cid:
            continue
        key_tail = str(comp.get("imi_type") or "").strip() or str(comp.get("label") or cid)
        out.append((f"{title}::{key_tail}", cid, answers.get(cid, "")))
    return out


def _export_aligned(items: list[dict[str, Any]]) -> str:
    columns: list[str] = []
    seen: set[str] = set()
    for app in items:
        for item in app.get("items") or []:
            for header, _cid, _value in _data_item_fields(item):
                if header not in seen:
                    seen.add(header)
                    columns.append(header)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["案内番号", "様式", "複製番号", *columns])
    for app in items:
        for item in app.get("items") or []:
            fields = _data_item_fields(item)
            if not fields:
                continue
            values = {header: _export_cell(value) for header, _cid, value in fields}
            writer.writerow(
                [
                    app.get("token") or "",
                    item.get("title") or "",
                    int(item.get("copy_index") or 0),
                    *[values.get(col, "") for col in columns],
                ]
            )
    return buf.getvalue()


def _submitted_fields(form: dict[str, Any]) -> list[tuple[str, str, Any]]:
    if form.get("status") != "submitted":
        return []
    answers = form.get("answers") or {}
    definition = form.get("definition") or {}
    title = form.get("title") or ""
    out: list[tuple[str, str, Any]] = []
    for comp in definition.get("components") or []:
        if comp.get("type") in spec.DISPLAY_TYPES:
            continue
        cid = str(comp.get("id") or "")
        if not cid:
            continue
        label = str(comp.get("label") or cid)
        out.append((f"{title}/{label}", cid, answers.get(cid, "")))
    return out


def export_application(
    application_id: str,
    *,
    fmt: str = "csv",
) -> tuple[str | None, str | None]:
    data = get_application(application_id)
    if not data:
        return None, "申請が見つかりません"
    kind = (fmt or "csv").lower()
    if kind in ("json", "jsonl"):
        payload = json.dumps(data, ensure_ascii=False, indent=2 if kind == "json" else None)
        if kind == "jsonl" and not payload.endswith("\n"):
            payload += "\n"
        return payload, None
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["様式", "控え番号", "回答者", "提出日時", "状態", "項目", "値"])
    for form in data.get("forms") or []:
        fields = _submitted_fields(form)
        if not fields:
            writer.writerow(
                [
                    form.get("title") or "",
                    form.get("receipt_code") or "",
                    form.get("respondent_label") or "",
                    form.get("submitted_at") or "",
                    form.get("status") or "",
                    "",
                    "",
                ]
            )
            continue
        for header, _cid, value in fields:
            label = header.split("/", 1)[-1]
            writer.writerow(
                [
                    form.get("title") or "",
                    form.get("receipt_code") or "",
                    form.get("respondent_label") or "",
                    form.get("submitted_at") or "",
                    form.get("status") or "",
                    label,
                    _export_cell(value),
                ]
            )
    return buf.getvalue(), None


def export_procedure_applications(
    procedure_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    fmt: str = "csv",
    since: str | None = None,
) -> tuple[str | None, str | None]:
    items, err = list_applications(
        procedure_id,
        actor_user_id=actor_user_id,
        actor_groups=actor_groups,
        since=since,
    )
    if err or items is None:
        return None, err
    kind = (fmt or "csv").lower()
    if kind == "jsonl":
        return "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + (
            "\n" if items else ""
        ), None
    if kind == "aligned":
        return _export_aligned(items), None
    columns: list[str] = []
    seen: set[str] = set()
    for app in items:
        for form in app.get("forms") or []:
            for header, _cid, _value in _submitted_fields(form):
                if header not in seen:
                    seen.add(header)
                    columns.append(header)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["案内番号", "申請日時", "提出数", "様式数", *columns])
    for app in items:
        values: dict[str, str] = {}
        submitted = 0
        for form in app.get("forms") or []:
            if form.get("status") == "submitted":
                submitted += 1
            for header, _cid, value in _submitted_fields(form):
                values[header] = _export_cell(value)
        writer.writerow(
            [
                app.get("token") or "",
                app.get("created_at") or "",
                submitted,
                len(app.get("forms") or []),
                *[values.get(col, "") for col in columns],
            ]
        )
    return buf.getvalue(), None
