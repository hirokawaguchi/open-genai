"""チーム / メンバー / AI アプリ(exApp) の永続化レイヤ (SQLite)。

クラウド版 源内 は DynamoDB + Cognito グループで管理するが、
Open GENAI ではマネージドサービスに依存せず SQLite で完結させる。

- 権限グループ(SystemAdminGroup 等) は Keycloak(SAML) 由来
- チーム単位の管理権限は team_users.isAdmin で表現
- 共通チーム(COMMON_TEAM_ID) のアプリは全認証済みユーザーが利用可能
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from typing import Any

DB_PATH = os.environ.get("TEAMS_DB_PATH", "/data/open-genai-teams.db")

COMMON_TEAM_ID = "00000000-0000-0000-0000-000000000000"
# 管理者向けアプリ（監査ログ参照/利用者一括管理/モデル制御/入力制限/RAGナレッジ管理）を
# 共通アプリから分離して表示するための専用チーム。システム管理者のみに見える。
ADMIN_TEAM_ID = "00000000-0000-0000-0000-0000000000a1"
ADMIN_TEAM_NAME = "管理者ツール"

# GenU 組み込み機能（DB 未登録）の itemId。共通チームのアプリとしてピン留め対象になる。
GENU_APP_IDS = frozenset({"chat", "generate", "translate", "image", "diagram"})

# 利用者ごとのピン留め上限
MAX_APP_PINS = 8

_lock = threading.Lock()


def _now() -> str:
    # フロントは createdDate/updatedDate を数値(ms)として扱うためエポック(ms)文字列で返す
    return str(int(time.time() * 1000))


def normalize_email(email: str | None) -> str:
    """利用者識別子(メール)を正規化する（前後空白除去＋小文字化）。

    識別子はメール（SAML NameID）で全体を横断するため、表記ゆれ（大文字小文字・
    余分な空白）で同一人物が別 ID 扱いになる/取り違えるのを防ぐ。保存・照合の
    両方で必ず本関数を通す。
    """
    return (email or "").strip().lower()


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# 初期化 + シード
# ---------------------------------------------------------------------------
def init_db(seed_exapps: list[dict[str, Any]] | None = None) -> None:
    with _lock, _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS teams (
                teamId TEXT PRIMARY KEY,
                teamName TEXT NOT NULL,
                createdDate TEXT NOT NULL,
                updatedDate TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS team_users (
                teamId TEXT NOT NULL,
                userId TEXT NOT NULL,
                username TEXT NOT NULL,
                isAdmin INTEGER NOT NULL DEFAULT 0,
                createdDate TEXT NOT NULL,
                updatedDate TEXT NOT NULL,
                PRIMARY KEY (teamId, userId)
            );

            CREATE TABLE IF NOT EXISTS exapps (
                exAppId TEXT PRIMARY KEY,
                teamId TEXT NOT NULL,
                exAppName TEXT NOT NULL,
                endpoint TEXT NOT NULL DEFAULT '',
                apiKey TEXT NOT NULL DEFAULT '',
                config TEXT NOT NULL DEFAULT '',
                placeholder TEXT NOT NULL DEFAULT '',
                systemPrompt TEXT,
                systemPromptKeyName TEXT,
                description TEXT NOT NULL DEFAULT '',
                howToUse TEXT NOT NULL DEFAULT '',
                copyable INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                createdDate TEXT NOT NULL,
                updatedDate TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS exapp_histories (
                teamId TEXT NOT NULL,
                exAppId TEXT NOT NULL,
                createdDate TEXT NOT NULL,
                teamName TEXT NOT NULL DEFAULT '',
                exAppName TEXT NOT NULL DEFAULT '',
                userId TEXT NOT NULL DEFAULT '',
                inputs TEXT NOT NULL DEFAULT '{}',
                outputs TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'COMPLETED',
                progress TEXT NOT NULL DEFAULT '',
                artifacts TEXT,
                sessionId TEXT,
                PRIMARY KEY (teamId, exAppId, createdDate)
            );

            CREATE TABLE IF NOT EXISTS user_app_pins (
                userId TEXT NOT NULL,
                teamId TEXT NOT NULL,
                itemId TEXT NOT NULL,
                displayOrder INTEGER NOT NULL,
                pinnedDate TEXT NOT NULL,
                PRIMARY KEY (userId, teamId, itemId)
            );
            """
        )
        # 共通チーム / 管理者ツール チーム（いずれもシステム管理下の固定チーム）
        for fixed_id, fixed_name in (
            (COMMON_TEAM_ID, "共通アプリ"),
            (ADMIN_TEAM_ID, ADMIN_TEAM_NAME),
        ):
            row = conn.execute(
                "SELECT teamId FROM teams WHERE teamId = ?", (fixed_id,)
            ).fetchone()
            if not row:
                now = _now()
                conn.execute(
                    "INSERT INTO teams (teamId, teamName, createdDate, updatedDate)"
                    " VALUES (?, ?, ?, ?)",
                    (fixed_id, fixed_name, now, now),
                )

    # 共通チームに既定アプリ(RAG 等)をシード
    for app in seed_exapps or []:
        upsert_seed_exapp(app)


