"""フォーム定義と回答の SQLite 永続化。"""

from __future__ import annotations

import csv
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

from . import crypto, spec

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
            CREATE INDEX IF NOT EXISTS idx_forms_creator ON forms(creator_user_id);
            CREATE INDEX IF NOT EXISTS idx_forms_guest ON forms(guest_token);
            CREATE INDEX IF NOT EXISTS idx_forms_status ON forms(status);
            CREATE INDEX IF NOT EXISTS idx_submissions_form ON submissions(form_id);
            """
        )
        db.commit()


def public_url_for(guest_token: str) -> str:
    if not PUBLIC_ENDPOINT:
        return f"/public/f/{guest_token}"
    return f"{PUBLIC_ENDPOINT}/public/f/{guest_token}"


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
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "public_url": public_url_for(row["guest_token"]),
    }
    if include_definition:
        out["definition"] = _definition(row)
    return out


def list_forms_for_user(user_id: str) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        rows = db.execute(
            """
            SELECT * FROM forms
            WHERE creator_user_id = ?
               OR id IN (
                 SELECT DISTINCT form_id FROM submissions WHERE submitter_user_id = ?
               )
            ORDER BY updated_at DESC
            """,
            (user_id, user_id),
        ).fetchall()
        return [_row_to_form(r, include_definition=False) for r in rows]


def get_form(
    form_id: str | None = None,
    *,
    guest_token: str | None = None,
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
        if row["published_version_id"]:
            ver = db.execute(
                "SELECT version, published_at FROM form_versions WHERE id = ?",
                (row["published_version_id"],),
            ).fetchone()
            if ver:
                out["published_version"] = ver["version"]
                out["published_at"] = ver["published_at"]
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
    detail = get_form(form_id)
    assert detail is not None
    return detail, None


def update_form(
    form_id: str,
    *,
    actor_user_id: str,
    title: str | None = None,
    description: str | None = None,
    visibility: str | None = None,
    definition: dict[str, Any] | None = None,
    pin: str | None = None,
    retention_days: int | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if row["creator_user_id"] != actor_user_id:
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
        db.execute(
            "UPDATE forms SET title = ?, description = ?, visibility = ?, definition_json = ?, "
            "pin_hash = ?, retention_days = ?, updated_at = ? WHERE id = ?",
            (
                new_title.strip(),
                new_desc,
                new_vis,
                json.dumps(normalized, ensure_ascii=False),
                pin_hash,
                days,
                _now_iso(),
                form_id,
            ),
        )
        db.commit()
    return get_form(form_id), None


def set_status(
    form_id: str,
    *,
    actor_user_id: str,
    status: str,
) -> tuple[dict[str, Any] | None, str | None]:
    if status not in spec.STATUSES:
        return None, "状態が不正です"
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if row["creator_user_id"] != actor_user_id:
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
    return get_form(form_id), None


def delete_form(form_id: str, *, actor_user_id: str) -> str | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return "フォームが見つかりません"
        if row["creator_user_id"] != actor_user_id:
            return "このフォームを削除する権限がありません"
        db.execute("DELETE FROM forms WHERE id = ?", (form_id,))
        db.commit()
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
            "definition": definition,
        }, None


def submit_answers(
    *,
    form_id: str | None = None,
    guest_token: str | None = None,
    answers: dict[str, Any],
    submitter_user_id: str | None,
    submitter_name: str | None,
    pin: str | None = None,
    is_draft: bool = False,
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
        if row["status"] != "published":
            return None, "このフォームは現在受け付けていません"
        if guest_token and row["visibility"] == "internal":
            return None, "このフォームは外部公開されていません"
        if not guest_token and row["visibility"] == "public" and not submitter_user_id:
            return None, "このフォームは庁内からは回答できません"
        if guest_token and row["pin_hash"]:
            if not pin or not verify_pin(pin, row["pin_hash"]):
                return None, "暗証番号が正しくありません"
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
        cleaned, err = spec.validate_answers(definition, answers)
        if err or cleaned is None:
            return None, err
        cleaned = crypto.protect_answers(definition, cleaned)
        sid = str(uuid.uuid4())
        receipt = secrets.token_urlsafe(10)
        now = _now_iso()
        db.execute(
            "INSERT INTO submissions (id, form_id, version_id, receipt_code, "
            "submitter_user_id, submitter_name, answers_json, is_draft, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                sid,
                row["id"],
                version_id,
                receipt,
                submitter_user_id,
                submitter_name,
                json.dumps(cleaned, ensure_ascii=False),
                1 if is_draft else 0,
                now,
                now,
            ),
        )
        db.commit()
    return {
        "id": sid,
        "receipt_code": receipt,
        "message": "下書きを保存しました" if is_draft else "回答を受け付けました",
    }, None


def list_submissions(form_id: str, *, actor_user_id: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM forms WHERE id = ?", (form_id,)).fetchone()
        if not row:
            return None, "フォームが見つかりません"
        if row["creator_user_id"] != actor_user_id:
            return None, "回答を閲覧する権限がありません"
        fallback = published_definition(form_id) or _definition(row)
        rows = db.execute(
            "SELECT s.id, s.receipt_code, s.submitter_user_id, s.submitter_name, "
            "s.answers_json, s.created_at, s.version_id, "
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
            answers = crypto.reveal_answers(definition, answers, mask=True)
            out.append(
                {
                    "id": r["id"],
                    "receipt_code": r["receipt_code"],
                    "submitter_user_id": r["submitter_user_id"],
                    "submitter_name": r["submitter_name"],
                    "answers": answers,
                    "created_at": r["created_at"],
                    "version_id": r["version_id"],
                    "form_version": r["form_version"],
                    "published_at": r["published_at"],
                    "definition": definition,
                }
            )
        return out, None


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


def export_csv(form_id: str, *, actor_user_id: str) -> tuple[str | None, str | None]:
    form = get_form(form_id)
    if not form:
        return None, "フォームが見つかりません"
    if form["creator_user_id"] != actor_user_id:
        return None, "回答を書き出す権限がありません"
    fallback = published_definition(form_id) or form["definition"]
    items, err = list_submissions(form_id, actor_user_id=actor_user_id)
    if err or items is None:
        return None, err
    comps = _union_answer_components(items, fallback)
    buf = io.StringIO()
    headers = ["receipt_code", "submitter_name", "created_at", "form_version"] + [
        c["label"] for c in comps
    ]
    writer = csv.writer(buf)
    writer.writerow(headers)
    for item in items:
        answers = item.get("answers") or {}
        row = [
            item["receipt_code"],
            item.get("submitter_name") or "",
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
    return buf.getvalue(), None


def export_jsonl(form_id: str, *, actor_user_id: str) -> tuple[str | None, str | None]:
    items, err = list_submissions(form_id, actor_user_id=actor_user_id)
    if err or items is None:
        return None, err
    lines = [
        json.dumps(
            {
                "receipt_code": item["receipt_code"],
                "submitter_name": item.get("submitter_name") or "",
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


def delete_old_forms(retention_days: int | None = None) -> int:
    """保持期限を過ぎたフォームを削除する。フォーム単位の retention_days を優先。"""
    default_days = retention_days if retention_days is not None else RETENTION_DAYS
    now = datetime.now(timezone.utc)
    db = connect()
    deleted = 0
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
                deleted += 1
        db.commit()
    return deleted
