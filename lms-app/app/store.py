"""LMS の台帳。ファイルのバイト列はストレージ、ここは目次と受講記録。"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import convert, storage

DB_PATH = os.environ.get("LMS_DB_PATH", "/data/lms.db")
UPLOAD_DIR = os.environ.get("LMS_UPLOAD_DIR", "/data/lms-uploads")
MAX_UPLOAD_BYTES = int(os.environ.get("LMS_MAX_UPLOAD_BYTES", str(2 * 1024 * 1024 * 1024)))
MAX_PART_BYTES = int(os.environ.get("LMS_MAX_PART_BYTES", str(8 * 1024 * 1024)))
SUSPEND_LIMIT = 4096

_lock = threading.Lock()
_upload_progress: dict[str, str] = {}


class LmsError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class TeamInfo:
    team_id: str
    team_name: str
    member_ids: tuple[str, ...]


@dataclass
class Access:
    user_id: str
    user_name: str
    tenant_id: str
    member: bool
    teams: dict[str, TeamInfo] = field(default_factory=dict)
    users: dict[str, str] = field(default_factory=dict)


def parse_access(payload: dict[str, Any]) -> Access:
    user_id = str(payload.get("userId") or "").strip()
    tenant_id = str(payload.get("tenantId") or "").strip()
    if not user_id or not tenant_id:
        raise LmsError("認証が必要です", 401)
    teams: dict[str, TeamInfo] = {}
    for raw in payload.get("teams") or []:
        team_id = str(raw.get("teamId") or "").strip()
        if not team_id:
            continue
        members = tuple(
            str(x).strip() for x in (raw.get("memberIds") or []) if str(x).strip()
        )
        teams[team_id] = TeamInfo(team_id, str(raw.get("teamName") or team_id), members)
    users = {
        str(raw.get("userId") or "").strip(): str(raw.get("userName") or raw.get("userId") or "").strip()
        for raw in (payload.get("users") or [])
        if str(raw.get("userId") or "").strip()
    }
    name = str(payload.get("userName") or users.get(user_id) or user_id)
    users.setdefault(user_id, name)
    return Access(
        user_id=user_id,
        user_name=name,
        tenant_id=tenant_id,
        member=bool(payload.get("member")),
        teams=teams,
        users=users,
    )


def init_db() -> None:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS materials (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                title TEXT NOT NULL,
                kind TEXT NOT NULL,
                original_key TEXT NOT NULL,
                content_type TEXT NOT NULL,
                slide_keys TEXT NOT NULL,
                hidden_at TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                draft_json TEXT NOT NULL,
                current_version_id TEXT,
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS course_roles (
                course_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                PRIMARY KEY (course_id, user_id, role)
            );
            CREATE TABLE IF NOT EXISTS course_versions (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                number INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                published_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assignments (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL,
                tenant_id TEXT NOT NULL,
                assignee_type TEXT NOT NULL,
                assignee_id TEXT NOT NULL,
                required INTEGER NOT NULL,
                due_at TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (course_id, assignee_type, assignee_id)
            );
            CREATE TABLE IF NOT EXISTS enrollments (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                course_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                user_name TEXT NOT NULL,
                version_id TEXT NOT NULL,
                started_at TEXT NOT NULL,
                UNIQUE (course_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS lesson_records (
                enrollment_id TEXT NOT NULL,
                lesson_id TEXT NOT NULL,
                lesson_status TEXT NOT NULL,
                score_raw REAL,
                lesson_location TEXT NOT NULL DEFAULT '',
                session_seconds INTEGER NOT NULL DEFAULT 0,
                total_seconds INTEGER NOT NULL DEFAULT 0,
                suspend_data TEXT NOT NULL DEFAULT '',
                graded_by TEXT,
                graded_at TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (enrollment_id, lesson_id)
            );
            CREATE TABLE IF NOT EXISTS upload_sessions (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                kind TEXT NOT NULL,
                content_type TEXT NOT NULL,
                size INTEGER NOT NULL,
                next_part INTEGER NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS material_transcripts (
                material_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                status TEXT NOT NULL,
                notice TEXT NOT NULL,
                error TEXT NOT NULL,
                segments_json TEXT NOT NULL,
                job_token TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )


def home(access: Access) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        editable = _role_course_ids(conn, access, "editor")
        certifiable = _role_course_ids(conn, access, "certifier")
        return {
            "userId": access.user_id,
            "userName": access.user_name,
            "tenantId": access.tenant_id,
            "canUseLibrary": True,
            "teams": [
                {"teamId": t.team_id, "teamName": t.team_name}
                for t in access.teams.values()
            ],
            "users": [
                {"userId": uid, "userName": name} for uid, name in sorted(access.users.items())
            ],
            "learning": _learning_rows(conn, access),
            "editableCourses": _course_summaries(conn, access, editable),
            "certifiableCourses": _course_summaries(conn, access, certifiable),
        }


def list_materials(access: Access, *, trashed: bool = False) -> dict[str, Any]:
    _require_member(access)
    hidden = "IS NOT NULL" if trashed else "IS NULL"
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT m.*, t.status AS transcript_status FROM materials m "
            "LEFT JOIN material_transcripts t ON t.material_id = m.id "
            f"WHERE m.tenant_id = ? AND m.hidden_at {hidden} ORDER BY m.created_at DESC",
            (access.tenant_id,),
        ).fetchall()
    return {"materials": [_material_row(r) for r in rows]}


def start_upload(access: Access, body: dict[str, Any]) -> dict[str, Any]:
    _require_member(access)
    title = _title(body.get("title"))
    filename = str(body.get("filename") or "").strip()
    kind = str(body.get("kind") or "")
    if kind not in ("video", "slides"):
        raise LmsError("種別は動画かテキストです")
    ext = Path(filename).suffix.lower()
    if kind == "video" and ext not in (".mp4", ".webm"):
        raise LmsError("動画は mp4 または webm です")
    if kind == "slides" and ext != ".pdf":
        raise LmsError("テキストは PDF です")
    size = int(body.get("size") or 0)
    if size <= 0 or size > MAX_UPLOAD_BYTES:
        raise LmsError("ファイルサイズが範囲外です")
    content_type = str(body.get("contentType") or "application/octet-stream")
    session_id = _new_id()
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO upload_sessions"
            " (id, tenant_id, user_id, title, filename, kind, content_type, size, next_part, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (session_id, access.tenant_id, access.user_id, title, filename, kind, content_type, size, now),
        )
    Path(UPLOAD_DIR, session_id).mkdir(parents=True, exist_ok=True)
    return {"id": session_id}


def append_part(access: Access, session_id: str, index: int, data: bytes) -> dict[str, Any]:
    _require_member(access)
    if len(data) > MAX_PART_BYTES:
        raise LmsError("分割が大きすぎます")
    with _lock, _connect() as conn:
        row = _session_row(conn, access, session_id)
        if index != int(row["next_part"]):
            raise LmsError("分割の順番が違います", 409)
        received = _session_bytes(session_id)
        if received + len(data) > int(row["size"]):
            raise LmsError("宣言したサイズを超えています")
        part = Path(UPLOAD_DIR, session_id, f"{index:06d}")
        part.write_bytes(data)
        conn.execute(
            "UPDATE upload_sessions SET next_part = ? WHERE id = ?",
            (index + 1, session_id),
        )
    return {"id": session_id, "nextPart": index + 1}


def upload_progress(access: Access, session_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        _session_row(conn, access, session_id)
        text = _upload_progress.get(session_id, "")
    return {"id": session_id, "progress": text}


def _note_upload(session_id: str, text: str) -> None:
    with _lock:
        _upload_progress[session_id] = text


def complete_upload(access: Access, session_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        row = _session_row(conn, access, session_id)
    data = _read_session(session_id)
    if len(data) != int(row["size"]):
        raise LmsError("届いたサイズが宣言と違います")
    kind = row["kind"]
    material_id = _new_id()
    original_key = f"{storage.PREFIX}/{access.tenant_id}/{material_id}/original{Path(row['filename']).suffix.lower()}"
    slide_keys: list[str] = []
    try:
        try:
            _note_upload(session_id, "ファイルを保存しています")
            storage.get_storage().put_bytes(original_key, data, row["content_type"])
            if kind == "slides":
                pngs = convert.pdf_to_pngs(data, on_status=lambda text: _note_upload(session_id, text))
                for i, png in enumerate(pngs, start=1):
                    _note_upload(session_id, f"ページ画像を保存しています {i}/{len(pngs)}")
                    key = f"{storage.PREFIX}/{access.tenant_id}/{material_id}/slide-{i}.png"
                    storage.get_storage().put_bytes(key, png, "image/png")
                    slide_keys.append(key)
            _note_upload(session_id, "教材庫に登録しています")
        except storage.StorageError as e:
            raise LmsError(e.message, e.status) from e
        except convert.ConvertError as e:
            raise LmsError(e.message, 422) from e
        now = _now()
        with _lock, _connect() as conn:
            conn.execute(
                "INSERT INTO materials"
                " (id, tenant_id, title, kind, original_key, content_type, slide_keys, hidden_at, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (
                    material_id,
                    access.tenant_id,
                    row["title"],
                    kind,
                    original_key,
                    row["content_type"],
                    json.dumps(slide_keys),
                    access.user_id,
                    now,
                ),
            )
            conn.execute("DELETE FROM upload_sessions WHERE id = ?", (session_id,))
            saved = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
        _clear_session(session_id)
        return _material_row(saved)
    finally:
        with _lock:
            _upload_progress.pop(session_id, None)


def rename_material(access: Access, material_id: str, title: str) -> dict[str, Any]:
    _require_member(access)
    title = _title(title)
    with _lock, _connect() as conn:
        row = _material_for_tenant(conn, access, material_id)
        conn.execute("UPDATE materials SET title = ? WHERE id = ?", (title, row["id"]))
        saved = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
    return _material_row(saved)


def hide_material(access: Access, material_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        row = _material_for_tenant(conn, access, material_id)
        conn.execute(
            "UPDATE materials SET hidden_at = ? WHERE id = ?",
            (_now(), row["id"]),
        )
    return {"id": material_id, "hidden": True}


def restore_material(access: Access, material_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        row = _material_for_tenant(conn, access, material_id)
        conn.execute("UPDATE materials SET hidden_at = NULL WHERE id = ?", (row["id"],))
        saved = conn.execute("SELECT * FROM materials WHERE id = ?", (row["id"],)).fetchone()
    return _material_row(saved)


def delete_material(access: Access, material_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        row = _material_for_tenant(conn, access, material_id)
        used = _courses_using_material(conn, access.tenant_id, row)
        if used:
            shown = "、".join(f"「{title}」" for title in used[:3])
            extra = f"ほか {len(used) - 3} 件" if len(used) > 3 else ""
            raise LmsError(
                f"{shown}{extra}で使っているので削除できません。コースから外してからもう一度試してください。"
            )
        keys = [str(row["original_key"])]
        keys.extend(str(key) for key in json.loads(row["slide_keys"] or "[]"))
        for key in keys:
            if key:
                storage.get_storage().delete(key)
        conn.execute(
            "DELETE FROM materials WHERE id = ? AND tenant_id = ?",
            (row["id"], access.tenant_id),
        )
        conn.execute(
            "DELETE FROM material_transcripts WHERE material_id = ? AND tenant_id = ?",
            (row["id"], access.tenant_id),
        )
    return {"ok": True}


def get_transcript(access: Access, material_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        material = _material_for_tenant(conn, access, material_id)
        transcript = _transcript_row(conn, access.tenant_id, material_id)
        return _transcript_payload(material, transcript)


def start_transcript(access: Access, material_id: str, *, redo: bool) -> dict[str, Any]:
    from app import transcript as jobs

    _require_member(access)
    claimed = False
    try:
        with _lock, _connect() as conn:
            material = _material_for_tenant(conn, access, material_id)
            current = _transcript_row(conn, access.tenant_id, material_id)
            if current and current["status"] == "running" and jobs.busy(material_id):
                if redo:
                    raise LmsError("文字起こしの途中です")
                return _transcript_payload(material, current)
            if current and current["status"] in ("draft", "confirmed") and not redo:
                raise LmsError("すでにある本文を置き換えるときは、やり直すを選んでください")
            if not jobs.claim(material_id):
                if redo:
                    raise LmsError("文字起こしの途中です")
                return _transcript_payload(material, current)
            claimed = True
            token = _new_id()
            now = _now()
            conn.execute(
                "INSERT INTO material_transcripts"
                " (material_id, tenant_id, status, notice, error, segments_json, job_token, updated_at)"
                " VALUES (?, ?, 'running', '', '', '[]', ?, ?)"
                " ON CONFLICT(material_id) DO UPDATE SET"
                " status = 'running', notice = '', error = '', segments_json = '[]',"
                " job_token = excluded.job_token, updated_at = excluded.updated_at",
                (material_id, access.tenant_id, token, now),
            )
        jobs.launch(access.tenant_id, material_id, token)
        claimed = False
    finally:
        if claimed:
            jobs.release(material_id)
    return get_transcript(access, material_id)


def save_transcript(access: Access, material_id: str, body: dict[str, Any]) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        material = _material_for_tenant(conn, access, material_id)
        current = _transcript_row(conn, access.tenant_id, material_id)
        if not current:
            raise LmsError("先に文字起こしを作ってください")
        if current["status"] == "running":
            raise LmsError("文字起こしの途中です")
        if current["status"] == "failed":
            raise LmsError("文字起こしをやり直してください")
        segments = _clean_segments(str(material["kind"]), body.get("segments"))
        now = _now()
        conn.execute(
            "UPDATE material_transcripts SET status = 'draft', segments_json = ?, updated_at = ?"
            " WHERE material_id = ? AND tenant_id = ?",
            (json.dumps(segments, ensure_ascii=False), now, material_id, access.tenant_id),
        )
        saved = _transcript_row(conn, access.tenant_id, material_id)
        return _transcript_payload(material, saved)


def confirm_transcript(access: Access, material_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        material = _material_for_tenant(conn, access, material_id)
        current = _transcript_row(conn, access.tenant_id, material_id)
        if not current or current["status"] == "running":
            raise LmsError("文字起こしの途中です" if current else "先に文字起こしを作ってください")
        if current["status"] == "failed":
            raise LmsError("文字起こしをやり直してください")
        segments = json.loads(current["segments_json"] or "[]")
        if not any(str(item.get("text") or "").strip() for item in segments):
            raise LmsError("本文がありません")
        now = _now()
        conn.execute(
            "UPDATE material_transcripts SET status = 'confirmed', notice = '', error = '', updated_at = ?"
            " WHERE material_id = ? AND tenant_id = ?",
            (now, material_id, access.tenant_id),
        )
        saved = _transcript_row(conn, access.tenant_id, material_id)
        return _transcript_payload(material, saved)


def load_material_for_job(tenant_id: str, material_id: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT * FROM materials WHERE id = ? AND tenant_id = ?",
            (material_id, tenant_id),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row["id"],
            "kind": row["kind"],
            "original_key": row["original_key"],
            "slide_keys": json.loads(row["slide_keys"] or "[]"),
            "slide_count": len(json.loads(row["slide_keys"] or "[]")),
        }


def note_transcript(tenant_id: str, material_id: str, token: str, notice: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE material_transcripts SET notice = ? WHERE material_id = ? AND tenant_id = ?"
            " AND status = 'running' AND job_token = ?",
            (notice, material_id, tenant_id, token),
        )


def finish_transcript(
    tenant_id: str,
    material_id: str,
    token: str,
    segments: list[dict[str, Any]],
    notice: str,
) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE material_transcripts SET status = 'draft', notice = ?, error = '',"
            " segments_json = ?, updated_at = ?"
            " WHERE material_id = ? AND tenant_id = ? AND status = 'running' AND job_token = ?",
            (
                notice,
                json.dumps(segments, ensure_ascii=False),
                _now(),
                material_id,
                tenant_id,
                token,
            ),
        )


def fail_transcript(tenant_id: str, material_id: str, token: str, message: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE material_transcripts SET status = 'failed', error = ?, segments_json = '[]', updated_at = ?"
            " WHERE material_id = ? AND tenant_id = ? AND status = 'running' AND job_token = ?",
            (message, _now(), material_id, tenant_id, token),
        )


def create_course(access: Access, title: str) -> dict[str, Any]:
    _require_member(access)
    title = _title(title)
    course_id = _new_id()
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO courses"
            " (id, tenant_id, title, status, draft_json, current_version_id, created_by, created_at, updated_at)"
            " VALUES (?, ?, ?, 'draft', ?, NULL, ?, ?, ?)",
            (course_id, access.tenant_id, title, json.dumps({"chapters": []}), access.user_id, now, now),
        )
        conn.execute(
            "INSERT INTO course_roles (course_id, user_id, role) VALUES (?, ?, 'editor')",
            (course_id, access.user_id),
        )
    return get_course(access, course_id)


def get_course(access: Access, course_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        return _course_detail(conn, access, course_id)


def save_draft(access: Access, course_id: str, body: dict[str, Any]) -> dict[str, Any]:
    chapters = _normalize_chapters(body.get("chapters"))
    title = _title(body.get("title")) if body.get("title") is not None else None
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        course = _course_row(conn, access, course_id)
        if title is None:
            title = course["title"]
        conn.execute(
            "UPDATE courses SET title = ?, draft_json = ?, updated_at = ? WHERE id = ?",
            (title, json.dumps({"chapters": chapters}, ensure_ascii=False), _now(), course_id),
        )
        return _course_detail(conn, access, course_id)


def publish_course(access: Access, course_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        course = _course_row(conn, access, course_id)
        draft = json.loads(course["draft_json"])
        snapshot = _snapshot_from_draft(conn, access, course["title"], draft.get("chapters") or [])
        number = conn.execute(
            "SELECT COALESCE(MAX(number), 0) + 1 FROM course_versions WHERE course_id = ?",
            (course_id,),
        ).fetchone()[0]
        version_id = _new_id()
        now = _now()
        conn.execute(
            "INSERT INTO course_versions (id, course_id, tenant_id, number, snapshot_json, published_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                version_id,
                course_id,
                access.tenant_id,
                number,
                json.dumps(snapshot, ensure_ascii=False),
                now,
            ),
        )
        conn.execute(
            "UPDATE courses SET status = 'published', current_version_id = ?, updated_at = ? WHERE id = ?",
            (version_id, now, course_id),
        )
        return _course_detail(conn, access, course_id)


def set_role(access: Access, course_id: str, user_id: str, role: str) -> dict[str, Any]:
    user_id = user_id.strip()
    if role not in ("editor", "certifier"):
        raise LmsError("役割は編集者か認定者です")
    if not user_id:
        raise LmsError("利用者を指定してください")
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        conn.execute(
            "INSERT OR IGNORE INTO course_roles (course_id, user_id, role) VALUES (?, ?, ?)",
            (course_id, user_id, role),
        )
        return _course_detail(conn, access, course_id)


def remove_role(access: Access, course_id: str, user_id: str, role: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        if role == "editor":
            count = conn.execute(
                "SELECT COUNT(*) FROM course_roles WHERE course_id = ? AND role = 'editor'",
                (course_id,),
            ).fetchone()[0]
            if count <= 1:
                raise LmsError("最後の編集者は外せません")
        conn.execute(
            "DELETE FROM course_roles WHERE course_id = ? AND user_id = ? AND role = ?",
            (course_id, user_id, role),
        )
        return _course_detail(conn, access, course_id)


def delete_course(access: Access, course_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        enrollment_ids = [
            row["id"]
            for row in conn.execute("SELECT id FROM enrollments WHERE course_id = ?", (course_id,))
        ]
        if enrollment_ids:
            marks = ",".join("?" * len(enrollment_ids))
            conn.execute(
                f"DELETE FROM lesson_records WHERE enrollment_id IN ({marks})",
                enrollment_ids,
            )
        conn.execute("DELETE FROM enrollments WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM assignments WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM course_versions WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM course_roles WHERE course_id = ?", (course_id,))
        conn.execute("DELETE FROM courses WHERE id = ?", (course_id,))
    return {"ok": True}


def set_assignment(access: Access, course_id: str, body: dict[str, Any]) -> dict[str, Any]:
    assignee_type = str(body.get("assigneeType") or "")
    assignee_id = str(body.get("assigneeId") or "").strip()
    if assignee_type not in ("user", "team") or not assignee_id:
        raise LmsError("割当先を指定してください")
    due_at = _due(body.get("dueAt"))
    required = 1 if body.get("required", True) else 0
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        _course_row(conn, access, course_id)
        existing = conn.execute(
            "SELECT id FROM assignments WHERE course_id = ? AND assignee_type = ? AND assignee_id = ?",
            (course_id, assignee_type, assignee_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE assignments SET required = ?, due_at = ? WHERE id = ?",
                (required, due_at, existing["id"]),
            )
        else:
            conn.execute(
                "INSERT INTO assignments"
                " (id, course_id, tenant_id, assignee_type, assignee_id, required, due_at, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (_new_id(), course_id, access.tenant_id, assignee_type, assignee_id, required, due_at, _now()),
            )
        return _course_detail(conn, access, course_id)


def remove_assignment(access: Access, course_id: str, assignment_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        conn.execute(
            "DELETE FROM assignments WHERE id = ? AND course_id = ? AND tenant_id = ?",
            (assignment_id, course_id, access.tenant_id),
        )
        return _course_detail(conn, access, course_id)


def preview_course(access: Access, course_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _require_role(conn, access, course_id, "editor")
        course = _course_row(conn, access, course_id)
        draft = json.loads(course["draft_json"])
        snapshot = _preview_snapshot(conn, access, course["title"], draft.get("chapters") or [])
    return {"preview": True, "courseId": course_id, "snapshot": _with_playback(snapshot, reveal=True)}


def learning(access: Access) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        return {"learning": _learning_rows(conn, access)}


def start_enrollment(access: Access, course_id: str) -> dict[str, Any]:
    _require_member(access)
    with _lock, _connect() as conn:
        course = _course_row(conn, access, course_id)
        if course["status"] != "published" or not course["current_version_id"]:
            raise LmsError("公開前のコースは受講できません")
        if not _is_assigned(conn, access, course_id, access.user_id):
            raise LmsError("このコースは割り当てられていません", 403)
        existing = conn.execute(
            "SELECT * FROM enrollments WHERE course_id = ? AND user_id = ?",
            (course_id, access.user_id),
        ).fetchone()
        if existing:
            enrollment_id = existing["id"]
        else:
            enrollment_id = _new_id()
            conn.execute(
                "INSERT INTO enrollments"
                " (id, tenant_id, course_id, user_id, user_name, version_id, started_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    enrollment_id,
                    access.tenant_id,
                    course_id,
                    access.user_id,
                    access.user_name,
                    course["current_version_id"],
                    _now(),
                ),
            )
        return _enrollment_payload(conn, access, enrollment_id)


def get_enrollment(access: Access, enrollment_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _enrollment_visible(conn, access, enrollment_id)
        return _enrollment_payload(conn, access, enrollment_id)


def record_progress(access: Access, enrollment_id: str, lesson_id: str, body: dict[str, Any]) -> dict[str, Any]:
    suspend = _suspend(body.get("suspend_data")) if "suspend_data" in body else None
    with _lock, _connect() as conn:
        enrollment = _own_enrollment(conn, access, enrollment_id)
        lesson = _lesson_in_enrollment(conn, enrollment, lesson_id)
        if lesson["kind"] not in ("video", "slides"):
            raise LmsError("このレッスンは視聴記録の対象ではありません")
        previous = _record_row(conn, enrollment_id, lesson_id)
        sitting = int(body.get("sessionSeconds") or 0)
        sitting = max(0, min(sitting, 24 * 3600))
        prev_session = int(previous["session_seconds"]) if previous else 0
        delta = sitting - prev_session if sitting >= prev_session else sitting
        delta = max(0, min(delta, 120))
        total = (int(previous["total_seconds"]) if previous else 0) + delta
        location = str(body.get("lesson_location") or "")
        if lesson["kind"] == "video":
            try:
                loc = float(location or 0)
                duration = float(body.get("duration") or 0)
            except ValueError as e:
                raise LmsError("再生位置が不正です") from e
            done = bool(body.get("ended")) or (duration > 0 and loc >= duration - 1.0)
            location = f"{loc:.3f}"
        else:
            try:
                page = int(float(location or 0))
                count = int(body.get("pageCount") or len(lesson.get("slideKeys") or []))
            except ValueError as e:
                raise LmsError("ページ位置が不正です") from e
            done = count > 0 and page >= count
            location = str(page)
        status = "completed" if done else "incomplete"
        if previous and previous["lesson_status"] in ("completed", "passed"):
            status = previous["lesson_status"]
        _upsert_record(
            conn,
            enrollment_id,
            lesson_id,
            status=status,
            score_raw=previous["score_raw"] if previous else None,
            location=location,
            session_seconds=sitting,
            total_seconds=total,
            suspend_data=suspend if suspend is not None else (previous["suspend_data"] if previous else ""),
            graded_by=previous["graded_by"] if previous else None,
            graded_at=previous["graded_at"] if previous else None,
        )
        return _enrollment_payload(conn, access, enrollment_id)


def submit_quiz(access: Access, enrollment_id: str, lesson_id: str, answers: list[Any]) -> dict[str, Any]:
    with _lock, _connect() as conn:
        enrollment = _own_enrollment(conn, access, enrollment_id)
        lesson = _lesson_in_enrollment(conn, enrollment, lesson_id)
        if lesson["kind"] != "quiz":
            raise LmsError("確認クイズではありません")
        questions = lesson.get("questions") or []
        if len(answers) != len(questions):
            raise LmsError("回答の数が設問と違います")
        correct = 0
        for question, answer in zip(questions, answers):
            try:
                picked = int(answer)
            except (TypeError, ValueError) as e:
                raise LmsError("回答が不正です") from e
            if picked == int(question["correctIndex"]):
                correct += 1
        score = round(100 * correct / len(questions), 2) if questions else 0
        mastery = float(lesson.get("masteryScore") or 0)
        status = "passed" if score >= mastery else "failed"
        previous = _record_row(conn, enrollment_id, lesson_id)
        _upsert_record(
            conn,
            enrollment_id,
            lesson_id,
            status=status,
            score_raw=score,
            location="",
            session_seconds=int(previous["session_seconds"]) if previous else 0,
            total_seconds=int(previous["total_seconds"]) if previous else 0,
            suspend_data=json.dumps({"answers": answers}, ensure_ascii=False)[:SUSPEND_LIMIT],
            graded_by=None,
            graded_at=None,
        )
        return _enrollment_payload(conn, access, enrollment_id)


def grade_practical(
    access: Access,
    enrollment_id: str,
    lesson_id: str,
    status: str,
    score_raw: Any,
) -> dict[str, Any]:
    if status not in ("passed", "failed"):
        raise LmsError("合否は passed か failed です")
    score = None if score_raw is None or score_raw == "" else float(score_raw)
    with _lock, _connect() as conn:
        enrollment = conn.execute(
            "SELECT * FROM enrollments WHERE id = ? AND tenant_id = ?",
            (enrollment_id, access.tenant_id),
        ).fetchone()
        if not enrollment:
            raise LmsError("受講が見つかりません", 404)
        _require_role(conn, access, enrollment["course_id"], "certifier")
        lesson = _lesson_in_enrollment(conn, enrollment, lesson_id)
        if lesson["kind"] != "practical":
            raise LmsError("実技項目ではありません")
        previous = _record_row(conn, enrollment_id, lesson_id)
        now = _now()
        _upsert_record(
            conn,
            enrollment_id,
            lesson_id,
            status=status,
            score_raw=score,
            location=lesson.get("practicalText") or "",
            session_seconds=int(previous["session_seconds"]) if previous else 0,
            total_seconds=int(previous["total_seconds"]) if previous else 0,
            suspend_data=previous["suspend_data"] if previous else "",
            graded_by=access.user_id,
            graded_at=now,
        )
        return _enrollment_payload(conn, access, enrollment_id, reveal=True)


def progress(access: Access, course_id: str) -> dict[str, Any]:
    with _lock, _connect() as conn:
        _require_progress_reader(conn, access, course_id)
        course = _course_row(conn, access, course_id)
        rows = _progress_rows(conn, access, course)
    return {"courseId": course_id, "title": course["title"], "rows": rows}


def progress_csv(access: Access, course_id: str) -> str:
    payload = progress(access, course_id)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["利用者", "状態", "必須", "期限", "期限超過", "教材完了", "実技未認定", "開始"])
    labels = {"not_started": "未着手", "in_progress": "受講中", "completed": "修了"}
    for row in payload["rows"]:
        writer.writerow(
            [
                row["userName"],
                labels.get(row["state"], row["state"]),
                "必須" if row["required"] else "",
                row["dueAt"] or "",
                "超過" if row["overdue"] else "",
                "完了" if row["materialDone"] else "",
                "未認定" if row["practicalPending"] else "",
                row["startedAt"] or "",
            ]
        )
    return buf.getvalue()


def _progress_rows(conn: sqlite3.Connection, access: Access, course: sqlite3.Row) -> list[dict[str, Any]]:
    assignments = _assignments(conn, course["id"])
    enrollments = conn.execute(
        "SELECT * FROM enrollments WHERE course_id = ?",
        (course["id"],),
    ).fetchall()
    by_user = {row["user_id"]: row for row in enrollments}
    user_ids = set(by_user)
    for assignment in assignments:
        user_ids.update(_assignee_users(access, assignment))
    rows = []
    for user_id in sorted(user_ids):
        enrollment = by_user.get(user_id)
        applicable = [
            a for a in assignments if user_id in _assignee_users(access, a) or (
                enrollment and a["assignee_type"] == "user" and a["assignee_id"] == user_id
            )
        ]
        due_values = [a["due_at"] for a in applicable if a["due_at"]]
        due_at = min(due_values) if due_values else None
        required = any(int(a["required"]) for a in applicable) if applicable else False
        name = access.users.get(user_id) or (enrollment["user_name"] if enrollment else user_id)
        if not enrollment:
            rows.append(
                {
                    "userId": user_id,
                    "userName": name,
                    "enrollmentId": None,
                    "state": "not_started",
                    "overdue": bool(due_at and due_at < _today()),
                    "dueAt": due_at,
                    "required": required,
                    "materialDone": False,
                    "practicalPending": False,
                    "startedAt": None,
                    "practicals": [],
                }
            )
            continue
        version = conn.execute(
            "SELECT * FROM course_versions WHERE id = ?",
            (enrollment["version_id"],),
        ).fetchone()
        snapshot = json.loads(version["snapshot_json"])
        records = {
            r["lesson_id"]: r
            for r in conn.execute(
                "SELECT * FROM lesson_records WHERE enrollment_id = ?",
                (enrollment["id"],),
            ).fetchall()
        }
        lessons = _flat_lessons(snapshot)
        required_lessons = [lesson for lesson in lessons if lesson.get("required", True)]
        material = [lesson for lesson in required_lessons if lesson["kind"] != "practical"]
        practical = [lesson for lesson in required_lessons if lesson["kind"] == "practical"]
        material_done = all(_satisfied(lesson, records.get(lesson["id"])) for lesson in material) if material else True
        practical_pending = any(not _satisfied(lesson, records.get(lesson["id"])) for lesson in practical)
        state = "completed" if all(_satisfied(lesson, records.get(lesson["id"])) for lesson in required_lessons) else "in_progress"
        if not required_lessons:
            state = "in_progress"
        rows.append(
            {
                "userId": user_id,
                "userName": name,
                "enrollmentId": enrollment["id"],
                "state": state,
                "overdue": bool(due_at and due_at < _today() and state != "completed"),
                "dueAt": due_at,
                "required": required,
                "materialDone": material_done and state != "not_started",
                "practicalPending": material_done and practical_pending,
                "startedAt": enrollment["started_at"],
                "practicals": [
                    {
                        "lessonId": lesson["id"],
                        "title": lesson["title"],
                        "lesson_status": records[lesson["id"]]["lesson_status"] if lesson["id"] in records else "not attempted",
                        "graded_by": records[lesson["id"]]["graded_by"] if lesson["id"] in records else None,
                        "graded_at": records[lesson["id"]]["graded_at"] if lesson["id"] in records else None,
                    }
                    for lesson in lessons
                    if lesson["kind"] == "practical"
                ],
            }
        )
    return rows


def _learning_rows(conn: sqlite3.Connection, access: Access) -> list[dict[str, Any]]:
    courses = conn.execute(
        "SELECT * FROM courses WHERE tenant_id = ? AND status = 'published'",
        (access.tenant_id,),
    ).fetchall()
    rows = []
    for course in courses:
        if not _is_assigned(conn, access, course["id"], access.user_id):
            continue
        assignment = _user_assignment(conn, access, course["id"], access.user_id)
        enrollment = conn.execute(
            "SELECT * FROM enrollments WHERE course_id = ? AND user_id = ?",
            (course["id"], access.user_id),
        ).fetchone()
        state = "not_started"
        practical_pending = False
        if enrollment:
            version = conn.execute(
                "SELECT * FROM course_versions WHERE id = ?",
                (enrollment["version_id"],),
            ).fetchone()
            snapshot = json.loads(version["snapshot_json"])
            records = {
                r["lesson_id"]: r
                for r in conn.execute(
                    "SELECT * FROM lesson_records WHERE enrollment_id = ?",
                    (enrollment["id"],),
                ).fetchall()
            }
            lessons = [lesson for lesson in _flat_lessons(snapshot) if lesson.get("required", True)]
            state = "completed" if lessons and all(_satisfied(lesson, records.get(lesson["id"])) for lesson in lessons) else "in_progress"
            material = [lesson for lesson in lessons if lesson["kind"] != "practical"]
            practical = [lesson for lesson in lessons if lesson["kind"] == "practical"]
            material_done = all(_satisfied(lesson, records.get(lesson["id"])) for lesson in material) if material else True
            practical_pending = material_done and any(not _satisfied(lesson, records.get(lesson["id"])) for lesson in practical)
        due_at = assignment["due_at"] if assignment else None
        rows.append(
            {
                "courseId": course["id"],
                "title": course["title"],
                "enrollmentId": enrollment["id"] if enrollment else None,
                "state": state,
                "required": bool(assignment and int(assignment["required"])),
                "dueAt": due_at,
                "overdue": bool(due_at and due_at < _today() and state != "completed"),
                "practicalPending": practical_pending,
            }
        )
    return rows


def _user_assignment(conn: sqlite3.Connection, access: Access, course_id: str, user_id: str) -> sqlite3.Row | None:
    found = None
    for assignment in _assignments(conn, course_id):
        if user_id not in _assignee_users(access, assignment):
            continue
        if found is None:
            found = assignment
            continue
        if assignment["due_at"] and (not found["due_at"] or assignment["due_at"] < found["due_at"]):
            found = assignment
    return found


def _is_assigned(conn: sqlite3.Connection, access: Access, course_id: str, user_id: str) -> bool:
    return _user_assignment(conn, access, course_id, user_id) is not None


def _assignee_users(access: Access, assignment: sqlite3.Row) -> set[str]:
    if assignment["assignee_type"] == "user":
        return {assignment["assignee_id"]}
    team = access.teams.get(assignment["assignee_id"])
    return set(team.member_ids) if team else set()


def _satisfied(lesson: dict[str, Any], record: sqlite3.Row | None) -> bool:
    if not record:
        return False
    status = record["lesson_status"]
    if lesson["kind"] in ("quiz", "practical"):
        return status == "passed"
    return status in ("completed", "passed")


def _enrollment_payload(
    conn: sqlite3.Connection,
    access: Access,
    enrollment_id: str,
    *,
    reveal: bool = False,
) -> dict[str, Any]:
    enrollment = conn.execute("SELECT * FROM enrollments WHERE id = ?", (enrollment_id,)).fetchone()
    version = conn.execute(
        "SELECT * FROM course_versions WHERE id = ?",
        (enrollment["version_id"],),
    ).fetchone()
    snapshot = json.loads(version["snapshot_json"])
    records = {
        r["lesson_id"]: _record_view(r)
        for r in conn.execute(
            "SELECT * FROM lesson_records WHERE enrollment_id = ?",
            (enrollment_id,),
        ).fetchall()
    }
    raw_records = {
        r["lesson_id"]: r
        for r in conn.execute(
            "SELECT * FROM lesson_records WHERE enrollment_id = ?",
            (enrollment_id,),
        ).fetchall()
    }
    owner = enrollment["user_id"] == access.user_id
    show_answers = reveal or owner
    played = _with_playback(snapshot, reveal=show_answers, records=raw_records)
    lessons = [lesson for lesson in _flat_lessons(played) if lesson.get("required", True)]
    state = "completed" if lessons and all(_satisfied(lesson, raw_records.get(lesson["id"])) for lesson in lessons) else "in_progress"
    return {
        "enrollmentId": enrollment["id"],
        "courseId": enrollment["course_id"],
        "userId": enrollment["user_id"],
        "userName": enrollment["user_name"],
        "versionId": enrollment["version_id"],
        "versionNumber": version["number"],
        "startedAt": enrollment["started_at"],
        "state": state,
        "snapshot": played,
        "records": records,
    }


def _with_playback(
    snapshot: dict[str, Any],
    *,
    reveal: bool,
    records: dict[str, sqlite3.Row] | None = None,
) -> dict[str, Any]:
    copied = json.loads(json.dumps(snapshot))
    for lesson in _flat_lessons(copied):
        attempted = bool(records and records.get(lesson["id"]))
        if lesson["kind"] == "quiz" and not (reveal and attempted):
            for question in lesson.get("questions") or []:
                question.pop("correctIndex", None)
        if lesson["kind"] == "video" and lesson.get("objectKey"):
            lesson["playbackUrl"] = _safe_presign(lesson["objectKey"])
        if lesson["kind"] == "slides":
            lesson["slideUrls"] = [_safe_presign(key) for key in lesson.get("slideKeys") or []]
        lesson.pop("objectKey", None)
        lesson.pop("slideKeys", None)
    return copied


def _safe_presign(key: str) -> str | None:
    try:
        return storage.get_storage().presign(key)
    except storage.StorageError:
        return None


def _upsert_record(
    conn: sqlite3.Connection,
    enrollment_id: str,
    lesson_id: str,
    *,
    status: str,
    score_raw: Any,
    location: str,
    session_seconds: int,
    total_seconds: int,
    suspend_data: str,
    graded_by: str | None,
    graded_at: str | None,
) -> None:
    conn.execute(
        "INSERT INTO lesson_records"
        " (enrollment_id, lesson_id, lesson_status, score_raw, lesson_location,"
        "  session_seconds, total_seconds, suspend_data, graded_by, graded_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(enrollment_id, lesson_id) DO UPDATE SET"
        " lesson_status = excluded.lesson_status,"
        " score_raw = excluded.score_raw,"
        " lesson_location = excluded.lesson_location,"
        " session_seconds = excluded.session_seconds,"
        " total_seconds = excluded.total_seconds,"
        " suspend_data = excluded.suspend_data,"
        " graded_by = excluded.graded_by,"
        " graded_at = excluded.graded_at,"
        " updated_at = excluded.updated_at",
        (
            enrollment_id,
            lesson_id,
            status,
            score_raw,
            location,
            session_seconds,
            total_seconds,
            suspend_data,
            graded_by,
            graded_at,
            _now(),
        ),
    )


def _record_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "lesson_status": row["lesson_status"],
        "score_raw": row["score_raw"],
        "lesson_location": row["lesson_location"],
        "session_time": _scorm_time(int(row["session_seconds"])),
        "total_time": _scorm_time(int(row["total_seconds"])),
        "suspend_data": row["suspend_data"],
        "graded_by": row["graded_by"],
        "graded_at": row["graded_at"],
    }


def _preview_snapshot(
    conn: sqlite3.Connection,
    access: Access,
    title: str,
    chapters: list[dict[str, Any]],
) -> dict[str, Any]:
    copied = {"title": title, "chapters": json.loads(json.dumps(_normalize_chapters(chapters)))}
    for lesson in _flat_lessons(copied):
        if lesson["kind"] not in ("video", "slides"):
            continue
        material_id = str(lesson.get("materialId") or "").strip()
        if not material_id:
            continue
        row = conn.execute(
            "SELECT * FROM materials WHERE id = ? AND tenant_id = ?",
            (material_id, access.tenant_id),
        ).fetchone()
        if not row or row["hidden_at"]:
            continue
        expected = "video" if lesson["kind"] == "video" else "slides"
        if row["kind"] != expected:
            continue
        lesson["objectKey"] = row["original_key"]
        lesson["contentType"] = row["content_type"]
        lesson["slideKeys"] = json.loads(row["slide_keys"] or "[]")
    return copied


def _snapshot_from_draft(
    conn: sqlite3.Connection,
    access: Access,
    title: str,
    chapters: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized = _normalize_chapters(chapters)
    lessons = _flat_lessons({"chapters": normalized})
    if not lessons:
        raise LmsError("レッスンが無いコースは公開できません")
    for chapter in normalized:
        if not str(chapter.get("title") or "").strip():
            raise LmsError("章タイトルを入力してください")
    copied_chapters = json.loads(json.dumps(normalized))
    for lesson in _flat_lessons({"chapters": copied_chapters}):
        if not str(lesson.get("title") or "").strip():
            raise LmsError("レッスン名を入力してください")
        if lesson["kind"] in ("video", "slides"):
            material = _material_for_tenant(conn, access, str(lesson.get("materialId") or ""))
            if material["hidden_at"]:
                raise LmsError(f"一覧から外した教材は使えません: {material['title']}")
            if material["kind"] != ("video" if lesson["kind"] == "video" else "slides"):
                raise LmsError("教材の種別がレッスンと違います")
            lesson["objectKey"] = material["original_key"]
            lesson["contentType"] = material["content_type"]
            lesson["slideKeys"] = json.loads(material["slide_keys"] or "[]")
            if lesson["kind"] == "slides" and not lesson["slideKeys"]:
                raise LmsError("ページ画像がありません")
        if lesson["kind"] == "quiz" and not lesson.get("questions"):
            raise LmsError("確認クイズに設問がありません")
        if lesson["kind"] == "practical" and not str(lesson.get("practicalText") or "").strip():
            raise LmsError("実技の文面がありません")
    return {"title": title, "chapters": copied_chapters}


def _normalize_chapters(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise LmsError("章の形が不正です")
    chapters = []
    for chapter in raw:
        if not isinstance(chapter, dict):
            raise LmsError("章の形が不正です")
        lessons = []
        for lesson in chapter.get("lessons") or []:
            if not isinstance(lesson, dict):
                raise LmsError("レッスンの形が不正です")
            kind = str(lesson.get("kind") or "")
            if kind not in ("video", "slides", "quiz", "practical"):
                raise LmsError("レッスン種別が不正です")
            item: dict[str, Any] = {
                "id": str(lesson.get("id") or _new_id()),
                "title": _draft_title(lesson.get("title")),
                "kind": kind,
                "required": bool(lesson.get("required", True)),
            }
            if kind in ("video", "slides"):
                item["materialId"] = str(lesson.get("materialId") or "")
            if kind == "quiz":
                item["masteryScore"] = _mastery(lesson.get("masteryScore"))
                item["questions"] = _questions(lesson.get("questions"))
            if kind == "practical":
                item["practicalText"] = str(lesson.get("practicalText") or "").strip()[:2000]
            lessons.append(item)
        chapters.append(
            {
                "id": str(chapter.get("id") or _new_id()),
                "title": _draft_title(chapter.get("title")),
                "lessons": lessons,
            }
        )
    return chapters


def _questions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise LmsError("設問の形が不正です")
    if len(raw) > 20:
        raise LmsError("設問は20までです")
    questions = []
    for question in raw:
        if not isinstance(question, dict):
            raise LmsError("設問の形が不正です")
        choices = [str(c).strip() for c in (question.get("choices") or []) if str(c).strip()]
        if not 2 <= len(choices) <= 6:
            raise LmsError("選択肢は2つから6つです")
        try:
            correct = int(question.get("correctIndex"))
        except (TypeError, ValueError) as e:
            raise LmsError("正答を指定してください") from e
        if not 0 <= correct < len(choices):
            raise LmsError("正答が選択肢の範囲外です")
        prompt = str(question.get("prompt") or "").strip()
        if not prompt:
            raise LmsError("設問文がありません")
        questions.append(
            {
                "id": str(question.get("id") or _new_id()),
                "prompt": prompt[:500],
                "choices": choices,
                "correctIndex": correct,
            }
        )
    return questions


def _course_detail(conn: sqlite3.Connection, access: Access, course_id: str) -> dict[str, Any]:
    course = _course_row(conn, access, course_id)
    roles = conn.execute(
        "SELECT user_id, role FROM course_roles WHERE course_id = ? ORDER BY role, user_id",
        (course_id,),
    ).fetchall()
    return {
        "id": course["id"],
        "title": course["title"],
        "status": course["status"],
        "draft": json.loads(course["draft_json"]),
        "currentVersionId": course["current_version_id"],
        "roles": [{"userId": r["user_id"], "role": r["role"]} for r in roles],
        "assignments": [
            {
                "id": a["id"],
                "assigneeType": a["assignee_type"],
                "assigneeId": a["assignee_id"],
                "required": bool(a["required"]),
                "dueAt": a["due_at"],
            }
            for a in _assignments(conn, course_id)
        ],
    }


def _course_summaries(conn: sqlite3.Connection, access: Access, ids: set[str]) -> list[dict[str, Any]]:
    if not ids:
        return []
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT id, title, status FROM courses WHERE tenant_id = ? AND id IN ({marks}) ORDER BY updated_at DESC",
        (access.tenant_id, *ids),
    ).fetchall()
    return [{"id": r["id"], "title": r["title"], "status": r["status"]} for r in rows]


def _assignments(conn: sqlite3.Connection, course_id: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM assignments WHERE course_id = ? ORDER BY created_at",
        (course_id,),
    ).fetchall()


def _role_course_ids(conn: sqlite3.Connection, access: Access, role: str) -> set[str]:
    rows = conn.execute(
        "SELECT r.course_id FROM course_roles r"
        " JOIN courses c ON c.id = r.course_id"
        " WHERE r.user_id = ? AND r.role = ? AND c.tenant_id = ?",
        (access.user_id, role, access.tenant_id),
    ).fetchall()
    return {r["course_id"] for r in rows}


def _require_role(conn: sqlite3.Connection, access: Access, course_id: str, role: str) -> None:
    _course_row(conn, access, course_id)
    row = conn.execute(
        "SELECT 1 FROM course_roles WHERE course_id = ? AND user_id = ? AND role = ?",
        (course_id, access.user_id, role),
    ).fetchone()
    if not row:
        raise LmsError("この操作はできません", 403)


def _require_progress_reader(conn: sqlite3.Connection, access: Access, course_id: str) -> None:
    _course_row(conn, access, course_id)
    row = conn.execute(
        "SELECT 1 FROM course_roles WHERE course_id = ? AND user_id = ? AND role IN ('editor', 'certifier')",
        (course_id, access.user_id),
    ).fetchone()
    if not row:
        raise LmsError("この操作はできません", 403)


def _require_member(access: Access) -> None:
    if not access.member:
        raise LmsError("この棟の所属者ではありません", 403)


def _course_row(conn: sqlite3.Connection, access: Access, course_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM courses WHERE id = ? AND tenant_id = ?",
        (course_id, access.tenant_id),
    ).fetchone()
    if not row:
        raise LmsError("コースが見つかりません", 404)
    return row


def _courses_using_material(conn: sqlite3.Connection, tenant_id: str, material: sqlite3.Row) -> list[str]:
    material_id = str(material["id"])
    keys = {str(material["original_key"])}
    keys.update(str(key) for key in json.loads(material["slide_keys"] or "[]") if str(key))
    titles: list[str] = []
    courses = conn.execute(
        "SELECT id, title, draft_json FROM courses WHERE tenant_id = ? ORDER BY updated_at DESC",
        (tenant_id,),
    ).fetchall()
    for course in courses:
        if _json_uses_material(course["draft_json"], material_id, keys):
            titles.append(str(course["title"]))
            continue
        versions = conn.execute(
            "SELECT snapshot_json FROM course_versions WHERE course_id = ?",
            (course["id"],),
        ).fetchall()
        if any(_json_uses_material(version["snapshot_json"], material_id, keys) for version in versions):
            titles.append(str(course["title"]))
    return titles


def _json_uses_material(raw: str, material_id: str, keys: set[str]) -> bool:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        text = raw or ""
        return material_id in text or any(key in text for key in keys)
    if not isinstance(data, dict):
        return False
    chapters = data.get("chapters") or []
    if not isinstance(chapters, list):
        return False
    lessons: list[Any] = []
    for chapter in chapters:
        if isinstance(chapter, dict) and isinstance(chapter.get("lessons"), list):
            lessons.extend(chapter["lessons"])
    for lesson in lessons:
        if not isinstance(lesson, dict):
            continue
        if str(lesson.get("materialId") or "") == material_id:
            return True
        if str(lesson.get("objectKey") or "") in keys:
            return True
        slides = lesson.get("slideKeys") or []
        if isinstance(slides, list) and any(str(slide) in keys for slide in slides):
            return True
    return False


def _material_for_tenant(conn: sqlite3.Connection, access: Access, material_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM materials WHERE id = ? AND tenant_id = ?",
        (material_id, access.tenant_id),
    ).fetchone()
    if not row:
        raise LmsError("教材が見つかりません", 404)
    return row


def _material_row(row: sqlite3.Row) -> dict[str, Any]:
    keys = set(row.keys())
    transcript_status = "none"
    if "transcript_status" in keys and row["transcript_status"]:
        transcript_status = str(row["transcript_status"])
    return {
        "id": row["id"],
        "title": row["title"],
        "kind": row["kind"],
        "contentType": row["content_type"],
        "slideCount": len(json.loads(row["slide_keys"] or "[]")),
        "createdAt": row["created_at"],
        "transcriptStatus": transcript_status,
    }


def _transcript_row(conn: sqlite3.Connection, tenant_id: str, material_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM material_transcripts WHERE material_id = ? AND tenant_id = ?",
        (material_id, tenant_id),
    ).fetchone()


def _transcript_payload(material: sqlite3.Row, transcript: sqlite3.Row | None) -> dict[str, Any]:
    status = "none"
    notice = ""
    error = ""
    updated_at = ""
    segments: list[Any] = []
    if transcript is not None:
        status = str(transcript["status"])
        notice = str(transcript["notice"] or "")
        error = str(transcript["error"] or "")
        updated_at = str(transcript["updated_at"] or "")
        segments = json.loads(transcript["segments_json"] or "[]")
    playback = ""
    if material["kind"] in ("video", "slides"):
        try:
            playback = storage.get_storage().presign(str(material["original_key"]))
        except storage.StorageError:
            playback = ""
    return {
        "materialId": material["id"],
        "title": material["title"],
        "kind": material["kind"],
        "status": status,
        "notice": notice,
        "error": error,
        "playbackUrl": playback,
        "segments": segments,
        "updatedAt": updated_at,
    }


def _clean_segments(kind: str, raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise LmsError("本文の形が不正です")
    if len(raw) > 5000:
        raise LmsError("区間が多すぎます")
    segments: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise LmsError("本文の形が不正です")
        text = str(item.get("text") if item.get("text") is not None else "")
        if len(text) > 50000:
            raise LmsError("1ページの文字が長すぎます" if kind == "slides" else "1区間の文字が長すぎます")
        try:
            start = float(item.get("start"))
            end = float(item.get("end"))
        except (TypeError, ValueError):
            raise LmsError("ページ番号が不正です" if kind == "slides" else "区間の時刻が不正です") from None
        if kind == "slides":
            page = int(start)
            if page < 1 or int(end) != page or start != page:
                raise LmsError("ページ番号が不正です")
            start_value: int | float = page
            end_value: int | float = page
        else:
            if start < 0 or end < start:
                raise LmsError("区間の時刻が不正です")
            start_value = round(start, 2)
            end_value = round(end, 2)
        seg_id = str(item.get("id") or "").strip() or _new_id()
        if len(seg_id) > 80:
            raise LmsError("区間の指定が不正です")
        segments.append({"id": seg_id, "start": start_value, "end": end_value, "text": text})
    return segments


def _session_row(conn: sqlite3.Connection, access: Access, session_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM upload_sessions WHERE id = ? AND tenant_id = ? AND user_id = ?",
        (session_id, access.tenant_id, access.user_id),
    ).fetchone()
    if not row:
        raise LmsError("アップロードが見つかりません", 404)
    return row


def _own_enrollment(conn: sqlite3.Connection, access: Access, enrollment_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM enrollments WHERE id = ? AND tenant_id = ? AND user_id = ?",
        (enrollment_id, access.tenant_id, access.user_id),
    ).fetchone()
    if not row:
        raise LmsError("受講が見つかりません", 404)
    return row


def _enrollment_visible(conn: sqlite3.Connection, access: Access, enrollment_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM enrollments WHERE id = ? AND tenant_id = ?",
        (enrollment_id, access.tenant_id),
    ).fetchone()
    if not row:
        raise LmsError("受講が見つかりません", 404)
    if row["user_id"] == access.user_id:
        return row
    reader = conn.execute(
        "SELECT 1 FROM course_roles WHERE course_id = ? AND user_id = ? AND role IN ('editor', 'certifier')",
        (row["course_id"], access.user_id),
    ).fetchone()
    if not reader:
        raise LmsError("この操作はできません", 403)
    return row


def _lesson_in_enrollment(conn: sqlite3.Connection, enrollment: sqlite3.Row, lesson_id: str) -> dict[str, Any]:
    version = conn.execute(
        "SELECT * FROM course_versions WHERE id = ?",
        (enrollment["version_id"],),
    ).fetchone()
    snapshot = json.loads(version["snapshot_json"])
    for lesson in _flat_lessons(snapshot):
        if lesson["id"] == lesson_id:
            return lesson
    raise LmsError("レッスンが見つかりません", 404)


def _record_row(conn: sqlite3.Connection, enrollment_id: str, lesson_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM lesson_records WHERE enrollment_id = ? AND lesson_id = ?",
        (enrollment_id, lesson_id),
    ).fetchone()


def _flat_lessons(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lessons = []
    for chapter in snapshot.get("chapters") or []:
        lessons.extend(chapter.get("lessons") or [])
    return lessons


def _session_bytes(session_id: str) -> int:
    root = Path(UPLOAD_DIR, session_id)
    if not root.exists():
        return 0
    return sum(path.stat().st_size for path in root.iterdir() if path.is_file())


def _read_session(session_id: str) -> bytes:
    root = Path(UPLOAD_DIR, session_id)
    parts = sorted(path for path in root.iterdir() if path.is_file())
    return b"".join(path.read_bytes() for path in parts)


def _clear_session(session_id: str) -> None:
    root = Path(UPLOAD_DIR, session_id)
    if not root.exists():
        return
    for path in root.iterdir():
        path.unlink(missing_ok=True)
    root.rmdir()


def _draft_title(value: Any) -> str:
    title = str(value or "").strip()
    if len(title) > 200:
        raise LmsError("名前が長すぎます")
    return title


def _title(value: Any) -> str:
    title = str(value or "").strip()
    if not title:
        raise LmsError("名前を入力してください")
    if len(title) > 200:
        raise LmsError("名前が長すぎます")
    return title


def _due(value: Any) -> str | None:
    if value is None or value == "":
        return None
    text = str(value).strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as e:
        raise LmsError("期限は YYYY-MM-DD です") from e
    return text


def _mastery(value: Any) -> float:
    try:
        score = float(80 if value is None else value)
    except (TypeError, ValueError) as e:
        raise LmsError("合格点が不正です") from e
    if not 0 <= score <= 100:
        raise LmsError("合格点は 0 から 100 です")
    return score


def _suspend(value: Any) -> str:
    text = "" if value is None else str(value)
    if len(text) > SUSPEND_LIMIT:
        raise LmsError("suspend_data は 4096 文字までです")
    return text


def _scorm_time(seconds: int) -> str:
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:04d}:{minutes:02d}:{secs:02d}.00"


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