def upsert_seed_exapp(app: dict[str, Any]) -> None:
    """固定 exAppId の既定アプリを冪等に登録する（RAG など）。

    既存の場合も、システム管理の表示・配線項目（フォーム定義 placeholder・説明・
    エンドポイント・API キー・config・状態）を最新のシード定義へ**更新**する。
    これにより、フォーム項目（タグ/URL 等）の追加が再起動で反映される。
    """
    with _lock, _connect() as conn:
        exists = conn.execute(
            "SELECT exAppId, teamId FROM exapps WHERE exAppId = ?", (app["exAppId"],)
        ).fetchone()
        now = _now()
        new_team = app.get("teamId", COMMON_TEAM_ID)
        if exists:
            old_team = exists["teamId"]
            # teamId もシード定義へ揃える（管理者アプリを専用チームへ移設する移行も兼ねる）
            conn.execute(
                "UPDATE exapps SET teamId=?, exAppName=?, endpoint=?, apiKey=?, config=?,"
                " placeholder=?, description=?, howToUse=?, copyable=?, status=?,"
                " updatedDate=? WHERE exAppId=?",
                (
                    new_team,
                    app.get("exAppName", ""),
                    app.get("endpoint", ""),
                    app.get("apiKey", ""),
                    app.get("config", ""),
                    app.get("placeholder", ""),
                    app.get("description", ""),
                    app.get("howToUse", ""),
                    1 if app.get("copyable") else 0,
                    app.get("status", "published"),
                    now,
                    app["exAppId"],
                ),
            )
            # teamId 変更時は履歴・ピン留めも追随（例: rag-manage の ADMIN→COMMON）
            if old_team != new_team:
                conn.execute(
                    "UPDATE exapp_histories SET teamId = ?, teamName = ?"
                    " WHERE teamId = ? AND exAppId = ?",
                    (
                        new_team,
                        app.get("exAppName", ""),
                        old_team,
                        app["exAppId"],
                    ),
                )
                # ピンは PK(userId, teamId, itemId)。移行先に既にある行は旧側を捨てる
                conflict_users = [
                    r["userId"]
                    for r in conn.execute(
                        "SELECT userId FROM user_app_pins"
                        " WHERE teamId = ? AND itemId = ?",
                        (new_team, app["exAppId"]),
                    ).fetchall()
                ]
                if conflict_users:
                    placeholders = ",".join("?" for _ in conflict_users)
                    conn.execute(
                        f"DELETE FROM user_app_pins WHERE teamId = ? AND itemId = ?"
                        f" AND userId IN ({placeholders})",
                        (old_team, app["exAppId"], *conflict_users),
                    )
                conn.execute(
                    "UPDATE user_app_pins SET teamId = ?"
                    " WHERE teamId = ? AND itemId = ?",
                    (new_team, old_team, app["exAppId"]),
                )
            return
        conn.execute(
            "INSERT INTO exapps (exAppId, teamId, exAppName, endpoint, apiKey, config,"
            " placeholder, systemPrompt, systemPromptKeyName, description, howToUse,"
            " copyable, status, createdDate, updatedDate)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                app["exAppId"],
                new_team,
                app.get("exAppName", ""),
                app.get("endpoint", ""),
                app.get("apiKey", ""),
                app.get("config", ""),
                app.get("placeholder", ""),
                app.get("systemPrompt"),
                app.get("systemPromptKeyName"),
                app.get("description", ""),
                app.get("howToUse", ""),
                1 if app.get("copyable") else 0,
                app.get("status", "published"),
                now,
                now,
            ),
        )


