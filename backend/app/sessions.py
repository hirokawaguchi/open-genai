"""アプリログインのサーバ側セッション。

JWT はブラウザにコピーされ得る。署名が正しくても、ここにあるセッションが
生きていなければ API も再発行も通さない。ログアウトと「すべてのログインを切る」は
同じ ID を無効にするので、コピーも同時に死ぬ。

期限はログインから24時間後ではなく、利用者が少ない時刻（既定は日本時間の
午前4時）に揃える。日中の作業中には切らない。その時刻の直前にログインした
場合は、すぐ切らず次の同時刻まで持つ。
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid

DB_PATH = os.environ.get("SESSION_DB_PATH", "/data/sessions.db")
# セッションを切る時刻。日本時間（通年 UTC+9）の時。既定は午前4時。
RESET_HOUR = int(os.environ.get("APP_SESSION_RESET_HOUR", "4"))
RESET_TZ_OFFSET_SECONDS = 9 * 60 * 60
# この秒数より近いリセットでは切らない。直前のログインをすぐ終わらせないため。
RESET_MIN_SECONDS = int(os.environ.get("APP_SESSION_RESET_MIN_SECONDS", str(4 * 60 * 60)))

_lock = threading.Lock()
_ready_path: str | None = None


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def _connect() -> sqlite3.Connection:
    global _ready_path
    directory = os.path.dirname(DB_PATH)
    if directory:
        os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    if _ready_path != DB_PATH:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                sid TEXT PRIMARY KEY,
                sub TEXT NOT NULL,
                email TEXT NOT NULL DEFAULT '',
                auth_time INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                revoked_at INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_sessions_sub ON sessions(sub);
            CREATE INDEX IF NOT EXISTS idx_sessions_email ON sessions(email);
            """
        )
        _ready_path = DB_PATH
    return conn


def deadline(auth_time: int) -> int:
    """このログインを切る UNIX 時刻。

    次のリセット時刻（既定は日本時間の午前4時）。ただしログインから
    RESET_MIN_SECONDS より近ければ、その次のリセット時刻にする。
    """
    auth_time = int(auth_time)
    local = auth_time + RESET_TZ_OFFSET_SECONDS
    day_start = local - (local % 86400)
    hour = min(max(RESET_HOUR, 0), 23)
    candidate = day_start + hour * 3600 - RESET_TZ_OFFSET_SECONDS
    if candidate <= auth_time:
        candidate += 86400
    if candidate - auth_time < RESET_MIN_SECONDS:
        candidate += 86400
    return candidate


def _purge(conn: sqlite3.Connection, now: int) -> None:
    # 期限を過ぎてから十分置いた行と、切ってから 1 日置いた行を捨てる。
    # 最長でもリセットを 1 回分だけ先送りするので、3 日より前のログインは不要。
    cutoff = now - 3 * 86400
    revoked_cutoff = now - 86400
    conn.execute(
        """
        DELETE FROM sessions
        WHERE auth_time < ?
           OR (revoked_at IS NOT NULL AND revoked_at < ?)
        """,
        (cutoff, revoked_cutoff),
    )


def create(*, sub: str, email: str, auth_time: int) -> str:
    """新しいログインを登録し、セッション ID を返す。"""
    sid = str(uuid.uuid4())
    now = int(time.time())
    with _lock, _connect() as conn:
        _purge(conn, now)
        conn.execute(
            """
            INSERT INTO sessions (sid, sub, email, auth_time, created_at, revoked_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (sid, _norm(sub), _norm(email), int(auth_time), now),
        )
    return sid


def get(sid: str) -> dict | None:
    if not sid:
        return None
    with _lock, _connect() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE sid = ?", (sid,)).fetchone()
    if row is None:
        return None
    return dict(row)


def is_active(sid: str) -> bool:
    """切られておらず、リセット時刻前なら True。"""
    row = get(sid)
    if row is None or row.get("revoked_at") is not None:
        return False
    auth_time = row.get("auth_time")
    if not isinstance(auth_time, int):
        return False
    return int(time.time()) <= deadline(auth_time)


def revoke(sid: str) -> bool:
    """1 件を切る。すでに切れていれば False。"""
    if not sid:
        return False
    now = int(time.time())
    with _lock, _connect() as conn:
        cur = conn.execute(
            """
            UPDATE sessions
            SET revoked_at = ?
            WHERE sid = ? AND revoked_at IS NULL
            """,
            (now, sid),
        )
        return cur.rowcount > 0


def revoke_matching(idents: list[str], *, keep_sid: str | None = None) -> int:
    """sub または email が識別子に一致する、生きているログインを切る。

    keep_sid を渡すと、その 1 件（今のブラウザ）は残す。
    """
    keys = []
    seen: set[str] = set()
    for raw in idents:
        key = _norm(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        keys.append(key)
    if not keys:
        return 0
    marks = ",".join("?" for _ in keys)
    sql = f"""
        UPDATE sessions
        SET revoked_at = ?
        WHERE revoked_at IS NULL
          AND (sub IN ({marks}) OR email IN ({marks}))
    """
    params: list[object] = [int(time.time()), *keys, *keys]
    if keep_sid:
        sql += " AND sid != ?"
        params.append(keep_sid)
    with _lock, _connect() as conn:
        cur = conn.execute(sql, params)
        return int(cur.rowcount)
