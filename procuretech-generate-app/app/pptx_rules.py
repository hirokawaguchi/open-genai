"""html / pptx 共通のスライド規約（プランナへ毎回渡す抜粋）。"""

from __future__ import annotations

from pathlib import Path

RULES_EXCERPT = """\
スライド規約（デジタル庁色。角丸禁止。ご清聴締め禁止）
- タイトルは結論。見出しのコピーにしない。「です」「ます」で終えない。
- タイトルだけ通し読みして 1 本の話になること。ラベル前置き（「現状：」）禁止。
- 「3つの理由」のような中身の個数をタイトルに入れない。
- 1 枚 1 メッセージ。原文に無い数値・固有名を作らない。
- 見せ方は先に基本形: axis-table / premise-conclusion / before-after-split / chart-insight。手順だけ chevron-steps。
- 左＝前提・事実、右＝意味合い。図の下にコメントを敷かない。下部 POINT 帯禁止。
- 出典は左下。評価語（最適・包括的）を根拠なく使わない。
"""


def rules_excerpt() -> str:
    return RULES_EXCERPT.strip()


def rules_full_path() -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / "pptx-slide-rules.md"