def refresh_placeholder_by_endpoint(
    endpoint: str,
    placeholder: str,
    how_to_use: str | None = None,
    exclude_team_id: str | None = None,
) -> int:
    """指定エンドポイントの exApp のフォーム定義(placeholder)を最新化する。

    同一マイクロサービスを指す既存アプリのフォーム項目を、名前や説明はそのままに
    更新する（exclude_team_id を指定するとそのチームは対象外＝共通の検索/管理
    アプリはシード側で個別管理するため除外できる）。更新件数を返す。
    """
    params: list[Any] = [placeholder]
    set_clause = "placeholder=?"
    if how_to_use is not None:
        set_clause += ", howToUse=?"
        params.append(how_to_use)
    set_clause += ", updatedDate=?"
    params.append(_now())
    where = "endpoint=?"
    params.append(endpoint)
    if exclude_team_id is not None:
        where += " AND teamId<>?"
        params.append(exclude_team_id)
    with _lock, _connect() as conn:
        cur = conn.execute(f"UPDATE exapps SET {set_clause} WHERE {where}", params)
        return cur.rowcount


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
def _row_to_team(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "teamId": r["teamId"],
        "teamName": r["teamName"],
        "createdDate": r["createdDate"],
        "updatedDate": r["updatedDate"],
    }


def list_teams() -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM teams ORDER BY createdDate ASC"
        ).fetchall()
    return [_row_to_team(r) for r in rows]


def list_teams_for_admin(user_id: str) -> list[dict[str, Any]]:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT t.* FROM teams t"
            " JOIN team_users u ON t.teamId = u.teamId"
            " WHERE u.userId = ? AND u.isAdmin = 1"
            " ORDER BY t.createdDate ASC",
            (user_id,),
        ).fetchall()
    return [_row_to_team(r) for r in rows]


def get_team(team_id: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT * FROM teams WHERE teamId = ?", (team_id,)
        ).fetchone()
    return _row_to_team(r) if r else None


def create_team(team_name: str, admin_email: str) -> dict[str, Any]:
    team_id = str(uuid.uuid4())
    admin_email = normalize_email(admin_email)
    now = _now()
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO teams (teamId, teamName, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?)",
            (team_id, team_name, now, now),
        )
        conn.execute(
            "INSERT INTO team_users (teamId, userId, username, isAdmin, createdDate, updatedDate)"
            " VALUES (?, ?, ?, 1, ?, ?)",
            (team_id, admin_email, admin_email, now, now),
        )
        team = conn.execute(
            "SELECT * FROM teams WHERE teamId = ?", (team_id,)
        ).fetchone()
        admin_user = conn.execute(
            "SELECT * FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, admin_email),
        ).fetchone()
    result = _row_to_team(team)
    result["teamUser"] = _row_to_team_user(admin_user)
    return result


def update_team(team_id: str, team_name: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE teams SET teamName = ?, updatedDate = ? WHERE teamId = ?",
            (team_name, _now(), team_id),
        )
        r = conn.execute(
            "SELECT * FROM teams WHERE teamId = ?", (team_id,)
        ).fetchone()
    return _row_to_team(r) if r else None


