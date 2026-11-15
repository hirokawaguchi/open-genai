"""台帳の定義、行、改訂、操作ログ。

棟は署名済み scope。チーム役割は署名済み tags と grants で判定する。
SystemAdmin は全棟の台帳を開ける。一覧はログイン中の棟だけ。
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_TENANT_ID = os.environ.get(
    "LEDGER_DEFAULT_TENANT_ID", "00000000-0000-0000-0000-0000000000t1"
)
NO_TENANT_ID = "__none__"
FIELD_TYPES = ("text", "number", "date", "select", "longtext", "file")
ROLES = ("admin", "editor", "viewer")
ROLE_RANK = {"viewer": 1, "editor": 2, "admin": 3}

DB_PATH = os.environ.get("LEDGER_DB_PATH", "/data/ledger.db")
_lock = threading.RLock()
_db: sqlite3.Connection | None = None


@dataclass
class Actor:
    user_id: str
    groups: list[str] = field(default_factory=list)
    team_ids: list[str] = field(default_factory=list)
    tenant_id: str = ""
    is_admin: bool = False

    def has_tenant(self) -> bool:
        return bool(self.tenant_id) and self.tenant_id != NO_TENANT_ID


def files_root() -> Path:
    return Path(os.environ.get("LEDGER_FILES_DIR") or "/data/ledger-files")


def reset_connection() -> None:
    global _db, DB_PATH
    if _db is not None:
        _db.close()
        _db = None
    DB_PATH = os.environ.get("LEDGER_DB_PATH", "/data/ledger.db")


def connect() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    _db = conn
    _init(conn)
    return conn


def _init(db: sqlite3.Connection) -> None:
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS ledgers (
          id TEXT PRIMARY KEY,
          tenant_id TEXT NOT NULL,
          name TEXT NOT NULL,
          statuses_json TEXT NOT NULL,
          fields_json TEXT NOT NULL,
          grants_json TEXT NOT NULL,
          creator_user_id TEXT NOT NULL,
          source_key TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger_rows (
          id TEXT PRIMARY KEY,
          ledger_id TEXT NOT NULL,
          business_key TEXT NOT NULL,
          assignee TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL,
          comment TEXT NOT NULL DEFAULT '',
          fields_json TEXT NOT NULL,
          extras_json TEXT NOT NULL,
          files_json TEXT NOT NULL,
          deleted_at TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE (ledger_id, business_key)
        );
        CREATE TABLE IF NOT EXISTS ledger_revisions (
          id TEXT PRIMARY KEY,
          row_id TEXT NOT NULL,
          actor_user_id TEXT NOT NULL,
          changes_json TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger_audit (
          id TEXT PRIMARY KEY,
          ledger_id TEXT NOT NULL,
          actor_user_id TEXT NOT NULL,
          action TEXT NOT NULL,
          detail TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS ledger_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_ledgers_tenant ON ledgers(tenant_id);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ledgers_source
          ON ledgers(tenant_id, source_key) WHERE source_key IS NOT NULL AND source_key != '';
        CREATE INDEX IF NOT EXISTS idx_rows_ledger ON ledger_rows(ledger_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_rev_row ON ledger_revisions(row_id, created_at);
        """
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(ledgers)")}
    if "deleted_at" not in columns:
        db.execute("ALTER TABLE ledgers ADD COLUMN deleted_at TEXT NOT NULL DEFAULT ''")
    if "system_json" not in columns:
        db.execute("ALTER TABLE ledgers ADD COLUMN system_json TEXT NOT NULL DEFAULT ''")
    db.commit()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _loads(raw: str | None, fallback: Any) -> Any:
    try:
        value = json.loads(raw or "")
    except json.JSONDecodeError:
        return fallback
    return value


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _new_id(prefix: str = "") -> str:
    token = uuid.uuid4().hex[:12]
    return f"{prefix}{token}" if prefix else str(uuid.uuid4())


def _audit(db: sqlite3.Connection, ledger_id: str, actor: Actor, action: str, detail: str = "") -> None:
    db.execute(
        "INSERT INTO ledger_audit (id, ledger_id, actor_user_id, action, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (_new_id(), ledger_id, actor.user_id, action, detail[:500], _now()),
    )


