"""モデル利用ポリシーの検証・整形（純ロジック・テスト対象）。

ポリシー JSON:
    {
      "enabled": true,
      "default": ["gpt-oss:20b"],
      "groups": {"PowerUsers": ["gemma3:27b"]}
    }
"""

from __future__ import annotations

import json
from typing import Any


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

    groups = data.get("groups", {})
    if not isinstance(groups, dict):
        return None, "`groups` はオブジェクト(グループ名→モデルID配列) である必要があります。"
    norm_groups: dict[str, list[str]] = {}
    for gname, models in groups.items():
        if not isinstance(models, list) or not all(isinstance(x, str) for x in models):
            return None, f"`groups.{gname}` は文字列(モデルID)の配列である必要があります。"
        norm_groups[str(gname)] = [str(m) for m in models]

    return (
        {
            "enabled": enabled,
            "default": [str(m) for m in default],
            "groups": norm_groups,
        },
        None,
    )


def render_policy(policy: dict[str, Any]) -> str:
    """ポリシーを Markdown で要約する。"""
    lines = [
        "## 現在のモデル利用ポリシー",
        "",
        f"- 制御: **{'有効' if policy.get('enabled') else '無効（全モデル利用可）'}**",
        f"- 全ユーザー共通で許可 (default): `{', '.join(policy.get('default') or []) or '(なし)'}`",
        "",
        "### グループ別の追加許可",
    ]
    groups = policy.get("groups") or {}
    if not groups:
        lines.append("- (なし)")
    else:
        lines.append("| グループ | 許可モデル |")
        lines.append("| --- | --- |")
        for g, models in groups.items():
            lines.append(f"| {g} | {', '.join(models) or '(なし)'} |")
    lines.append("")
    lines.append(
        "> システム管理者(SystemAdminGroup)は常に全モデル利用可。"
        "制御が「無効」の間は誰でも全モデル利用可。"
    )
    return "\n".join(lines)