def delete_team(team_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM user_app_pins WHERE teamId = ?", (team_id,))
        conn.execute("DELETE FROM exapps WHERE teamId = ?", (team_id,))
        conn.execute("DELETE FROM team_users WHERE teamId = ?", (team_id,))
        conn.execute("DELETE FROM teams WHERE teamId = ?", (team_id,))


# ---------------------------------------------------------------------------
# Team users (members)
# ---------------------------------------------------------------------------
def _row_to_team_user(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "teamId": r["teamId"],
        "userId": r["userId"],
        "username": r["username"],
        "isAdmin": bool(r["isAdmin"]),
        "createdDate": r["createdDate"],
        "updatedDate": r["updatedDate"],
    }


def list_team_users(team_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM team_users WHERE teamId = ? ORDER BY createdDate ASC",
            (team_id,),
        ).fetchall()
    return [_row_to_team_user(r) for r in rows]


def get_team_user(team_id: str, user_id: str) -> dict[str, Any] | None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT * FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, user_id),
        ).fetchone()
    return _row_to_team_user(r) if r else None


def create_team_user(team_id: str, email: str, is_admin: bool) -> dict[str, Any] | None:
    """新規メンバーを追加する。

    既存メンバーがいる場合は **何も変更せず None を返す**（INSERT OR REPLACE による
    参加日時リセットや権限の意図しない上書きを防ぐ）。権限変更は明示的な更新
    (`update_team_user`) で行うこと。
    """
    email = normalize_email(email)
    now = _now()
    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, email),
        ).fetchone()
        if existing:
            return None
        conn.execute(
            "INSERT INTO team_users"
            " (teamId, userId, username, isAdmin, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (team_id, email, email, 1 if is_admin else 0, now, now),
        )
        r = conn.execute(
            "SELECT * FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, email),
        ).fetchone()
    return _row_to_team_user(r)


def update_team_user(team_id: str, user_id: str, is_admin: bool) -> dict[str, Any] | None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE team_users SET isAdmin = ?, updatedDate = ?"
            " WHERE teamId = ? AND userId = ?",
            (1 if is_admin else 0, _now(), team_id, user_id),
        )
        r = conn.execute(
            "SELECT * FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, user_id),
        ).fetchone()
    return _row_to_team_user(r) if r else None


def delete_team_user(team_id: str, user_id: str) -> None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, user_id),
        )


def count_team_admins(team_id: str) -> int:
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT COUNT(*) AS c FROM team_users WHERE teamId = ? AND isAdmin = 1",
            (team_id,),
        ).fetchone()
    return r["c"]


def is_team_admin(team_id: str, user_id: str) -> bool:
    u = get_team_user(team_id, user_id)
    return bool(u and u["isAdmin"])


def is_team_member(team_id: str, user_id: str) -> bool:
    return get_team_user(team_id, user_id) is not None


def user_admins_any_team(user_id: str) -> bool:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT 1 FROM team_users WHERE userId = ? AND isAdmin = 1 LIMIT 1",
            (user_id,),
        ).fetchone()
    return r is not None


def list_team_ids_for_user(user_id: str) -> list[str]:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT teamId FROM team_users WHERE userId = ?", (user_id,)
        ).fetchall()
    return [r["teamId"] for r in rows]


# 全体公開を表す予約スコープ（全利用者が暗黙保持）。チームIDとは衝突しない固定値。
PUBLIC_SCOPE = "public"


def list_teams_for_member(user_id: str) -> list[dict[str, str]]:
    """利用者が所属するチーム（id+name）。共有先の選択肢に使う。

    共通/管理者ツールの固定チームは共有先にしないため除外する。
    """
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT t.teamId AS teamId, t.teamName AS teamName"
            " FROM teams t JOIN team_users u ON t.teamId = u.teamId"
            " WHERE u.userId = ? ORDER BY t.createdDate ASC",
            (user_id,),
        ).fetchall()
    return [
        {"teamId": r["teamId"], "teamName": r["teamName"]}
        for r in rows
        if r["teamId"] not in (COMMON_TEAM_ID, ADMIN_TEAM_ID)
    ]


