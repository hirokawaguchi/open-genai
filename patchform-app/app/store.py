"""フォーム定義と回答の SQLite 永続化。"""

from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import sqlite3
import threading
import uuid
from collections.abc import Callable
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


# ---------------------------------------------------------------------------
# 庁外（外部ユーザー）向け軽量認証: メール＋マジックリンク → HMAC 署名セッション
# ---------------------------------------------------------------------------
# セッション署名の秘密鍵。未設定時はサービスキーを流用し、それも無ければ
# 起動ごとにランダム（＝再起動でセッション失効）。本番は必ず固定値を設定する。
EXT_SECRET = (
    os.environ.get("PATCHFORM_EXT_SECRET")
    or os.environ.get("PATCHFORM_SERVICE_KEY")
    or secrets.token_hex(32)
)
MAGIC_TTL_MIN = int(os.environ.get("PATCHFORM_MAGIC_TTL_MIN", "15"))
EXT_SESSION_TTL_DAYS = int(os.environ.get("PATCHFORM_EXT_SESSION_TTL_DAYS", "30"))

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email or ""))


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def create_magic_token(email: str) -> tuple[str, str]:
    """マジックリンク用の単回・短命トークンを発行し、(平文トークン, 失効ISO) を返す。"""
    token_plain = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    exp = now + timedelta(minutes=MAGIC_TTL_MIN)
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO magic_tokens (id, token_hash, email, created_at, expires_at, "
            "consumed_at) VALUES (?,?,?,?,?,NULL)",
            (
                str(uuid.uuid4()),
                _sha256_hex(token_plain),
                normalize_email(email),
                now.isoformat(),
                exp.isoformat(),
            ),
        )
        db.commit()
    return token_plain, exp.isoformat()


def _sign_session(sid: str, exp_ts: int) -> str:
    msg = f"{sid}.{exp_ts}"
    sig = hmac.new(EXT_SECRET.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{msg}.{sig}"


def issue_external_session(email: str) -> tuple[str, str]:
    """外部セッションを作成し、(Bearer トークン, 失効ISO) を返す。"""
    sid = str(uuid.uuid4())
    now = datetime.now(timezone.utc).replace(microsecond=0)
    exp = now + timedelta(days=EXT_SESSION_TTL_DAYS)
    exp_ts = int(exp.timestamp())
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO external_sessions (id, email, created_at, expires_at, revoked_at) "
            "VALUES (?,?,?,?,NULL)",
            (sid, normalize_email(email), now.isoformat(), exp.isoformat()),
        )
        db.commit()
    return _sign_session(sid, exp_ts), exp.isoformat()


def consume_magic_token(token_plain: str) -> tuple[str | None, str | None]:
    """マジックトークンを検証・消費し、(正規化メール, エラー) を返す。"""
    if not token_plain:
        return None, "トークンがありません"
    token_hash = _sha256_hex(token_plain)
    now = datetime.now(timezone.utc)
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM magic_tokens WHERE token_hash = ?", (token_hash,)
        ).fetchone()
        if not row:
            return None, "リンクが無効です"
        if row["consumed_at"]:
            return None, "このリンクは使用済みです"
        exp = _parse_iso(row["expires_at"])
        if exp and now > exp:
            return None, "リンクの有効期限が切れています"
        db.execute(
            "UPDATE magic_tokens SET consumed_at = ? WHERE id = ?",
            (_now_iso(), row["id"]),
        )
        db.commit()
        return normalize_email(row["email"]), None


def verify_external_session(bearer: str | None) -> tuple[str | None, str | None]:
    """Bearer トークンを検証し、(正規化メール, エラー) を返す。"""
    if not bearer:
        return None, "認証が必要です"
    token = bearer.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        return None, "セッションが不正です"
    sid, exp_ts_s, sig = parts
    try:
        exp_ts = int(exp_ts_s)
    except ValueError:
        return None, "セッションが不正です"
    expected = hmac.new(
        EXT_SECRET.encode("utf-8"), f"{sid}.{exp_ts_s}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None, "セッションが不正です"
    if int(datetime.now(timezone.utc).timestamp()) > exp_ts:
        return None, "セッションの有効期限が切れています"
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM external_sessions WHERE id = ?", (sid,)
        ).fetchone()
    if not row or row["revoked_at"]:
        return None, "セッションが失効しています"
    exp = _parse_iso(row["expires_at"])
    if exp and datetime.now(timezone.utc) > exp:
        return None, "セッションの有効期限が切れています"
    return normalize_email(row["email"]), None


def revoke_external_session(bearer: str | None) -> None:
    if not bearer:
        return
    token = bearer.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    parts = token.split(".")
    if len(parts) != 3:
        return
    sid = parts[0]
    db = connect()
    with _lock:
        db.execute(
            "UPDATE external_sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (_now_iso(), sid),
        )
        db.commit()


