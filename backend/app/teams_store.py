"""チーム / テナント / メンバー / AI アプリ(exApp) の永続化レイヤ (SQLite)。

クラウド版 源内 は DynamoDB + Cognito グループで管理するが、
Open GENAI ではマネージドサービスに依存せず SQLite で完結させる。

- 権限グループ(SystemAdminGroup 等) は Keycloak(SAML) 由来
- テナント（棟）がチームより上位。主鍵 / 招待鍵 / 共有棟の共通鍵で区切る
- チーム単位の管理権限は team_users.isAdmin で表現
- 共通チーム(COMMON_TEAM_ID) はデフォルト棟の部屋（従来の共有ナレッジ）。共有棟の鍵は自動では付与しない
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import unicodedata
import uuid
from typing import Any

DB_PATH = os.environ.get("TEAMS_DB_PATH", "/data/open-genai-teams.db")

COMMON_TEAM_ID = "00000000-0000-0000-0000-000000000000"
# 管理者向けアプリ（監査ログ参照/利用者一括管理/モデル制御/入力制限/RAGナレッジ管理）を
# 共通アプリから分離して表示するための専用チーム。システム管理者のみに見える。
ADMIN_TEAM_ID = "00000000-0000-0000-0000-0000000000a1"
ADMIN_TEAM_NAME = "管理者ツール"

# テナント（棟）。DEFAULT は既存組織の移行先。SHARED は共有棟（COMMON_TEAM の親）。
DEFAULT_TENANT_ID = "00000000-0000-0000-0000-0000000000t1"
SHARED_TENANT_ID = "00000000-0000-0000-0000-0000000000t0"
DEFAULT_TENANT_NAME = "デフォルト"
SHARED_TENANT_NAME = "共有"
TENANT_KIND_ORG = "org"
TENANT_KIND_SHARED = "shared"
TENANT_ROLE_PRIMARY = "primary"
TENANT_ROLE_GUEST = "guest"
TENANT_ROLE_SHARED = "shared"
FIXED_TENANT_IDS = frozenset({DEFAULT_TENANT_ID, SHARED_TENANT_ID})

# GenU 組み込み機能の itemId。共通チームのカタログ（名前・紹介・公開）として登録し、
# ピン留め対象にもする。knowledge は専用ページだが同じカタログで出し分ける。
GENU_APP_IDS = frozenset({"chat", "generate", "translate", "image", "diagram", "knowledge"})

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


def normalize_org_name(name: str | None) -> str:
    """所属・チーム名の表記ゆれを潰す（全角英数→半角、前後空白除去）。

    初期リストの「ＤＸ推進課」と画面入力の「DX推進課」を同一視する。
    """
    return unicodedata.normalize("NFKC", (name or "")).strip()


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
                parentTeamId TEXT,
                createdDate TEXT NOT NULL,
                updatedDate TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS team_users (
                teamId TEXT NOT NULL,
                userId TEXT NOT NULL,
                username TEXT NOT NULL,
                isAdmin INTEGER NOT NULL DEFAULT 0,
                isPrimary INTEGER NOT NULL DEFAULT 0,
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
        _migrate_org_columns(conn)
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
        _migrate_tenants(conn)
        _migrate_app_settings(conn)

    # 共通チームに既定アプリ(RAG 等)をシード
    for app in seed_exapps or []:
        upsert_seed_exapp(app)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_org_columns(conn: sqlite3.Connection) -> None:
    """既存 DB に parentTeamId / isPrimary を加算する。"""
    if "parentTeamId" not in _table_columns(conn, "teams"):
        conn.execute("ALTER TABLE teams ADD COLUMN parentTeamId TEXT")
    if "isPrimary" not in _table_columns(conn, "team_users"):
        conn.execute(
            "ALTER TABLE team_users ADD COLUMN isPrimary INTEGER NOT NULL DEFAULT 0"
        )
        # 既存メンバーは、利用者ごとに最も古い所属を主所属にする
        conn.execute(
            """
            UPDATE team_users SET isPrimary = 1
            WHERE rowid IN (
                SELECT MIN(rowid) FROM team_users GROUP BY userId
            )
            """
        )


# 公式カタログ（棟の機能・おすすめ設定）。未設定時のおすすめもこの順。
OFFICIAL_CATALOG_EXAPP_IDS = (
    "chat",
    "generate",
    "translate",
    "image",
    "diagram",
    "whisper",
    "prompt",
    "chosei",
    "doccheck",
    "patchform",
    "docmaker",
    "procuretech-navigator",
    "procuretech-editor",
    "knowledge",
    "rag",
    "notebook",
    "ssh",
)
DEFAULT_RECOMMENDED_EXAPP_IDS = OFFICIAL_CATALOG_EXAPP_IDS
# 本体に同梱。外部マイクロサービスや画像生成サーバの起動は見ない。
ALWAYS_ON_OFFICIAL_EXAPP_IDS = (
    "chat",
    "generate",
    "translate",
    "diagram",
    "knowledge",
    "rag",
)
RECOMMENDED_SETTING_KEY = "recommendedExAppIds"
# 後からおすすめ候補に足した ID。保存済み設定に無ければ一度だけ既定オンにする。
RECOMMENDED_BACKFILL_IDS = ("rag",)
RECOMMENDED_BACKFILL_KEY = "recommendedExAppIdsBackfill"


def select_running_official_exapp_ids(
    *,
    image_up: bool,
    service_up: dict[str, bool],
) -> list[str]:
    """起動中の公式アプリ ID。棟の機能フラグは見ない（管理画面の候補用）。"""
    ok = set(ALWAYS_ON_OFFICIAL_EXAPP_IDS)
    if image_up:
        ok.add("image")
    ok.update(app_id for app_id, up in service_up.items() if up)
    return [i for i in OFFICIAL_CATALOG_EXAPP_IDS if i in ok]


def _migrate_app_settings(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updatedDate TEXT NOT NULL
        )
        """
    )


def normalize_recommended_exapp_ids(ids: list[str] | None) -> list[str]:
    wanted = {str(i).strip() for i in (ids or []) if str(i).strip()}
    return [i for i in DEFAULT_RECOMMENDED_EXAPP_IDS if i in wanted]


