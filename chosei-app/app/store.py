"""日程調整の SQLite 永続化。"""

from __future__ import annotations

import os
import re
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt

DB_PATH = os.environ.get("CHOSEI_DB_PATH", "/data/chosei.db")
RETENTION_DAYS = int(os.environ.get("CHOSEI_RETENTION_DAYS", "90"))
PUBLIC_ENDPOINT = (os.environ.get("CHOSEI_PUBLIC_ENDPOINT") or "").rstrip("/")

_PIN_RE = re.compile(r"^\d{4}$")
_lock = threading.Lock()
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


def validate_pin(pin: str | None) -> str | None:
    """不正ならエラーメッセージ、正しければ None。"""
    if not pin:
        return "暗証番号は必須です（4桁の数字）"
    if not _PIN_RE.match(pin):
        return "暗証番号は4桁の数字である必要があります"
    return None


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
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY,
              guest_token TEXT NOT NULL UNIQUE,
              title TEXT NOT NULL,
              description TEXT,
              creator_name TEXT,
              creator_user_id TEXT,
              event_password_hash TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS event_dates (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_id TEXT NOT NULL,
              date_time TEXT NOT NULL,
              end_time TEXT,
              is_all_day INTEGER DEFAULT 0,
              created_at TEXT NOT NULL,
              FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS responses (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_date_id INTEGER NOT NULL,
              participant_name TEXT NOT NULL,
              participant_user_id TEXT,
              status TEXT NOT NULL CHECK (status IN ('ok', 'ng', 'maybe')),
              created_at TEXT NOT NULL,
              FOREIGN KEY (event_date_id) REFERENCES event_dates(id) ON DELETE CASCADE,
              UNIQUE(event_date_id, participant_name)
            );
            CREATE TABLE IF NOT EXISTS participant_passwords (
              event_id TEXT NOT NULL,
              participant_name TEXT NOT NULL,
              participant_user_id TEXT,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY (event_id, participant_name),
              FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_event_dates_event_id ON event_dates(event_id);
            CREATE INDEX IF NOT EXISTS idx_responses_event_date_id ON responses(event_date_id);
            CREATE INDEX IF NOT EXISTS idx_events_creator ON events(creator_user_id);
            CREATE INDEX IF NOT EXISTS idx_events_guest_token ON events(guest_token);
            """
        )
        db.commit()


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "guest_token": row["guest_token"],
        "title": row["title"],
        "description": row["description"],
        "creator_name": row["creator_name"],
        "creator_user_id": row["creator_user_id"],
        "has_event_password": bool(row["event_password_hash"]),
        "created_at": row["created_at"],
        "public_url": public_url_for(row["guest_token"]),
    }


def public_url_for(guest_token: str) -> str:
    if not PUBLIC_ENDPOINT:
        return f"/public/e/{guest_token}"
    return f"{PUBLIC_ENDPOINT}/public/e/{guest_token}"


def _get_dates(db: sqlite3.Connection, event_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        "SELECT id, date_time, end_time, is_all_day, created_at "
        "FROM event_dates WHERE event_id = ? ORDER BY date_time",
        (event_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "date_time": r["date_time"],
            "end_time": r["end_time"],
            "is_all_day": bool(r["is_all_day"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def _get_responses(db: sqlite3.Connection, event_id: str) -> list[dict[str, Any]]:
    rows = db.execute(
        """
        SELECT r.id, r.participant_name, r.participant_user_id, r.event_date_id,
               r.status, ed.date_time
        FROM responses r
        JOIN event_dates ed ON r.event_date_id = ed.id
        WHERE ed.event_id = ?
        ORDER BY r.participant_name, ed.date_time
        """,
        (event_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "participant_name": r["participant_name"],
            "participant_user_id": r["participant_user_id"],
            "event_date_id": r["event_date_id"],
            "status": r["status"],
            "date_time": r["date_time"],
        }
        for r in rows
    ]


def _statistics(dates: list[dict[str, Any]], responses: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for d in dates:
        stats[str(d["id"])] = {
            "date_time": d["date_time"],
            "ok": 0,
            "ng": 0,
            "maybe": 0,
            "participants": [],
        }
    for r in responses:
        key = str(r["event_date_id"])
        st = stats.get(key)
        if not st:
            continue
        st[r["status"]] = st.get(r["status"], 0) + 1
        if r["participant_name"] not in st["participants"]:
            st["participants"].append(r["participant_name"])
    return stats


def event_detail(event_id: str | None = None, guest_token: str | None = None) -> dict[str, Any] | None:
    db = connect()
    with _lock:
        if guest_token:
            row = db.execute(
                "SELECT * FROM events WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None
        dates = _get_dates(db, row["id"])
        responses = _get_responses(db, row["id"])
        return {
            "event": _row_to_event(row),
            "dates": dates,
            "responses": responses,
            "statistics": _statistics(dates, responses),
        }


def list_events_for_user(user_id: str) -> list[dict[str, Any]]:
    db = connect()
    with _lock:
        rows = db.execute(
            """
            SELECT * FROM events
            WHERE creator_user_id = ?
               OR id IN (
                 SELECT DISTINCT ed.event_id FROM event_dates ed
                 JOIN responses r ON r.event_date_id = ed.id
                 WHERE r.participant_user_id = ?
               )
            ORDER BY created_at DESC
            """,
            (user_id, user_id),
        ).fetchall()
        return [_row_to_event(r) for r in rows]


def create_event(
    *,
    title: str,
    description: str | None,
    creator_name: str | None,
    creator_user_id: str,
    event_password: str | None,
    dates: list[dict[str, Any]],
) -> dict[str, Any]:
    event_id = str(uuid.uuid4())
    guest_token = secrets.token_urlsafe(24)
    now = _now_iso()
    pw_hash = hash_pin(event_password) if event_password else None
    db = connect()
    with _lock:
        db.execute(
            "INSERT INTO events (id, guest_token, title, description, creator_name, "
            "creator_user_id, event_password_hash, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (
                event_id,
                guest_token,
                title,
                description,
                creator_name,
                creator_user_id,
                pw_hash,
                now,
            ),
        )
        for d in dates:
            db.execute(
                "INSERT INTO event_dates (event_id, date_time, end_time, is_all_day, created_at) "
                "VALUES (?,?,?,?,?)",
                (
                    event_id,
                    d["start_time"],
                    d.get("end_time"),
                    1 if d.get("is_all_day") else 0,
                    now,
                ),
            )
        db.commit()
    detail = event_detail(event_id=event_id)
    assert detail is not None
    return detail


def update_event(
    event_id: str,
    *,
    title: str,
    description: str | None,
    creator_name: str | None,
    dates: list[dict[str, Any]] | None,
    event_password: str | None,
    actor_user_id: str,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return None, "イベントが見つかりません"
        is_creator = row["creator_user_id"] == actor_user_id
        if not is_creator:
            if not row["event_password_hash"]:
                return None, "このイベントには暗証番号が設定されていないため、編集できません"
            if not event_password or not verify_pin(event_password, row["event_password_hash"]):
                return None, "イベントの暗証番号が正しくありません"
        now = _now_iso()
        db.execute(
            "UPDATE events SET title = ?, description = ?, creator_name = ? WHERE id = ?",
            (title, description, creator_name, event_id),
        )
        if dates is not None and len(dates) > 0:
            db.execute("DELETE FROM event_dates WHERE event_id = ?", (event_id,))
            for d in dates:
                db.execute(
                    "INSERT INTO event_dates (event_id, date_time, end_time, is_all_day, created_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        event_id,
                        d["start_time"],
                        d.get("end_time"),
                        1 if d.get("is_all_day") else 0,
                        now,
                    ),
                )
        db.commit()
    return event_detail(event_id=event_id), None


def delete_event(
    event_id: str, *, event_password: str | None, actor_user_id: str
) -> str | None:
    db = connect()
    with _lock:
        row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if not row:
            return "イベントが見つかりません"
        is_creator = row["creator_user_id"] == actor_user_id
        if not is_creator:
            if not row["event_password_hash"]:
                return "このイベントには暗証番号が設定されていないため、削除できません"
            if not event_password or not verify_pin(event_password, row["event_password_hash"]):
                return "イベントの暗証番号が正しくありません"
        db.execute("DELETE FROM events WHERE id = ?", (event_id,))
        db.commit()
    return None


def submit_response(
    *,
    event_id: str | None = None,
    guest_token: str | None = None,
    participant_name: str,
    responses: list[dict[str, Any]],
    password: str | None,
    participant_user_id: str | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    db = connect()
    with _lock:
        if guest_token:
            event = db.execute(
                "SELECT id FROM events WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            event = db.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            return None, "イベントが見つかりません"
        eid = event["id"]

        existing = db.execute(
            "SELECT password_hash, participant_user_id FROM participant_passwords "
            "WHERE event_id = ? AND participant_name = ?",
            (eid, participant_name),
        ).fetchone()

        # 認証ユーザーで同一 user_id の既存参加者がいれば PIN 不要で上書き可
        auth_owned = False
        if participant_user_id and existing and existing["participant_user_id"] == participant_user_id:
            auth_owned = True

        if existing and not auth_owned:
            err = validate_pin(password)
            if err:
                return None, err
            if not verify_pin(password or "", existing["password_hash"]):
                return None, "暗証番号が正しくありません"
        elif not existing:
            err = validate_pin(password)
            if err:
                return None, err

        now = _now_iso()
        if not existing:
            db.execute(
                "INSERT INTO participant_passwords "
                "(event_id, participant_name, participant_user_id, password_hash, created_at) "
                "VALUES (?,?,?,?,?)",
                (eid, participant_name, participant_user_id, hash_pin(password or ""), now),
            )
        elif participant_user_id and not existing["participant_user_id"]:
            db.execute(
                "UPDATE participant_passwords SET participant_user_id = ? "
                "WHERE event_id = ? AND participant_name = ?",
                (participant_user_id, eid, participant_name),
            )

        db.execute(
            """
            DELETE FROM responses
            WHERE event_date_id IN (SELECT id FROM event_dates WHERE event_id = ?)
              AND participant_name = ?
            """,
            (eid, participant_name),
        )
        for r in responses:
            status = r.get("status")
            date_id = r.get("event_date_id")
            if status not in ("ok", "ng", "maybe") or date_id is None:
                continue
            # 日程がこのイベントのものか確認
            owned = db.execute(
                "SELECT 1 FROM event_dates WHERE id = ? AND event_id = ?",
                (date_id, eid),
            ).fetchone()
            if not owned:
                continue
            db.execute(
                "INSERT INTO responses "
                "(event_date_id, participant_name, participant_user_id, status, created_at) "
                "VALUES (?,?,?,?,?)",
                (date_id, participant_name, participant_user_id, status, now),
            )
        db.commit()
    return {
        "message": "回答が送信されました",
        "is_new_participant": existing is None,
    }, None


def delete_participant(
    *,
    event_id: str | None = None,
    guest_token: str | None = None,
    participant_name: str,
    password: str | None,
    actor_user_id: str | None = None,
) -> str | None:
    db = connect()
    with _lock:
        if guest_token:
            event = db.execute(
                "SELECT id FROM events WHERE guest_token = ?", (guest_token,)
            ).fetchone()
        else:
            event = db.execute("SELECT id FROM events WHERE id = ?", (event_id,)).fetchone()
        if not event:
            return "イベントが見つかりません"
        eid = event["id"]
        existing = db.execute(
            "SELECT password_hash, participant_user_id FROM participant_passwords "
            "WHERE event_id = ? AND participant_name = ?",
            (eid, participant_name),
        ).fetchone()
        if not existing:
            return "参加者が見つかりません"
        auth_owned = (
            actor_user_id
            and existing["participant_user_id"]
            and existing["participant_user_id"] == actor_user_id
        )
        if not auth_owned:
            err = validate_pin(password)
            if err:
                return err
            if not verify_pin(password or "", existing["password_hash"]):
                return "暗証番号が正しくありません"
        db.execute(
            """
            DELETE FROM responses
            WHERE event_date_id IN (SELECT id FROM event_dates WHERE event_id = ?)
              AND participant_name = ?
            """,
            (eid, participant_name),
        )
        db.execute(
            "DELETE FROM participant_passwords WHERE event_id = ? AND participant_name = ?",
            (eid, participant_name),
        )
        db.commit()
    return None


def delete_old_events(retention_days: int | None = None) -> int:
    days = retention_days if retention_days is not None else RETENTION_DAYS
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat()
    db = connect()
    with _lock:
        cur = db.execute("DELETE FROM events WHERE created_at < ?", (cutoff,))
        db.commit()
        return cur.rowcount