def cleanup_expired_auth() -> None:
    """期限切れマジックトークン/セッションの掃除（任意呼び出し）。"""
    now = _now_iso()
    db = connect()
    with _lock:
        db.execute("DELETE FROM magic_tokens WHERE expires_at < ?", (now,))
        db.execute("DELETE FROM external_sessions WHERE expires_at < ?", (now,))
        db.commit()


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
            CREATE TABLE IF NOT EXISTS application_events (
              id TEXT PRIMARY KEY,
              application_id TEXT NOT NULL,
              actor_role TEXT NOT NULL,
              actor_user_id TEXT NOT NULL DEFAULT '',
              action TEXT NOT NULL,
              target TEXT NOT NULL DEFAULT '',
              detail TEXT NOT NULL DEFAULT '',
              changes TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS magic_tokens (
              id TEXT PRIMARY KEY,
              token_hash TEXT NOT NULL UNIQUE,
              email TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              consumed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS external_sessions (
              id TEXT PRIMARY KEY,
              email TEXT NOT NULL,
              created_at TEXT NOT NULL,
              expires_at TEXT NOT NULL,
              revoked_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_procedures_guide ON procedures(guide_form_id);
            CREATE INDEX IF NOT EXISTS idx_procedures_status ON procedures(status);
            CREATE INDEX IF NOT EXISTS idx_applications_token ON applications(token);
            CREATE INDEX IF NOT EXISTS idx_applications_proc ON applications(procedure_id);
            CREATE INDEX IF NOT EXISTS idx_applications_owner ON applications(owner_kind, owner_key);
            CREATE INDEX IF NOT EXISTS idx_app_events_app ON application_events(application_id);
            CREATE INDEX IF NOT EXISTS idx_magic_email ON magic_tokens(email);
            CREATE INDEX IF NOT EXISTS idx_extsess_email ON external_sessions(email);
            """
        )
        _ensure_columns(db)
        _migrate_applications_optional_submission(db)
        file_moves = _migrate_legacy_receptions(db)
        _migrate_slot_templates_to_forms(db)
        db.commit()
    for old_id, new_id in file_moves:
        files.rename_form_dir(old_id, new_id)


def _migrate_applications_optional_submission(db: sqlite3.Connection) -> None:
    """マイ手続き（project-first）のため、案内提出前の空プロジェクトを許す。

    元の applications は guide_submission_id が NOT NULL かつ submissions への
    FK を持つため、案内回答前の束を作れない。当該 FK のみ外し、guide_submission_id
    を nullable にしたテーブルへ再構築する（procedure/guide の FK は維持）。冪等。
    """
    fks = db.execute("PRAGMA foreign_key_list(applications)").fetchall()
    if not any(fk["from"] == "guide_submission_id" for fk in fks):
        return  # 既に移行済み
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute(
        """
        CREATE TABLE applications_new (
          id TEXT PRIMARY KEY,
          token TEXT NOT NULL UNIQUE,
          procedure_id TEXT NOT NULL,
          guide_form_id TEXT NOT NULL,
          guide_submission_id TEXT,
          form_ids_json TEXT NOT NULL,
          notice_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          items_json TEXT NOT NULL DEFAULT '[]',
          owner_kind TEXT NOT NULL DEFAULT '',
          owner_key TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL DEFAULT '',
          status_override TEXT NOT NULL DEFAULT '',
          updated_at TEXT NOT NULL DEFAULT '',
          assignee TEXT NOT NULL DEFAULT '',
          deadline TEXT NOT NULL DEFAULT '',
          next_action_date TEXT NOT NULL DEFAULT '',
          FOREIGN KEY (procedure_id) REFERENCES procedures(id),
          FOREIGN KEY (guide_form_id) REFERENCES forms(id)
        )
        """
    )
    db.execute(
        "INSERT INTO applications_new (id, token, procedure_id, guide_form_id, "
        "guide_submission_id, form_ids_json, notice_json, created_at, items_json, "
        "owner_kind, owner_key, title, status_override, updated_at, "
        "assignee, deadline, next_action_date) "
        "SELECT id, token, procedure_id, guide_form_id, guide_submission_id, "
        "form_ids_json, notice_json, created_at, items_json, owner_kind, owner_key, "
        "title, status_override, updated_at, assignee, deadline, next_action_date "
        "FROM applications"
    )
    db.execute("DROP TABLE applications")
    db.execute("ALTER TABLE applications_new RENAME TO applications")
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_applications_token ON applications(token)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_applications_proc ON applications(procedure_id)"
    )
    db.execute("PRAGMA foreign_keys = ON")


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
        # 庁内/庁外の公開範囲は手続き単位で決める（internal / both）。
        ("procedures", "visibility", "TEXT NOT NULL DEFAULT 'internal'"),
        ("applications", "items_json", "TEXT NOT NULL DEFAULT '[]'"),
        # マイ手続き: 所有者・タイトル・状態の手動上書き・更新時刻
        ("applications", "owner_kind", "TEXT NOT NULL DEFAULT ''"),
        ("applications", "owner_key", "TEXT NOT NULL DEFAULT ''"),
        ("applications", "title", "TEXT NOT NULL DEFAULT ''"),
        ("applications", "status_override", "TEXT NOT NULL DEFAULT ''"),
        ("applications", "updated_at", "TEXT NOT NULL DEFAULT ''"),
        # docmaker Index 相当: 担当者・期限・次回更新日
        ("applications", "assignee", "TEXT NOT NULL DEFAULT ''"),
        ("applications", "deadline", "TEXT NOT NULL DEFAULT ''"),
        ("applications", "next_action_date", "TEXT NOT NULL DEFAULT ''"),
        # 申請（提出）した時点。これ以降の変更だけを履歴に残す。
        ("applications", "submitted_at", "TEXT NOT NULL DEFAULT ''"),
        # 変更履歴: 記入内容の差分（変更前→後）を JSON で保持
        ("application_events", "changes", "TEXT NOT NULL DEFAULT ''"),
        # 添付ファイルの由来（internal=庁内 / external=庁外アップロード）。
        # 庁外由来は庁内で直接ストリームせず SeaweedFS 再ホスト経由で受け渡す。
        ("uploaded_files", "origin", "TEXT NOT NULL DEFAULT 'internal'"),
    )
    added: set[tuple[str, str]] = set()
    for table, name, decl in wanted:
        cols = {r[1] for r in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if name not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
            added.add((table, name))
    db.execute("CREATE INDEX IF NOT EXISTS idx_forms_source ON forms(source_form_id)")
    if ("procedures", "visibility") in added:
        _backfill_procedure_visibility(db)


def _backfill_procedure_visibility(db: sqlite3.Connection) -> None:
    """既存手続きの公開範囲を、案内フォームの現行 visibility から一度だけ引き継ぐ。"""
    for r in db.execute("SELECT id, guide_form_id FROM procedures").fetchall():
        gid = r["guide_form_id"]
        rec = db.execute(
            "SELECT visibility FROM forms WHERE source_form_id = ? AND status = 'published' "
            "ORDER BY created_at DESC LIMIT 1",
            (gid,),
        ).fetchone()
        if not rec:
            rec = db.execute("SELECT visibility FROM forms WHERE id = ?", (gid,)).fetchone()
        vis = (rec["visibility"] if rec else "internal") or "internal"
        db.execute(
            "UPDATE procedures SET visibility = ? WHERE id = ?",
            ("internal" if vis == "internal" else "both", r["id"]),
        )


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


def _migrate_slot_templates_to_forms(db: sqlite3.Connection) -> None:
    """旧・手続きスロット別ひな型（template:yoshiki:{fid}）を様式フォーム自身へ移す。

    ひな型は「その様式の1つ」に集約する方が自然なので、フォームの定義IDの
    バケットへ移設し component_id を template:self に付け替える。冪等。
    """
    try:
        rows = db.execute(
            "SELECT id, form_id, component_id FROM uploaded_files "
            "WHERE component_id LIKE 'template:yoshiki:%'"
        ).fetchall()
    except sqlite3.OperationalError:
        return
    prefix = "template:yoshiki:"
    for r in rows:
        fid = str(r["component_id"])[len(prefix):]
        target = _form_row(db, fid)
        if not target:
            continue
        def_id = _definition_id(target)
        exists = db.execute(
            "SELECT 1 FROM uploaded_files WHERE form_id = ? AND component_id = ?",
            (def_id, FORM_TEMPLATE_COMP),
        ).fetchone()
        if exists:
            continue
        src_bucket = str(r["form_id"])
        if src_bucket == def_id:
            db.execute(
                "UPDATE uploaded_files SET component_id = ? WHERE id = ?",
                (FORM_TEMPLATE_COMP, r["id"]),
            )
            continue
        try:
            blob = files.stored_path(src_bucket, r["id"]).read_bytes()
        except (ValueError, OSError):
            continue
        files.write_blob(def_id, r["id"], blob)
        db.execute(
            "UPDATE uploaded_files SET form_id = ?, component_id = ? WHERE id = ?",
            (def_id, FORM_TEMPLATE_COMP, r["id"]),
        )
        files.remove_blob(src_bucket, r["id"])


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
        # 様式フォーム自身に登録されたひな型（作成画面で登録/差し替え）。
        out["template"] = _form_template_meta(db, row["id"])
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


def _apply_default_imi(definition: dict[str, Any]) -> dict[str, Any]:
    """型から一意に決まる語彙（IMI）を空欄だけ補完する。手動保存/公開でも適用する。"""
    comps = definition.get("components")
    if not isinstance(comps, list):
        return definition
    out = dict(definition)
    out["components"] = [spec.fill_default_imi(c) for c in comps]
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
    normalized = _apply_default_imi(normalized)
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
        normalized = _apply_default_imi(normalized)
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
        # 公開範囲を変えたら、公開中の受付(reception)にも反映する。受付側の visibility が
        # 古いままだと手続きの庁外URL/QRに反映されないため（案内フォーム編集での庁外公開）。
        if new_vis != row["visibility"] and not _is_reception(row):
            db.execute(
                "UPDATE forms SET visibility = ?, updated_at = ? "
                "WHERE source_form_id = ? AND status = 'published'",
                (new_vis, _now_iso(), form_id),
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


def _reception_matches_source(reception: sqlite3.Row, source: sqlite3.Row) -> bool:
    """閉じた受付が、現在の原本（定義・公開設定）と一致しているか。

    一致するなら受付を再開して使い回してよい（在申請の互換を保つ）。原本を編集して
    いれば不一致となり、呼び出し側は新しい受付（新バージョン）を作り直す。
    """
    src_def = _definition(source)
    norm, err = spec.validate_definition(src_def, visibility=source["visibility"])
    if err or norm is None:
        # 検証できない原本は無用な作り直しを避け、再開を許す。
        return True
    try:
        rec_def = json.loads(reception["definition_json"] or "{}")
    except (TypeError, ValueError):
        return False
    if json.dumps(norm, ensure_ascii=False, sort_keys=True) != json.dumps(
        rec_def, ensure_ascii=False, sort_keys=True
    ):
        return False
    for key in ("title", "description", "visibility", "pin_hash", "retention_days"):
        rec_val = reception[key] if key in reception.keys() else None
        src_val = source[key] if key in source.keys() else None
        if rec_val != src_val:
            return False
    if _flag(reception, "allow_draft") != _flag(source, "allow_draft"):
        return False
    if _flag(reception, "allow_multiple") != _flag(source, "allow_multiple"):
        return False
    if _identity_mode(reception) != _identity_mode(source):
        return False
    if _tags_json(_row_tags(reception)) != _tags_json(_row_tags(source)):
        return False
    return True


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
    # 原本が編集されていなければ、内容が一致する閉じた受付をそのまま再開して使い回す
    # （在申請は同じ受付IDを参照し続けるため壊れない）。原本を編集していれば一致する受付が
    # 無いので新しい受付（新バージョン）を作る。新規申請だけが最新版になる。
    # created_at は秒精度のため同秒のタイブレークとして rowid も併用する。
    closed_rows = db.execute(
        "SELECT * FROM forms WHERE source_form_id = ? AND status = 'closed' "
        "ORDER BY created_at DESC, rowid DESC",
        (_definition_id(source),),
    ).fetchall()
    match = next(
        (r for r in closed_rows if _reception_matches_source(r, source)), None
    )
    if match is not None:
        db.execute(
            "UPDATE forms SET status = 'published', updated_at = ? WHERE id = ?",
            (_now_iso(), match["id"]),
        )
        return match["id"], None
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


def list_all_tags(
    *, actor_user_id: str, actor_groups: list[str] | None = None
) -> list[dict[str, Any]]:
    """編集権限のある様式フォームに付いているタグを、使用件数付きで集計する。

    ゴミ箱（archived）のフォームも数えるため、未使用に見えるタグの掃除にも使える。
    受付窓口（reception）は様式ペア側で数えるので二重計上しない。
    """
    db = connect()
    with _lock:
        rows = db.execute("SELECT * FROM forms").fetchall()
        counts: dict[str, int] = {}
        for row in rows:
            if _is_reception(row):
                continue
            if not _can_edit(row, actor_user_id, actor_groups):
                continue
            for t in _row_tags(row):
                counts[t] = counts.get(t, 0) + 1
        return [{"tag": t, "count": counts[t]} for t in sorted(counts)]


def _apply_tag_change(
    db: sqlite3.Connection,
    def_row: sqlite3.Row,
    transform: Callable[[list[str]], list[str]],
) -> bool:
    """様式フォーム本体とその受付窓口ペアのタグを、transform で一括更新する。"""
    ids = [def_row["id"]]
    for r in db.execute(
        "SELECT id FROM forms WHERE source_form_id = ?", (def_row["id"],)
    ).fetchall():
        ids.append(r["id"])
    changed = False
    for fid in ids:
        r = db.execute("SELECT tags FROM forms WHERE id = ?", (fid,)).fetchone()
        if not r:
            continue
        cur = _row_tags(r)
        nxt = transform(cur)
        if nxt != cur:
            db.execute(
                "UPDATE forms SET tags = ?, updated_at = ? WHERE id = ?",
                (_tags_json(nxt), _now_iso(), fid),
            )
            changed = True
    return changed


def rename_tag(
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    old: str,
    new: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """タグを、編集権限のある全フォームでまとめて改名する。"""
    old_tag = (old or "").strip()
    if not old_tag:
        return None, "元のタグを指定してください"
    norm, err = normalize_tags([new])
    if err or not norm:
        return None, err or "新しいタグ名が不正です"
    new_tag = norm[0]

    def transform(tags: list[str]) -> list[str]:
        if old_tag not in tags:
            return tags
        out: list[str] = []
        for t in tags:
            repl = new_tag if t == old_tag else t
            if repl not in out:
                out.append(repl)
        return out

    db = connect()
    with _lock:
        rows = db.execute("SELECT * FROM forms").fetchall()
        n = 0
        for row in rows:
            if _is_reception(row) or not _can_edit(row, actor_user_id, actor_groups):
                continue
            if old_tag not in _row_tags(row):
                continue
            if _apply_tag_change(db, row, transform):
                n += 1
        db.commit()
        return {"changed": n}, None


def delete_tag(
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    tag: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """タグを、編集権限のある全フォームからまとめて外す。"""
    target = (tag or "").strip()
    if not target:
        return None, "タグを指定してください"

    def transform(tags: list[str]) -> list[str]:
        return [t for t in tags if t != target]

    db = connect()
    with _lock:
        rows = db.execute("SELECT * FROM forms").fetchall()
        n = 0
        for row in rows:
            if _is_reception(row) or not _can_edit(row, actor_user_id, actor_groups):
                continue
            if target not in _row_tags(row):
                continue
            if _apply_tag_change(db, row, transform):
                n += 1
        db.commit()
        return {"changed": n}, None


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
        removed_dirs: list[str] = []
        if not _is_reception(row):
            children = db.execute(
                "SELECT id, status FROM forms WHERE source_form_id = ?", (form_id,)
            ).fetchall()
            active = [c for c in children if c["status"] == "published"]
            if active:
                return "受付中の窓口があるため削除できません。先に窓口を終了してから削除してください。"
            used_name = _procedure_using_form(db, form_id)
            if used_name:
                return used_name
            # 終了済みの窓口（reception）は本体と一緒に完全削除する。
            for c in children:
                db.execute("DELETE FROM forms WHERE id = ?", (c["id"],))
                removed_dirs.append(c["id"])
        db.execute("DELETE FROM forms WHERE id = ?", (form_id,))
        removed_dirs.append(form_id)
        db.commit()
    for d in removed_dirs:
        files.remove_form_dir(d)
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
    origin: str = "internal",
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
            "filename, mime, size, created_at, origin) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                file_id,
                row["id"],
                None,
                None,
                name,
                mime,
                len(blob),
                now,
                "external" if origin == "external" else "internal",
            ),
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
        row_keys = row.keys()
        origin = row["origin"] if "origin" in row_keys else None
        return {
            "filename": row["filename"],
            "mime": row["mime"] or "application/octet-stream",
            "path": str(path),
            "size": row["size"],
            "origin": "external" if origin == "external" else "internal",
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
        # 申請束（作業台）の中のフォームは、共有・双方向で内容を直せるよう、
        # フォーム設定の allow_multiple に関わらず再記入（修正）を許可する。
        in_bundle = bool(
            (application_token or "").strip() or (application_item_id or "").strip()
        )
        allow_multi = bool(_flag(row, "allow_multiple")) or in_bundle
        existing = _find_draft(
            db, row["id"], submitter_user_id=submitter_user_id, resume_token=resume_token
        )
        if resume_token and not existing:
            return None, "再開用の下書きが見つかりません"
        if existing and not existing["is_draft"]:
            if is_draft:
                return None, "この控えはすでに提出済みです"
            if not allow_multi:
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
        if not is_draft and not allow_multi:
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
        new_plain = dict(cleaned)
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
        app_for_link = None
        prev_answers: dict[str, Any] = {}
        if linked_app_id:
            app_for_link = db.execute(
                "SELECT * FROM applications WHERE id = ?", (linked_app_id,)
            ).fetchone()
            is_guide = (
                app_for_link is not None
                and str(app_for_link["guide_form_id"]) == row["id"]
            )
            # 条件（案内）の変更は申請者本人（束の所有者）だけが行える。
            if is_guide and app_for_link is not None:
                owner_kind = str(app_for_link["owner_kind"] or "")
                owner_key = str(app_for_link["owner_key"] or "")
                if owner_kind == "internal" and owner_key:
                    # 庁内所有: 本人（submitter_user_id 一致）以外は不可。
                    if not submitter_user_id or submitter_user_id != owner_key:
                        return None, "条件を変更する権限がありません"
                elif owner_kind == "external":
                    # 庁外所有: 本人（トークン経由＝submitter_user_id なし）のみ可。
                    # 庁内ユーザー（受付）による条件変更は不可。
                    if submitter_user_id:
                        return None, "条件を変更する権限がありません"
            # 差分算出のため、上書き前の直近の提出内容を控える。
            if not is_draft:
                prev_row = None
                if linked_item_id:
                    prev_row = db.execute(
                        "SELECT answers_json FROM submissions WHERE application_id = ? "
                        "AND application_item_id = ? AND is_draft = 0 "
                        "ORDER BY created_at DESC LIMIT 1",
                        (linked_app_id, linked_item_id),
                    ).fetchone()
                if prev_row is None:
                    prev_row = db.execute(
                        "SELECT answers_json FROM submissions WHERE application_id = ? "
                        "AND form_id = ? AND is_draft = 0 ORDER BY created_at DESC LIMIT 1",
                        (linked_app_id, row["id"]),
                    ).fetchone()
                if prev_row is not None:
                    try:
                        parsed_prev = json.loads(prev_row["answers_json"])
                        if isinstance(parsed_prev, dict):
                            prev_answers = parsed_prev
                    except (TypeError, json.JSONDecodeError):
                        prev_answers = {}
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
            if linked_app_id:
                opened = _populate_project_from_guide(
                    db, linked_app_id, row["id"], sid, cleaned
                )
            if opened is None:
                opened = _open_application_from_guide(
                    db, row["id"], sid, cleaned, submitter_user_id=submitter_user_id
                )
            if opened:
                notify_proc = db.execute(
                    "SELECT name, notify_emails_json FROM procedures WHERE id = ?",
                    (opened.get("procedure_id"),),
                ).fetchone()
            if linked_app_id and app_for_link is not None and _app_is_submitted(
                app_for_link
            ):
                is_guide = str(app_for_link["guide_form_id"]) == row["id"]
                diffs = _answers_diff(definition, prev_answers, new_plain)
                _log_app_event(
                    db,
                    linked_app_id,
                    actor_role=_actor_role(app_for_link, submitter_user_id),
                    actor_user_id=submitter_user_id or "",
                    action="条件を変更" if is_guide else "記入を修正",
                    target="" if is_guide else str(row["title"] or ""),
                    changes=diffs,
                )
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


def _is_single_form_app(db: sqlite3.Connection, app: sqlite3.Row) -> bool:
    """選択肢(ラジオ/プルダウン等)を持たない『申請用紙1枚』の手続きか。

    案内(nav)としての分岐が無い手続きでは、案内フォーム＝申請用紙本体になる。
    """
    proc = db.execute(
        "SELECT * FROM procedures WHERE id = ?", (app["procedure_id"],)
    ).fetchone()
    if not proc:
        return False
    guide_def = _guide_definition(db, proc["guide_form_id"])
    return not procedure.choice_fields(guide_def)


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
        # 公開範囲は手続き単位。guide_visibility は後方互換のためのミラー。
        "visibility": _proc_visibility(row),
        "guide_visibility": _proc_visibility(row),
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
    vis = proc.get("visibility") or proc.get("guide_visibility")
    external_url = proc.get("guide_public_url") if vis in ("both", "public") else None
    return {
        "id": proc["id"],
        "name": proc["name"],
        "internal_url": internal_url,
        "external_url": external_url,
        "internal_qr_svg": _qr_svg(internal_url),
        "external_qr_svg": _qr_svg(external_url) if external_url else None,
        # 庁外URLが出ない原因（手続きの公開範囲）を画面で説明・修正できるよう返す。
        "guide_form_id": proc.get("guide_form_id"),
        "visibility": vis,
        "guide_visibility": vis,
    }, None


def set_procedure_visibility(
    procedure_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    visibility: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """手続きの公開範囲（庁内のみ / 庁内と外部）を変更する。

    公開範囲は手続き単位で決める。公開中は案内＋全様式の定義・受付にも即時反映し、
    既存の共有URL・QRへ反映する。庁外(both)にする場合、機微部品(mynumber等)を含む
    様式があれば拒否する。
    """
    proc_vis = _norm_proc_visibility(visibility)
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        if not _can_edit_procedure(proc, actor_user_id, actor_groups):
            return None, "この手続きを変更する権限がありません"
        err = _apply_procedure_visibility(
            db, proc, proc_vis, propagate=(proc["status"] == "published")
        )
        if err:
            return None, err
        db.execute(
            "UPDATE procedures SET visibility = ?, updated_at = ? WHERE id = ?",
            (proc_vis, _now_iso(), procedure_id),
        )
        db.commit()
        row = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        detail = _row_to_procedure(
            db, row, actor_user_id=actor_user_id, actor_groups=actor_groups
        )
        return detail, None


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
    if shown["status"] == "published" and shown["visibility"] in ("both", "public"):
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
        if shown["status"] == "published" and shown["visibility"] in ("both", "public"):
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


def list_published_procedures(
    *, query: str | None = None, external_only: bool = False
) -> list[dict[str, Any]]:
    """公開中の手続き一覧。external_only=True なら庁外公開(both/public)のみに絞る。"""
    needle = (query or "").strip().lower()
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT * FROM procedures "
            "WHERE status = 'published' ORDER BY updated_at DESC"
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            if external_only and _proc_visibility(row) == "internal":
                continue
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


def _norm_proc_visibility(value: Any) -> str:
    """手続きの公開範囲を internal / both に正規化する（外部のみ=public は both 扱い）。"""
    v = str(value or "internal").strip()
    return "internal" if v == "internal" else "both"


def _proc_visibility(row: sqlite3.Row) -> str:
    if "visibility" in row.keys():
        return (row["visibility"] or "internal")
    return "internal"


def _procedure_definition_ids(db: sqlite3.Connection, proc_row: sqlite3.Row) -> list[str]:
    """案内＋mapping内の全様式の『定義ID』を重複なしで返す。"""
    mapping, _merr = procedure.normalize_mapping(proc_row["mapping_json"])
    ids = [_as_definition_id(db, proc_row["guide_form_id"]) or proc_row["guide_form_id"]]
    for rule in mapping.get("rules") or []:
        for fid in rule.get("form_ids") or []:
            ids.append(_as_definition_id(db, fid) or fid)
    return list(dict.fromkeys(ids))


def _apply_procedure_visibility(
    db: sqlite3.Connection,
    proc_row: sqlite3.Row,
    visibility: str,
    *,
    propagate: bool,
) -> str | None:
    """手続きの公開範囲を検証し、propagate 時は案内＋全様式の定義・受付へ反映する。

    庁外(both)にする場合、機微部品(mynumber等)を含む定義があれば拒否する。
    エラー文字列を返す。問題なければ None。
    """
    def_ids = _procedure_definition_ids(db, proc_row)
    for did in def_ids:
        drow = _form_row(db, did)
        if not drow:
            continue
        _, err = spec.validate_definition(_definition(drow), visibility=visibility)
        if err:
            return err
    if propagate:
        now = _now_iso()
        for did in def_ids:
            db.execute(
                "UPDATE forms SET visibility = ?, updated_at = ? WHERE id = ?",
                (visibility, now, did),
            )
            db.execute(
                "UPDATE forms SET visibility = ?, updated_at = ? "
                "WHERE source_form_id = ? AND status IN ('published', 'closed')",
                (visibility, now, did),
            )
    return None


def create_procedure(
    *,
    name: str,
    description: str | None,
    guide_form_id: str,
    mapping: Any = None,
    notify_emails: Any = None,
    visibility: str = "internal",
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
            "notify_emails_json, status, visibility, creator_user_id, creator_name, "
            "created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid,
                title,
                (description or "").strip() or None,
                stored_guide,
                json.dumps(mapping_norm, ensure_ascii=False),
                json.dumps(emails or [], ensure_ascii=False),
                "draft",
                _norm_proc_visibility(visibility),
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
            visibility=visibility,
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
            # 公開範囲は手続きが決める。案内＋全様式の定義・受付へ一括反映する。
            vis_err = _apply_procedure_visibility(
                db, row, _proc_visibility(row), propagate=True
            )
            if vis_err:
                return None, vis_err
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


def _item_form_status(db: sqlite3.Connection, application_id: str, item: dict[str, Any]) -> str:
    """様式（form_id）側の記入状況だけを見た状態。ファイル添付は考慮しない。"""
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


def _item_status(db: sqlite3.Connection, application_id: str, item: dict[str, Any]) -> str:
    """採用ソース（fulfillment）を踏まえた枠の状態。

    記入と添付は併存でき、どちらを申請データとして採用するかは fulfillment で決める。
    - "file": 添付ファイルを採用（記入があっても添付優先）
    - "form": オンライン記入を採用（添付があっても記入優先）
    - "": 未指定。添付があれば添付、無ければ記入を見る（従来動作）
    """
    fulfillment = item.get("fulfillment") or ""
    file_attached = bool(item.get("file_id"))
    if fulfillment == "file":
        return "submitted" if file_attached else "none"
    if fulfillment == "form":
        return _item_form_status(db, application_id, item)
    if file_attached:
        return "submitted"
    return _item_form_status(db, application_id, item)


# フォーム自身のひな型（枠あたり1つ）。様式の定義ID（def_id）のバケットに置く。
FORM_TEMPLATE_COMP = "template:self"
# 追加の添付に備えて常設する「その他」枠の固定スロットID。
OTHER_ATTACH_SLOT = "attach:__other__"


def _form_template_meta(
    db: sqlite3.Connection, form_id: str
) -> dict[str, Any] | None:
    """様式フォームに登録されたひな型を1件返す。受付版IDでも定義IDでも解決する。"""
    if not form_id:
        return None
    def_id = _as_definition_id(db, form_id) or form_id
    r = db.execute(
        "SELECT id, filename, mime, size FROM uploaded_files "
        "WHERE form_id = ? AND component_id = ? ORDER BY created_at DESC",
        (def_id, FORM_TEMPLATE_COMP),
    ).fetchone()
    if not r:
        return None
    return {
        "file_id": r["id"],
        "filename": r["filename"],
        "mime": r["mime"] or "",
        "size": int(r["size"] or 0),
    }


def _form_has_fillable_fields(db: sqlite3.Connection, form_id: str) -> bool:
    """様式に『ファイル添付以外』の入力部品があるかを返す。

    アシストが自動生成した様式は file 部品だけのプレースホルダで、オンライン記入
    しても実質は添付と同じになる。実入力欄が無い様式は「オンライン記入」を出さず、
    添付のみに寄せることで、記入と添付の併用が意味を持つようにする。
    """
    if not form_id:
        return False
    form = _form_row(db, form_id)
    if not form:
        return False
    for comp in _definition(form).get("components") or []:
        if not isinstance(comp, dict):
            continue
        ctype = comp.get("type") or ""
        if ctype in spec.DISPLAY_TYPES or ctype == "file":
            continue
        return True
    return False


# マイ手続きの自動ステータス（本人が手動で上書きも可能）
APP_STATUS_TODO = "未着手"
APP_STATUS_WORKING = "作業中"
APP_STATUS_READY = "準備完了"
APP_STATUS_SUBMITTED = "提出済"
# 自動導出する状態。提出済は「提出する」操作でのみ付く（自動では付けない）。
APP_STATUS_AUTO = (APP_STATUS_TODO, APP_STATUS_WORKING, APP_STATUS_READY)
# 手動上書きで許可する状態（自動値＋提出/終端の状態）
APP_STATUS_OVERRIDE_ALLOWED = APP_STATUS_AUTO + (APP_STATUS_SUBMITTED, "取下げ", "完了")


def _auto_status(items: list[dict[str, Any]]) -> str:
    """枠の充足状況から状態を導出する。

    - 案内(data)が未提出: 未着手
    - 案内は済だが書類が残る: 作業中
    - 書類がすべて揃った（または書類が無い）: 準備完了

    「提出済」は自動では付けない。実際に提出したかは本人にしか分からないため、
    明示的な「提出する」操作（status_override）でのみ付く。
    """
    data_items = [it for it in items if it.get("kind") == "data"]
    nav_done = any(it.get("status") == "submitted" for it in data_items)
    if not nav_done:
        return APP_STATUS_TODO
    # 任意枠（常設の「その他」など）は完了判定の妨げにしない。
    docs = [
        it
        for it in items
        if it.get("kind") != "data" and it.get("required") != "optional"
    ]
    if not docs or all(it.get("status") == "submitted" for it in docs):
        return APP_STATUS_READY
    return APP_STATUS_WORKING


def _status_block(items: list[dict[str, Any]], override: str) -> dict[str, str]:
    auto = _auto_status(items)
    ov = override if override in APP_STATUS_OVERRIDE_ALLOWED else ""
    return {"auto": auto, "override": ov, "effective": ov or auto}


def _touch_application(db: sqlite3.Connection, application_id: str) -> None:
    db.execute(
        "UPDATE applications SET updated_at = ? WHERE id = ?",
        (_now_iso(), application_id),
    )


def _item_file_external(db: sqlite3.Connection, item: dict[str, Any]) -> bool:
    """アイテムの添付ファイルが庁外（external）由来かどうか。"""
    file_id = item.get("file_id") or ""
    if not file_id:
        return False
    origin = item.get("file_origin")
    if origin:
        return origin == "external"
    try:
        row = db.execute(
            "SELECT origin FROM uploaded_files WHERE id = ?", (file_id,)
        ).fetchone()
    except sqlite3.Error:
        return False
    if not row:
        return False
    keys = row.keys()
    return "origin" in keys and row["origin"] == "external"


def _item_payload(
    db: sqlite3.Connection,
    app_row: sqlite3.Row,
    item: dict[str, Any],
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
        "can_fill_online": _form_has_fillable_fields(db, item.get("form_id") or ""),
        # ひな型は様式フォーム自身に登録されたものを使う。
        "template": _form_template_meta(db, item.get("form_id") or ""),
        "status": "none",
        # 記入と添付の併存判定用（採用ソースの切り替えUIに使う）
        "form_submitted": False,
        "file_attached": bool(item.get("file_id")),
        # 添付が庁外由来か（庁内DL時に SeaweedFS 再ホスト経由へ回すための印）
        "file_external": _item_file_external(db, item),
    }
    form_id = item.get("form_id") or ""
    if form_id:
        form = _form_row(db, form_id)
        if form:
            out["title"] = out["title"] or form["title"]
            out["guest_token"] = form["guest_token"]
            out["public_url"] = public_url_for(form["guest_token"])
            out["visibility"] = form["visibility"]
    out["form_submitted"] = _item_form_status(db, app_row["id"], item) == "submitted"
    out["status"] = _item_status(db, app_row["id"], item)
    # 添付を採用中でも、記入済みなら記入内容は「保管」として引ける（採用切替のため）。
    show_form_answers = item.get("fulfillment") != "file" and out["form_submitted"]
    if form_id and show_form_answers:
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
    items = [_item_payload(db, row, item) for item in raw_items]
    stamps = [str(row["created_at"] or "")]
    for form in forms:
        submitted = form.get("submitted_at")
        if submitted:
            stamps.append(str(submitted))
    for item in items:
        submitted = item.get("submitted_at")
        if submitted:
            stamps.append(str(submitted))
    keys = row.keys()
    stored_updated = str(row["updated_at"]) if "updated_at" in keys and row["updated_at"] else ""
    if stored_updated:
        stamps.append(stored_updated)
    override = str(row["status_override"]) if "status_override" in keys and row["status_override"] else ""
    title = str(row["title"]) if "title" in keys and row["title"] else ""

    def _meta(name: str) -> str:
        return str(row[name]) if name in keys and row[name] else ""

    return {
        "id": row["id"],
        "token": row["token"],
        "procedure_id": row["procedure_id"],
        "procedure_name": proc["name"] if proc else "",
        "procedure_description": proc["description"] if proc else None,
        "title": title or (proc["name"] if proc else ""),
        "assignee": _meta("assignee"),
        "deadline": _meta("deadline"),
        "next_action_date": _meta("next_action_date"),
        "owner_kind": str(row["owner_kind"]) if "owner_kind" in keys and row["owner_kind"] else "",
        "owner_key": str(row["owner_key"]) if "owner_key" in keys and row["owner_key"] else "",
        "status": _status_block(items, override),
        "guide_form_id": row["guide_form_id"],
        "guide_submission_id": row["guide_submission_id"],
        "form_ids": form_ids,
        "notice": notice,
        "forms": forms,
        "items": items,
        "public_url": public_application_url_for(row["token"]),
        "created_at": row["created_at"],
        "updated_at": max(stamps),
        "events": list_application_events(db, row["id"]),
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
    *,
    submitter_user_id: str | None = None,
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
    # ログイン中の庁内ユーザーが案内に回答したら、その人を所有者にする
    # （＝マイ手続きに載る）。ゲスト回答は所有者なし（P2でクレーム取り込み）。
    owner_kind = "internal" if submitter_user_id else ""
    owner_key = submitter_user_id or ""
    db.execute(
        "INSERT INTO applications (id, token, procedure_id, guide_form_id, "
        "guide_submission_id, form_ids_json, notice_json, items_json, created_at, "
        "owner_kind, owner_key, title, status_override, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
            owner_kind,
            owner_key,
            proc["name"],
            "",
            now,
        ),
    )
    db.execute(
        "UPDATE submissions SET application_id = ?, application_item_id = ? WHERE id = ?",
        (aid, items[0]["id"], submission_id),
    )
    row = db.execute("SELECT * FROM applications WHERE id = ?", (aid,)).fetchone()
    return _application_payload(db, row) if row else None


def _resolve_bundle_items(
    db: sqlite3.Connection,
    proc: sqlite3.Row,
    submitted: sqlite3.Row,
    answers: dict[str, Any],
) -> dict[str, Any] | None:
    """案内フォームの回答から、束の枠（nav + 対応様式/添付）を組み立てる。"""
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
    # 追加の添付に備えて、常設の「その他」枠を必ず1つ用意する。
    items.append(
        _new_item(
            slot_id=OTHER_ATTACH_SLOT,
            title="その他（別途ファイルを添付する場合にお使いください）",
            kind="attach",
            required="optional",
            cardinality="many",
            form_id="",
            added_by="system",
        )
    )
    return {"reception_ids": reception_ids, "notice": notice, "items": items}


def _merge_items(
    existing: list[dict[str, Any]], new_system: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """再解決した枠を、既存の作業（充足済み・手動追加）を残しつつ統合する。"""
    new_nav = new_system[0]
    new_others = new_system[1:]
    new_slots = {n.get("slot_id") for n in new_others}
    existing_nav = next((it for it in existing if it.get("kind") == "data"), None)
    result: list[dict[str, Any]] = [existing_nav or new_nav]
    handled: set[Any] = set()
    for it in existing:
        if it.get("kind") == "data" or it.get("added_by") != "system":
            continue
        slot = it.get("slot_id")
        if slot in new_slots:
            result.append(it)  # 同じ枠は既存（充足・複製）を維持
            handled.add(slot)
        elif it.get("fulfillment") == "file" and it.get("file_id"):
            result.append(it)  # 対象外になっても済みの添付は残す
    for ni in new_others:
        if ni.get("slot_id") not in handled:
            result.append(ni)
    for it in existing:
        if it.get("kind") != "data" and it.get("added_by") != "system":
            result.append(it)  # 申請者が手動で足した枠
    return result


def _populate_project_from_guide(
    db: sqlite3.Connection,
    application_id: str,
    form_id: str,
    submission_id: str,
    answers: dict[str, Any],
) -> dict[str, Any] | None:
    """既存プロジェクトの案内回答で、書類リストを（再）生成する。"""
    app_row = db.execute(
        "SELECT * FROM applications WHERE id = ?", (application_id,)
    ).fetchone()
    if not app_row:
        return None
    proc = db.execute(
        "SELECT * FROM procedures WHERE id = ?", (app_row["procedure_id"],)
    ).fetchone()
    if not proc:
        return None
    submitted = _form_row(db, form_id)
    if not submitted:
        return None
    submitted_def = _definition_id(submitted)
    guide_def = _as_definition_id(db, proc["guide_form_id"]) or proc["guide_form_id"]
    if not (
        proc["guide_form_id"] in (form_id, submitted_def) or guide_def == submitted_def
    ):
        return None  # 送信フォームがこの手続きの案内でなければ何もしない
    resolved = _resolve_bundle_items(db, proc, submitted, answers)
    if resolved is None:
        return None
    existing = _application_items(app_row)
    merged = _merge_items(existing, resolved["items"])
    nav = merged[0]
    nav["form_id"] = submitted["id"]
    nav["fulfillment"] = "form"
    form_ids = list(resolved["reception_ids"])
    for it in merged:
        fid = it.get("form_id")
        if fid and fid not in form_ids:
            form_ids.append(fid)
    db.execute(
        "UPDATE applications SET guide_submission_id = ?, guide_form_id = ?, "
        "form_ids_json = ?, notice_json = ?, items_json = ?, updated_at = ? WHERE id = ?",
        (
            submission_id,
            submitted["id"],
            json.dumps(form_ids, ensure_ascii=False),
            json.dumps(resolved["notice"], ensure_ascii=False),
            json.dumps(merged, ensure_ascii=False),
            _now_iso(),
            application_id,
        ),
    )
    db.execute(
        "UPDATE submissions SET application_id = ?, application_item_id = ? WHERE id = ?",
        (application_id, nav["id"], submission_id),
    )
    row = db.execute(
        "SELECT * FROM applications WHERE id = ?", (application_id,)
    ).fetchone()
    return _application_payload(db, row) if row else None


def create_project(
    *,
    procedure_id: str,
    owner_kind: str,
    owner_key: str,
    title: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """空のプロジェクト（申請束）を先に作る。以後、案内回答で中身が埋まる。"""
    if owner_kind not in ("internal", "external") or not owner_key:
        return None, "所有者が不正です"
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        if proc["status"] != "published":
            return None, "公開中の手続きではありません"
        guide_rec = _published_reception_row(db, proc["guide_form_id"])
        if not guide_rec:
            return None, "案内フォームが公開されていません"
        now = _now_iso()
        aid = str(uuid.uuid4())
        token = secrets.token_urlsafe(10)
        nav = _new_item(
            slot_id="",
            title=guide_rec["title"],
            kind="data",
            required="required",
            cardinality="one",
            form_id=guide_rec["id"],
            fulfillment="",
            added_by="system",
        )
        notice = {"notes": [], "prepare": [], "refs": []}
        db.execute(
            "INSERT INTO applications (id, token, procedure_id, guide_form_id, "
            "guide_submission_id, form_ids_json, notice_json, items_json, created_at, "
            "owner_kind, owner_key, title, status_override, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                aid,
                token,
                proc["id"],
                guide_rec["id"],
                None,
                json.dumps([guide_rec["id"]], ensure_ascii=False),
                json.dumps(notice, ensure_ascii=False),
                json.dumps([nav], ensure_ascii=False),
                now,
                owner_kind,
                owner_key,
                (title or proc["name"]).strip() or proc["name"],
                "",
                now,
            ),
        )
        row = db.execute("SELECT * FROM applications WHERE id = ?", (aid,)).fetchone()
        db.commit()
        return (_application_payload(db, row) if row else None), None


def resolve_procedure_preview(
    *, procedure_id: str, answers: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """案内回答から必要書類/案内文を DB 書き込みなしで算出する（ウィザードのプレビュー用）。"""
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        guide = _form_row(db, proc["guide_form_id"])
        if not guide:
            return None, "案内フォームが見つかりません"
        resolved = _resolve_bundle_items(db, proc, guide, answers or {})
        if resolved is None:
            return None, "案内の解決に失敗しました"
        items: list[dict[str, Any]] = []
        for it in resolved["items"]:
            if it.get("kind") == "data":
                continue  # 案内（ナビ）本体はプレビューに出さない
            items.append(
                {
                    "slot_id": it.get("slot_id") or "",
                    "title": it.get("title") or "",
                    "kind": it.get("kind") or "yoshiki",
                    "required": it.get("required") or "recommended",
                    "cardinality": it.get("cardinality") or "one",
                    "has_template": bool(_form_template_meta(db, it.get("form_id") or "")),
                    "can_fill_online": _form_has_fillable_fields(
                        db, it.get("form_id") or ""
                    ),
                }
            )
        return {
            "notice": resolved["notice"],
            "items": items,
            "count": len(items),
        }, None


def _application_summary(db: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    payload = _application_payload(db, row)
    items = payload["items"]
    doc_items = [it for it in items if it.get("kind") != "data"]
    done = len([it for it in doc_items if it.get("status") == "submitted"])
    return {
        "id": payload["id"],
        "token": payload["token"],
        "title": payload["title"],
        "procedure_id": payload["procedure_id"],
        "procedure_name": payload["procedure_name"],
        "status": payload["status"],
        "assignee": payload["assignee"],
        "deadline": payload["deadline"],
        "next_action_date": payload["next_action_date"],
        "created_at": payload["created_at"],
        "updated_at": payload["updated_at"],
        "done": done,
        "total": len(doc_items),
        "public_url": payload["public_url"],
    }


def list_my_applications(
    *, owner_kind: str, owner_key: str
) -> list[dict[str, Any]]:
    """本人が所有するプロジェクト一覧（マイ手続き）。"""
    if not owner_kind or not owner_key:
        return []
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT * FROM applications WHERE owner_kind = ? AND owner_key = ? "
            "ORDER BY updated_at DESC, created_at DESC",
            (owner_kind, owner_key),
        ).fetchall()
        return [_application_summary(db, row) for row in rows]


def application_imi_sources(
    *, application_id: str, owner_kind: str, owner_key: str
) -> tuple[dict[str, Any] | None, str | None]:
    """本人が所有する他の申請から、記入済みの様式（定義＋回答）を IMI 候補源として集める。

    同一オーナーの別プロジェクトに入力済みの氏名・住所などを、記入時の候補に使う。
    """
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not row:
            return None, "申請が見つかりません"
        if not _owns_application(row, owner_kind, owner_key):
            return None, "この手続きを操作する権限がありません"
        rows = db.execute(
            "SELECT * FROM applications WHERE owner_kind = ? AND owner_key = ? "
            "ORDER BY updated_at DESC, created_at DESC",
            (owner_kind, owner_key),
        ).fetchall()
        sources: list[dict[str, Any]] = []
        for r in rows:
            if r["id"] == application_id:
                continue
            payload = _application_payload(db, r)
            base_title = payload.get("title") or payload.get("procedure_name") or ""
            for coll in (payload.get("forms") or [], payload.get("items") or []):
                for f in coll:
                    if f.get("status") != "submitted":
                        continue
                    definition = f.get("definition") or {}
                    answers = f.get("answers")
                    comps = definition.get("components") if isinstance(definition, dict) else None
                    if not comps or not isinstance(answers, dict):
                        continue
                    label = f.get("title") or ""
                    title = f"{base_title} / {label}".strip(" /") if base_title else label
                    sources.append(
                        {"title": title, "components": comps, "answers": answers}
                    )
        return {"sources": sources}, None


def _owns_application(row: sqlite3.Row, owner_kind: str, owner_key: str) -> bool:
    keys = row.keys()
    if "owner_kind" not in keys:
        return False
    return str(row["owner_kind"]) == owner_kind and str(row["owner_key"]) == owner_key


def application_owned(
    application_id: str, *, owner_kind: str, owner_key: str
) -> tuple[bool, str | None]:
    """application_id が指定オーナーの所有物か確認する（庁外マイ手続きの所有者チェック）。"""
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not row:
            return False, "申請が見つかりません"
        if not _owns_application(row, owner_kind, owner_key):
            return False, "この手続きを操作する権限がありません"
        return True, None


def application_owned_by_token(
    token: str, *, owner_kind: str, owner_key: str
) -> tuple[bool, str | None]:
    """公開トークンが指定オーナーの所有する申請束のものか確認する。"""
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM applications WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return False, "申請が見つかりません"
        if not _owns_application(row, owner_kind, owner_key):
            return False, "この手続きを操作する権限がありません"
        return True, None


def claim_application(token: str, *, owner_key: str) -> tuple[str | None, str | None]:
    """未所有の申請束を庁外ユーザー(external+email)の所有に付け替える（引き取り）。

    - 未所有(owner_kind=='')のみ付替。
    - 既に同一 external+owner_key なら冪等成功（既存 id を返す）。
    - 他所有者なら「別の利用者が管理中です」を返す（呼び出し側で 409）。
    戻り値: (application_id, error)。
    """
    key = normalize_email(owner_key)
    if not key:
        return None, "所有者が不正です"
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM applications WHERE token = ?", (token,)
        ).fetchone()
        if not row:
            return None, "申請が見つかりません"
        cur_kind = str(row["owner_kind"] or "")
        cur_key = str(row["owner_key"] or "")
        if cur_kind == "external" and cur_key == key:
            return str(row["id"]), None
        if cur_kind:
            return None, "別の利用者が管理中です"
        db.execute(
            "UPDATE applications SET owner_kind = 'external', owner_key = ?, "
            "updated_at = ? WHERE token = ?",
            (key, _now_iso(), token),
        )
        db.commit()
        return str(row["id"]), None


def _guest_token_for_form(db: sqlite3.Connection, form_id: str) -> str | None:
    row = db.execute("SELECT guest_token FROM forms WHERE id = ?", (form_id,)).fetchone()
    return row["guest_token"] if row and row["guest_token"] else None


def mine_form_detail(form_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """庁外マイ手続きの記入モーダル用。公開/受付フォームの記入定義を form_id で返す。"""
    db = connect()
    with _lock:
        gt = _guest_token_for_form(db, form_id)
    if not gt:
        return None, "フォームが見つかりません"
    detail, msg = public_form(gt)
    if msg or detail is None:
        return None, msg
    detail["id"] = form_id
    detail["fill_definition"] = detail.get("definition")
    return detail, None


def mine_submit_answers(
    *,
    form_id: str,
    answers: dict[str, Any],
    submitter_name: str | None,
    is_draft: bool,
    application_token: str | None,
    application_item_id: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    """庁外マイ手続きの記入送信。form_id → guest_token に解決して公開経路で保存する。

    申請束の所有権チェックは呼び出し側（application_token）で済ませている前提。
    submitter_user_id は None（＝本人＝申請者）として扱う。
    """
    db = connect()
    with _lock:
        gt = _guest_token_for_form(db, form_id)
    if not gt:
        return None, "フォームが見つかりません"
    return submit_answers(
        guest_token=gt,
        answers=answers,
        submitter_user_id=None,
        submitter_name=submitter_name,
        is_draft=is_draft,
        application_token=application_token,
        application_item_id=application_item_id,
    )


def mine_upload_file(
    *, form_id: str, filename: str, data: str, kind: str = "file"
) -> tuple[dict[str, Any] | None, str | None]:
    """庁外マイ手続きの記入中ファイル添付。origin=external で保存する。"""
    db = connect()
    with _lock:
        gt = _guest_token_for_form(db, form_id)
    if not gt:
        return None, "フォームが見つかりません"
    return save_upload(
        guest_token=gt, filename=filename, data=data, kind=kind, origin="external"
    )


def _actor_role(app: sqlite3.Row, actor_user_id: str | None) -> str:
    """変更履歴に残す実行者の役割を判定する。

    申請者本人（束の所有者、または公開トークン経由）は「申請者」、それ以外の
    庁内ユーザーは受領側の「受付」として扱う。
    """
    if actor_user_id and (
        _owns_application(app, "internal", actor_user_id)
        or _owns_application(app, "external", actor_user_id)
    ):
        return "申請者"
    if actor_user_id:
        return "受付"
    return "申請者"


def _app_is_submitted(app: sqlite3.Row) -> bool:
    """申請者が「提出」した後かどうか。提出前は履歴を残さず自由に修正できる。"""
    keys = app.keys()
    return "submitted_at" in keys and bool(app["submitted_at"])


def _diff_cell(value: Any) -> str:
    if value is None or value == "":
        return ""
    if isinstance(value, list):
        return "；".join(str(v) for v in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _answers_diff(
    definition: dict[str, Any],
    old_answers: dict[str, Any],
    new_answers: dict[str, Any],
) -> list[dict[str, str]]:
    """記入内容の変更前→後を、フィールドごとに算出する（機微な値はマスク）。"""
    old_disp = crypto.reveal_answers(definition, old_answers or {}, mask=True)
    new_disp = crypto.reveal_answers(definition, new_answers or {}, mask=True)
    skip = {"display", "heading", "note", "divider", "page_break", "section"}
    diffs: list[dict[str, str]] = []
    for comp in definition.get("components") or []:
        if comp.get("type") in skip:
            continue
        cid = comp.get("id")
        if not cid:
            continue
        before = _diff_cell(old_disp.get(cid))
        after = _diff_cell(new_disp.get(cid))
        if before != after:
            diffs.append(
                {
                    "label": str(comp.get("label") or cid),
                    "before": before,
                    "after": after,
                }
            )
    return diffs


def _log_app_event(
    db: sqlite3.Connection,
    application_id: str,
    *,
    actor_role: str,
    actor_user_id: str = "",
    action: str,
    target: str = "",
    detail: str = "",
    changes: list[dict[str, str]] | None = None,
) -> None:
    """申請束の追加・削除・修正を変更履歴として記録する。"""
    db.execute(
        "INSERT INTO application_events (id, application_id, actor_role, "
        "actor_user_id, action, target, detail, changes, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (
            str(uuid.uuid4()),
            application_id,
            actor_role,
            actor_user_id or "",
            action,
            target or "",
            detail or "",
            json.dumps(changes, ensure_ascii=False) if changes else "",
            _now_iso(),
        ),
    )


def list_application_events(
    db: sqlite3.Connection, application_id: str, limit: int = 200
) -> list[dict[str, Any]]:
    """新しい順に変更履歴を返す。"""
    keys = {r[1] for r in db.execute("PRAGMA table_info(application_events)").fetchall()}
    has_changes = "changes" in keys
    cols = "actor_role, actor_user_id, action, target, detail, created_at" + (
        ", changes" if has_changes else ""
    )
    rows = db.execute(
        f"SELECT {cols} FROM application_events WHERE application_id = ? "
        "ORDER BY created_at DESC, rowid DESC LIMIT ?",
        (application_id, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        changes_raw = r["changes"] if has_changes else ""
        try:
            changes = json.loads(changes_raw) if changes_raw else []
        except (TypeError, json.JSONDecodeError):
            changes = []
        out.append(
            {
                "actor_role": r["actor_role"],
                "actor_user_id": r["actor_user_id"],
                "action": r["action"],
                "target": r["target"],
                "detail": r["detail"],
                "changes": changes,
                "created_at": r["created_at"],
            }
        )
    return out


def set_application_status(
    *, application_id: str, owner_kind: str, owner_key: str, status: str
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not row:
            return None, "申請が見つかりません"
        if not _owns_application(row, owner_kind, owner_key):
            return None, "この手続きを操作する権限がありません"
        ov = (status or "").strip()
        if ov and ov not in APP_STATUS_OVERRIDE_ALLOWED:
            return None, "不正な状態です"
        now = _now_iso()
        was_submitted = _app_is_submitted(row)
        # 「提出」した瞬間から履歴の記録を始める。提出前は自由に修正でき記録しない。
        newly_submitted = ov == APP_STATUS_SUBMITTED and not was_submitted
        if newly_submitted:
            db.execute(
                "UPDATE applications SET status_override = ?, submitted_at = ?, "
                "updated_at = ? WHERE id = ?",
                (ov, now, now, application_id),
            )
            _log_app_event(
                db,
                application_id,
                actor_role=_actor_role(row, owner_key),
                actor_user_id=owner_key,
                action="提出",
            )
        else:
            db.execute(
                "UPDATE applications SET status_override = ?, updated_at = ? WHERE id = ?",
                (ov, now, application_id),
            )
            if was_submitted:
                _log_app_event(
                    db,
                    application_id,
                    actor_role=_actor_role(row, owner_key),
                    actor_user_id=owner_key,
                    action="状態を変更",
                    detail=ov or "自動",
                )
        row = db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        db.commit()
        return _application_payload(db, row), None


def _normalize_date(value: str) -> str | None:
    """空文字は許可（クリア）。YYYY-MM-DD のみ受け付け、不正は None を返す。"""
    v = (value or "").strip()
    if not v:
        return ""
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        return None
    return v


def update_application_meta(
    *,
    application_id: str,
    owner_kind: str,
    owner_key: str,
    title: str | None = None,
    assignee: str | None = None,
    deadline: str | None = None,
    next_action_date: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """マイ手続きの案件メタ（名称・担当者・期限・次回更新日）を更新する。

    None のフィールドは変更しない。日付は空文字でクリア可。
    """
    db = connect()
    with _lock:
        row = db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if not row:
            return None, "申請が見つかりません"
        if not _owns_application(row, owner_kind, owner_key):
            return None, "この手続きを操作する権限がありません"
        sets: list[str] = []
        params: list[Any] = []
        if title is not None:
            t = title.strip()
            if not t:
                return None, "名称を入力してください"
            sets.append("title = ?")
            params.append(t)
        if assignee is not None:
            sets.append("assignee = ?")
            params.append(assignee.strip())
        if deadline is not None:
            d = _normalize_date(deadline)
            if d is None:
                return None, "期限は YYYY-MM-DD で入力してください"
            sets.append("deadline = ?")
            params.append(d)
        if next_action_date is not None:
            d = _normalize_date(next_action_date)
            if d is None:
                return None, "次回更新日は YYYY-MM-DD で入力してください"
            sets.append("next_action_date = ?")
            params.append(d)
        if not sets:
            return _application_payload(db, row), None
        sets.append("updated_at = ?")
        params.append(_now_iso())
        params.append(application_id)
        db.execute(
            f"UPDATE applications SET {', '.join(sets)} WHERE id = ?",
            tuple(params),
        )
        row = db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        db.commit()
        return _application_payload(db, row), None


def delete_application(
    *,
    application_id: str | None = None,
    token: str | None = None,
    actor_user_id: str | None = None,
    actor_groups: list[str] | None = None,
    owner_kind: str | None = None,
    owner_key: str | None = None,
) -> str | None:
    """申請束（プロジェクト）を、ひも付く提出・添付ごと削除する。

    権限は「所有者本人（庁内/庁外）」「システム管理者」「その手続きの編集者」のいずれか。
    庁外マイ手続きは owner_kind="external"/owner_key=email で本人確認する。
    """
    db = connect()
    with _lock:
        row = _app_row(db, application_id, token)
        if not row:
            return "申請が見つかりません"
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (row["procedure_id"],)
        ).fetchone()
        allowed = (
            (actor_user_id is not None and _owns_application(row, "internal", actor_user_id))
            or (
                owner_kind is not None
                and owner_key is not None
                and _owns_application(row, owner_kind, owner_key)
            )
            or _is_admin(actor_groups)
            or (proc is not None and _can_edit_procedure(proc, actor_user_id, actor_groups))
        )
        if not allowed:
            return "この申請を削除する権限がありません"
        app_id = row["id"]
        # アイテムに添付されたファイル（bucket/file_id）を掃除
        try:
            items = json.loads(row["items_json"] or "[]")
        except (TypeError, json.JSONDecodeError):
            items = []
        for it in items if isinstance(items, list) else []:
            fid = it.get("file_id")
            if not fid:
                continue
            bucket = it.get("file_bucket") or row["guide_form_id"]
            files.remove_blob(bucket, fid)
            db.execute("DELETE FROM uploaded_files WHERE id = ?", (fid,))
        # この申請にひも付く提出と、その添付ファイル
        subs = db.execute(
            "SELECT id FROM submissions WHERE application_id = ?", (app_id,)
        ).fetchall()
        for s in subs:
            for uf in db.execute(
                "SELECT id, form_id FROM uploaded_files WHERE submission_id = ?",
                (s["id"],),
            ).fetchall():
                files.remove_blob(uf["form_id"], uf["id"])
                db.execute("DELETE FROM uploaded_files WHERE id = ?", (uf["id"],))
            db.execute("DELETE FROM audit_events WHERE submission_id = ?", (s["id"],))
        db.execute("DELETE FROM submissions WHERE application_id = ?", (app_id,))
        db.execute("DELETE FROM applications WHERE id = ?", (app_id,))
        db.commit()
        return None


def rename_application(
    *, application_id: str, owner_kind: str, owner_key: str, title: str
) -> tuple[dict[str, Any] | None, str | None]:
    return update_application_meta(
        application_id=application_id,
        owner_kind=owner_kind,
        owner_key=owner_key,
        title=title,
    )


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
                        "template": _form_template_meta(db, rec["id"]),
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
                        "template": None,
                    }
                )
        return {"procedure_id": procedure_id, "slots": slots}, None


def set_form_template(
    *,
    form_id: str,
    filename: str,
    data: str,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """様式フォーム自身にひな型を登録する（フォームあたり1つ、既存は差し替え）。"""
    db = connect()
    with _lock:
        row = _form_row(db, form_id)
        if not row:
            return None, "フォームが見つかりません"
        if not _can_edit(row, actor_user_id, actor_groups):
            return None, "このフォームを編集する権限がありません"
        def_id = _definition_id(row)
        name = files.safe_filename(filename)
        try:
            blob, mime = files.decode_upload(data, filename=name, kind="file")
        except ValueError as e:
            return None, str(e)
        for old in db.execute(
            "SELECT id FROM uploaded_files WHERE form_id = ? AND component_id = ?",
            (def_id, FORM_TEMPLATE_COMP),
        ).fetchall():
            files.remove_blob(def_id, old["id"])
            db.execute("DELETE FROM uploaded_files WHERE id = ?", (old["id"],))
        file_id = str(uuid.uuid4())
        files.write_blob(def_id, file_id, blob)
        db.execute(
            "INSERT INTO uploaded_files (id, form_id, submission_id, component_id, "
            "filename, mime, size, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (file_id, def_id, None, FORM_TEMPLATE_COMP, name, mime, len(blob), _now_iso()),
        )
        db.commit()
        return {
            "file_id": file_id,
            "filename": name,
            "mime": mime,
            "size": len(blob),
        }, None


def delete_form_template(
    *,
    form_id: str,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> str | None:
    db = connect()
    with _lock:
        row = _form_row(db, form_id)
        if not row:
            return "フォームが見つかりません"
        if not _can_edit(row, actor_user_id, actor_groups):
            return "このフォームを編集する権限がありません"
        def_id = _definition_id(row)
        removed = False
        for old in db.execute(
            "SELECT id FROM uploaded_files WHERE form_id = ? AND component_id = ?",
            (def_id, FORM_TEMPLATE_COMP),
        ).fetchall():
            files.remove_blob(def_id, old["id"])
            db.execute("DELETE FROM uploaded_files WHERE id = ?", (old["id"],))
            removed = True
        db.commit()
        return None if removed else "ひな型が登録されていません"


def _form_template_file_at(
    db: sqlite3.Connection, def_id: str, file_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    row = db.execute(
        "SELECT * FROM uploaded_files WHERE id = ? AND form_id = ? AND component_id = ?",
        (file_id, def_id, FORM_TEMPLATE_COMP),
    ).fetchone()
    if not row:
        return None, "ひな型が見つかりません"
    try:
        path = files.stored_path(def_id, file_id)
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


def get_form_template_file(
    form_id: str, file_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = _form_row(db, form_id)
        if not row:
            return None, "フォームが見つかりません"
        return _form_template_file_at(db, _definition_id(row), file_id)


def get_item_template_file(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """申請束のアイテムに紐づく様式ひな型を返す。"""
    db = connect()
    with _lock:
        app = _app_row(db, application_id, token)
        if not app:
            return None, "申請が見つかりません"
        items = _application_items(app)
        if not items:
            items = _items_from_form_ids(db, app)
        item = next((it for it in items if it.get("id") == item_id), None)
        if not item:
            return None, "アイテムが見つかりません"
        form_id = item.get("form_id") or ""
        meta = _form_template_meta(db, form_id)
        if not meta:
            return None, "ひな型が見つかりません"
        return _form_template_file_at(
            db, _as_definition_id(db, form_id) or form_id, meta["file_id"]
        )


def get_item_file(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """申請束のアイテムに添付された、申請者アップロードのファイルを返す。"""
    db = connect()
    with _lock:
        app = _app_row(db, application_id, token)
        if not app:
            return None, "申請が見つかりません"
        items = _application_items(app)
        if not items:
            items = _items_from_form_ids(db, app)
        item = next((it for it in items if it.get("id") == item_id), None)
        if not item:
            return None, "アイテムが見つかりません"
        file_id = item.get("file_id") or ""
        if not file_id:
            return None, "添付ファイルがありません"
        bucket = item.get("file_bucket") or app["guide_form_id"]
        row = db.execute(
            "SELECT * FROM uploaded_files WHERE id = ? AND form_id = ?",
            (file_id, bucket),
        ).fetchone()
        if not row:
            return None, "添付ファイルが見つかりません"
        try:
            path = files.stored_path(bucket, file_id)
        except ValueError:
            return None, "添付ファイルが見つかりません"
        if not path.is_file():
            return None, "添付ファイルが見つかりません"
        row_keys = row.keys()
        origin = row["origin"] if "origin" in row_keys else None
        if not origin:
            origin = str(item.get("file_origin") or "internal")
        return {
            "filename": row["filename"],
            "mime": row["mime"] or "application/octet-stream",
            "path": str(path),
            "size": row["size"],
            "origin": "external" if origin == "external" else "internal",
        }, None


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
    actor_user_id: str | None = None,
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
        insert_at: int | None = None
        action_label = "枠を追加"
        if duplicate_of:
            action_label = "枠を複製"
        elif form_id:
            action_label = "様式を追加"
        else:
            action_label = "添付枠を追加"
        if duplicate_of:
            src = next((it for it in items if it.get("id") == duplicate_of), None)
            if not src:
                return None, "複製元のアイテムが見つかりません"
            # 案内(data)＝単一フォームの申請用紙も複製できる。複製は通常の様式(yoshiki)
            # として扱い、案内の再解決で消えないようにする（案内本体は1つのまま）。
            if src.get("kind") == "data":
                dup_slot = f"yoshiki:{src.get('form_id') or src.get('id')}"
                dup_kind = "yoshiki"
                copies = [it for it in items if it.get("slot_id") == dup_slot]
                copy_index = len(copies) + 1
            else:
                dup_slot = src.get("slot_id") or ""
                dup_kind = src.get("kind") or "yoshiki"
                copies = [
                    it
                    for it in items
                    if it.get("slot_id") and it.get("slot_id") == dup_slot
                ]
                copy_index = len(copies)
            new_item = _new_item(
                slot_id=dup_slot,
                title=src.get("title") or "",
                kind=dup_kind,
                required="optional",
                cardinality="many",
                form_id=src.get("form_id") or "",
                template_file_id=src.get("template_file_id") or "",
                copy_index=copy_index,
                added_by=added_by,
            )
            # 複製は末尾ではなく、複製元の行の直下に置く。
            insert_at = items.index(src) + 1
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
        if insert_at is not None:
            items.insert(insert_at, new_item)
        else:
            items.append(new_item)
        db.execute(
            "UPDATE applications SET items_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), _now_iso(), app["id"]),
        )
        if _app_is_submitted(app):
            _log_app_event(
                db,
                app["id"],
                actor_role=_actor_role(app, actor_user_id),
                actor_user_id=actor_user_id or "",
                action=action_label,
                target=str(new_item.get("title") or "") if new_item else "",
            )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def delete_application_item(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
    actor_user_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """申請束から、あとから足した枠（複製・手動追加）を1件外す。

    案内（nav）や、案内の解決で置かれた必須の枠は消せない。複製（copy_index>0）と
    ユーザーが足した枠（added_by が system 以外）だけを削除できる。
    """
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
            return None, "案内は削除できません"
        removable = bool(target.get("copy_index")) or (
            target.get("added_by") not in (None, "", "system")
        )
        if not removable:
            return None, "この枠は削除できません"
        fid = target.get("file_id")
        if fid:
            bucket = target.get("file_bucket") or app["guide_form_id"]
            files.remove_blob(bucket, fid)
            db.execute("DELETE FROM uploaded_files WHERE id = ?", (fid,))
        items = [it for it in items if it.get("id") != item_id]
        db.execute(
            "UPDATE applications SET items_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), _now_iso(), app["id"]),
        )
        if _app_is_submitted(app):
            _log_app_event(
                db,
                app["id"],
                actor_role=_actor_role(app, actor_user_id),
                actor_user_id=actor_user_id or "",
                action="枠を削除",
                target=str(target.get("title") or ""),
            )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def _store_item_file(
    db: sqlite3.Connection,
    bucket_form_id: str,
    filename: str,
    data: str,
    origin: str = "internal",
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
        "filename, mime, size, created_at, origin) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            file_id,
            bucket_form_id,
            None,
            None,
            name,
            mime,
            len(blob),
            _now_iso(),
            "external" if origin == "external" else "internal",
        ),
    )
    return {"file_id": file_id, "filename": name, "mime": mime, "size": len(blob)}, None


def fulfill_item_with_file(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
    filename: str,
    data: str,
    actor_user_id: str | None = None,
    origin: str = "internal",
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
        if target.get("kind") == "data" and not _is_single_form_app(db, app):
            # 選択肢のある案内(nav)は記入専用。単一フォーム手続きは申請用紙本体
            # なので、記入済みファイルの添付も許可する。
            return None, "この枠はオンライン記入のみです"
        bucket = target.get("form_id") or app["guide_form_id"]
        saved, err = _store_item_file(db, bucket, filename, data, origin=origin)
        if err or saved is None:
            return None, err
        target["fulfillment"] = "file"
        target["file_id"] = saved["file_id"]
        target["file_name"] = saved["filename"]
        target["file_bucket"] = bucket
        target["file_origin"] = "external" if origin == "external" else "internal"
        db.execute(
            "UPDATE applications SET items_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), _now_iso(), app["id"]),
        )
        if _app_is_submitted(app):
            _log_app_event(
                db,
                app["id"],
                actor_role=_actor_role(app, actor_user_id),
                actor_user_id=actor_user_id or "",
                action="ファイルを添付",
                target=str(target.get("title") or ""),
                detail=str(saved.get("filename") or ""),
            )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def clear_item_fulfillment(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
    actor_user_id: str | None = None,
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
        prev_file = str(target.get("file_name") or "")
        target["fulfillment"] = ""
        target["file_id"] = ""
        target["file_name"] = ""
        target.pop("file_bucket", None)
        db.execute(
            "UPDATE applications SET items_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), _now_iso(), app["id"]),
        )
        if _app_is_submitted(app):
            _log_app_event(
                db,
                app["id"],
                actor_role=_actor_role(app, actor_user_id),
                actor_user_id=actor_user_id or "",
                action="添付を取り消し",
                target=str(target.get("title") or ""),
                detail=prev_file,
            )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def set_item_source(
    *,
    application_id: str | None = None,
    token: str | None = None,
    item_id: str,
    source: str,
    actor_user_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """記入と添付が併存する枠で、どちらを申請データとして採用するかを決める。"""
    if source not in ("form", "file"):
        return None, "採用ソースは form か file を指定してください"
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
        if source == "file" and not target.get("file_id"):
            return None, "添付ファイルがありません"
        if source == "form" and not target.get("form_id"):
            return None, "この枠にはオンライン記入がありません"
        target["fulfillment"] = source
        db.execute(
            "UPDATE applications SET items_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(items, ensure_ascii=False), _now_iso(), app["id"]),
        )
        if _app_is_submitted(app):
            _log_app_event(
                db,
                app["id"],
                actor_role=_actor_role(app, actor_user_id),
                actor_user_id=actor_user_id or "",
                action="採用ソースを変更",
                target=str(target.get("title") or ""),
                detail="オンライン記入" if source == "form" else "添付ファイル",
            )
        db.commit()
        row = _app_row(db, app["id"], None)
        return _application_payload(db, row) if row else None, None


def reorder_application_items(
    *,
    application_id: str | None = None,
    token: str | None = None,
    order: list[str],
    actor_user_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """提出書類一覧の並び順を、申請者が指定した順に並べ替える。

    order に無いアイテムは末尾へ元の順序で残す（欠落による消失を防ぐ）。
    """
    db = connect()
    with _lock:
        app = _app_row(db, application_id, token)
        if not app:
            return None, "申請が見つかりません"
        items = _application_items(app)
        if not items:
            items = _items_from_form_ids(db, app)
        by_id = {str(it.get("id")): it for it in items}
        seen: set[str] = set()
        ordered: list[dict[str, Any]] = []
        for iid in order:
            it = by_id.get(str(iid))
            if it is not None and str(iid) not in seen:
                ordered.append(it)
                seen.add(str(iid))
        for it in items:
            if str(it.get("id")) not in seen:
                ordered.append(it)
        db.execute(
            "UPDATE applications SET items_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(ordered, ensure_ascii=False), _now_iso(), app["id"]),
        )
        # 並び替え（順番変更）は申請内容の変更に当たらないため履歴には残さない。
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


# --- 可搬化: フォーム/手続きの書き出し・読み込み ----------------------------
# 定義（部品・設定）とひな型ファイルを1つのJSONにまとめ、別環境・別作成者へ
# 持ち運べるようにする。提出データ・受付・PIN・トークン・IDは含めない（非可搬・
# 秘匿情報）。手続きは案内＋全構成様式を同梱する自己完結型で、読み込み時は全フォーム
# を新規IDで作り直し、参照（案内・mapping）を張り替える。

EXPORT_VERSION = "opengenai-patchform/export/1"


def _portable_form(db: sqlite3.Connection, def_row: sqlite3.Row) -> dict[str, Any]:
    """フォーム定義行を可搬なdictへ。ひな型はBase64で同梱する。"""
    def_id = def_row["id"]
    template: dict[str, Any] | None = None
    trow = db.execute(
        "SELECT id, filename, mime FROM uploaded_files "
        "WHERE form_id = ? AND component_id = ?",
        (def_id, FORM_TEMPLATE_COMP),
    ).fetchone()
    if trow:
        try:
            path = files.stored_path(def_id, trow["id"])
            if path.is_file():
                template = {
                    "filename": trow["filename"],
                    "mime": trow["mime"] or "application/octet-stream",
                    "data_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
                }
        except ValueError:
            template = None
    return {
        "export_key": def_id,
        "title": def_row["title"],
        "description": def_row["description"],
        "visibility": def_row["visibility"],
        "definition": _definition(def_row),
        "retention_days": def_row["retention_days"],
        "allow_draft": bool(_flag(def_row, "allow_draft")),
        "allow_multiple": bool(_flag(def_row, "allow_multiple")),
        "identity_mode": _identity_mode(def_row),
        "tags": _row_tags(def_row),
        "template": template,
    }


def export_form(
    form_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = _form_row(db, form_id)
        if not row:
            return None, "フォームが見つかりません"
        def_row = row if not _is_reception(row) else _form_row(db, _definition_id(row))
        if not def_row:
            return None, "フォームが見つかりません"
        if not (_is_admin(actor_groups) or _can_edit(def_row, actor_user_id, actor_groups)):
            return None, "このフォームを書き出す権限がありません"
        return {
            "$export": EXPORT_VERSION,
            "kind": "form",
            "exported_at": _now_iso(),
            "spec_version": spec.SPEC_VERSION,
            "form": _portable_form(db, def_row),
        }, None


def export_procedure_bundle(
    procedure_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        proc = db.execute(
            "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
        ).fetchone()
        if not proc:
            return None, "手続きが見つかりません"
        if not (
            _is_admin(actor_groups)
            or _can_edit_procedure(proc, actor_user_id, actor_groups)
        ):
            return None, "この手続きを書き出す権限がありません"
        mapping, _merr = procedure.normalize_mapping(proc["mapping_json"])
        ids = [proc["guide_form_id"]]
        for rule in mapping.get("rules") or []:
            ids.extend(rule.get("form_ids") or [])
        keymap: dict[str, str] = {}
        forms_out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for fid in ids:
            if not fid:
                continue
            frow = _form_row(db, fid)
            if not frow:
                continue
            def_row = frow if not _is_reception(frow) else _form_row(db, _definition_id(frow))
            if not def_row:
                continue
            did = def_row["id"]
            keymap[fid] = did
            if did in seen:
                continue
            seen.add(did)
            forms_out.append(_portable_form(db, def_row))
        rules_out: list[dict[str, Any]] = []
        for rule in mapping.get("rules") or []:
            fkeys = [keymap[fid] for fid in (rule.get("form_ids") or []) if fid in keymap]
            rules_out.append(
                {
                    "component_id": rule.get("component_id"),
                    "option": rule.get("option"),
                    "form_ids": fkeys,
                    "notes": rule.get("notes") or "",
                    "prepare": rule.get("prepare") or [],
                    "refs": rule.get("refs") or [],
                }
            )
        guide_key = keymap.get(proc["guide_form_id"])
        if not guide_key:
            guide_row = _form_row(db, proc["guide_form_id"])
            guide_key = _definition_id(guide_row) if guide_row else None
        if not guide_key:
            return None, "案内フォームが見つかりません"
        return {
            "$export": EXPORT_VERSION,
            "kind": "procedure",
            "exported_at": _now_iso(),
            "spec_version": spec.SPEC_VERSION,
            "procedure": {
                "name": proc["name"],
                "description": proc["description"],
                "visibility": _proc_visibility(proc),
                "notify_emails": _emails_from_row(proc),
                "guide_export_key": guide_key,
                "mapping": {"rules": rules_out},
                "forms": forms_out,
            },
        }, None


def _validate_bundle(bundle: Any, kind: str) -> tuple[bool, str | None]:
    if not isinstance(bundle, dict):
        return False, "取り込みデータが不正です"
    if bundle.get("$export") != EXPORT_VERSION:
        return False, "対応していない書き出し形式です"
    if bundle.get("kind") != kind:
        label = "フォーム" if kind == "form" else "手続き"
        return False, f"{label}の書き出しデータを選んでください"
    return True, None


def _import_one_form(
    pform: dict[str, Any],
    *,
    creator_user_id: str,
    creator_name: str | None,
) -> tuple[dict[str, Any] | None, str | None]:
    title = str(pform.get("title") or "").strip() or "無題フォーム"
    vis = pform.get("visibility")
    if vis not in spec.VISIBILITIES:
        vis = "internal"
    definition = pform.get("definition") if isinstance(pform.get("definition"), dict) else None
    form, err = create_form(
        title=title,
        description=pform.get("description"),
        creator_user_id=creator_user_id,
        creator_name=creator_name,
        visibility=vis,
        definition=definition,
        retention_days=pform.get("retention_days"),
        tags=pform.get("tags"),
    )
    if err or not form:
        return None, err or "フォームの取り込みに失敗しました"
    fid = form["id"]
    identity = pform.get("identity_mode")
    if identity not in spec.IDENTITY_MODES:
        identity = None
    _detail, uerr = update_form(
        fid,
        actor_user_id=creator_user_id,
        allow_draft=bool(pform.get("allow_draft", True)),
        allow_multiple=bool(pform.get("allow_multiple", True)),
        identity_mode=identity,
    )
    if uerr:
        return None, uerr
    tmpl = pform.get("template")
    if isinstance(tmpl, dict) and tmpl.get("data_base64"):
        mime = tmpl.get("mime") or "application/octet-stream"
        data_url = f"data:{mime};base64,{tmpl['data_base64']}"
        _res, terr = set_form_template(
            form_id=fid,
            filename=tmpl.get("filename") or "template",
            data=data_url,
            actor_user_id=creator_user_id,
        )
        if terr:
            return None, terr
    # 部品があれば作成完了(ロック)にして、そのまま手続きで使える状態にする。
    if (definition or {}).get("components"):
        _s, serr = set_status(
            fid, actor_user_id=creator_user_id, status="draft", locked=True
        )
        if serr:
            return None, serr
    return get_form(fid, actor_user_id=creator_user_id), None


def import_form(
    bundle: Any,
    *,
    creator_user_id: str,
    creator_name: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    ok, err = _validate_bundle(bundle, "form")
    if not ok:
        return None, err
    pform = bundle.get("form")
    if not isinstance(pform, dict):
        return None, "フォームデータが不正です"
    return _import_one_form(
        pform, creator_user_id=creator_user_id, creator_name=creator_name
    )


def import_procedure(
    bundle: Any,
    *,
    creator_user_id: str,
    creator_name: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    ok, err = _validate_bundle(bundle, "procedure")
    if not ok:
        return None, err
    pproc = bundle.get("procedure")
    if not isinstance(pproc, dict):
        return None, "手続きデータが不正です"
    forms = pproc.get("forms") if isinstance(pproc.get("forms"), list) else []
    keymap: dict[str, str] = {}
    for pform in forms:
        if not isinstance(pform, dict):
            continue
        key = pform.get("export_key")
        created, ferr = _import_one_form(
            pform, creator_user_id=creator_user_id, creator_name=creator_name
        )
        if ferr or not created:
            return None, ferr or "様式の取り込みに失敗しました"
        if key:
            keymap[str(key)] = created["id"]
    guide_key = pproc.get("guide_export_key")
    guide_id = keymap.get(str(guide_key)) if guide_key is not None else None
    if not guide_id:
        return None, "案内フォームが見つかりません"
    rules: list[dict[str, Any]] = []
    for rule in (pproc.get("mapping") or {}).get("rules") or []:
        if not isinstance(rule, dict):
            continue
        fids = [keymap[str(k)] for k in (rule.get("form_ids") or []) if str(k) in keymap]
        rules.append(
            {
                "component_id": rule.get("component_id"),
                "option": rule.get("option"),
                "form_ids": fids,
                "notes": rule.get("notes") or "",
                "prepare": rule.get("prepare") or [],
                "refs": rule.get("refs") or [],
            }
        )
    vis = pproc.get("visibility")
    proc, perr = create_procedure(
        name=str(pproc.get("name") or "取り込み手続き"),
        description=pproc.get("description"),
        guide_form_id=guide_id,
        mapping={"rules": rules},
        notify_emails=pproc.get("notify_emails"),
        visibility=vis if vis in ("internal", "both") else "internal",
        creator_user_id=creator_user_id,
        creator_name=creator_name,
    )
    return proc, perr


def _copy_title(name: str) -> str:
    base = (name or "").strip() or "無題"
    return f"{base} のコピー"


def duplicate_form(
    form_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    creator_name: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """フォームを独立したコピーとして複製する（ひな型も含む）。"""
    bundle, err = export_form(
        form_id, actor_user_id=actor_user_id, actor_groups=actor_groups
    )
    if err or not bundle:
        return None, err or "複製元のフォームが見つかりません"
    pform = bundle.get("form")
    if isinstance(pform, dict):
        pform["title"] = _copy_title(str(pform.get("title") or ""))
    return import_form(
        bundle, creator_user_id=actor_user_id, creator_name=creator_name
    )


def duplicate_procedure(
    procedure_id: str,
    *,
    actor_user_id: str,
    actor_groups: list[str] | None = None,
    creator_name: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    """手続きを独立したコピーとして複製する（構成フォームも複製する）。"""
    bundle, err = export_procedure_bundle(
        procedure_id, actor_user_id=actor_user_id, actor_groups=actor_groups
    )
    if err or not bundle:
        return None, err or "複製元の手続きが見つかりません"
    pproc = bundle.get("procedure")
    if isinstance(pproc, dict):
        pproc["name"] = _copy_title(str(pproc.get("name") or ""))
    return import_procedure(
        bundle, creator_user_id=actor_user_id, creator_name=creator_name
    )