def _read_json_list(conn: sqlite3.Connection, key: str) -> list[str] | None:
    row = conn.execute(
        "SELECT value FROM app_settings WHERE key = ?", (key,)
    ).fetchone()
    if not row:
        return None
    try:
        raw = json.loads(row["value"])
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(raw, list):
        return None
    return [str(x) for x in raw]


def _write_json_list(conn: sqlite3.Connection, key: str, values: list[str]) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value, updatedDate) VALUES (?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
        " updatedDate = excluded.updatedDate",
        (key, json.dumps(values, ensure_ascii=False), _now()),
    )


def get_recommended_exapp_ids() -> list[str]:
    """おすすめに出す公式アプリ。未保存なら既定の全件。"""
    with _lock, _connect() as conn:
        _migrate_app_settings(conn)
        raw = _read_json_list(conn, RECOMMENDED_SETTING_KEY)
        if raw is None:
            return list(DEFAULT_RECOMMENDED_EXAPP_IDS)
        saved = normalize_recommended_exapp_ids(raw)
        done = set(_read_json_list(conn, RECOMMENDED_BACKFILL_KEY) or [])
        add = [
            i
            for i in RECOMMENDED_BACKFILL_IDS
            if i in DEFAULT_RECOMMENDED_EXAPP_IDS and i not in saved and i not in done
        ]
        if add:
            saved = normalize_recommended_exapp_ids([*saved, *add])
            _write_json_list(conn, RECOMMENDED_SETTING_KEY, saved)
            _write_json_list(conn, RECOMMENDED_BACKFILL_KEY, sorted(done | set(add)))
        return saved


def set_recommended_exapp_ids(ids: list[str] | None) -> list[str]:
    normalized = normalize_recommended_exapp_ids(ids)
    with _lock, _connect() as conn:
        _migrate_app_settings(conn)
        _write_json_list(conn, RECOMMENDED_SETTING_KEY, normalized)
        done = set(_read_json_list(conn, RECOMMENDED_BACKFILL_KEY) or [])
        done.update(RECOMMENDED_BACKFILL_IDS)
        _write_json_list(conn, RECOMMENDED_BACKFILL_KEY, sorted(done))
    return normalized


