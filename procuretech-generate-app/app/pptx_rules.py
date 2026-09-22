"""html / pptx 共通のスライド規約（プランナへ毎回渡す抜粋）。"""

from __future__ import annotations

from pathlib import Path

RULES_EXCERPT = """\
スライド規約（デジタル庁色。角丸禁止。ご清聴締め禁止）
- タイトルは主語と述語のある完全文。原文に判断があれば事実＋含意。無ければ事実文。推奨（すべきだ）を作らない。見出しのコピーにしない。「です」「ます」で終えない。
- 「A。B」の二段構え・体言止め・ダッシュ・「本ページ」禁止。ラベル前置き（「現状：」）禁止。
- 「3つの理由」のような中身の個数をタイトルに入れない。数字は実質値だけ最大2つ。30〜60字（まず36字）。
- 1 枚 1 メッセージ。溢れたら分割。原文に無い数値・固有名を作らない。
- 見せ方は用途で引く: explain / decompose / compare / change / time / relation。基本形は fullwidth-points / axis-table / before-after-split / chart-insight / chevron-steps。カード羅列は最後。
- 重要指標は左上、詳細・表は右下。左＝前提・事実、右＝意味合い。図の下にコメントを敷かない。下部 POINT 帯禁止。
- 出典は左下。評価語（最適・包括的）を根拠なく使わない。
"""


def rules_excerpt() -> str:
    return RULES_EXCERPT.strip()


def rules_full_path() -> Path:
    return Path(__file__).resolve().parent.parent / "docs" / "pptx-slide-rules.md"