# ---------------------------------------------------------------------------
# exApps
# ---------------------------------------------------------------------------
def _row_to_exapp(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "teamId": r["teamId"],
        "exAppId": r["exAppId"],
        "exAppName": r["exAppName"],
        "endpoint": r["endpoint"],
        "apiKey": r["apiKey"],
        "config": r["config"],
        "placeholder": r["placeholder"],
        "systemPrompt": r["systemPrompt"],
        "systemPromptKeyName": r["systemPromptKeyName"],
        "description": r["description"],
        "howToUse": r["howToUse"],
        "copyable": bool(r["copyable"]),
        "status": r["status"],
        "createdDate": r["createdDate"],
        "updatedDate": r["updatedDate"],
    }


def list_team_exapps(team_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM exapps WHERE teamId = ? ORDER BY createdDate ASC",
            (team_id,),
        ).fetchall()
    return [_row_to_exapp(r) for r in rows]


def get_exapp(team_id: str, ex_app_id: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT * FROM exapps WHERE teamId = ? AND exAppId = ?",
            (team_id, ex_app_id),
        ).fetchone()
    return _row_to_exapp(r) if r else None


def get_exapp_by_id(ex_app_id: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT * FROM exapps WHERE exAppId = ?", (ex_app_id,)
        ).fetchone()
    return _row_to_exapp(r) if r else None


def _write_exapp(conn: sqlite3.Connection, ex_app_id: str, team_id: str, data: dict[str, Any]) -> None:
    now = _now()
    conn.execute(
        "INSERT OR REPLACE INTO exapps (exAppId, teamId, exAppName, endpoint, apiKey,"
        " config, placeholder, systemPrompt, systemPromptKeyName, description, howToUse,"
        " copyable, status, createdDate, updatedDate)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            ex_app_id,
            team_id,
            data.get("exAppName", ""),
            data.get("endpoint", ""),
            data.get("apiKey", ""),
            data.get("config", ""),
            data.get("placeholder", ""),
            data.get("systemPrompt"),
            data.get("systemPromptKeyName"),
            data.get("description", ""),
            data.get("howToUse", ""),
            1 if data.get("copyable") else 0,
            data.get("status", "draft"),
            data.get("createdDate", now),
            now,
        ),
    )


def create_exapp(team_id: str, data: dict[str, Any]) -> dict[str, Any]:
    ex_app_id = str(uuid.uuid4())
    with _lock, _connect() as conn:
        _write_exapp(conn, ex_app_id, team_id, data)
        r = conn.execute(
            "SELECT * FROM exapps WHERE exAppId = ?", (ex_app_id,)
        ).fetchone()
    return _row_to_exapp(r)


def update_exapp(team_id: str, ex_app_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    current = get_exapp(team_id, ex_app_id)
    if not current:
        return None
    merged = {**current, **{k: v for k, v in data.items() if v is not None}}
    merged["createdDate"] = current["createdDate"]
    with _lock, _connect() as conn:
        _write_exapp(conn, ex_app_id, team_id, merged)
        r = conn.execute(
            "SELECT * FROM exapps WHERE exAppId = ?", (ex_app_id,)
        ).fetchone()
    return _row_to_exapp(r)


def delete_exapp(team_id: str, ex_app_id: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM exapps WHERE teamId = ? AND exAppId = ?",
            (team_id, ex_app_id),
        )
        conn.execute(
            "DELETE FROM user_app_pins WHERE teamId = ? AND itemId = ?",
            (team_id, ex_app_id),
        )


def copy_exapp(team_id: str, ex_app_id: str, overrides: dict[str, Any]) -> dict[str, Any] | None:
    src = get_exapp(team_id, ex_app_id)
    if not src:
        return None
    data = {**src, **{k: v for k, v in overrides.items() if v is not None}}
    if not overrides.get("exAppName"):
        data["exAppName"] = f"{src['exAppName']} のコピー"
    data.pop("createdDate", None)
    return create_exapp(team_id, data)


def list_visible_exapps(user_id: str, is_system_admin: bool) -> list[dict[str, Any]]:
    """AI アプリ一覧（公開済み）を可視範囲で返す（teamName 付き）。

    - システム管理者: 全チームの公開アプリ
    - それ以外: 所属チーム + 共通チームの公開アプリ（管理者ツールチームは除外）
    """
    teams = {t["teamId"]: t["teamName"] for t in list_teams()}
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM exapps WHERE status = 'published'"
        ).fetchall()
    visible_team_ids = set(list_team_ids_for_user(user_id))
    visible_team_ids.add(COMMON_TEAM_ID)
    result = []
    for r in rows:
        app = _row_to_exapp(r)
        if app["teamId"] == ADMIN_TEAM_ID and not is_system_admin:
            continue
        if is_system_admin or app["teamId"] in visible_team_ids:
            result.append({**app, "teamName": teams.get(app["teamId"], "")})
    return result