def _role(row: sqlite3.Row, actor: Actor) -> str | None:
    if actor.is_admin:
        return "admin"
    grants = _loads(row["grants_json"], [])
    if not isinstance(grants, list):
        grants = []
    best = 0
    found = ""
    teams = set(actor.team_ids)
    for grant in grants:
        if not isinstance(grant, dict):
            continue
        if str(grant.get("team_id") or "") not in teams:
            continue
        role = str(grant.get("role") or "")
        rank = ROLE_RANK.get(role, 0)
        if rank > best:
            best = rank
            found = role
    if found:
        return found
    return None


def _can(row: sqlite3.Row, actor: Actor, need: str) -> bool:
    role = _role(row, actor)
    if role is None:
        return False
    if not actor.is_admin and row["tenant_id"] != actor.tenant_id and need:
        return False
    return ROLE_RANK.get(role, 0) >= ROLE_RANK[need]


def _ledger_or_error(db: sqlite3.Connection, ledger_id: str, actor: Actor, need: str):
    row = db.execute("SELECT * FROM ledgers WHERE id = ?", (ledger_id,)).fetchone()
    if row is None or str(row["deleted_at"] or ""):
        return None, "台帳が見つかりません"
    if not _can(row, actor, need):
        return None, "この台帳を操作する権限がありません"
    return row, None


SYSTEM_FIELDS = (
    ("business_key", "業務キー"),
    ("status", "状態"),
    ("assignee", "担当"),
    ("registered_at", "データ登録日時"),
    ("comment", "コメント"),
)


def _system_view(raw: Any) -> list[dict[str, Any]]:
    incoming: dict[str, bool] = {}
    data = _loads(raw, []) if isinstance(raw, str) else raw
    if isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "").strip()
            if key:
                incoming[key] = bool(item.get("visible", True))
    return [
        {"key": key, "label": label, "visible": incoming.get(key, True)}
        for key, label in SYSTEM_FIELDS
    ]


