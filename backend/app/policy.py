"""モデル利用ポリシー（6-(5) 管理者によるモデル利用制御）の読取・判定。

- ポリシーの書き込みは管理者限定 exApp（modelpolicy-app）が担い、backend は
  **読み取り専用**で参照して predict 系の利用可否を強制する（単一ライター構成で
  SQLite のロック競合を避ける）。
- ポリシー未設定/読取不可の場合は「無制限（enabled=false）」として扱う（フェイルオープン）。

ポリシー JSON の形:
    {
      "enabled": true,
      "default": ["gpt-oss:20b"],              # 全ユーザー共通で許可
      "teams": {"<teamId>": ["gemma3:27b"]}    # チーム別に追加許可（所属チームで判定）
    }
- 判定は利用者の所属チーム(teamId)で行う。旧 `groups`（ロール別）も後方互換で併用。
- システム管理者(SystemAdminGroup) は常に全モデル許可。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import Any

POLICY_DB_PATH = os.environ.get("POLICY_DB_PATH", "/data/policy.db")

_DEFAULT_POLICY: dict[str, Any] = {"enabled": False, "default": [], "groups": {}}

# mtime ベースの簡易キャッシュ（predict 毎の読取を避ける）
_cache: dict[str, Any] = {"mtime": None, "policy": _DEFAULT_POLICY}


def _read_policy_from_db() -> dict[str, Any]:
    if not os.path.exists(POLICY_DB_PATH):
        return dict(_DEFAULT_POLICY)
    try:
        conn = sqlite3.connect(f"file:{POLICY_DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute(
                "SELECT policy FROM model_policy WHERE id = 1"
            ).fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return dict(_DEFAULT_POLICY)
        data = json.loads(row[0])
        if not isinstance(data, dict):
            return dict(_DEFAULT_POLICY)
        return data
    except Exception:  # noqa: BLE001 - 読取不可時は無制限扱い（フェイルオープン）
        return dict(_DEFAULT_POLICY)


def get_policy() -> dict[str, Any]:
    """現在のポリシーを返す（mtime キャッシュ付き）。"""
    try:
        mtime = os.path.getmtime(POLICY_DB_PATH) if os.path.exists(POLICY_DB_PATH) else None
    except OSError:
        mtime = None
    if mtime != _cache["mtime"]:
        _cache["policy"] = _read_policy_from_db()
        _cache["mtime"] = mtime
    return _cache["policy"]


def allowed_models(scopes: list[str], is_admin: bool) -> set[str] | None:
    """ユーザーが利用可能なモデル ID 集合。None は「無制限」。

    `scopes` は利用者の所属チームID（team-based）。後方互換として旧 `groups`
    （ロール別）マップも併せて参照する（キーが一致した場合のみ加算許可）。
    """
    policy = get_policy()
    if not policy.get("enabled"):
        return None
    if is_admin:
        return None
    allowed: set[str] = set(policy.get("default") or [])
    scope_map: dict[str, Any] = {}
    scope_map.update(policy.get("groups") or {})  # 旧: ロール別（後方互換）
    scope_map.update(policy.get("teams") or {})  # 新: チーム別
    for s in scopes or []:
        allowed |= set(scope_map.get(s) or [])
    return allowed


def is_model_allowed(scopes: list[str], is_admin: bool, model_id: str) -> bool:
    allowed = allowed_models(scopes, is_admin)
    if allowed is None:
        return True
    return model_id in allowed
