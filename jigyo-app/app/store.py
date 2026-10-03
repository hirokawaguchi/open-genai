"""二週間の仕事の永続化と権限。

課題の持ち主はチーム。個人の担当欄は持たない。
計画の課題を期枠へ入れること、優先度、完了条件は所属長だけが決める。
定常は定型のボタン（登録 API）で今期枠へ入る。
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

from app.holidays import holidays_between

DB_PATH = os.environ.get("JIGYO_DB_PATH", "/data/jigyo.db")
UNDO_SECONDS = 600
# 1 は 1人の1日。0.25 はおよそ2時間。0.5 は半日。
SIZES = frozenset({0.25, 0.5, 1, 2, 3, 5, 8})
UNFILED_KEY = "UNFILED"
PRIORITIES = frozenset({"high", "normal", "low"})
WORK_STATUSES = frozenset({"todo", "doing", "waiting"})
KINDS = frozenset({"work", "confirm", "decision", "adjust", "leave"})
COMPLETION_MODES = frozenset({"objective", "chief"})
ROLES = frozenset({"admin", "editor", "viewer"})

_lock = threading.Lock()


class JigyoError(Exception):
    def __init__(self, status: int, message: str) -> None:
        self.status = status
        self.message = message
        super().__init__(message)


def today() -> date:
    return date.today()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _connect() -> sqlite3.Connection:
    parent = os.path.dirname(DB_PATH)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS team_settings (
                team_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                week_start INTEGER NOT NULL DEFAULT 0,
                chief_user_id TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                team_id TEXT NOT NULL,
                key TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                mode TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS project_members (
                project_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (project_id, user_id)
            );

            CREATE TABLE IF NOT EXISTS templates (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                team_id TEXT NOT NULL,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                size INTEGER NOT NULL,
                priority TEXT NOT NULL,
                completion_text TEXT NOT NULL,
                completion_mode TEXT NOT NULL,
                checks_json TEXT NOT NULL DEFAULT '[]',
                key_hash TEXT,
                key_hint TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS issues (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                number INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'todo',
                priority TEXT,
                size INTEGER,
                kind TEXT NOT NULL DEFAULT 'work',
                leave_name TEXT NOT NULL DEFAULT '',
                holiday_date TEXT,
                completion_text TEXT NOT NULL DEFAULT '',
                completion_mode TEXT,
                timebox_start TEXT,
                template_id TEXT,
                milestone_name TEXT NOT NULL DEFAULT '',
                milestone_date TEXT,
                start_date TEXT,
                due_date TEXT,
                event_id TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                done_at TEXT,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS checks (
                id TEXT PRIMARY KEY,
                issue_id TEXT NOT NULL,
                label TEXT NOT NULL,
                position INTEGER NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                done_by TEXT,
                done_at TEXT
            );

            CREATE TABLE IF NOT EXISTS comments (
                id TEXT PRIMARY KEY,
                issue_id TEXT NOT NULL,
                author TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS history (
                id TEXT PRIMARY KEY,
                team_id TEXT NOT NULL,
                issue_id TEXT,
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS projects_team_key
                ON projects(team_id, key) WHERE deleted_at IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS issues_event
                ON issues(template_id, event_id)
                WHERE event_id IS NOT NULL AND deleted_at IS NULL;
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(team_settings)")}
        if "headcount" not in columns:
            conn.execute("ALTER TABLE team_settings ADD COLUMN headcount INTEGER")


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def box_bounds(day: date, week_start: int) -> tuple[date, date]:
    """week_start（0=月曜）に揃えた 14 日の期枠。"""
    start_wd = week_start % 7
    epoch = date(2024, 1, 1)
    epoch = epoch + timedelta(days=(start_wd - epoch.weekday()) % 7)
    index = (day - epoch).days // 14
    start = epoch + timedelta(days=index * 14)
    return start, start + timedelta(days=13)


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError as e:
        raise JigyoError(400, "日付の形式が正しくありません") from e


class Access:
    def __init__(self, user_id: str, tenant_id: str, teams: dict[str, dict[str, Any]]) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.teams = teams

    def team(self, team_id: str) -> dict[str, Any]:
        row = self.teams.get(team_id)
        if not row:
            raise JigyoError(403, "このチームを見る権限がありません")
        return row

    def can_read(self, team_id: str) -> bool:
        return team_id in self.teams

    def is_member(self, team_id: str) -> bool:
        row = self.teams.get(team_id) or {}
        return bool(row.get("member")) and not bool(row.get("inherited"))

    def is_admin(self, team_id: str) -> bool:
        return bool((self.teams.get(team_id) or {}).get("admin"))


def parse_access(payload: dict[str, Any]) -> Access:
    user_id = str(payload.get("userId") or "").strip().lower()
    tenant_id = str(payload.get("tenantId") or "").strip()
    if not user_id or not tenant_id:
        raise JigyoError(401, "利用者情報が見つかりません")
    teams: dict[str, dict[str, Any]] = {}
    for row in payload.get("teams") or []:
        tid = str(row.get("teamId") or "")
        if tid:
            teams[tid] = row
    return Access(user_id, tenant_id, teams)


def _settings(conn: sqlite3.Connection, team_id: str, tenant_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM team_settings WHERE team_id = ?", (team_id,)
    ).fetchone()
    if row:
        return row
    conn.execute(
        "INSERT INTO team_settings (team_id, tenant_id, week_start, chief_user_id, updated_at)"
        " VALUES (?, ?, 0, NULL, ?)",
        (team_id, tenant_id, _now()),
    )
    return conn.execute(
        "SELECT * FROM team_settings WHERE team_id = ?", (team_id,)
    ).fetchone()


def _is_chief(conn: sqlite3.Connection, access: Access, team_id: str) -> bool:
    row = conn.execute(
        "SELECT chief_user_id FROM team_settings WHERE team_id = ?", (team_id,)
    ).fetchone()
    return bool(row and row["chief_user_id"] == access.user_id)


def _require_chief(conn: sqlite3.Connection, access: Access, team_id: str) -> None:
    if not _is_chief(conn, access, team_id):
        raise JigyoError(403, "所属長だけが決められます")


def _unfiled_project(conn: sqlite3.Connection, team_id: str, tenant_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM projects WHERE team_id = ? AND key = ? AND deleted_at IS NULL",
        (team_id, UNFILED_KEY),
    ).fetchone()
    if row:
        return row
    project_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO projects"
        " (id, tenant_id, team_id, key, name, description, mode, status, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, '事業未定', '', 'plan', 'active', ?, ?)",
        (project_id, tenant_id, team_id, UNFILED_KEY, now, now),
    )
    return _project(conn, project_id)


def _project(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ? AND deleted_at IS NULL", (project_id,)
    ).fetchone()
    if not row:
        raise JigyoError(404, "事業が見つかりません")
    return row


def _issue(conn: sqlite3.Connection, issue_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM issues WHERE id = ? AND deleted_at IS NULL", (issue_id,)
    ).fetchone()
    if not row:
        raise JigyoError(404, "課題が見つかりません")
    return row


def _member_role(conn: sqlite3.Connection, project_id: str, user_id: str) -> str | None:
    row = conn.execute(
        "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
        (project_id, user_id),
    ).fetchone()
    return row["role"] if row else None


def _can_edit_project(conn: sqlite3.Connection, access: Access, project: sqlite3.Row) -> bool:
    if access.is_admin(project["team_id"]) or _is_chief(conn, access, project["team_id"]):
        return True
    role = _member_role(conn, project["id"], access.user_id)
    return role in {"admin", "editor"}


def _hist(
    conn: sqlite3.Connection,
    team_id: str,
    actor: str,
    action: str,
    detail: str = "",
    issue_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO history (id, team_id, issue_id, actor, action, detail, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), team_id, issue_id, actor, action, detail, _now()),
    )


def _next_number(conn: sqlite3.Connection, project_id: str) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(number), 0) + 1 AS n FROM issues WHERE project_id = ?",
        (project_id,),
    ).fetchone()
    return int(row["n"])


def _size(value: Any, *, required: bool) -> int | float | None:
    if value is None or value == "":
        if required:
            raise JigyoError(400, "規模を選んでください")
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise JigyoError(400, "規模は 0.25、0.5、1、2、3、5、8 です") from e
    quarters = round(number * 4)
    if quarters / 4 not in SIZES:
        raise JigyoError(400, "規模は 0.25、0.5、1、2、3、5、8 です")
    canonical = quarters / 4
    return int(canonical) if canonical == int(canonical) else canonical


def _priority(value: Any, *, required: bool) -> str | None:
    if not value:
        if required:
            raise JigyoError(400, "優先度を選んでください")
        return None
    if value not in PRIORITIES:
        raise JigyoError(400, "優先度が正しくありません")
    return str(value)


def set_chief(access: Access, team_id: str, chief_user_id: str) -> dict[str, Any]:
    access.team(team_id)
    if not access.is_admin(team_id):
        raise JigyoError(403, "所属長の任命はチームの管理者が行います")
    chief = chief_user_id.strip().lower()
    if not chief:
        raise JigyoError(400, "所属長の利用者 ID を入力してください")
    with _lock, _connect() as conn:
        _settings(conn, team_id, access.tenant_id)
        conn.execute(
            "UPDATE team_settings SET chief_user_id = ?, updated_at = ? WHERE team_id = ?",
            (chief, _now(), team_id),
        )
        _hist(conn, team_id, access.user_id, "chief", chief)
    return {"teamId": team_id, "chiefUserId": chief}


def _headcount(settings: sqlite3.Row) -> int | None:
    keys = settings.keys()
    if "headcount" not in keys or settings["headcount"] is None:
        return None
    return int(settings["headcount"])


def set_headcount(access: Access, team_id: str, headcount: Any) -> dict[str, Any]:
    access.team(team_id)
    with _lock, _connect() as conn:
        if not access.is_admin(team_id) and not _is_chief(conn, access, team_id):
            raise JigyoError(403, "人数はチームの管理者か所属長が置きます")
        try:
            count = int(headcount)
        except (TypeError, ValueError) as e:
            raise JigyoError(400, "人数は1人以上の整数です") from e
        if count < 1 or count > 200:
            raise JigyoError(400, "人数は1人以上の整数です")
        _settings(conn, team_id, access.tenant_id)
        conn.execute(
            "UPDATE team_settings SET headcount = ?, updated_at = ? WHERE team_id = ?",
            (count, _now(), team_id),
        )
        conn.execute(
            "UPDATE issues SET size = ?, updated_at = ?"
            " WHERE holiday_date IS NOT NULL AND deleted_at IS NULL"
            " AND project_id IN (SELECT id FROM projects WHERE team_id = ?)",
            (count, _now(), team_id),
        )
        _hist(conn, team_id, access.user_id, "headcount", str(count))
    return {"teamId": team_id, "headcount": count}


def _leave_amount(value: Any) -> int | float:
    try:
        number = float(value)
    except (TypeError, ValueError) as e:
        raise JigyoError(400, "休暇の規模を入力してください") from e
    if number < 0 or number > 500:
        raise JigyoError(400, "休暇の規模を入力してください")
    quarters = round(number * 4) / 4
    return int(quarters) if quarters == int(quarters) else quarters


def set_vacation(access: Access, team_id: str, timebox_start: str, size: Any) -> dict[str, Any]:
    start = _parse_date(timebox_start)
    if not start:
        raise JigyoError(400, "期枠を指定してください")
    amount = _leave_amount(size)
    with _lock, _connect() as conn:
        access.team(team_id)
        _require_chief(conn, access, team_id)
        rows = conn.execute(
            "SELECT i.id FROM issues i JOIN projects p ON p.id = i.project_id"
            " WHERE p.team_id = ? AND i.kind = 'leave' AND i.deleted_at IS NULL"
            " AND i.timebox_start = ? AND i.holiday_date IS NULL AND i.leave_name = ''"
            " AND i.title = '休暇'"
            " ORDER BY i.created_at",
            (team_id, start.isoformat()),
        ).fetchall()
        now = _now()
        if amount == 0:
            for row in rows:
                conn.execute(
                    "UPDATE issues SET deleted_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, row["id"]),
                )
            _hist(conn, team_id, access.user_id, "vacation", "0")
            return {"timeboxStart": start.isoformat(), "size": 0}
        if rows:
            issue_id = rows[0]["id"]
            conn.execute(
                "UPDATE issues SET size = ?, updated_at = ? WHERE id = ?",
                (amount, now, issue_id),
            )
            for extra in rows[1:]:
                conn.execute(
                    "UPDATE issues SET deleted_at = ?, updated_at = ? WHERE id = ?",
                    (now, now, extra["id"]),
                )
        else:
            project = _unfiled_project(conn, team_id, access.tenant_id)
            issue_id = _insert_issue(
                conn,
                project=project,
                title="休暇",
                body="",
                status="todo",
                priority=None,
                size=amount,
                kind="leave",
                leave_name="",
                holiday_date=None,
                completion_text="",
                completion_mode=None,
                timebox_start=start.isoformat(),
                template_id=None,
                event_id=None,
                created_by=access.user_id,
                checks=[],
            )
        _hist(conn, team_id, access.user_id, "vacation", str(amount))
        issue = _issue_dict(conn, _issue(conn, issue_id))
    return issue


def create_project(access: Access, body: dict[str, Any]) -> dict[str, Any]:
    team_id = str(body.get("teamId") or "")
    access.team(team_id)
    if not access.is_admin(team_id):
        raise JigyoError(403, "事業の作成はチームの管理者が行います")
    mode = body.get("mode")
    if mode not in {"plan", "routine"}:
        raise JigyoError(400, "進め方は計画か定常です")
    name = str(body.get("name") or "").strip()
    key = str(body.get("key") or "").strip().upper()
    if not name or not key:
        raise JigyoError(400, "名前と記号を入力してください")
    if not key.isalnum():
        raise JigyoError(400, "記号は英数字だけにしてください")
    if key == UNFILED_KEY:
        raise JigyoError(400, "この記号は使えません")
    now = _now()
    project_id = str(uuid.uuid4())
    with _lock, _connect() as conn:
        _settings(conn, team_id, access.tenant_id)
        try:
            conn.execute(
                "INSERT INTO projects"
                " (id, tenant_id, team_id, key, name, description, mode, status, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)",
                (
                    project_id,
                    access.tenant_id,
                    team_id,
                    key,
                    name,
                    str(body.get("description") or ""),
                    mode,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as e:
            raise JigyoError(409, "同じ記号の事業があります") from e
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (?, ?, 'admin')",
            (project_id, access.user_id),
        )
        _hist(conn, team_id, access.user_id, "project", f"{key} {name}")
    return get_project(access, project_id)


def get_project(access: Access, project_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = _project(conn, project_id)
        access.team(row["team_id"])
        return _project_dict(conn, row)


def _project_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    members = [
        {"userId": r["user_id"], "role": r["role"]}
        for r in conn.execute(
            "SELECT user_id, role FROM project_members WHERE project_id = ? ORDER BY user_id",
            (row["id"],),
        )
    ]
    return {
        "id": row["id"],
        "teamId": row["team_id"],
        "key": row["key"],
        "name": row["name"],
        "description": row["description"],
        "mode": row["mode"],
        "status": row["status"],
        "members": members,
    }


def add_member(access: Access, project_id: str, user_id: str, role: str) -> dict[str, Any]:
    if role not in ROLES:
        raise JigyoError(400, "役割は管理者、編集、閲覧です")
    user_id = user_id.strip().lower()
    if not user_id:
        raise JigyoError(400, "利用者 ID を入力してください")
    with _lock, _connect() as conn:
        project = _project(conn, project_id)
        if not access.is_admin(project["team_id"]):
            raise JigyoError(403, "メンバーの変更はチームの管理者が行います")
        conn.execute(
            "INSERT INTO project_members (project_id, user_id, role) VALUES (?, ?, ?)"
            " ON CONFLICT(project_id, user_id) DO UPDATE SET role = excluded.role",
            (project_id, user_id, role),
        )
        _hist(conn, project["team_id"], access.user_id, "member", f"{user_id} {role}")
    return get_project(access, project_id)


def create_template(access: Access, body: dict[str, Any]) -> dict[str, Any]:
    project_id = str(body.get("projectId") or "")
    name = str(body.get("name") or "").strip()
    completion = str(body.get("completionText") or "").strip()
    mode = body.get("completionMode")
    checks = body.get("checks") or []
    if not name or not completion:
        raise JigyoError(400, "名前と完了条件を入力してください")
    if mode not in COMPLETION_MODES:
        raise JigyoError(400, "完了の決め方を選んでください")
    if not isinstance(checks, list):
        raise JigyoError(400, "確認項目の形式が正しくありません")
    labels = [str(x).strip() for x in checks if str(x).strip()]
    if mode == "objective" and not labels:
        raise JigyoError(400, "客観評価には確認項目が必要です")
    with _lock, _connect() as conn:
        project = _project(conn, project_id)
        if project["mode"] != "routine":
            raise JigyoError(400, "定型は定常の事業に登録します")
        _require_chief(conn, access, project["team_id"])
        now = _now()
        template_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO templates"
            " (id, tenant_id, team_id, project_id, name, size, priority,"
            "  completion_text, completion_mode, checks_json, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                template_id,
                project["tenant_id"],
                project["team_id"],
                project_id,
                name,
                _size(body.get("size"), required=True),
                _priority(body.get("priority") or "normal", required=True),
                completion,
                mode,
                json.dumps(labels, ensure_ascii=False),
                now,
                now,
            ),
        )
        _hist(conn, project["team_id"], access.user_id, "template", name)
        row = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        return _template_dict(row)


def _live_on_project(conn: sqlite3.Connection, project_id: str) -> bool:
    issue = conn.execute(
        "SELECT 1 FROM issues WHERE project_id = ? AND deleted_at IS NULL",
        (project_id,),
    ).fetchone()
    template = conn.execute(
        "SELECT 1 FROM templates WHERE project_id = ? AND deleted_at IS NULL",
        (project_id,),
    ).fetchone()
    return bool(issue or template)


def update_project(access: Access, project_id: str, body: dict[str, Any]) -> dict[str, Any]:
    with _lock, _connect() as conn:
        project = _project(conn, project_id)
        if project["key"] == UNFILED_KEY:
            raise JigyoError(400, "この事業は直せません")
        if not access.is_admin(project["team_id"]):
            raise JigyoError(403, "事業の修正はチームの管理者が行います")
        name = str(body.get("name") if "name" in body else project["name"]).strip()
        key = str(body.get("key") if "key" in body else project["key"]).strip().upper()
        mode = body.get("mode") if "mode" in body else project["mode"]
        if not name or not key:
            raise JigyoError(400, "名前と記号を入力してください")
        if not key.isalnum() or key == UNFILED_KEY:
            raise JigyoError(400, "記号は英数字だけにしてください")
        if mode not in {"plan", "routine"}:
            raise JigyoError(400, "進め方は計画か定常です")
        if mode != project["mode"] and _live_on_project(conn, project_id):
            raise JigyoError(400, "作業や定型が残っているあいだは、進め方を変えられません")
        try:
            conn.execute(
                "UPDATE projects SET name = ?, key = ?, mode = ?, updated_at = ? WHERE id = ?",
                (name, key, mode, _now(), project_id),
            )
        except sqlite3.IntegrityError as e:
            raise JigyoError(409, "同じ記号の事業があります") from e
        _hist(conn, project["team_id"], access.user_id, "project", f"{key} {name}")
        return _project_dict(conn, _project(conn, project_id))


def delete_project(access: Access, project_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        project = _project(conn, project_id)
        if project["key"] == UNFILED_KEY:
            raise JigyoError(400, "この事業は消せません")
        if not access.is_admin(project["team_id"]):
            raise JigyoError(403, "事業を消せるのはチームの管理者です")
        if _live_on_project(conn, project_id):
            raise JigyoError(400, "作業や定型が残っている事業は消せません。名前は直せます")
        now = _now()
        conn.execute(
            "UPDATE projects SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, project_id),
        )
        _hist(conn, project["team_id"], access.user_id, "project-delete", project["name"])
    return {"id": project_id, "deleted": True}


def update_template(access: Access, template_id: str, body: dict[str, Any]) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM templates WHERE id = ? AND deleted_at IS NULL", (template_id,)
        ).fetchone()
        if not row:
            raise JigyoError(404, "定型が見つかりません")
        _require_chief(conn, access, row["team_id"])
        name = str(body.get("name") if "name" in body else row["name"]).strip()
        completion = str(
            body.get("completionText") if "completionText" in body else row["completion_text"]
        ).strip()
        mode = body.get("completionMode") if "completionMode" in body else row["completion_mode"]
        if not name or not completion:
            raise JigyoError(400, "名前と完了条件を入力してください")
        if mode not in COMPLETION_MODES:
            raise JigyoError(400, "完了の決め方を選んでください")
        if "checks" in body:
            raw_checks = body.get("checks") or []
            if not isinstance(raw_checks, list):
                raise JigyoError(400, "確認項目の形式が正しくありません")
            labels = [str(item).strip() for item in raw_checks if str(item).strip()]
        else:
            labels = json.loads(row["checks_json"] or "[]")
        if mode == "objective" and not labels:
            raise JigyoError(400, "客観評価には確認項目が必要です")
        project_id = str(body.get("projectId") or row["project_id"])
        project = _project(conn, project_id)
        if project["team_id"] != row["team_id"] or project["mode"] != "routine":
            raise JigyoError(400, "定型は同じチームの定常の事業に置きます")
        size = _size(body.get("size"), required=True) if "size" in body else row["size"]
        conn.execute(
            "UPDATE templates SET project_id = ?, name = ?, size = ?, completion_text = ?,"
            " completion_mode = ?, checks_json = ?, updated_at = ? WHERE id = ?",
            (
                project_id,
                name,
                size,
                completion,
                mode,
                json.dumps(labels, ensure_ascii=False),
                _now(),
                template_id,
            ),
        )
        _hist(conn, row["team_id"], access.user_id, "template", name)
        updated = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
        return _template_dict(updated)


def delete_template(access: Access, template_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM templates WHERE id = ? AND deleted_at IS NULL", (template_id,)
        ).fetchone()
        if not row:
            raise JigyoError(404, "定型が見つかりません")
        _require_chief(conn, access, row["team_id"])
        now = _now()
        conn.execute(
            "UPDATE templates SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, template_id),
        )
        _hist(conn, row["team_id"], access.user_id, "template-delete", row["name"])
    return {"id": template_id, "deleted": True}


def _template_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "teamId": row["team_id"],
        "projectId": row["project_id"],
        "name": row["name"],
        "size": row["size"],
        "priority": row["priority"],
        "completionText": row["completion_text"],
        "completionMode": row["completion_mode"],
        "checks": json.loads(row["checks_json"] or "[]"),
        "hasReceiptKey": bool(row["key_hash"]),
        "keyHint": row["key_hint"],
    }


def issue_receipt_key(access: Access, template_id: str) -> dict[str, Any]:
    raw = secrets.token_urlsafe(24)
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM templates WHERE id = ? AND deleted_at IS NULL", (template_id,)
        ).fetchone()
        if not row:
            raise JigyoError(404, "定型が見つかりません")
        _require_chief(conn, access, row["team_id"])
        conn.execute(
            "UPDATE templates SET key_hash = ?, key_hint = ?, updated_at = ? WHERE id = ?",
            (_hash_key(raw), raw[:6], _now(), template_id),
        )
        _hist(conn, row["team_id"], access.user_id, "receipt-key", row["name"])
    return {"templateId": template_id, "receiptKey": raw}


def revoke_receipt_key(access: Access, template_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM templates WHERE id = ? AND deleted_at IS NULL", (template_id,)
        ).fetchone()
        if not row:
            raise JigyoError(404, "定型が見つかりません")
        _require_chief(conn, access, row["team_id"])
        conn.execute(
            "UPDATE templates SET key_hash = NULL, key_hint = NULL, updated_at = ? WHERE id = ?",
            (_now(), template_id),
        )
    return {"templateId": template_id, "hasReceiptKey": False}


def _insert_issue(
    conn: sqlite3.Connection,
    *,
    project: sqlite3.Row,
    title: str,
    body: str,
    status: str,
    priority: str | None,
    size: int | float | None,
    kind: str,
    leave_name: str,
    holiday_date: str | None,
    completion_text: str,
    completion_mode: str | None,
    timebox_start: str | None,
    template_id: str | None,
    event_id: str | None,
    created_by: str,
    checks: list[str],
) -> str:
    issue_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO issues"
        " (id, project_id, number, title, body, status, priority, size, kind, leave_name,"
        "  holiday_date, completion_text, completion_mode, timebox_start, template_id,"
        "  event_id, created_by, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            issue_id,
            project["id"],
            _next_number(conn, project["id"]),
            title,
            body,
            status,
            priority,
            size,
            kind,
            leave_name,
            holiday_date,
            completion_text,
            completion_mode,
            timebox_start,
            template_id,
            event_id,
            created_by,
            now,
            now,
        ),
    )
    for index, label in enumerate(checks):
        conn.execute(
            "INSERT INTO checks (id, issue_id, label, position) VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), issue_id, label, index),
        )
    return issue_id


def _current_box_start(conn: sqlite3.Connection, team_id: str, tenant_id: str) -> str:
    settings = _settings(conn, team_id, tenant_id)
    start, _end = box_bounds(today(), int(settings["week_start"]))
    return start.isoformat()


def arrive(
    template_id: str,
    *,
    access: Access | None = None,
    receipt_key: str | None = None,
    event_id: str | None = None,
    title: str | None = None,
) -> dict[str, Any]:
    event_id = (event_id or "").strip() or None
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM templates WHERE id = ? AND deleted_at IS NULL", (template_id,)
        ).fetchone()
        if not row:
            raise JigyoError(404, "定型が見つかりません")
        if access is not None:
            if not access.is_member(row["team_id"]):
                raise JigyoError(403, "このチームの定型は押せません")
            actor = access.user_id
        else:
            if not row["key_hash"] or not receipt_key or _hash_key(receipt_key) != row["key_hash"]:
                raise JigyoError(401, "受付鍵が正しくありません")
            actor = "receipt"
        if event_id:
            existing = conn.execute(
                "SELECT id FROM issues WHERE template_id = ? AND event_id = ? AND deleted_at IS NULL",
                (template_id, event_id),
            ).fetchone()
            if existing:
                return _issue_dict(conn, _issue(conn, existing["id"]))
        project = _project(conn, row["project_id"])
        box = _current_box_start(conn, row["team_id"], row["tenant_id"])
        name = (title or "").strip() or row["name"]
        try:
            issue_id = _insert_issue(
                conn,
                project=project,
                title=name,
                body="",
                status="todo",
                priority=row["priority"],
                size=row["size"],
                kind="work",
                leave_name="",
                holiday_date=None,
                completion_text=row["completion_text"],
                completion_mode=row["completion_mode"],
                timebox_start=box,
                template_id=template_id,
                event_id=event_id,
                created_by=actor,
                checks=json.loads(row["checks_json"] or "[]"),
            )
        except sqlite3.IntegrityError:
            if not event_id:
                raise
            existing = conn.execute(
                "SELECT id FROM issues WHERE template_id = ? AND event_id = ? AND deleted_at IS NULL",
                (template_id, event_id),
            ).fetchone()
            if not existing:
                raise
            return _issue_dict(conn, _issue(conn, existing["id"]))
        _hist(conn, row["team_id"], actor, "arrive", name, issue_id)
        return _issue_dict(conn, _issue(conn, issue_id))


def undo_issue(access: Access, issue_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = _issue(conn, issue_id)
        project = _project(conn, row["project_id"])
        if row["created_by"] != access.user_id and not _is_chief(conn, access, project["team_id"]):
            raise JigyoError(403, "取り消せるのは押した本人か所属長です")
        created = datetime.strptime(row["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        if (datetime.now(timezone.utc) - created).total_seconds() > UNDO_SECONDS:
            raise JigyoError(409, "押した直後だけ取り消せます")
        comments = conn.execute(
            "SELECT 1 FROM comments WHERE issue_id = ?", (issue_id,)
        ).fetchone()
        done_check = conn.execute(
            "SELECT 1 FROM checks WHERE issue_id = ? AND done = 1", (issue_id,)
        ).fetchone()
        if comments or done_check or row["status"] != "todo":
            raise JigyoError(409, "手を付けた課題は取り消せません")
        conn.execute(
            "UPDATE issues SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (_now(), _now(), issue_id),
        )
        _hist(conn, project["team_id"], access.user_id, "undo", row["title"], issue_id)
    return {"id": issue_id, "deleted": True}


def create_issue(access: Access, body: dict[str, Any]) -> dict[str, Any]:
    project_id = str(body.get("projectId") or "")
    kind = body.get("kind") or "work"
    if kind not in KINDS:
        raise JigyoError(400, "種別が正しくありません")
    with _lock, _connect() as conn:
        if project_id:
            project = _project(conn, project_id)
        else:
            if kind == "leave":
                raise JigyoError(400, "休みを入れる事業を指定してください")
            team_id = str(body.get("teamId") or "")
            if not team_id:
                raise JigyoError(400, "事業かチームを指定してください")
            access.team(team_id)
            project = _unfiled_project(conn, team_id, access.tenant_id)
        access.team(project["team_id"])
        chief = _is_chief(conn, access, project["team_id"])
        if kind == "leave":
            if not chief:
                raise JigyoError(403, "休みの課題は所属長が入れます")
            box = str(body.get("timeboxStart") or "")
            if not box:
                raise JigyoError(400, "期枠を指定してください")
            title = str(body.get("title") or "").strip() or (
                "有給" if body.get("leaveName") else "休み"
            )
            issue_id = _insert_issue(
                conn,
                project=project,
                title=title,
                body=str(body.get("body") or ""),
                status="todo",
                priority=None,
                size=_size(body.get("size"), required=True),
                kind="leave",
                leave_name=str(body.get("leaveName") or "").strip(),
                holiday_date=body.get("holidayDate"),
                completion_text="",
                completion_mode=None,
                timebox_start=box,
                template_id=None,
                event_id=None,
                created_by=access.user_id,
                checks=[],
            )
            _hist(conn, project["team_id"], access.user_id, "leave", title, issue_id)
            return _issue_dict(conn, _issue(conn, issue_id))
        if project["mode"] != "plan":
            raise JigyoError(400, "定常の課題は定型のボタンから起こします")
        if project["key"] == UNFILED_KEY:
            if (
                not access.is_member(project["team_id"])
                and not access.is_admin(project["team_id"])
                and not chief
            ):
                raise JigyoError(403, "このチームの課題は作れません")
        elif not _can_edit_project(conn, access, project):
            raise JigyoError(403, "この事業の課題は編集できません")
        title = str(body.get("title") or "").strip()
        if not title:
            raise JigyoError(400, "題名を入力してください")
        completion = str(body.get("completionText") or "").strip()
        completion_mode = body.get("completionMode") or None
        timebox = body.get("timeboxStart") or None
        priority = body.get("priority") or None
        if any([completion, completion_mode, timebox, priority, body.get("size")]):
            if not chief:
                raise JigyoError(403, "期枠、優先度、完了条件は所属長が決めます")
        if timebox and (not completion or completion_mode not in COMPLETION_MODES):
            raise JigyoError(400, "期枠に入れるには完了条件と決め方が必要です")
        checks = body.get("checks") or []
        labels = [str(x).strip() for x in checks if str(x).strip()] if isinstance(checks, list) else []
        if completion_mode == "objective" and timebox and not labels:
            raise JigyoError(400, "客観評価には確認項目が必要です")
        issue_id = _insert_issue(
            conn,
            project=project,
            title=title,
            body=str(body.get("body") or ""),
            status="todo",
            priority=_priority(priority, required=False),
            size=_size(body.get("size"), required=False) if chief else None,
            kind=kind,
            leave_name="",
            holiday_date=None,
            completion_text=completion if chief else "",
            completion_mode=completion_mode if chief else None,
            timebox_start=timebox if chief else None,
            template_id=None,
            event_id=None,
            created_by=access.user_id,
            checks=labels if chief else [],
        )
        if body.get("dueDate"):
            conn.execute(
                "UPDATE issues SET due_date = ? WHERE id = ?",
                (_parse_date(str(body["dueDate"])).isoformat(), issue_id),
            )
        _hist(conn, project["team_id"], access.user_id, "create", title, issue_id)
        return _issue_dict(conn, _issue(conn, issue_id))


def update_issue(access: Access, issue_id: str, body: dict[str, Any]) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = _issue(conn, issue_id)
        project = _project(conn, row["project_id"])
        if row["kind"] == "leave":
            raise JigyoError(400, "休みの課題は状態を変えません")
        chief = _is_chief(conn, access, project["team_id"])
        unfiled = project["key"] == UNFILED_KEY
        if not _can_edit_project(conn, access, project) and not (
            row["template_id"] and access.is_member(project["team_id"])
        ) and not (unfiled and access.is_member(project["team_id"])):
            raise JigyoError(403, "この課題は編集できません")
        fields: list[str] = []
        values: list[Any] = []
        if any(key in body for key in ("title", "body", "kind", "dueDate", "startDate", "projectId")):
            if not _can_edit_project(conn, access, project) and not access.is_member(project["team_id"]):
                raise JigyoError(403, "この課題は編集できません")
        if "title" in body:
            title = str(body.get("title") or "").strip()
            if not title:
                raise JigyoError(400, "名称を入力してください")
            fields.append("title = ?")
            values.append(title)
        if "body" in body:
            fields.append("body = ?")
            values.append(str(body.get("body") or ""))
        if "kind" in body and body["kind"] in KINDS and body["kind"] != "leave":
            fields.append("kind = ?")
            values.append(body["kind"])
        if "dueDate" in body:
            fields.append("due_date = ?")
            values.append(_iso(_parse_date(body.get("dueDate"))))
        if "startDate" in body:
            fields.append("start_date = ?")
            values.append(_iso(_parse_date(body.get("startDate"))))
        if "status" in body:
            status = body["status"]
            if status == "done":
                raise JigyoError(403, "完了は自己判断では決められません")
            if status not in WORK_STATUSES:
                raise JigyoError(400, "状態が正しくありません")
            fields.append("status = ?")
            values.append(status)
            _hist(conn, project["team_id"], access.user_id, "status", status, issue_id)
        if "projectId" in body:
            raw_project = str(body.get("projectId") or "")
            target = (
                _project(conn, raw_project)
                if raw_project
                else _unfiled_project(conn, project["team_id"], project["tenant_id"])
            )
            if target["team_id"] != project["team_id"]:
                raise JigyoError(400, "同じチームの事業に付けられます")
            if row["template_id"]:
                if target["mode"] != "routine":
                    raise JigyoError(400, "定常の課題は定常の事業に付けます")
            elif target["mode"] != "plan":
                raise JigyoError(400, "計画の課題は計画の事業に付けます")
            if target["id"] != row["project_id"]:
                fields.append("project_id = ?")
                values.append(target["id"])
                fields.append("number = ?")
                values.append(_next_number(conn, target["id"]))
                label = "事業未定" if target["key"] == UNFILED_KEY else f"{target['key']} {target['name']}"
                _hist(conn, project["team_id"], access.user_id, "project", label, issue_id)
        pending_checks: list[str] | None = None
        chief_fields = ("priority", "timeboxStart", "completionText", "completionMode", "size", "checks")
        if any(key in body for key in chief_fields):
            if not chief:
                raise JigyoError(403, "期枠、優先度、完了条件は所属長が決めます")
            if row["timebox_start"] and any(
                key in body for key in ("completionText", "completionMode", "checks")
            ):
                raise JigyoError(400, "完了条件は期枠未定のあいだだけ書けます")
            if "priority" in body:
                fields.append("priority = ?")
                values.append(_priority(body.get("priority"), required=False))
                _hist(conn, project["team_id"], access.user_id, "priority", str(body.get("priority")), issue_id)
            if "size" in body:
                fields.append("size = ?")
                values.append(_size(body.get("size"), required=False))
            if "completionText" in body:
                fields.append("completion_text = ?")
                values.append(str(body.get("completionText") or "").strip())
            if "completionMode" in body:
                mode = body.get("completionMode")
                if mode not in COMPLETION_MODES:
                    raise JigyoError(400, "完了の決め方が正しくありません")
                fields.append("completion_mode = ?")
                values.append(mode)
            if "checks" in body:
                raw_checks = body.get("checks") or []
                if not isinstance(raw_checks, list):
                    raise JigyoError(400, "確認項目の形式が正しくありません")
                pending_checks = [str(item).strip() for item in raw_checks if str(item).strip()]
            if "timeboxStart" in body:
                box = body.get("timeboxStart") or None
                text = str(body["completionText"]).strip() if "completionText" in body else row["completion_text"]
                mode = body.get("completionMode") if "completionMode" in body else row["completion_mode"]
                if box and (not text or mode not in COMPLETION_MODES):
                    raise JigyoError(400, "期枠に入れるには完了条件と決め方が必要です")
                if box and mode == "objective":
                    count = (
                        len(pending_checks)
                        if pending_checks is not None
                        else conn.execute(
                            "SELECT COUNT(*) AS n FROM checks WHERE issue_id = ?", (issue_id,)
                        ).fetchone()["n"]
                    )
                    if not count:
                        raise JigyoError(400, "客観評価には確認項目が必要です")
                fields.append("timebox_start = ?")
                values.append(box)
                _hist(conn, project["team_id"], access.user_id, "timebox", str(box), issue_id)
        if "complete" in body:
            if not chief or row["completion_mode"] != "chief":
                raise JigyoError(403, "この課題の完了は所属長の判定ではありません")
            if not row["completion_text"]:
                raise JigyoError(400, "完了条件がありません")
            fields.append("status = ?")
            values.append("done")
            fields.append("done_at = ?")
            values.append(_now())
            _hist(conn, project["team_id"], access.user_id, "done", "chief", issue_id)
        if not fields and pending_checks is None:
            return _issue_dict(conn, row)
        if fields:
            fields.append("updated_at = ?")
            values.append(_now())
            values.append(issue_id)
            conn.execute(f"UPDATE issues SET {', '.join(fields)} WHERE id = ?", values)
        if pending_checks is not None:
            conn.execute("DELETE FROM checks WHERE issue_id = ?", (issue_id,))
            for index, label in enumerate(pending_checks):
                conn.execute(
                    "INSERT INTO checks (id, issue_id, label, position) VALUES (?, ?, ?, ?)",
                    (str(uuid.uuid4()), issue_id, label, index),
                )
            if not fields:
                conn.execute(
                    "UPDATE issues SET updated_at = ? WHERE id = ?", (_now(), issue_id)
                )
        return _issue_dict(conn, _issue(conn, issue_id))


def set_check(access: Access, issue_id: str, check_id: str, done: bool) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = _issue(conn, issue_id)
        project = _project(conn, row["project_id"])
        if row["completion_mode"] != "objective":
            raise JigyoError(400, "確認項目は客観評価の課題にだけあります")
        if not _can_edit_project(conn, access, project) and not access.is_member(project["team_id"]):
            raise JigyoError(403, "確認項目を記録できません")
        check = conn.execute(
            "SELECT * FROM checks WHERE id = ? AND issue_id = ?", (check_id, issue_id)
        ).fetchone()
        if not check:
            raise JigyoError(404, "確認項目が見つかりません")
        conn.execute(
            "UPDATE checks SET done = ?, done_by = ?, done_at = ? WHERE id = ?",
            (1 if done else 0, access.user_id if done else None, _now() if done else None, check_id),
        )
        pending = conn.execute(
            "SELECT 1 FROM checks WHERE issue_id = ? AND done = 0", (issue_id,)
        ).fetchone()
        if done and not pending:
            conn.execute(
                "UPDATE issues SET status = 'done', done_at = ?, updated_at = ? WHERE id = ?",
                (_now(), _now(), issue_id),
            )
            _hist(conn, project["team_id"], access.user_id, "done", "objective", issue_id)
        elif not done and row["status"] == "done":
            conn.execute(
                "UPDATE issues SET status = 'doing', done_at = NULL, updated_at = ? WHERE id = ?",
                (_now(), issue_id),
            )
        return _issue_dict(conn, _issue(conn, issue_id))


def add_comment(access: Access, issue_id: str, body: str) -> dict[str, Any]:
    text = body.strip()
    if not text:
        raise JigyoError(400, "コメントを入力してください")
    with _lock, _connect() as conn:
        row = _issue(conn, issue_id)
        project = _project(conn, row["project_id"])
        if not access.can_read(project["team_id"]):
            raise JigyoError(403, "この課題は見られません")
        if not access.is_member(project["team_id"]) and not _can_edit_project(conn, access, project):
            raise JigyoError(403, "コメントはチームのメンバーが書けます")
        conn.execute(
            "INSERT INTO comments (id, issue_id, author, body, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), issue_id, access.user_id, text, _now()),
        )
        return _issue_dict(conn, row)


def get_issue(access: Access, issue_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        row = _issue(conn, issue_id)
        project = _project(conn, row["project_id"])
        access.team(project["team_id"])
        return _issue_dict(conn, row)


def _issue_dict(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    project = conn.execute(
        "SELECT key, mode, team_id, name FROM projects WHERE id = ?", (row["project_id"],)
    ).fetchone()
    unfiled = bool(project and project["key"] == UNFILED_KEY)
    checks = [
        {
            "id": c["id"],
            "label": c["label"],
            "done": bool(c["done"]),
            "doneBy": c["done_by"],
        }
        for c in conn.execute(
            "SELECT * FROM checks WHERE issue_id = ? ORDER BY position", (row["id"],)
        )
    ]
    comments = [
        {"id": c["id"], "author": c["author"], "body": c["body"], "createdAt": c["created_at"]}
        for c in conn.execute(
            "SELECT * FROM comments WHERE issue_id = ? ORDER BY created_at", (row["id"],)
        )
    ]
    return {
        "id": row["id"],
        "projectId": "" if unfiled else row["project_id"],
        "projectKey": "" if unfiled or not project else project["key"],
        "projectName": "" if unfiled or not project else project["name"],
        "projectMode": project["mode"] if project else "",
        "teamId": project["team_id"] if project else "",
        "number": row["number"],
        "title": row["title"],
        "body": row["body"],
        "status": row["status"],
        "priority": row["priority"],
        "size": row["size"],
        "kind": row["kind"],
        "leaveName": row["leave_name"],
        "holidayDate": row["holiday_date"],
        "completionText": row["completion_text"],
        "completionMode": row["completion_mode"],
        "timeboxStart": row["timebox_start"],
        "templateId": row["template_id"],
        "startDate": row["start_date"],
        "dueDate": row["due_date"],
        "createdBy": row["created_by"],
        "createdAt": row["created_at"],
        "doneAt": row["done_at"],
        "checks": checks,
        "comments": comments,
    }


def _ensure_holidays(
    conn: sqlite3.Connection,
    team_id: str,
    tenant_id: str,
    starts: list[date],
    headcount: int | None,
) -> None:
    """見える期枠の日本の祝日を、まだ無ければ休みとして入れる。"""
    project = None
    for start in starts:
        end = start + timedelta(days=13)
        for day, name in holidays_between(start, end):
            iso = day.isoformat()
            exists = conn.execute(
                "SELECT 1 FROM issues i JOIN projects p ON p.id = i.project_id"
                " WHERE p.team_id = ? AND i.holiday_date = ? AND i.deleted_at IS NULL",
                (team_id, iso),
            ).fetchone()
            if exists:
                continue
            if project is None:
                project = _unfiled_project(conn, team_id, tenant_id)
            _insert_issue(
                conn,
                project=project,
                title=name,
                body="",
                status="todo",
                priority=None,
                size=headcount,
                kind="leave",
                leave_name="",
                holiday_date=iso,
                completion_text="",
                completion_mode=None,
                timebox_start=start.isoformat(),
                template_id=None,
                event_id=None,
                created_by="calendar",
                checks=[],
            )


def apply_holidays(access: Access, team_id: str, timebox_start: str, project_id: str, size: Any = None) -> dict[str, Any]:
    del project_id, size
    start = _parse_date(timebox_start)
    if not start:
        raise JigyoError(400, "期枠を指定してください")
    with _lock, _connect() as conn:
        access.team(team_id)
        settings = _settings(conn, team_id, access.tenant_id)
        _ensure_holidays(conn, team_id, access.tenant_id, [start], _headcount(settings))
    return {"created": []}


def home(access: Access, team_id: str | None) -> dict[str, Any]:
    chosen = team_id or _default_team(access)
    if not chosen:
        return {
            "enabled": True,
            "userId": access.user_id,
            "tenantId": access.tenant_id,
            "teams": [],
            "teamId": None,
        }
    access.team(chosen)
    with _lock, _connect() as conn:
        settings = _settings(conn, chosen, access.tenant_id)
        week_start = int(settings["week_start"])
        chief = settings["chief_user_id"]
        current_start, current_end = box_bounds(today(), week_start)
        prev_start = current_start - timedelta(days=14)
        next_start = current_start + timedelta(days=14)
        projects = [
            _project_dict(conn, r)
            for r in conn.execute(
                "SELECT * FROM projects WHERE team_id = ? AND deleted_at IS NULL ORDER BY name",
                (chosen,),
            )
            if r["key"] != UNFILED_KEY
        ]
        templates = [
            _template_dict(r)
            for r in conn.execute(
                "SELECT * FROM templates WHERE team_id = ? AND deleted_at IS NULL ORDER BY name",
                (chosen,),
            )
        ]
        template_names = {
            r["id"]: r["name"]
            for r in conn.execute("SELECT id, name FROM templates WHERE team_id = ?", (chosen,))
        }
        headcount = _headcount(settings)
        _ensure_holidays(
            conn,
            chosen,
            access.tenant_id,
            [prev_start, current_start, next_start],
            headcount,
        )
        issues = [
            _issue_dict(conn, r)
            for r in conn.execute(
                "SELECT i.* FROM issues i JOIN projects p ON p.id = i.project_id"
                " WHERE p.team_id = ? AND i.deleted_at IS NULL",
                (chosen,),
            )
        ]
    for issue in issues:
        if issue.get("holidayDate"):
            issue["size"] = headcount
        if issue.get("templateId"):
            issue["templateName"] = template_names.get(issue["templateId"]) or ""
    boxes = {
        "previous": _box_payload(prev_start, issues),
        "current": _box_payload(current_start, issues),
        "next": _box_payload(next_start, issues),
    }
    prev_routine = _routine_size(boxes["previous"]["issues"])
    pace = sum(
        i["size"] or 0
        for i in boxes["previous"]["issues"]
        if i["status"] == "done" and i["kind"] != "leave"
    )
    next_forecast = boxes["next"]["size"] + prev_routine
    return {
        "enabled": True,
        "userId": access.user_id,
        "tenantId": access.tenant_id,
        "teamId": chosen,
        "isAdmin": access.is_admin(chosen),
        "isMember": access.is_member(chosen),
        "isChief": chief == access.user_id,
        "chiefUserId": chief,
        "headcount": headcount,
        "weekStart": week_start,
        "teams": [
            {
                "teamId": tid,
                "teamName": row.get("teamName") or tid,
                "admin": bool(row.get("admin")),
                "member": bool(row.get("member")) and not bool(row.get("inherited")),
            }
            for tid, row in access.teams.items()
        ],
        "projects": projects,
        "templates": templates,
        "boxes": {
            "previous": {**boxes["previous"], "start": prev_start.isoformat(), "end": (prev_start + timedelta(days=13)).isoformat()},
            "current": {**boxes["current"], "start": current_start.isoformat(), "end": current_end.isoformat()},
            "next": {
                **boxes["next"],
                "start": next_start.isoformat(),
                "end": (next_start + timedelta(days=13)).isoformat(),
                "forecastSize": next_forecast,
                "routineReserve": prev_routine,
            },
        },
        "pace": pace,
        "planIssues": [
            i for i in issues if i["projectMode"] == "plan" and i["kind"] != "leave"
        ],
        "leaveIssues": [i for i in issues if i["kind"] == "leave"],
        "routine": _routine_groups(issues, template_names),
    }


def _default_team(access: Access) -> str | None:
    members = [tid for tid, row in access.teams.items() if row.get("member") and not row.get("inherited")]
    if members:
        return members[0]
    return next(iter(access.teams), None)


def _box_payload(start: date, issues: list[dict[str, Any]]) -> dict[str, Any]:
    iso = start.isoformat()
    inside = [i for i in issues if i["timeboxStart"] == iso]
    return {
        "issues": inside,
        "size": sum(i["size"] or 0 for i in inside),
    }


def _routine_size(issues: list[dict[str, Any]]) -> int:
    return sum(i["size"] or 0 for i in issues if i["templateId"])


def _routine_groups(issues: list[dict[str, Any]], names: dict[str, str] | None = None) -> list[dict[str, Any]]:
    names = names or {}
    groups: dict[str, dict[str, Any]] = {}
    for issue in issues:
        if not issue["templateId"]:
            continue
        group = groups.setdefault(
            issue["templateId"],
            {
                "templateId": issue["templateId"],
                "name": names.get(issue["templateId"]) or issue["title"],
                "count": 0,
                "openCount": 0,
                "size": 0,
                "issues": [],
            },
        )
        group["count"] += 1
        group["size"] += issue["size"] or 0
        if issue["status"] != "done":
            group["openCount"] += 1
        group["issues"].append(issue)
    return list(groups.values())