def _public_ledger(row: sqlite3.Row, actor: Actor) -> dict[str, Any]:
    return {
        "id": row["id"],
        "tenant_id": row["tenant_id"],
        "name": row["name"],
        "statuses": _loads(row["statuses_json"], []),
        "fields": _loads(row["fields_json"], []),
        "system": _system_view(row["system_json"] if "system_json" in row.keys() else ""),
        "grants": _loads(row["grants_json"], []),
        "creator_user_id": row["creator_user_id"],
        "source_key": row["source_key"] or "",
        "role": _role(row, actor),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _normalize_grants(raw: Any) -> tuple[list[dict[str, str]] | None, str | None]:
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "チームの役割を読めません"
    grants: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            return None, "チームの役割を読めません"
        team_id = str(item.get("team_id") or "").strip()
        role = str(item.get("role") or "").strip()
        if not team_id or role not in ROLES:
            return None, "チームの役割が不正です"
        if team_id in seen:
            continue
        seen.add(team_id)
        grants.append({"team_id": team_id[:80], "role": role})
    return grants[:40], None


def _normalize_fields(raw: Any, *, previous: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(raw, list):
        return None, "項目を読めません"
    prev = {str(item.get("id")): item for item in (previous or []) if isinstance(item, dict)}
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            return None, "項目を読めません"
        fid = str(item.get("id") or "").strip() or _new_id("f")
        if fid in seen:
            return None, "項目 ID が重複しています"
        label = str(item.get("label") or "").strip()
        if not label:
            return None, "項目の名前を書いてください"
        kind = str(item.get("type") or "text").strip()
        if kind not in FIELD_TYPES:
            return None, "項目の型が不正です"
        old = prev.get(fid)
        if old is not None and str(old.get("type") or "text") != kind:
            return None, "項目の型は変えられません"
        options: list[str] = []
        if kind == "select":
            for opt in item.get("options") or []:
                text = str(opt or "").strip()
                if text and text not in options:
                    options.append(text[:40])
            if not options:
                return None, "選択項目の候補を1つ以上書いてください"
        fields.append(
            {
                "id": fid[:40],
                "label": label[:80],
                "type": kind,
                "masked": bool(item.get("masked")),
                "options": options[:30],
            }
        )
        seen.add(fid)
    if previous:
        old_ids = set(prev)
        if not old_ids.issubset(seen):
            return None, "項目は削除できません"
    return fields[:80], None


def _normalize_statuses(raw: Any, *, previous: list[str] | None = None) -> tuple[list[str] | None, str | None]:
    if not isinstance(raw, list) or not raw:
        return None, "状態を1つ以上書いてください"
    statuses: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text and text not in statuses:
            statuses.append(text[:40])
    if not statuses:
        return None, "状態を1つ以上書いてください"
    if previous and not set(previous).issubset(set(statuses)):
        return None, "状態は削除できません"
    return statuses[:12], None


def _require_create_grant(actor: Actor, grants: list[dict[str, str]]) -> str | None:
    if actor.is_admin:
        return None
    mine = set(actor.team_ids)
    if any(g["role"] == "admin" and g["team_id"] in mine for g in grants):
        return None
    return "自分が属するチームを管理者にしてください"


def create_ledger(actor: Actor, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    if not actor.user_id:
        return None, "認証が必要です"
    if not actor.has_tenant():
        return None, "棟に入ってから台帳を作れます"
    name = str(body.get("name") or "").strip()
    if not name:
        return None, "台帳の名前を書いてください"
    statuses, err = _normalize_statuses(body.get("statuses") or ["受付", "処理中", "完了"])
    if err or statuses is None:
        return None, err
    fields, err = _normalize_fields(body.get("fields") or [])
    if err or fields is None:
        return None, err
    grants, err = _normalize_grants(body.get("grants") or [])
    if err or grants is None:
        return None, err
    err = _require_create_grant(actor, grants)
    if err:
        return None, err
    source_key = str(body.get("source_key") or "").strip()[:80]
    db = connect()
    with _lock:
        if source_key:
            existing = db.execute(
                "SELECT * FROM ledgers WHERE tenant_id = ? AND source_key = ?",
                (actor.tenant_id, source_key),
            ).fetchone()
            if existing:
                if not _can(existing, actor, "editor"):
                    return None, "この台帳を操作する権限がありません"
                return _public_ledger(existing, actor), None
        now = _now()
        ledger_id = _new_id()
        db.execute(
            "INSERT INTO ledgers (id, tenant_id, name, statuses_json, fields_json, grants_json, "
            "creator_user_id, source_key, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                ledger_id,
                actor.tenant_id,
                name[:80],
                _dump(statuses),
                _dump(fields),
                _dump(grants),
                actor.user_id,
                source_key or None,
                now,
                now,
            ),
        )
        row = db.execute("SELECT * FROM ledgers WHERE id = ?", (ledger_id,)).fetchone()
        _audit(db, ledger_id, actor, "台帳を作った", name[:80])
        db.commit()
        return _public_ledger(row, actor), None


def update_ledger(actor: Actor, ledger_id: str, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row, err = _ledger_or_error(db, ledger_id, actor, "admin")
        if err or row is None:
            return None, err
        name = str(body["name"]).strip()[:80] if "name" in body else row["name"]
        if not name:
            return None, "台帳の名前を書いてください"
        prev_fields = _loads(row["fields_json"], [])
        prev_statuses = _loads(row["statuses_json"], [])
        if "fields" in body:
            fields, ferr = _normalize_fields(body.get("fields"), previous=prev_fields)
            if ferr or fields is None:
                return None, ferr
        else:
            fields = prev_fields
        if "statuses" in body:
            statuses, serr = _normalize_statuses(body.get("statuses"), previous=prev_statuses)
            if serr or statuses is None:
                return None, serr
        else:
            statuses = prev_statuses
        if "grants" in body:
            grants, gerr = _normalize_grants(body.get("grants"))
            if gerr or grants is None:
                return None, gerr
            if not any(item["role"] == "admin" for item in grants):
                return None, "オーナーにするチームを1つ残してください"
        else:
            grants = _loads(row["grants_json"], [])
        if "system" in body:
            system = _system_view(body.get("system"))
        else:
            system = _system_view(row["system_json"] if "system_json" in row.keys() else "")
        now = _now()
        db.execute(
            "UPDATE ledgers SET name = ?, statuses_json = ?, fields_json = ?, grants_json = ?, "
            "system_json = ?, updated_at = ? WHERE id = ?",
            (
                _dump(name) if False else name,
                _dump(statuses),
                _dump(fields),
                _dump(grants),
                _dump(system),
                now,
                ledger_id,
            ),
        )
        _audit(db, ledger_id, actor, "定義を変えた", name)
        db.commit()
        saved = db.execute("SELECT * FROM ledgers WHERE id = ?", (ledger_id,)).fetchone()
        return _public_ledger(saved, actor), None


def list_ledgers(actor: Actor) -> list[dict[str, Any]]:
    if not actor.has_tenant():
        return []
    db = connect()
    with _lock:
        rows = db.execute(
            "SELECT * FROM ledgers WHERE tenant_id = ? AND deleted_at = '' ORDER BY updated_at DESC",
            (actor.tenant_id,),
        ).fetchall()
        counts = {
            item["ledger_id"]: int(item["n"])
            for item in db.execute(
                "SELECT ledger_id, COUNT(*) AS n FROM ledger_rows WHERE deleted_at = '' GROUP BY ledger_id"
            )
        }
        shown = []
        for row in rows:
            if _can(row, actor, "viewer"):
                public = _public_ledger(row, actor)
                public["row_count"] = counts.get(row["id"], 0)
                shown.append(public)
        return shown


def delete_ledger(actor: Actor, ledger_id: str) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row, err = _ledger_or_error(db, ledger_id, actor, "admin")
        if err or row is None:
            return None, err
        now = _now()
        db.execute(
            "UPDATE ledgers SET deleted_at = ?, source_key = NULL, updated_at = ? WHERE id = ?",
            (now, now, ledger_id),
        )
        _audit(db, ledger_id, actor, "台帳を削除した", str(row["name"]))
        db.commit()
        return {"id": ledger_id}, None


def get_ledger(actor: Actor, ledger_id: str) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row, err = _ledger_or_error(db, ledger_id, actor, "viewer")
        if err or row is None:
            return None, err
        _audit(db, ledger_id, actor, "台帳を見た", "")
        db.commit()
        return _public_ledger(row, actor), None


def _field_map(row: sqlite3.Row) -> dict[str, dict[str, Any]]:
    fields = _loads(row["fields_json"], [])
    return {str(item.get("id")): item for item in fields if isinstance(item, dict)}


def _check_value(field_def: dict[str, Any], value: str) -> str | None:
    kind = str(field_def.get("type") or "text")
    if value == "":
        return None
    if kind == "number":
        try:
            float(value.replace(",", ""))
        except ValueError:
            return f"{field_def.get('label')} は数値で書いてください"
    if kind == "date" and len(value) >= 10:
        try:
            datetime.strptime(value[:10], "%Y-%m-%d")
        except ValueError:
            return f"{field_def.get('label')} は日付で書いてください"
    if kind == "select":
        options = [str(x) for x in field_def.get("options") or []]
        if value not in options:
            return f"{field_def.get('label')} の候補にありません"
    limit = 8000 if kind == "longtext" else 2000
    if len(value) > limit:
        return f"{field_def.get('label')} が長すぎます"
    return None


def _mask_fields(field_defs: dict[str, dict[str, Any]], values: dict[str, str], role: str | None) -> dict[str, str]:
    if role in ("admin", "editor"):
        return values
    out = {}
    for fid, value in values.items():
        spec = field_defs.get(fid) or {}
        out[fid] = "" if spec.get("masked") else value
    return out


def _public_row(ledger: sqlite3.Row, row: sqlite3.Row, actor: Actor, *, with_revisions: bool = False) -> dict[str, Any]:
    role = _role(ledger, actor)
    defs = _field_map(ledger)
    values = {str(k): str(v) for k, v in _loads(row["fields_json"], {}).items()}
    extras = _loads(row["extras_json"], [])
    if not isinstance(extras, list):
        extras = []
    payload = {
        "id": row["id"],
        "ledger_id": row["ledger_id"],
        "business_key": row["business_key"],
        "assignee": row["assignee"],
        "status": row["status"],
        "comment": row["comment"],
        "fields": _mask_fields(defs, values, role),
        "extras": [
            {"label": str(item.get("label") or ""), "value": str(item.get("value") or "")}
            for item in extras
            if isinstance(item, dict)
        ],
        "files": _loads(row["files_json"], []),
        "deleted_at": row["deleted_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if with_revisions:
        payload["revisions"] = list_revisions(row["id"])
    return payload


def list_revisions(row_id: str) -> list[dict[str, Any]]:
    db = connect()
    rows = db.execute(
        "SELECT * FROM ledger_revisions WHERE row_id = ? ORDER BY created_at DESC",
        (row_id,),
    ).fetchall()
    return [
        {
            "id": item["id"],
            "actor_user_id": item["actor_user_id"],
            "changes": _loads(item["changes_json"], []),
            "created_at": item["created_at"],
        }
        for item in rows
    ]


def _normalize_extras(raw: Any) -> tuple[list[dict[str, str]] | None, str | None]:
    if raw is None:
        return [], None
    if not isinstance(raw, list):
        return None, "追加項目を読めません"
    extras: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            return None, "追加項目を読めません"
        label = str(item.get("label") or "").strip()
        value = str(item.get("value") or "").strip()
        if not label:
            continue
        extras.append({"label": label[:80], "value": value[:2000]})
    return extras[:80], None


def _apply_fields(
    defs: dict[str, dict[str, Any]],
    current: dict[str, str],
    incoming: Any,
) -> tuple[dict[str, str] | None, list[dict[str, str]], str | None]:
    if incoming is None:
        return current, [], None
    if not isinstance(incoming, dict):
        return None, [], "項目の値を読めません"
    nxt = dict(current)
    changes: list[dict[str, str]] = []
    for key, raw in incoming.items():
        fid = str(key)
        spec = defs.get(fid)
        value = "" if raw is None else str(raw).strip()
        if spec is None:
            return None, [], "定義に無い項目です"
        err = _check_value(spec, value)
        if err:
            return None, [], err
        before = current.get(fid, "")
        if before != value:
            nxt[fid] = value
            changes.append(
                {
                    "key": f"field:{fid}",
                    "label": str(spec.get("label") or fid),
                    "before": before,
                    "after": value,
                }
            )
    return nxt, changes, None


def _save_revision(
    db: sqlite3.Connection, row_id: str, actor: Actor, changes: list[dict[str, str]], now: str
) -> None:
    if not changes:
        return
    db.execute(
        "INSERT INTO ledger_revisions (id, row_id, actor_user_id, changes_json, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (_new_id(), row_id, actor.user_id, _dump(changes), now),
    )


def upsert_row(actor: Actor, ledger_id: str, body: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        ledger, err = _ledger_or_error(db, ledger_id, actor, "editor")
        if err or ledger is None:
            return None, err
        statuses = [str(x) for x in _loads(ledger["statuses_json"], [])]
        defs = _field_map(ledger)
        key = str(body.get("business_key") or "").strip() or _new_id("k")
        existing = db.execute(
            "SELECT * FROM ledger_rows WHERE ledger_id = ? AND business_key = ?",
            (ledger_id, key),
        ).fetchone()
        status = str(body.get("status") or (existing["status"] if existing else statuses[0])).strip()
        if status not in statuses:
            return None, "その状態はこの台帳にありません"
        assignee = str(
            body["assignee"] if "assignee" in body else (existing["assignee"] if existing else "")
        ).strip()[:80]
        comment = str(
            body["comment"] if "comment" in body else (existing["comment"] if existing else "")
        ).strip()[:500]
        current_fields = (
            {str(k): str(v) for k, v in _loads(existing["fields_json"], {}).items()} if existing else {}
        )
        fields, field_changes, ferr = _apply_fields(defs, current_fields, body.get("fields"))
        if ferr or fields is None:
            return None, ferr
        if "extras" in body:
            extras, eerr = _normalize_extras(body.get("extras"))
            if eerr or extras is None:
                return None, eerr
        else:
            extras = _loads(existing["extras_json"], []) if existing else []
        now = _now()
        changes = list(field_changes)
        if existing:
            if assignee != existing["assignee"]:
                changes.append({"key": "assignee", "label": "担当", "before": existing["assignee"], "after": assignee})
            if status != existing["status"]:
                changes.append({"key": "status", "label": "状態", "before": existing["status"], "after": status})
            if comment != existing["comment"]:
                changes.append({"key": "comment", "label": "コメント", "before": existing["comment"], "after": comment})
            old_extras = _loads(existing["extras_json"], [])
            if "extras" in body and extras != old_extras:
                changes.append(
                    {
                        "key": "extras",
                        "label": "追加項目",
                        "before": _dump(old_extras),
                        "after": _dump(extras),
                    }
                )
            db.execute(
                "UPDATE ledger_rows SET assignee = ?, status = ?, comment = ?, fields_json = ?, "
                "extras_json = ?, updated_at = ?, deleted_at = '' WHERE id = ?",
                (_dump(assignee) if False else assignee, status, comment, _dump(fields), _dump(extras), now, existing["id"]),
            )
            _save_revision(db, existing["id"], actor, changes, now)
            db.commit()
            saved = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (existing["id"],)).fetchone()
            return _public_row(ledger, saved, actor), None
        row_id = _new_id()
        changes.insert(0, {"key": "created", "label": "作成", "before": "", "after": key})
        db.execute(
            "INSERT INTO ledger_rows (id, ledger_id, business_key, assignee, status, comment, "
            "fields_json, extras_json, files_json, deleted_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '[]', '', ?, ?)",
            (row_id, ledger_id, key[:80], assignee, status, comment, _dump(fields), _dump(extras), now, now),
        )
        _save_revision(db, row_id, actor, changes, now)
        db.commit()
        saved = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        return _public_row(ledger, saved, actor), None


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def list_rows(
    actor: Actor,
    ledger_id: str,
    *,
    status: str = "",
    assignee: str = "",
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    offset: int = 0,
    limit: int = 50,
    include_deleted: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        ledger, err = _ledger_or_error(db, ledger_id, actor, "viewer")
        if err or ledger is None:
            return None, err
        if include_deleted and not _can(ledger, actor, "admin"):
            include_deleted = False
        where = ["ledger_id = ?"]
        params: list[Any] = [ledger_id]
        if not include_deleted:
            where.append("deleted_at = ''")
        if status:
            where.append("status = ?")
            params.append(status)
        if assignee:
            where.append("assignee LIKE ? ESCAPE '\\'")
            params.append(_like(assignee))
        if date_from:
            where.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            where.append("created_at <= ?")
            params.append(date_to + "T23:59:59")
        if q:
            where.append(
                "(comment LIKE ? ESCAPE '\\' OR assignee LIKE ? ESCAPE '\\' "
                "OR fields_json LIKE ? ESCAPE '\\' OR extras_json LIKE ? ESCAPE '\\' "
                "OR business_key LIKE ? ESCAPE '\\')"
            )
            token = _like(q)
            params.extend([token, token, token, token, token])
        limit = max(1, min(limit, 200))
        offset = max(0, offset)
        sql = (
            f"SELECT * FROM ledger_rows WHERE {' AND '.join(where)} "
            "ORDER BY created_at DESC LIMIT ? OFFSET ?"
        )
        rows = db.execute(sql, [*params, limit, offset]).fetchall()
        return {"rows": [_public_row(ledger, row, actor) for row in rows], "offset": offset, "limit": limit}, None


def get_row(actor: Actor, row_id: str) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None, "行が見つかりません"
        ledger, err = _ledger_or_error(db, row["ledger_id"], actor, "viewer")
        if err or ledger is None:
            return None, err
        _audit(db, ledger["id"], actor, "行を見た", row_id)
        db.commit()
        return _public_row(ledger, row, actor, with_revisions=True), None


def set_deleted(actor: Actor, row_id: str, deleted: bool) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None, "行が見つかりません"
        need = "admin" if not deleted else "editor"
        if not deleted:
            need = "admin"
        ledger, err = _ledger_or_error(db, row["ledger_id"], actor, need)
        if err or ledger is None:
            return None, err
        now = _now()
        stamp = "" if not deleted else now
        if (row["deleted_at"] == "") == (not deleted):
            return _public_row(ledger, row, actor), None
        db.execute(
            "UPDATE ledger_rows SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (stamp, now, row_id),
        )
        _save_revision(
            db,
            row_id,
            actor,
            [{"key": "deleted", "label": "削除", "before": row["deleted_at"], "after": stamp}],
            now,
        )
        db.commit()
        saved = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        return _public_row(ledger, saved, actor), None


def add_file(
    actor: Actor, row_id: str, *, filename: str, mime: str, data: bytes
) -> tuple[dict[str, Any] | None, str | None]:
    if len(data) > int(os.environ.get("LEDGER_MAX_UPLOAD_BYTES", "10485760")):
        return None, "ファイルが大きすぎます"
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None, "行が見つかりません"
        ledger, err = _ledger_or_error(db, row["ledger_id"], actor, "editor")
        if err or ledger is None:
            return None, err
        file_id = str(uuid.uuid4())
        dest_dir = files_root() / row_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / file_id).write_bytes(data)
        files = _loads(row["files_json"], [])
        files.append({"file_id": file_id, "name": filename[:200] or file_id, "mime": mime[:120]})
        now = _now()
        db.execute(
            "UPDATE ledger_rows SET files_json = ?, updated_at = ? WHERE id = ?",
            (_dump(files), now, row_id),
        )
        _save_revision(
            db,
            row_id,
            actor,
            [{"key": "file", "label": "添付", "before": "", "after": filename[:200]}],
            now,
        )
        db.commit()
        saved = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        return _public_row(ledger, saved, actor), None


def file_path(actor: Actor, row_id: str, file_id: str) -> tuple[Path | None, str | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM ledger_rows WHERE id = ?", (row_id,)).fetchone()
        if row is None:
            return None, None, "行が見つかりません"
        ledger, err = _ledger_or_error(db, row["ledger_id"], actor, "viewer")
        if err or ledger is None:
            return None, None, err
        files = _loads(row["files_json"], [])
        match = next((item for item in files if str(item.get("file_id")) == file_id), None)
        if match is None:
            return None, None, "ファイルが見つかりません"
        path = files_root() / row_id / file_id
        if not path.is_file():
            return None, None, "ファイルが見つかりません"
        return path, str(match.get("name") or file_id), None


def promote_extra(
    actor: Actor, ledger_id: str, *, label: str, field_id: str = "", field_type: str = "text"
) -> tuple[dict[str, Any] | None, str | None]:
    label = label.strip()
    if not label:
        return None, "追加項目の名前を書いてください"
    db = connect()
    with _lock:
        ledger, err = _ledger_or_error(db, ledger_id, actor, "admin")
        if err or ledger is None:
            return None, err
        fields = _loads(ledger["fields_json"], [])
        target = None
        if field_id:
            target = next((item for item in fields if item.get("id") == field_id), None)
            if target is None:
                return None, "昇格先の項目がありません"
        else:
            kind = field_type if field_type in FIELD_TYPES and field_type != "select" else "text"
            target = {"id": _new_id("f"), "label": label[:80], "type": kind, "masked": False, "options": []}
            fields.append(target)
            db.execute(
                "UPDATE ledgers SET fields_json = ?, updated_at = ? WHERE id = ?",
                (_dump(fields), _now(), ledger_id),
            )
        fid = str(target["id"])
        rows = db.execute(
            "SELECT * FROM ledger_rows WHERE ledger_id = ? AND deleted_at = ''",
            (ledger_id,),
        ).fetchall()
        now = _now()
        for row in rows:
            extras = _loads(row["extras_json"], [])
            kept = []
            moved = ""
            for item in extras:
                if isinstance(item, dict) and str(item.get("label") or "") == label and moved == "":
                    moved = str(item.get("value") or "")
                else:
                    kept.append(item)
            if moved == "":
                continue
            values = {str(k): str(v) for k, v in _loads(row["fields_json"], {}).items()}
            before = values.get(fid, "")
            values[fid] = moved
            db.execute(
                "UPDATE ledger_rows SET fields_json = ?, extras_json = ?, updated_at = ? WHERE id = ?",
                (_dump(values), _dump(kept), now, row["id"]),
            )
            _save_revision(
                db,
                row["id"],
                actor,
                [
                    {
                        "key": f"field:{fid}",
                        "label": label,
                        "before": before,
                        "after": moved,
                    }
                ],
                now,
            )
        _audit(db, ledger_id, actor, "追加項目を定義項目にした", label)
        db.commit()
        saved = db.execute("SELECT * FROM ledgers WHERE id = ?", (ledger_id,)).fetchone()
        return _public_ledger(saved, actor), None


def sample_extras(actor: Actor, ledger_id: str, limit: int = 40) -> tuple[list[dict[str, str]] | None, str | None]:
    db = connect()
    with _lock:
        ledger, err = _ledger_or_error(db, ledger_id, actor, "viewer")
        if err or ledger is None:
            return None, err
        rows = db.execute(
            "SELECT extras_json, fields_json FROM ledger_rows WHERE ledger_id = ? AND deleted_at = '' "
            "ORDER BY updated_at DESC LIMIT 200",
            (ledger_id,),
        ).fetchall()
        defs = _field_map(ledger)
        masked = {fid for fid, spec in defs.items() if spec.get("masked")}
        bag: list[dict[str, str]] = []
        for row in rows:
            for item in _loads(row["extras_json"], []):
                if isinstance(item, dict):
                    label = str(item.get("label") or "")
                    if "マイナンバー" in label or "個人番号" in label:
                        continue
                    bag.append({"label": label, "value": str(item.get("value") or "")[:200]})
            for fid, value in _loads(row["fields_json"], {}).items():
                if fid in masked:
                    continue
                spec = defs.get(str(fid)) or {}
                bag.append({"label": str(spec.get("label") or fid), "value": str(value)[:200]})
            if len(bag) >= limit:
                break
        return bag[:limit], None


def import_legacy(db_path: str, files_dir: str = "") -> int:
    """旧 patchform 台帳を既定の棟へ一度だけ移す。作成者は最初の確定者。"""
    source = Path(db_path)
    if not source.is_file():
        return 0
    db = connect()
    with _lock:
        done = db.execute(
            "SELECT value FROM ledger_meta WHERE key = ?", (f"import:{source}",)
        ).fetchone()
        if done:
            return 0
        src = sqlite3.connect(source)
        src.row_factory = sqlite3.Row
        try:
            rows = src.execute("SELECT * FROM ledger_rows ORDER BY confirmed_at").fetchall()
        except sqlite3.Error:
            src.close()
            return 0
        grouped: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            grouped.setdefault(str(row["procedure_id"]), []).append(row)
        copied = 0
        origin = Path(files_dir) if files_dir else None
        for procedure_id, items in grouped.items():
            first = items[0]
            creator = str(first["confirmed_by"] or "")
            name = str(first["procedure_name"] or "手続き")
            statuses = []
            for item in items:
                text = str(item["status"] or "").strip()
                if text and text not in statuses:
                    statuses.append(text)
            if "受理" not in statuses:
                statuses.insert(0, "受理")
            now = _now()
            ledger_id = _new_id()
            db.execute(
                "INSERT INTO ledgers (id, tenant_id, name, statuses_json, fields_json, grants_json, "
                "creator_user_id, source_key, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, '[]', '[]', ?, ?, ?, ?)",
                (
                    ledger_id,
                    DEFAULT_TENANT_ID,
                    name[:80],
                    _dump(statuses or ["受理"]),
                    creator,
                    f"procedure:{procedure_id}"[:80],
                    now,
                    now,
                ),
            )
            for item in items:
                snapshot = _loads(item["snapshot_json"], {})
                extras = []
                for block in snapshot.get("answers") or []:
                    if not isinstance(block, dict):
                        continue
                    for line in block.get("lines") or []:
                        if isinstance(line, dict):
                            extras.append(
                                {
                                    "label": str(line.get("label") or "")[:80],
                                    "value": str(line.get("value") or "")[:2000],
                                }
                            )
                        elif isinstance(line, str) and ":" in line:
                            label, _, value = line.partition(":")
                            extras.append({"label": label.strip()[:80], "value": value.strip()[:2000]})
                files = []
                row_id = str(item["id"])
                for info in snapshot.get("files") or []:
                    if isinstance(info, dict) and info.get("file_id"):
                        files.append(
                            {
                                "file_id": str(info.get("file_id")),
                                "name": str(info.get("name") or ""),
                                "mime": str(info.get("mime") or ""),
                            }
                        )
                if origin is not None:
                    src_dir = origin / row_id
                    if src_dir.is_dir():
                        dest = files_root() / row_id
                        dest.mkdir(parents=True, exist_ok=True)
                        for child in src_dir.iterdir():
                            if child.is_file():
                                shutil.copyfile(child, dest / child.name)
                created = str(item["confirmed_at"] or now)
                db.execute(
                    "INSERT OR IGNORE INTO ledger_rows (id, ledger_id, business_key, assignee, status, "
                    "comment, fields_json, extras_json, files_json, deleted_at, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, '{}', ?, ?, '', ?, ?)",
                    (
                        row_id,
                        ledger_id,
                        str(item["application_id"])[:80],
                        str(item["assignee"] or "")[:80],
                        str(item["status"] or statuses[0]),
                        str(item["comment"] or "")[:500],
                        _dump(extras),
                        _dump(files),
                        created,
                        str(item["updated_at"] or created),
                    ),
                )
                db.execute(
                    "INSERT INTO ledger_revisions (id, row_id, actor_user_id, changes_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        _new_id(),
                        row_id,
                        creator,
                        _dump([{"key": "snapshot", "label": "確定内容", "before": "", "after": _dump(snapshot)[:4000]}]),
                        created,
                    ),
                )
                copied += 1
        src.close()
        db.execute(
            "INSERT INTO ledger_meta (key, value) VALUES (?, ?)",
            (f"import:{source}", _now()),
        )
        db.commit()
        return copied


def maybe_import() -> int:
    path = os.environ.get("LEDGER_IMPORT_DB", "")
    if not path:
        return 0
    return import_legacy(path, os.environ.get("LEDGER_IMPORT_FILES", ""))