def _migrate_tenants(conn: sqlite3.Connection) -> None:
    """テナント表と teams.tenantId を足し、既存データをデフォルト棟／共有棟へ寄せる。"""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS tenants (
            tenantId TEXT PRIMARY KEY,
            tenantName TEXT NOT NULL,
            kind TEXT NOT NULL DEFAULT 'org',
            features TEXT NOT NULL DEFAULT '{}',
            createdDate TEXT NOT NULL,
            updatedDate TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS tenant_memberships (
            tenantId TEXT NOT NULL,
            userId TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'guest',
            isAdmin INTEGER NOT NULL DEFAULT 0,
            createdDate TEXT NOT NULL,
            updatedDate TEXT NOT NULL,
            PRIMARY KEY (tenantId, userId)
        );
        CREATE TABLE IF NOT EXISTS user_tenant_prefs (
            userId TEXT PRIMARY KEY,
            activeTenantId TEXT,
            updatedDate TEXT NOT NULL
        );
        """
    )
    if "tenantId" not in _table_columns(conn, "teams"):
        conn.execute("ALTER TABLE teams ADD COLUMN tenantId TEXT")
    now = _now()
    for tid, name, kind in (
        (DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME, TENANT_KIND_ORG),
        (SHARED_TENANT_ID, SHARED_TENANT_NAME, TENANT_KIND_SHARED),
    ):
        if not conn.execute(
            "SELECT 1 FROM tenants WHERE tenantId = ?", (tid,)
        ).fetchone():
            conn.execute(
                "INSERT INTO tenants"
                " (tenantId, tenantName, kind, features, createdDate, updatedDate)"
                " VALUES (?, ?, ?, '{}', ?, ?)",
                (tid, name, kind, now, now),
            )
    conn.execute(
        "UPDATE teams SET tenantId = ? WHERE teamId = ?",
        (DEFAULT_TENANT_ID, COMMON_TEAM_ID),
    )
    conn.execute(
        "UPDATE teams SET tenantId = NULL WHERE teamId = ?",
        (ADMIN_TEAM_ID,),
    )
    conn.execute(
        "UPDATE teams SET tenantId = ? WHERE tenantId IS NULL AND teamId NOT IN (?, ?)",
        (DEFAULT_TENANT_ID, COMMON_TEAM_ID, ADMIN_TEAM_ID),
    )
    for row in conn.execute("SELECT DISTINCT userId FROM team_users").fetchall():
        _ensure_home_key(conn, row["userId"])


def upsert_seed_exapp(app: dict[str, Any]) -> None:
    """固定 exAppId の既定アプリを冪等に登録する（RAG など）。

    既存の場合も、配線項目（フォーム定義 placeholder・エンドポイント・API キー・
    config・状態）は最新のシードへ更新する。名前・紹介文・使い方は管理者が共通アプリ
    編集で直していることがあるので、空のときだけシードで埋める。
    """
    with _lock, _connect() as conn:
        exists = conn.execute(
            "SELECT exAppId, teamId, exAppName, description, howToUse, status"
            " FROM exapps WHERE exAppId = ?",
            (app["exAppId"],),
        ).fetchone()
        now = _now()
        new_team = app.get("teamId", COMMON_TEAM_ID)
        if exists:
            old_team = exists["teamId"]
            name = (exists["exAppName"] or "").strip() or app.get("exAppName", "")
            description = (exists["description"] or "").strip() or app.get("description", "")
            how_to_use = (exists["howToUse"] or "").strip() or app.get("howToUse", "")
            # 公開ステータスは管理者がメニュー表示の切り替えに使うので上書きしない
            status = (exists["status"] or "").strip() or app.get("status", "published")
            # teamId もシード定義へ揃える（管理者アプリを専用チームへ移設する移行も兼ねる）
            conn.execute(
                "UPDATE exapps SET teamId=?, exAppName=?, endpoint=?, apiKey=?, config=?,"
                " placeholder=?, description=?, howToUse=?, copyable=?, status=?,"
                " updatedDate=? WHERE exAppId=?",
                (
                    new_team,
                    name,
                    app.get("endpoint", ""),
                    app.get("apiKey", ""),
                    app.get("config", ""),
                    app.get("placeholder", ""),
                    description,
                    how_to_use,
                    1 if app.get("copyable") else 0,
                    status,
                    now,
                    app["exAppId"],
                ),
            )
            # teamId 変更時は履歴・ピン留めも追随（例: rag-manage の ADMIN→COMMON）
            if old_team != new_team:
                team_row = conn.execute(
                    "SELECT teamName FROM teams WHERE teamId = ?", (new_team,)
                ).fetchone()
                if team_row:
                    new_team_name = team_row["teamName"]
                elif new_team == COMMON_TEAM_ID:
                    new_team_name = "共通アプリ"
                elif new_team == ADMIN_TEAM_ID:
                    new_team_name = ADMIN_TEAM_NAME
                else:
                    new_team_name = ""
                conn.execute(
                    "UPDATE exapp_histories SET teamId = ?, teamName = ?"
                    " WHERE teamId = ? AND exAppId = ?",
                    (
                        new_team,
                        new_team_name,
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
# Tenant helpers (conn を既に持っているとき用。外側で _lock)
# ---------------------------------------------------------------------------
def _parse_features(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _row_to_tenant(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "tenantId": r["tenantId"],
        "tenantName": r["tenantName"],
        "kind": r["kind"],
        "features": _parse_features(r["features"] if "features" in r.keys() else "{}"),
        "createdDate": r["createdDate"],
        "updatedDate": r["updatedDate"],
    }


def _row_to_membership(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "tenantId": r["tenantId"],
        "userId": r["userId"],
        "role": r["role"],
        "isAdmin": bool(r["isAdmin"]),
        "createdDate": r["createdDate"],
        "updatedDate": r["updatedDate"],
    }


def _unset_primary_tenant(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute(
        "UPDATE tenant_memberships SET role = ?, updatedDate = ?"
        " WHERE userId = ? AND role = ?",
        (TENANT_ROLE_GUEST, _now(), user_id, TENANT_ROLE_PRIMARY),
    )


def _upsert_membership_conn(
    conn: sqlite3.Connection,
    tenant_id: str,
    user_id: str,
    *,
    role: str,
    is_admin: bool = False,
    overwrite: bool = False,
) -> None:
    user_id = normalize_email(user_id)
    now = _now()
    existing = conn.execute(
        "SELECT role, isAdmin FROM tenant_memberships"
        " WHERE tenantId = ? AND userId = ?",
        (tenant_id, user_id),
    ).fetchone()
    if existing and not overwrite:
        return
    if role == TENANT_ROLE_PRIMARY:
        _unset_primary_tenant(conn, user_id)
    if existing:
        conn.execute(
            "UPDATE tenant_memberships SET role = ?, isAdmin = ?, updatedDate = ?"
            " WHERE tenantId = ? AND userId = ?",
            (role, 1 if is_admin else 0, now, tenant_id, user_id),
        )
        return
    conn.execute(
        "INSERT INTO tenant_memberships"
        " (tenantId, userId, role, isAdmin, createdDate, updatedDate)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (tenant_id, user_id, role, 1 if is_admin else 0, now, now),
    )


def _has_primary_tenant(conn: sqlite3.Connection, user_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM tenant_memberships WHERE userId = ? AND role = ? LIMIT 1",
            (user_id, TENANT_ROLE_PRIMARY),
        ).fetchone()
        is not None
    )


def _ensure_home_key(conn: sqlite3.Connection, user_id: str) -> None:
    """既存利用者にデフォルト棟の主鍵だけ付ける。共有棟は自動では付けない。"""
    user_id = normalize_email(user_id)
    if not user_id:
        return
    role = (
        TENANT_ROLE_PRIMARY
        if not _has_primary_tenant(conn, user_id)
        else TENANT_ROLE_GUEST
    )
    _upsert_membership_conn(conn, DEFAULT_TENANT_ID, user_id, role=role)


def ensure_user_home_tenant(user_id: str) -> None:
    """チーム未所属でもデフォルト棟の主鍵を付ける（ログイン時）。"""
    with _lock, _connect() as conn:
        _ensure_home_key(conn, user_id)


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------
def _row_to_team(r: sqlite3.Row) -> dict[str, Any]:
    keys = set(r.keys())
    parent = r["parentTeamId"] if "parentTeamId" in keys else None
    tenant = r["tenantId"] if "tenantId" in keys else None
    return {
        "teamId": r["teamId"],
        "teamName": r["teamName"],
        "parentTeamId": parent or None,
        "tenantId": tenant or None,
        "createdDate": r["createdDate"],
        "updatedDate": r["updatedDate"],
    }


def _would_cycle(conn: sqlite3.Connection, team_id: str, parent_id: str) -> bool:
    """parent_id を祖先方向へ辿り、team_id に戻れば循環。"""
    seen: set[str] = set()
    current: str | None = parent_id
    while current:
        if current == team_id or current in seen:
            return True
        seen.add(current)
        row = conn.execute(
            "SELECT parentTeamId FROM teams WHERE teamId = ?", (current,)
        ).fetchone()
        current = (row["parentTeamId"] if row else None) or None
    return False


def validate_parent_team_id(
    team_id: str | None,
    parent_team_id: str | None,
    *,
    tenant_id: str | None = None,
) -> str | None:
    """親子設定の妥当性。問題があればメッセージ、なければ None。"""
    parent_team_id = (parent_team_id or "").strip() or None
    if not parent_team_id:
        return None
    if parent_team_id in (COMMON_TEAM_ID, ADMIN_TEAM_ID):
        return "固定チームを親にはできません"
    if team_id and parent_team_id == team_id:
        return "自分自身を親にはできません"
    with _lock, _connect() as conn:
        parent = conn.execute(
            "SELECT teamId, tenantId FROM teams WHERE teamId = ?", (parent_team_id,)
        ).fetchone()
        if not parent:
            return "親チームが見つかりません"
        parent_tenant = parent["tenantId"] if "tenantId" in parent.keys() else None
        if tenant_id and parent_tenant and parent_tenant != tenant_id:
            return "親チームは同じ棟のチームにしてください"
        if team_id and _would_cycle(conn, team_id, parent_team_id):
            return "親チームの指定が循環しています"
    return None


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


def create_team(
    team_name: str,
    admin_email: str,
    parent_team_id: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any]:
    team_id = str(uuid.uuid4())
    admin_email = normalize_email(admin_email)
    team_name = normalize_org_name(team_name)
    parent_team_id = (parent_team_id or "").strip() or None
    tenant_id = (tenant_id or "").strip() or None
    now = _now()
    with _lock, _connect() as conn:
        if parent_team_id and not tenant_id:
            parent = conn.execute(
                "SELECT tenantId FROM teams WHERE teamId = ?", (parent_team_id,)
            ).fetchone()
            if parent and parent["tenantId"]:
                tenant_id = parent["tenantId"]
        if not tenant_id:
            tenant_id = DEFAULT_TENANT_ID
        has_primary = conn.execute(
            "SELECT 1 FROM team_users WHERE userId = ? AND isPrimary = 1 LIMIT 1",
            (admin_email,),
        ).fetchone()
        conn.execute(
            "INSERT INTO teams"
            " (teamId, teamName, parentTeamId, tenantId, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (team_id, team_name, parent_team_id, tenant_id, now, now),
        )
        conn.execute(
            "INSERT INTO team_users"
            " (teamId, userId, username, isAdmin, isPrimary, createdDate, updatedDate)"
            " VALUES (?, ?, ?, 1, ?, ?, ?)",
            (team_id, admin_email, admin_email, 0 if has_primary else 1, now, now),
        )
        if tenant_id == SHARED_TENANT_ID:
            _upsert_membership_conn(
                conn, SHARED_TENANT_ID, admin_email, role=TENANT_ROLE_SHARED
            )
        else:
            role = (
                TENANT_ROLE_PRIMARY
                if not _has_primary_tenant(conn, admin_email)
                else TENANT_ROLE_GUEST
            )
            _upsert_membership_conn(conn, tenant_id, admin_email, role=role)
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


def update_team(
    team_id: str, team_name: str, parent_team_id: str | None | object = ...
) -> dict[str, Any] | None:
    team_name = normalize_org_name(team_name)
    with _lock, _connect() as conn:
        if parent_team_id is ...:
            conn.execute(
                "UPDATE teams SET teamName = ?, updatedDate = ? WHERE teamId = ?",
                (team_name, _now(), team_id),
            )
        else:
            parent = (parent_team_id or "").strip() or None
            conn.execute(
                "UPDATE teams SET teamName = ?, parentTeamId = ?, updatedDate = ?"
                " WHERE teamId = ?",
                (team_name, parent, _now(), team_id),
            )
        r = conn.execute(
            "SELECT * FROM teams WHERE teamId = ?", (team_id,)
        ).fetchone()
    return _row_to_team(r) if r else None


def delete_team(team_id: str) -> None:
    with _lock, _connect() as conn:
        parent_row = conn.execute(
            "SELECT parentTeamId FROM teams WHERE teamId = ?", (team_id,)
        ).fetchone()
        new_parent = (parent_row["parentTeamId"] if parent_row else None) or None
        conn.execute(
            "UPDATE teams SET parentTeamId = ? WHERE parentTeamId = ?",
            (new_parent, team_id),
        )
        conn.execute("DELETE FROM user_app_pins WHERE teamId = ?", (team_id,))
        conn.execute("DELETE FROM exapps WHERE teamId = ?", (team_id,))
        conn.execute("DELETE FROM team_users WHERE teamId = ?", (team_id,))
        conn.execute("DELETE FROM teams WHERE teamId = ?", (team_id,))


# ---------------------------------------------------------------------------
# Team users (members)
# ---------------------------------------------------------------------------
def _row_to_team_user(r: sqlite3.Row) -> dict[str, Any]:
    keys = set(r.keys())
    return {
        "teamId": r["teamId"],
        "userId": r["userId"],
        "username": r["username"],
        "isAdmin": bool(r["isAdmin"]),
        "isPrimary": bool(r["isPrimary"]) if "isPrimary" in keys else False,
        "createdDate": r["createdDate"],
        "updatedDate": r["updatedDate"],
    }


def _unset_primary(conn: sqlite3.Connection, user_id: str) -> None:
    conn.execute(
        "UPDATE team_users SET isPrimary = 0, updatedDate = ? WHERE userId = ?",
        (_now(), user_id),
    )


def _user_has_primary(conn: sqlite3.Connection, user_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM team_users WHERE userId = ? AND isPrimary = 1 LIMIT 1",
            (user_id,),
        ).fetchone()
        is not None
    )


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


def create_team_user(
    team_id: str, email: str, is_admin: bool, is_primary: bool | None = None
) -> dict[str, Any] | None:
    """新規メンバーを追加する。

    既存メンバーがいる場合は **何も変更せず None を返す**（INSERT OR REPLACE による
    参加日時リセットや権限の意図しない上書きを防ぐ）。権限変更は明示的な更新
    (`update_team_user`) で行うこと。
    is_primary 未指定なら、主所属が無い利用者だけ主所属にする。
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
        if is_primary is None:
            is_primary = not _user_has_primary(conn, email)
        if is_primary:
            _unset_primary(conn, email)
        conn.execute(
            "INSERT INTO team_users"
            " (teamId, userId, username, isAdmin, isPrimary, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (team_id, email, email, 1 if is_admin else 0, 1 if is_primary else 0, now, now),
        )
        team_row = conn.execute(
            "SELECT tenantId FROM teams WHERE teamId = ?", (team_id,)
        ).fetchone()
        tenant_id = (team_row["tenantId"] if team_row else None) or DEFAULT_TENANT_ID
        if tenant_id == SHARED_TENANT_ID:
            _upsert_membership_conn(
                conn, SHARED_TENANT_ID, email, role=TENANT_ROLE_SHARED
            )
        else:
            role = (
                TENANT_ROLE_PRIMARY
                if not _has_primary_tenant(conn, email)
                else TENANT_ROLE_GUEST
            )
            _upsert_membership_conn(conn, tenant_id, email, role=role)
        r = conn.execute(
            "SELECT * FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, email),
        ).fetchone()
    return _row_to_team_user(r)


def update_team_user(
    team_id: str,
    user_id: str,
    is_admin: bool,
    is_primary: bool | None = None,
) -> dict[str, Any] | None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        if is_primary:
            _unset_primary(conn, user_id)
        sets = "isAdmin = ?, updatedDate = ?"
        params: list[Any] = [1 if is_admin else 0, _now()]
        if is_primary is not None:
            sets += ", isPrimary = ?"
            params.append(1 if is_primary else 0)
        params.extend([team_id, user_id])
        conn.execute(
            f"UPDATE team_users SET {sets} WHERE teamId = ? AND userId = ?",
            params,
        )
        r = conn.execute(
            "SELECT * FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, user_id),
        ).fetchone()
    return _row_to_team_user(r) if r else None


def delete_team_user(team_id: str, user_id: str) -> None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        row = conn.execute(
            "SELECT isPrimary FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, user_id),
        ).fetchone()
        conn.execute(
            "DELETE FROM team_users WHERE teamId = ? AND userId = ?",
            (team_id, user_id),
        )
        if row and row["isPrimary"]:
            nxt = conn.execute(
                "SELECT teamId FROM team_users WHERE userId = ?"
                " ORDER BY createdDate ASC LIMIT 1",
                (user_id,),
            ).fetchone()
            if nxt:
                conn.execute(
                    "UPDATE team_users SET isPrimary = 1, updatedDate = ?"
                    " WHERE teamId = ? AND userId = ?",
                    (_now(), nxt["teamId"], user_id),
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


def get_primary_team_id(user_id: str) -> str | None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT teamId FROM team_users WHERE userId = ? AND isPrimary = 1 LIMIT 1",
            (user_id,),
        ).fetchone()
    return r["teamId"] if r else None


def list_descendant_team_ids(team_id: str) -> list[str]:
    """team_id の子孫（自身は含まない）。深さ優先で循環を防ぐ。"""
    if not team_id:
        return []
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT teamId, parentTeamId FROM teams").fetchall()
    children: dict[str, list[str]] = {}
    for r in rows:
        parent = r["parentTeamId"]
        if parent:
            children.setdefault(parent, []).append(r["teamId"])
    out: list[str] = []
    stack = list(children.get(team_id, []))
    seen = {team_id}
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        out.append(current)
        stack.extend(children.get(current, []))
    return out


def list_effective_team_ids_for_user(user_id: str) -> list[str]:
    """読取用タグ = 明示所属 + 主所属の子孫。追加タグ（兼務）は展開しない。"""
    member_ids = list_team_ids_for_user(user_id)
    primary = get_primary_team_id(user_id)
    result = set(member_ids)
    if primary:
        result.update(list_descendant_team_ids(primary))
    return [tid for tid in result if tid]


def can_read_team(team_id: str, user_id: str) -> bool:
    return team_id in list_effective_team_ids_for_user(user_id)


def list_inherited_teams_for_user(user_id: str) -> list[dict[str, str]]:
    """主所属の子孫のうち、明示所属していないチーム（閲覧専用）。"""
    member_ids = set(list_team_ids_for_user(user_id))
    primary = get_primary_team_id(user_id)
    if not primary:
        return []
    inherited_ids = [
        tid for tid in list_descendant_team_ids(primary) if tid not in member_ids
    ]
    if not inherited_ids:
        return []
    placeholders = ",".join("?" for _ in inherited_ids)
    with _lock, _connect() as conn:
        rows = conn.execute(
            f"SELECT teamId, teamName FROM teams WHERE teamId IN ({placeholders})"
            " ORDER BY createdDate ASC",
            inherited_ids,
        ).fetchall()
    return [
        {"teamId": r["teamId"], "teamName": r["teamName"]}
        for r in rows
        if r["teamId"] not in (COMMON_TEAM_ID, ADMIN_TEAM_ID)
    ]


# 全体公開を表す予約スコープ（全利用者が暗黙保持）。チームIDとは衝突しない固定値。
PUBLIC_SCOPE = "public"


def list_teams_for_member(user_id: str) -> list[dict[str, Any]]:
    """利用者が所属するチーム（id+name）。共有先の選択肢に使う。

    共通/管理者ツールの固定チームは共有先にしないため除外する。
    配下の閲覧専用チームは含めない（明示所属だけ）。
    """
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT t.teamId AS teamId, t.teamName AS teamName,"
            " u.isPrimary AS isPrimary"
            " FROM teams t JOIN team_users u ON t.teamId = u.teamId"
            " WHERE u.userId = ? ORDER BY t.createdDate ASC",
            (user_id,),
        ).fetchall()
    return [
        {
            "teamId": r["teamId"],
            "teamName": r["teamName"],
            "isPrimary": bool(r["isPrimary"]),
        }
        for r in rows
        if r["teamId"] not in (COMMON_TEAM_ID, ADMIN_TEAM_ID)
    ]


