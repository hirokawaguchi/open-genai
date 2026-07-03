"""モデル利用ポリシーの検証・整形（純ロジック・テスト対象）。

ポリシー JSON（チーム基準）:
    {
      "enabled": true,
      "default": ["gpt-oss:20b"],
      "teams": {"<teamId>": ["gemma3:27b"]}
    }
- 旧 `groups`（ロール別）も後方互換で受理・保持する。
"""

from __future__ import annotations

import json
from typing import Any


def _norm_scope_map(data: dict[str, Any], key: str) -> tuple[dict[str, list[str]] | None, str | None]:
    m = data.get(key, {})
    if not isinstance(m, dict):
        return None, f"`{key}` はオブジェクト(キー→モデルID配列) である必要があります。"
    norm: dict[str, list[str]] = {}
    for name, models in m.items():
        if not isinstance(models, list) or not all(isinstance(x, str) for x in models):
            return None, f"`{key}.{name}` は文字列(モデルID)の配列である必要があります。"
        norm[str(name)] = [str(mm) for mm in models]
    return norm, None


def parse_and_validate(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """ポリシー JSON を検証し、正規化した dict を返す。エラー時は (None, message)。"""
    text = (text or "").strip()
    if not text:
        return None, "ポリシー JSON が空です。"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"JSON として解釈できません: {e}"
    if not isinstance(data, dict):
        return None, "ポリシーはオブジェクト(JSON) である必要があります。"

    enabled = bool(data.get("enabled", False))

    default = data.get("default", [])
    if not isinstance(default, list) or not all(isinstance(x, str) for x in default):
        return None, "`default` は文字列(モデルID)の配列である必要があります。"

    teams, terr = _norm_scope_map(data, "teams")
    if terr:
        return None, terr
    groups, gerr = _norm_scope_map(data, "groups")  # 後方互換
    if gerr:
        return None, gerr

    result: dict[str, Any] = {
        "enabled": enabled,
        "default": [str(m) for m in default],
        "teams": teams,
    }
    # 旧 groups は存在する場合のみ保持（新規はチーム基準）
    if groups:
        result["groups"] = groups
    return result, None


def render_policy(policy: dict[str, Any], team_names: dict[str, str] | None = None) -> str:
    """ポリシーを Markdown で要約する。team_names で teamId→表示名を解決する。"""
    team_names = team_names or {}
    lines = [
        "## 現在のモデル利用ポリシー",
        "",
        f"- 制御: **{'有効' if policy.get('enabled') else '無効（全モデル利用可）'}**",
        f"- 全ユーザー共通で許可 (default): `{', '.join(policy.get('default') or []) or '(なし)'}`",
        "",
        "### チーム別の追加許可",
    ]
    teams = policy.get("teams") or {}
    if not teams:
        lines.append("- (なし)")
    else:
        lines.append("| チーム | 許可モデル |")
        lines.append("| --- | --- |")
        for tid, models in teams.items():
            label = team_names.get(tid, tid)
            lines.append(f"| {label} | {', '.join(models) or '(なし)'} |")
    # 旧 groups が残っている場合のみ参考表示（後方互換）
    legacy = policy.get("groups") or {}
    if legacy:
        lines.append("")
        lines.append("### （旧）グループ別の追加許可 ※後方互換")
        lines.append("| グループ | 許可モデル |")
        lines.append("| --- | --- |")
        for g, models in legacy.items():
            lines.append(f"| {g} | {', '.join(models) or '(なし)'} |")
    lines.append("")
    lines.append(
        "> システム管理者(SystemAdminGroup)は常に全モデル利用可。"
        "制御が「無効」の間は誰でも全モデル利用可。所属チームの許可の和集合が使えます。"
    )
    return "\n".join(lines)
