"""RAG フォルダ（階層・アクセス権限）レジストリ。

本サービス仕様書:
- 6-(10) グループ毎フォルダ作成（上限無制限）
- 6-(11) 2階層以上の階層構造
- 6-(13) フォルダ毎のアクセス権限

設計:
- フォルダは「パス文字列」で表現（例: `総務/例規`）。`/` 区切りで階層＝2階層以上に対応。
  上限は設けない（無制限）。
- Qdrant の各チャンク payload に `folder`（そのフォルダ）と `folder_path`
  （祖先を含むパス配列）を持たせ、サブツリー検索を可能にする（vectorstore 側）。
- アクセス権限は本レジストリ(SQLite)に `scope`+`path`+`allowed_groups` として保持。
  ある操作の可否は「対象フォルダ→祖先」の順で最も近い ACL を継承して判定する。
- パス正規化・祖先計算はネットワーク非依存の純関数（テスト対象）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any

FOLDERS_DB_PATH = os.environ.get("FOLDERS_DB_PATH", "/data/rag_folders.db")

_lock_timeout = 5


# ---------------------------------------------------------------------------
# 純関数: パス正規化・祖先
# ---------------------------------------------------------------------------
def normalize_path(path: str | None) -> str:
    """フォルダパスを正規化する（前後空白除去・スラッシュ整理・先頭末尾スラッシュ除去）。

    空文字はルート（フォルダ指定なし）を意味する。
    """
    if not path:
        return ""
    parts = [seg.strip() for seg in str(path).replace("\\", "/").split("/")]
    parts = [seg for seg in parts if seg and seg not in (".", "..")]
    return "/".join(parts)


def ancestors(path: str) -> list[str]:
    """自身を含む祖先パスの配列を、浅い順で返す。ルート("")は []。

    例: "a/b/c" -> ["a", "a/b", "a/b/c"]
    """
    path = normalize_path(path)
    if not path:
        return []
    segs = path.split("/")
    return ["/".join(segs[: i + 1]) for i in range(len(segs))]


def parent_of(path: str) -> str:
    path = normalize_path(path)
    if "/" not in path:
        return ""
    return path.rsplit("/", 1)[0]


# ---------------------------------------------------------------------------
# SQLite レジストリ
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(FOLDERS_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(FOLDERS_DB_PATH, timeout=_lock_timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS folders ("
            " scope TEXT NOT NULL,"
            " path TEXT NOT NULL,"
            " allowedGroups TEXT NOT NULL DEFAULT '[]',"
            " createdDate TEXT NOT NULL,"
            " updatedDate TEXT NOT NULL,"
            " PRIMARY KEY (scope, path))"
        )


def _now() -> str:
    return str(int(time.time() * 1000))


def create_folder(scope: str, path: str, allowed_groups: list[str] | None = None) -> str:
    """フォルダ（および未登録の祖先）をレジストリに作成する。作成したパスを返す。"""
    path = normalize_path(path)
    if not path:
        return ""
    now = _now()
    groups_json = json.dumps(allowed_groups or [], ensure_ascii=False)
    with _connect() as conn:
        # 祖先を空 ACL で作成（存在しなければ）
        for anc in ancestors(path)[:-1]:
            conn.execute(
                "INSERT OR IGNORE INTO folders (scope, path, allowedGroups, createdDate, updatedDate)"
                " VALUES (?, ?, '[]', ?, ?)",
                (scope, anc, now, now),
            )
        conn.execute(
            "INSERT INTO folders (scope, path, allowedGroups, createdDate, updatedDate)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(scope, path) DO UPDATE SET allowedGroups = excluded.allowedGroups,"
            " updatedDate = excluded.updatedDate",
            (scope, path, groups_json, now, now),
        )
    return path


def set_acl(scope: str, path: str, allowed_groups: list[str]) -> str:
    return create_folder(scope, path, allowed_groups)


def list_folders(scope: str, parent: str | None = None) -> list[dict[str, Any]]:
    """スコープ内のフォルダ一覧。parent 指定時はその直下のみ。"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT path, allowedGroups FROM folders WHERE scope = ? ORDER BY path",
            (scope,),
        ).fetchall()
    result: list[dict[str, Any]] = []
    parent_norm = normalize_path(parent) if parent is not None else None
    for r in rows:
        p = r["path"]
        if parent_norm is not None and parent_of(p) != parent_norm:
            continue
        try:
            groups = json.loads(r["allowedGroups"])
        except (json.JSONDecodeError, TypeError):
            groups = []
        result.append({"path": p, "allowedGroups": groups})
    return result


def delete_folder(scope: str, path: str) -> None:
    """フォルダ（サブツリー含む）をレジストリから削除する。ベクトル削除は呼び出し側。"""
    path = normalize_path(path)
    if not path:
        return
    like = path + "/%"
    with _connect() as conn:
        conn.execute(
            "DELETE FROM folders WHERE scope = ? AND (path = ? OR path LIKE ?)",
            (scope, path, like),
        )


def _get_allowed_groups(conn: sqlite3.Connection, scope: str, path: str) -> list[str] | None:
    row = conn.execute(
        "SELECT allowedGroups FROM folders WHERE scope = ? AND path = ?",
        (scope, path),
    ).fetchone()
    if not row:
        return None
    try:
        groups = json.loads(row["allowedGroups"])
    except (json.JSONDecodeError, TypeError):
        return None
    return groups if groups else None


def effective_allowed_groups(scope: str, path: str) -> list[str] | None:
    """対象→祖先の順で最も近い非空 ACL を返す。無ければ None（＝制限なし）。"""
    path = normalize_path(path)
    if not path:
        return None
    with _connect() as conn:
        for anc in reversed(ancestors(path)):  # 近い順
            groups = _get_allowed_groups(conn, scope, anc)
            if groups:
                return groups
    return None


def can_access(scope: str, path: str, user_groups: list[str], is_admin: bool) -> bool:
    """フォルダへのアクセス可否。管理者は常に可。ACL 未設定は可（制限なし）。"""
    if is_admin:
        return True
    eff = effective_allowed_groups(scope, path)
    if eff is None:
        return True
    ug = set(user_groups or [])
    return any(g in ug for g in eff)