# ---------------------------------------------------------------------------
# 利用者ごとの AI アプリ ピン留め（カテゴリ横断・本人のみ）
# ---------------------------------------------------------------------------
def list_user_app_pins(user_id: str) -> list[dict[str, Any]]:
    """本人のピン留め一覧（displayOrder 昇順）。"""
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT teamId, itemId, displayOrder FROM user_app_pins"
            " WHERE userId = ? ORDER BY displayOrder ASC",
            (user_id,),
        ).fetchall()
    return [
        {"teamId": r["teamId"], "itemId": r["itemId"], "displayOrder": r["displayOrder"]}
        for r in rows
    ]


def _is_pinnable_app(user_id: str, team_id: str, item_id: str, is_system_admin: bool) -> bool:
    """ピン留め可能か（本人が見える公開 exApp、または共通チームの GenU 機能）。"""
    if team_id == COMMON_TEAM_ID and item_id in GENU_APP_IDS:
        return True
    visible = list_visible_exapps(user_id, is_system_admin)
    return any(a["teamId"] == team_id and a["exAppId"] == item_id for a in visible)


def add_user_app_pin(
    user_id: str, team_id: str, item_id: str, is_system_admin: bool
) -> tuple[list[dict[str, Any]] | None, str | None]:
    """ピンを追加する。成功時は最新一覧、失敗時はエラーメッセージを返す。"""
    user_id = normalize_email(user_id)
    if not _is_pinnable_app(user_id, team_id, item_id, is_system_admin):
        return None, "ピン留めできないアプリです"
    with _lock, _connect() as conn:
        existing = conn.execute(
            "SELECT 1 FROM user_app_pins WHERE userId = ? AND teamId = ? AND itemId = ?",
            (user_id, team_id, item_id),
        ).fetchone()
        if not existing:
            count_row = conn.execute(
                "SELECT COUNT(*) AS c FROM user_app_pins WHERE userId = ?", (user_id,)
            ).fetchone()
            if int(count_row["c"]) >= MAX_APP_PINS:
                return None, f"ピン留めは{MAX_APP_PINS}件までです"
            max_row = conn.execute(
                "SELECT COALESCE(MAX(displayOrder), -1) AS m FROM user_app_pins"
                " WHERE userId = ?",
                (user_id,),
            ).fetchone()
            next_order = int(max_row["m"]) + 1
            conn.execute(
                "INSERT INTO user_app_pins (userId, teamId, itemId, displayOrder, pinnedDate)"
                " VALUES (?, ?, ?, ?, ?)",
                (user_id, team_id, item_id, next_order, _now()),
            )
    return list_user_app_pins(user_id), None


def remove_user_app_pin(user_id: str, team_id: str, item_id: str) -> list[dict[str, Any]]:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM user_app_pins WHERE userId = ? AND teamId = ? AND itemId = ?",
            (user_id, team_id, item_id),
        )
    return list_user_app_pins(user_id)


# ---------------------------------------------------------------------------
# exApp 実行履歴（会話継続/履歴表示のためにローカルでも保持する）
# ---------------------------------------------------------------------------
def _row_to_history(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "teamId": r["teamId"],
        "teamName": r["teamName"],
        "exAppId": r["exAppId"],
        "exAppName": r["exAppName"],
        "userId": r["userId"],
        "inputs": json.loads(r["inputs"] or "{}"),
        "outputs": r["outputs"],
        "createdDate": r["createdDate"],
        "status": r["status"],
        "progress": r["progress"],
        "artifacts": json.loads(r["artifacts"]) if r["artifacts"] else None,
        "sessionId": r["sessionId"],
    }


