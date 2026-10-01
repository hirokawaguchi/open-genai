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
# 既定の棟（大分市役所。既存データの居場所）。teams_store.DEFAULT_TENANT_ID と一致。
DEFAULT_TENANT_ID = os.environ.get(
    "DEFAULT_TENANT_ID", "00000000-0000-0000-0000-0000000000t1"
)

_DEFAULT_POLICY: dict[str, Any] = {"enabled": False, "default": [], "groups": {}}

# mtime ベースの簡易キャッシュ（predict 毎の読取を避ける）。棟ごとに保持する。
_cache: dict[str, Any] = {"mtime": None, "policies": {}}


def _read_policy_from_db(tenant_id: str) -> dict[str, Any]:
    """棟別ポリシーを読む。行が無ければ無制限（フェイルオープン）。

    既定の棟だけは、未移行の旧・単一行（id=1）も後方互換で参照する。
    """
    if not os.path.exists(POLICY_DB_PATH):
        return dict(_DEFAULT_POLICY)
    try:
        conn = sqlite3.connect(f"file:{POLICY_DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            row = None
            try:
                row = conn.execute(
                    "SELECT policy FROM model_policy_v2 WHERE tenantId = ?",
                    (tenant_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None  # v2 未作成（writer 未更新）。旧表へフォールバック。
            if (not row or not row[0]) and tenant_id == DEFAULT_TENANT_ID:
                try:
                    row = conn.execute(
                        "SELECT policy FROM model_policy WHERE id = 1"
                    ).fetchone()
                except sqlite3.OperationalError:
                    row = None
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


def get_policy(tenant_id: str | None = None) -> dict[str, Any]:
    """指定した棟のポリシーを返す（mtime キャッシュ付き・棟ごと）。"""
    tid = (tenant_id or "").strip() or DEFAULT_TENANT_ID
    try:
        mtime = os.path.getmtime(POLICY_DB_PATH) if os.path.exists(POLICY_DB_PATH) else None
    except OSError:
        mtime = None
    if mtime != _cache["mtime"]:
        _cache["mtime"] = mtime
        _cache["policies"] = {}
    policies = _cache["policies"]
    if tid not in policies:
        policies[tid] = _read_policy_from_db(tid)
    return policies[tid]


def allowed_models(
    scopes: list[str], is_admin: bool, tenant_id: str | None = None
) -> set[str] | None:
    """ユーザーが利用可能なモデル ID 集合。None は「無制限」。

    `scopes` は利用者の所属チームID（team-based）。後方互換として旧 `groups`
    （ロール別）マップも併せて参照する（キーが一致した場合のみ加算許可）。
    判定は開いている棟（tenant_id）のポリシーで行う。
    """
    policy = get_policy(tenant_id)
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


def is_model_allowed(
    scopes: list[str], is_admin: bool, model_id: str, tenant_id: str | None = None
) -> bool:
    allowed = allowed_models(scopes, is_admin, tenant_id)
    if allowed is None:
        return True
    return model_id in allowed