# ---------------------------------------------------------------------------
# Tenant (棟)
# ---------------------------------------------------------------------------
def list_tenants() -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tenants ORDER BY kind DESC, createdDate ASC"
        ).fetchall()
    return [_row_to_tenant(r) for r in rows]


def get_tenant(tenant_id: str) -> dict[str, Any] | None:
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT * FROM tenants WHERE tenantId = ?", (tenant_id,)
        ).fetchone()
    return _row_to_tenant(r) if r else None


def create_tenant(
    tenant_name: str,
    *,
    kind: str = TENANT_KIND_ORG,
    features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tenant_id = str(uuid.uuid4())
    tenant_name = normalize_org_name(tenant_name)
    if kind not in (TENANT_KIND_ORG, TENANT_KIND_SHARED):
        kind = TENANT_KIND_ORG
    now = _now()
    feat = json.dumps(features or {}, ensure_ascii=False)
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO tenants"
            " (tenantId, tenantName, kind, features, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (tenant_id, tenant_name, kind, feat, now, now),
        )
        r = conn.execute(
            "SELECT * FROM tenants WHERE tenantId = ?", (tenant_id,)
        ).fetchone()
    return _row_to_tenant(r)


def update_tenant(
    tenant_id: str,
    *,
    tenant_name: str | None = None,
    features: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    current = get_tenant(tenant_id)
    if not current:
        return None
    name = (
        normalize_org_name(tenant_name)
        if tenant_name is not None
        else current["tenantName"]
    )
    feat = json.dumps(
        features if features is not None else current["features"],
        ensure_ascii=False,
    )
    with _lock, _connect() as conn:
        conn.execute(
            "UPDATE tenants SET tenantName = ?, features = ?, updatedDate = ?"
            " WHERE tenantId = ?",
            (name, feat, _now(), tenant_id),
        )
        r = conn.execute(
            "SELECT * FROM tenants WHERE tenantId = ?", (tenant_id,)
        ).fetchone()
    return _row_to_tenant(r) if r else None


def delete_tenant(tenant_id: str) -> str | None:
    """削除する。問題があればメッセージ、なければ None。"""
    if tenant_id in FIXED_TENANT_IDS:
        return "固定の棟は削除できません"
    tenant = get_tenant(tenant_id)
    if not tenant:
        return "棟が見つかりません"
    with _lock, _connect() as conn:
        used = conn.execute(
            "SELECT 1 FROM teams WHERE tenantId = ? LIMIT 1", (tenant_id,)
        ).fetchone()
        if used:
            return "チームが残っている棟は削除できません"
        conn.execute(
            "DELETE FROM tenant_memberships WHERE tenantId = ?", (tenant_id,)
        )
        conn.execute(
            "UPDATE user_tenant_prefs SET activeTenantId = NULL"
            " WHERE activeTenantId = ?",
            (tenant_id,),
        )
        conn.execute("DELETE FROM tenants WHERE tenantId = ?", (tenant_id,))
    return None


def list_tenant_memberships(tenant_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM tenant_memberships WHERE tenantId = ?"
            " ORDER BY createdDate ASC",
            (tenant_id,),
        ).fetchall()
    return [_row_to_membership(r) for r in rows]


def get_tenant_membership(tenant_id: str, user_id: str) -> dict[str, Any] | None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT * FROM tenant_memberships WHERE tenantId = ? AND userId = ?",
            (tenant_id, user_id),
        ).fetchone()
    return _row_to_membership(r) if r else None


