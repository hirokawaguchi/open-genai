"""禁止ワード/機密情報ルールの検証・整形（純ロジック・テスト対象）。

ルール JSON:
    {
      "enabled": true,
      "case_sensitive": false,
      "check_mynumber": true,
      "warn_attachments": true,
      "scan_knowledge_pii": true,
      "check_pii_ner": true,
      "words": ["禁止語1"],
      "patterns": ["\\\\d{3}-\\\\d{4}"]
    }

注: 個人番号は検査用数字付きの専用判定（check_mynumber）。
    パターンに \\d{12} だけを書いても専用判定へ委譲される。
"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_and_validate(text: str) -> tuple[dict[str, Any] | None, str | None]:
    text = (text or "").strip()
    if not text:
        return None, "ルール JSON が空です。"
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"JSON として解釈できません: {e}"
    if not isinstance(data, dict):
        return None, "ルールはオブジェクト(JSON) である必要があります。"

    enabled = bool(data.get("enabled", False))
    case_sensitive = bool(data.get("case_sensitive", False))
    check_mynumber = bool(data.get("check_mynumber", True))
    warn_attachments = bool(data.get("warn_attachments", True))
    scan_knowledge_pii = bool(data.get("scan_knowledge_pii", True))
    check_pii_ner = bool(data.get("check_pii_ner", True))

    words = data.get("words", [])
    if not isinstance(words, list) or not all(isinstance(x, str) for x in words):
        return None, "`words` は文字列の配列である必要があります。"

    patterns = data.get("patterns", [])
    if not isinstance(patterns, list) or not all(isinstance(x, str) for x in patterns):
        return None, "`patterns` は文字列(正規表現)の配列である必要があります。"
    for p in patterns:
        try:
            re.compile(p)
        except re.error as e:
            return None, f"正規表現が不正です: {p!r} ({e})"

    return (
        {
            "enabled": enabled,
            "case_sensitive": case_sensitive,
            "check_mynumber": check_mynumber,
            "warn_attachments": warn_attachments,
            "scan_knowledge_pii": scan_knowledge_pii,
            "check_pii_ner": check_pii_ner,
            "words": [str(w) for w in words if w],
            "patterns": [str(p) for p in patterns if p],
        },
        None,
    )


def render_rules(rules: dict[str, Any]) -> str:
    words = rules.get("words") or []
    patterns = rules.get("patterns") or []
    lines = [
        "## 現在の入力制限ルール",
        "",
        f"- 制御: **{'有効' if rules.get('enabled') else '無効（制限なし）'}**",
        f"- 大文字小文字の区別: {'する' if rules.get('case_sensitive') else 'しない'}",
        f"- マイナンバー検査（検査数字）: "
        f"{'する' if rules.get('check_mynumber', True) else 'しない'}",
        f"- 添付アップロード時の個人情報警告: "
        f"{'する' if rules.get('warn_attachments', True) else 'しない'}",
        f"- ナレッジ登録時の個人情報検知: "
        f"{'する' if rules.get('scan_knowledge_pii', True) else 'しない'}",
        f"- 氏名・住所の NER 検知: "
        f"{'する' if rules.get('check_pii_ner', True) else 'しない'}",
        f"- 禁止ワード数: {len(words)}",
        f"- 機密パターン数: {len(patterns)}",
    ]
    if words:
        lines.append("")
        lines.append("### 禁止ワード")
        lines.extend(f"- `{w}`" for w in words)
    if patterns:
        lines.append("")
        lines.append("### 機密情報パターン（正規表現）")
        lines.extend(f"- `{p}`" for p in patterns)
        lines.append("")
        lines.append(
            "> `\\d{12}` 単体はマイナンバー専用検査（検査数字一致）に委譲されます。"
        )
    lines.append("")
    lines.append(
        "> システム管理者による管理系アプリの実行は本制限の対象外です。"
        "無効の間は制限しません。"
    )
    return "\n".join(lines)