def create_exapp_history(data: dict[str, Any]) -> dict[str, Any]:
    """AI アプリの実行結果を履歴として保存する。

    createdDate は (teamId, exAppId) 内で一意になるよう、衝突時は +1ms ずらす。
    """
    team_id = data.get("teamId", "")
    ex_app_id = data.get("exAppId", "")
    created = data.get("createdDate") or _now()
    with _lock, _connect() as conn:
        # 同一ミリ秒の衝突を避ける
        while conn.execute(
            "SELECT 1 FROM exapp_histories WHERE teamId = ? AND exAppId = ? AND createdDate = ?",
            (team_id, ex_app_id, created),
        ).fetchone():
            created = str(int(created) + 1)
        conn.execute(
            "INSERT INTO exapp_histories (teamId, exAppId, createdDate, teamName,"
            " exAppName, userId, inputs, outputs, status, progress, artifacts, sessionId)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                team_id,
                ex_app_id,
                created,
                data.get("teamName", ""),
                data.get("exAppName", ""),
                data.get("userId", ""),
                json.dumps(data.get("inputs") or {}, ensure_ascii=False),
                data.get("outputs", ""),
                data.get("status", "COMPLETED"),
                data.get("progress", ""),
                json.dumps(data["artifacts"], ensure_ascii=False)
                if data.get("artifacts")
                else None,
                data.get("sessionId"),
            ),
        )
        r = conn.execute(
            "SELECT * FROM exapp_histories WHERE teamId = ? AND exAppId = ? AND createdDate = ?",
            (team_id, ex_app_id, created),
        ).fetchone()
    return _row_to_history(r)


def list_exapp_histories(
    team_id: str, ex_app_id: str, user_id: str
) -> list[dict[str, Any]]:
    """指定ユーザーの、特定 AI アプリの実行履歴を新しい順で返す。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM exapp_histories"
            " WHERE teamId = ? AND exAppId = ? AND userId = ?"
            " ORDER BY createdDate DESC",
            (team_id, ex_app_id, user_id),
        ).fetchall()
    return [_row_to_history(r) for r in rows]


def get_exapp_history(
    team_id: str, ex_app_id: str, created_date: str, user_id: str | None = None
) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        if user_id is not None:
            r = conn.execute(
                "SELECT * FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND createdDate = ? AND userId = ?",
                (team_id, ex_app_id, created_date, user_id),
            ).fetchone()
        else:
            r = conn.execute(
                "SELECT * FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND createdDate = ?",
                (team_id, ex_app_id, created_date),
            ).fetchone()
    return _row_to_history(r) if r else None


def list_exapp_histories_older_than(cutoff_created: str) -> list[dict[str, Any]]:
    """createdDate が cutoff より古い実行履歴を返す。"""
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM exapp_histories WHERE createdDate < ?",
            (cutoff_created,),
        ).fetchall()
    return [_row_to_history(r) for r in rows]


def delete_histories_older_than(cutoff_created: str) -> int:
    """createdDate が cutoff より古い実行履歴を削除する。削除件数を返す。"""
    with _lock, _connect() as conn:
        cur = conn.execute(
            "DELETE FROM exapp_histories WHERE createdDate < ?",
            (cutoff_created,),
        )
        return cur.rowcount


def delete_exapp_history(
    team_id: str, ex_app_id: str, created_date: str, user_id: str | None = None
) -> bool:
    with _lock, _connect() as conn:
        if user_id is not None:
            cur = conn.execute(
                "DELETE FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND createdDate = ? AND userId = ?",
                (team_id, ex_app_id, created_date, user_id),
            )
        else:
            cur = conn.execute(
                "DELETE FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND createdDate = ?",
                (team_id, ex_app_id, created_date),
            )
        return cur.rowcount > 0