def upsert_tenant_membership(
    tenant_id: str,
    user_id: str,
    *,
    role: str,
    is_admin: bool = False,
) -> dict[str, Any] | None:
    """主鍵 / 招待鍵 / 共通鍵を渡す。tenant が無ければ None。"""
    if role not in (
        TENANT_ROLE_PRIMARY,
        TENANT_ROLE_GUEST,
        TENANT_ROLE_SHARED,
    ):
        role = TENANT_ROLE_GUEST
    if not get_tenant(tenant_id):
        return None
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        _upsert_membership_conn(
            conn, tenant_id, user_id, role=role, is_admin=is_admin, overwrite=True
        )
        r = conn.execute(
            "SELECT * FROM tenant_memberships WHERE tenantId = ? AND userId = ?",
            (tenant_id, user_id),
        ).fetchone()
    return _row_to_membership(r) if r else None


def remove_tenant_membership(tenant_id: str, user_id: str) -> None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM tenant_memberships WHERE tenantId = ? AND userId = ?",
            (tenant_id, user_id),
        )
        pref = conn.execute(
            "SELECT activeTenantId FROM user_tenant_prefs WHERE userId = ?",
            (user_id,),
        ).fetchone()
        if pref and pref["activeTenantId"] == tenant_id:
            conn.execute(
                "UPDATE user_tenant_prefs SET activeTenantId = NULL, updatedDate = ?"
                " WHERE userId = ?",
                (_now(), user_id),
            )


def list_tenants_for_user(user_id: str) -> list[dict[str, Any]]:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT t.*, m.role AS role, m.isAdmin AS isAdmin"
            " FROM tenants t JOIN tenant_memberships m ON t.tenantId = m.tenantId"
            " WHERE m.userId = ? ORDER BY t.kind DESC, t.createdDate ASC",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        item = _row_to_tenant(r)
        item["role"] = r["role"]
        item["isAdmin"] = bool(r["isAdmin"])
        out.append(item)
    return out


def get_primary_tenant_id(user_id: str) -> str | None:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT tenantId FROM tenant_memberships"
            " WHERE userId = ? AND role = ? LIMIT 1",
            (user_id, TENANT_ROLE_PRIMARY),
        ).fetchone()
    return r["tenantId"] if r else None


def can_access_tenant(tenant_id: str, user_id: str) -> bool:
    return get_tenant_membership(tenant_id, user_id) is not None


def is_tenant_admin(tenant_id: str, user_id: str) -> bool:
    m = get_tenant_membership(tenant_id, user_id)
    return bool(m and m["isAdmin"])


def tenant_id_of_team(team_id: str) -> str | None:
    team = get_team(team_id)
    return (team or {}).get("tenantId")


def is_tenant_admin_of_team(user_id: str, team_id: str) -> bool:
    """そのチームが属する棟の管理者か。基盤専用チームは対象外。"""
    tid = tenant_id_of_team(team_id)
    if not tid:
        return False
    return is_tenant_admin(tid, user_id)


def list_tenant_ids_administered(user_id: str) -> list[str]:
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT tenantId FROM tenant_memberships"
            " WHERE userId = ? AND isAdmin = 1",
            (user_id,),
        ).fetchall()
    return [r["tenantId"] for r in rows]


def list_teams_for_tenant_admin(user_id: str) -> list[dict[str, Any]]:
    """棟管理者が見られるチーム（管理対象棟のチーム）。"""
    tenant_ids = list_tenant_ids_administered(user_id)
    if not tenant_ids:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tid in tenant_ids:
        for team in list_teams_in_tenant(tid):
            if team["teamId"] in seen or team["teamId"] == ADMIN_TEAM_ID:
                continue
            seen.add(team["teamId"])
            out.append(team)
    return out


def get_active_tenant_id(user_id: str, *, allow_any: bool = False) -> str:
    """活性棟。保存値が鍵に含まれるならそれ、なければ主鍵、なければデフォルト棟。"""
    user_id = normalize_email(user_id)
    with _lock, _connect() as conn:
        pref = conn.execute(
            "SELECT activeTenantId FROM user_tenant_prefs WHERE userId = ?",
            (user_id,),
        ).fetchone()
        saved = (pref["activeTenantId"] if pref else None) or None
        if saved:
            exists = conn.execute(
                "SELECT 1 FROM tenants WHERE tenantId = ?", (saved,)
            ).fetchone()
            member = conn.execute(
                "SELECT 1 FROM tenant_memberships WHERE tenantId = ? AND userId = ?",
                (saved, user_id),
            ).fetchone()
            if exists and (allow_any or member):
                return saved
    primary = get_primary_tenant_id(user_id)
    if primary:
        return primary
    if can_access_tenant(SHARED_TENANT_ID, user_id):
        return SHARED_TENANT_ID
    return DEFAULT_TENANT_ID


def set_active_tenant_id(
    user_id: str, tenant_id: str, *, allow_any: bool = False
) -> str | None:
    """活性棟を保存。鍵が無ければメッセージ。"""
    user_id = normalize_email(user_id)
    if not get_tenant(tenant_id):
        return "棟が見つかりません"
    if not allow_any and not can_access_tenant(tenant_id, user_id):
        return "この棟の鍵がありません"
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO user_tenant_prefs (userId, activeTenantId, updatedDate)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(userId) DO UPDATE SET"
            " activeTenantId = excluded.activeTenantId,"
            " updatedDate = excluded.updatedDate",
            (user_id, tenant_id, _now()),
        )
    return None


def list_teams_in_tenant(tenant_id: str) -> list[dict[str, Any]]:
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM teams WHERE tenantId = ? ORDER BY createdDate ASC",
            (tenant_id,),
        ).fetchall()
    return [_row_to_team(r) for r in rows]


def visible_tenant_ids_for_scope(active_tenant_id: str) -> set[str]:
    """活性棟で見てよい tenantId。共有棟は活性が共有のときだけ。"""
    return {active_tenant_id}


def team_visible_in_tenant(team_id: str, active_tenant_id: str) -> bool:
    """活性棟からそのチームのナレッジ／アプリを見てよいか。"""
    if team_id == ADMIN_TEAM_ID:
        return False
    team = get_team(team_id)
    if not team:
        return False
    tid = team.get("tenantId")
    return tid in visible_tenant_ids_for_scope(active_tenant_id)


def filter_team_ids_for_tenant(
    team_ids: list[str], active_tenant_id: str
) -> list[str]:
    allowed = visible_tenant_ids_for_scope(active_tenant_id)
    out: list[str] = []
    for tid in team_ids:
        if tid == ADMIN_TEAM_ID:
            continue
        team = get_team(tid)
        if team and team.get("tenantId") in allowed:
            out.append(tid)
    return out


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


def is_builtin_exapp(app: dict[str, Any] | None) -> bool:
    """源内の汎用ページ（チャット等）をカタログ登録した組み込みアプリか。"""
    if not app:
        return False
    try:
        cfg = json.loads(app.get("config") or "{}")
    except (json.JSONDecodeError, TypeError):
        return False
    return bool(cfg.get("builtin"))


def list_builtin_exapps() -> list[dict[str, Any]]:
    """組み込みカタログ（下書き含む）。メニュー表示の判定用。"""
    teams = {t["teamId"]: t["teamName"] for t in list_teams()}
    with _lock, _connect() as conn:
        rows = conn.execute("SELECT * FROM exapps").fetchall()
    result = []
    for r in rows:
        app = _row_to_exapp(r)
        if is_builtin_exapp(app):
            result.append({**app, "teamName": teams.get(app["teamId"], "")})
    return result


def update_exapp(team_id: str, ex_app_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    current = get_exapp(team_id, ex_app_id)
    if not current:
        return None
    incoming = {k: v for k, v in data.items() if v is not None}
    if is_builtin_exapp(current):
        incoming = {
            k: incoming[k]
            for k in ("exAppName", "description", "howToUse", "status")
            if k in incoming
        }
    merged = {**current, **incoming}
    merged["createdDate"] = current["createdDate"]
    with _lock, _connect() as conn:
        _write_exapp(conn, ex_app_id, team_id, merged)
        r = conn.execute(
            "SELECT * FROM exapps WHERE exAppId = ?", (ex_app_id,)
        ).fetchone()
    return _row_to_exapp(r)


def delete_exapp(team_id: str, ex_app_id: str) -> bool:
    """削除する。組み込みカタログは削除不可（False）。"""
    current = get_exapp(team_id, ex_app_id)
    if current and is_builtin_exapp(current):
        return False
    with _lock, _connect() as conn:
        conn.execute(
            "DELETE FROM exapps WHERE teamId = ? AND exAppId = ?",
            (team_id, ex_app_id),
        )
        conn.execute(
            "DELETE FROM user_app_pins WHERE teamId = ? AND itemId = ?",
            (team_id, ex_app_id),
        )
    return True


def reassign_exapp_refs(team_id: str, old_id: str, new_id: str) -> None:
    """旧 exAppId のピン・履歴を新 ID へ付け替える。

    新 ID 側に既にあるピンは旧側を捨てる（PK 衝突回避）。履歴は両方残してよいので
    旧 ID のままにする（監査の識別子を書き換えない）。
    """
    with _lock, _connect() as conn:
        conflict_users = [
            r["userId"]
            for r in conn.execute(
                "SELECT userId FROM user_app_pins WHERE teamId = ? AND itemId = ?",
                (team_id, new_id),
            ).fetchall()
        ]
        if conflict_users:
            placeholders = ",".join("?" for _ in conflict_users)
            conn.execute(
                f"DELETE FROM user_app_pins WHERE teamId = ? AND itemId = ?"
                f" AND userId IN ({placeholders})",
                (team_id, old_id, *conflict_users),
            )
        conn.execute(
            "UPDATE user_app_pins SET itemId = ? WHERE teamId = ? AND itemId = ?",
            (new_id, team_id, old_id),
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


def list_knowledge_scopes(
    user_id: str, is_system_admin: bool, tenant_id: str | None = None
) -> list[dict[str, Any]]:
    """ナレッジ UI 用のスコープ一覧（活性棟のチーム。共通は自棟にあるときだけ）。"""
    active = tenant_id or get_active_tenant_id(user_id)
    scopes: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(scope: str, name: str, kind: str, can_manage: bool) -> None:
        if scope in seen:
            if can_manage:
                for item in scopes:
                    if item["scope"] == scope:
                        item["canManage"] = True
            return
        seen.add(scope)
        scopes.append(
            {"scope": scope, "name": name, "kind": kind, "canManage": can_manage}
        )

    if team_visible_in_tenant(COMMON_TEAM_ID, active):
        _add(
            COMMON_TEAM_ID,
            "共有ナレッジ（共通）",
            "common",
            is_system_admin or is_tenant_admin_of_team(user_id, COMMON_TEAM_ID),
        )
    for t in list_teams_for_tenant_admin(user_id):
        if t["teamId"] in (COMMON_TEAM_ID, ADMIN_TEAM_ID):
            continue
        if not team_visible_in_tenant(t["teamId"], active):
            continue
        _add(t["teamId"], t.get("teamName") or t["teamId"], "team", True)
    for t in list_teams_for_member(user_id):
        if t["teamId"] in (COMMON_TEAM_ID, ADMIN_TEAM_ID):
            continue
        if not team_visible_in_tenant(t["teamId"], active):
            continue
        _add(t["teamId"], t.get("teamName") or t["teamId"], "team", True)
    for t in list_inherited_teams_for_user(user_id):
        if t["teamId"] in (COMMON_TEAM_ID, ADMIN_TEAM_ID):
            continue
        if not team_visible_in_tenant(t["teamId"], active):
            continue
        _add(
            t["teamId"],
            f"{t.get('teamName') or t['teamId']}（配下・閲覧）",
            "team",
            False,
        )
    return scopes


def builtin_feature_enabled(tenant_id: str | None, ex_app_id: str) -> bool:
    """tenants.features で組み込みアプリを隠す。キーが無ければ出す。"""
    if not tenant_id or not ex_app_id:
        return True
    tenant = get_tenant(tenant_id)
    if not tenant:
        return True
    features = tenant.get("features") or {}
    if ex_app_id not in features:
        return True
    return bool(features[ex_app_id])


def list_visible_exapps(
    user_id: str,
    is_system_admin: bool,
    tenant_id: str | None = None,
) -> list[dict[str, Any]]:
    """AI アプリ一覧（公開済み）を可視範囲で返す（teamName 付き）。

    - システム管理者: 活性棟＋共有棟（管理者ツールは常に可）
    - それ以外: 明示所属 + 主所属の配下 + 共通チーム（管理者ツールは除外）
    """
    teams = {t["teamId"]: t["teamName"] for t in list_teams()}
    with _lock, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM exapps WHERE status = 'published'"
        ).fetchall()
    visible_team_ids = set(list_effective_team_ids_for_user(user_id))
    if tenant_id:
        if team_visible_in_tenant(COMMON_TEAM_ID, tenant_id):
            visible_team_ids.add(COMMON_TEAM_ID)
        visible_team_ids = set(
            filter_team_ids_for_tenant(list(visible_team_ids), tenant_id)
        )
    else:
        visible_team_ids.add(COMMON_TEAM_ID)
    result = []
    for r in rows:
        app = _row_to_exapp(r)
        if app["teamId"] == ADMIN_TEAM_ID and not is_system_admin:
            continue
        if is_system_admin and app["teamId"] == ADMIN_TEAM_ID:
            result.append({**app, "teamName": teams.get(app["teamId"], "")})
            continue
        if is_system_admin or app["teamId"] in visible_team_ids:
            if tenant_id and app["teamId"] != ADMIN_TEAM_ID:
                if not team_visible_in_tenant(app["teamId"], tenant_id):
                    continue
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
        app = get_exapp(COMMON_TEAM_ID, item_id)
        # 未シード環境の後方互換。登録済みなら公開中だけピン留め可。
        if app is None:
            return True
        return app.get("status") == "published"
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


def list_exapp_histories_by_session(
    team_id: str, ex_app_id: str, session_id: str, user_id: str | None = None
) -> list[dict[str, Any]]:
    """同一 sessionId の実行履歴を古い順で返す（会話単位の削除用）。"""
    if not session_id:
        return []
    with _lock, _connect() as conn:
        if user_id is not None:
            rows = conn.execute(
                "SELECT * FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND sessionId = ? AND userId = ?"
                " ORDER BY createdDate ASC",
                (team_id, ex_app_id, session_id, user_id),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND sessionId = ?"
                " ORDER BY createdDate ASC",
                (team_id, ex_app_id, session_id),
            ).fetchall()
    return [_row_to_history(r) for r in rows]


def delete_exapp_histories_by_session(
    team_id: str, ex_app_id: str, session_id: str, user_id: str | None = None
) -> int:
    """同一 sessionId の実行履歴をまとめて削除する。削除件数を返す。"""
    if not session_id:
        return 0
    with _lock, _connect() as conn:
        if user_id is not None:
            cur = conn.execute(
                "DELETE FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND sessionId = ? AND userId = ?",
                (team_id, ex_app_id, session_id, user_id),
            )
        else:
            cur = conn.execute(
                "DELETE FROM exapp_histories"
                " WHERE teamId = ? AND exAppId = ? AND sessionId = ?",
                (team_id, ex_app_id, session_id),
            )
        return cur.rowcount
