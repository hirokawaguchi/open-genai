"""PPTX レイアウトカタログ（slide-builder の ID / スロット形を正とする）。"""

from __future__ import annotations

from typing import Any

SLIDE_TYPES = frozenset({"cover", "section", "content", "case-study", "ending"})
DEFAULT_LAYOUT = "parallel-items"

LAYOUT_IDS: tuple[str, ...] = (
    "kpi-three-col",
    "kpi-formula",
    "kpi-logic-tree",
    "text-data-emphasis",
    "doughnut-three-col",
    "two-col-text-chart",
    "pie-chart-highlight",
    "stacked-bar-chart",
    "horizontal-bar-ranking",
    "step-flow",
    "timeline",
    "vertical-timeline",
    "funnel",
    "pyramid",
    "cycle",
    "step-up",
    "comparison-table",
    "before-after-split",
    "matrix-quadrant",
    "pricing-table",
    "schedule-list",
    "checklist-table",
    "ceo-message",
    "member-grid",
    "member-three-col",
    "venn-diagram",
    "three-way-relation",
    "radial-spread",
    "convergence",
    "containment",
    "business-concept",
    "tam-concentric",
    "tam-parallel",
    "channel-mapping",
    "user-pain-points",
    "quote",
    "chat-dialogue",
    "year-list",
    "three-column",
    "three-step-column",
    "parallel-items",
    "numbered-feature-cards",
    "awards-parallel",
    "fullscreen-photo",
    "logo-wall",
    "location-map",
    "case-two-col",
    "qa-grid",
)

LAYOUT_ID_SET = frozenset(LAYOUT_IDS)

# 図的で、画像（Mermaid PNG 含む）があるときは画像 layout を優先する。
DIAGRAM_LAYOUTS = frozenset(
    {
        "venn-diagram",
        "three-way-relation",
        "radial-spread",
        "convergence",
        "containment",
        "funnel",
        "pyramid",
        "cycle",
        "kpi-logic-tree",
        "channel-mapping",
        "tam-concentric",
        "matrix-quadrant",
    }
)

NUMERIC_LAYOUTS = frozenset(
    {
        "kpi-three-col",
        "kpi-formula",
        "text-data-emphasis",
        "doughnut-three-col",
        "two-col-text-chart",
        "pie-chart-highlight",
        "stacked-bar-chart",
        "horizontal-bar-ranking",
    }
)

SELECTION_GUIDE = """\
内容のタイプ → 推奨 layout（避けるべきもの）
- 数値KPI: kpi-three-col / text-data-emphasis（本文に数値があるときだけ）
- 機能・要点 3-4個: parallel-items / numbered-feature-cards（kpi-three-col は使わない）
- 要件・チェック: checklist-table / numbered-feature-cards
- Before/After 比較: comparison-table / before-after-split
- 時系列・沿革: timeline / vertical-timeline / year-list
- 手順・プロセス（画像なし）: step-flow / three-step-column
- 人物紹介: ceo-message / member-grid / member-three-col
- Q&A: qa-grid
- 引用: quote
- 表・料金・日程: pricing-table / schedule-list
- 節に画像または Mermaid PNG がある図的内容: fullscreen-photo または two-col-text-chart ではなく
  画像を主にした layout（fullscreen-photo）。venn-diagram / cycle / radial-spread 等は画像が無いときだけ。
- 数値が本文に無いときは KPI・チャート系を選ばない。
"""


def content_nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (int, float, bool)):
        return True
    if isinstance(value, list):
        return any(content_nonempty(item) for item in value)
    if isinstance(value, dict):
        return any(content_nonempty(item) for item in value.values())
    return True


def normalize_layout(raw: Any) -> str:
    name = str(raw or "").strip()
    return name if name in LAYOUT_ID_SET else DEFAULT_LAYOUT


def minimal_fixture(layout: str) -> dict[str, Any]:
    """テスト・未知 content の最低限サンプル。"""
    fixtures: dict[str, dict[str, Any]] = {
        "kpi-three-col": {
            "items": [
                {"value": "120%", "label": "成長率"},
                {"value": "80", "label": "件数"},
                {"value": "4.5", "label": "評価"},
            ]
        },
        "kpi-formula": {
            "kpiName": "CVR",
            "numerator": "CV数",
            "denominator": "訪問者数",
            "annotations": ["注釈"],
        },
        "kpi-logic-tree": {
            "root": {"label": "成果"},
            "branches": [
                {"label": "入力", "children": [{"label": "A"}]},
                {"label": "出力", "children": [{"label": "B"}]},
            ],
        },
        "text-data-emphasis": {
            "narrative": "説明文",
            "bigNumber": "97%",
            "bigNumberLabel": "達成率",
        },
        "doughnut-three-col": {
            "charts": [
                {"title": "部門A", "labels": ["X", "Y"], "values": [60, 40]},
                {"title": "部門B", "labels": ["X", "Y"], "values": [30, 70]},
            ]
        },
        "two-col-text-chart": {
            "left": {"heading": "見出し", "body": "説明"},
            "right": {"chartType": "bar", "data": {"labels": ["A", "B"], "values": [30, 70]}},
        },
        "pie-chart-highlight": {
            "data": {"labels": ["A", "B", "C"], "values": [50, 30, 20]},
            "highlight": {"value": "50%", "message": "Aが半数"},
        },
        "stacked-bar-chart": {
            "categories": ["Q1", "Q2"],
            "series": [{"name": "A", "values": [10, 20]}, {"name": "B", "values": [5, 8]}],
        },
        "horizontal-bar-ranking": {
            "items": [{"label": "項目A", "value": 85}, {"label": "項目B", "value": 60}]
        },
        "step-flow": {
            "steps": [
                {"label": "計画", "description": "要件"},
                {"label": "実行", "description": "実装"},
            ]
        },
        "timeline": {
            "items": [
                {"date": "2024/04", "title": "開始", "description": "発足"},
                {"date": "2024/10", "title": "完了", "description": "稼働"},
            ]
        },
        "vertical-timeline": {
            "items": [
                {"date": "2024/04", "title": "開始", "description": "発足"},
                {"date": "2024/10", "title": "完了", "description": "稼働"},
            ]
        },
        "funnel": {
            "heading": "流入",
            "body": "説明",
            "steps": [{"label": "認知"}, {"label": "検討"}, {"label": "決定"}],
        },
        "pyramid": {
            "levels": [
                {"label": "方針", "description": "上位"},
                {"label": "施策", "description": "下位"},
            ]
        },
        "cycle": {
            "items": [{"label": "計画"}, {"label": "実行"}, {"label": "評価"}],
            "centerText": "改善",
        },
        "step-up": {
            "steps": [
                {"label": "基礎", "description": "土台"},
                {"label": "応用", "description": "展開"},
            ]
        },
        "comparison-table": {
            "beforeTitle": "導入前",
            "afterTitle": "導入後",
            "rows": [{"category": "コスト", "before": "100", "after": "50"}],
        },
        "before-after-split": {
            "before": {"title": "Before", "points": ["手作業"]},
            "after": {"title": "After", "points": ["自動化"]},
        },
        "matrix-quadrant": {
            "axisX": {"low": "低", "high": "高"},
            "axisY": {"low": "低", "high": "高"},
            "quadrants": [
                {"title": "Q1", "description": "説明"},
                {"title": "Q2", "description": "説明"},
                {"title": "Q3", "description": "説明"},
                {"title": "Q4", "description": "説明"},
            ],
        },
        "pricing-table": {
            "headers": [{"text": "項目"}, {"text": "内容"}],
            "rows": [[{"text": "容量"}, {"text": "10GB"}]],
        },
        "schedule-list": {
            "phases": [
                {"phase": "Phase1", "period": "4-5月", "owner": "開発", "details": "設計"}
            ]
        },
        "checklist-table": {
            "headers": ["項目", "状態", "備考"],
            "items": [{"label": "環境", "checked": True, "note": "完了"}],
        },
        "ceo-message": {
            "name": "山田太郎",
            "role": "担当",
            "message": "本文",
        },
        "member-grid": {
            "members": [
                {"name": "田中", "role": "設計", "bio": "経歴"},
                {"name": "佐藤", "role": "開発", "bio": "経歴"},
            ]
        },
        "member-three-col": {
            "members": [
                {"name": "田中", "role": "設計", "bio": "経歴"},
                {"name": "佐藤", "role": "開発", "bio": "経歴"},
                {"name": "鈴木", "role": "運用", "bio": "経歴"},
            ]
        },
        "venn-diagram": {
            "items": [{"label": "技術"}, {"label": "業務"}],
            "overlapText": "接点",
        },
        "three-way-relation": {
            "nodes": [{"label": "A"}, {"label": "B"}, {"label": "C"}],
            "relations": [{"label": "連携"}],
        },
        "radial-spread": {
            "center": {"label": "中核"},
            "items": [{"label": "機能A"}, {"label": "機能B"}],
        },
        "convergence": {
            "target": {"label": "目標"},
            "items": [{"label": "要素A"}, {"label": "要素B"}],
        },
        "containment": {
            "outer": {"label": "基盤"},
            "inner": [{"label": "モジュールA", "description": "説明"}],
        },
        "business-concept": {
            "a": {"title": "概念A", "description": "説明"},
            "b": {"title": "概念B", "description": "説明"},
        },
        "tam-concentric": {
            "rings": [{"label": "全体", "value": "100"}, {"label": "対象", "value": "30"}]
        },
        "tam-parallel": {
            "items": [{"label": "全体", "value": "100"}, {"label": "対象", "value": "30"}]
        },
        "channel-mapping": {
            "phases": ["認知", "検討", "決定"],
            "channels": [{"label": "案内", "startPhase": 0, "endPhase": 1}],
        },
        "user-pain-points": {"painPoints": ["検索が遅い", "重複が多い"]},
        "quote": {"text": "引用文", "author": "著者", "role": "役職"},
        "chat-dialogue": {
            "messages": [
                {"speaker": "質問", "text": "内容は？"},
                {"speaker": "回答", "text": "次のとおりです。"},
            ]
        },
        "year-list": {"items": [{"year": "2020", "description": "開始"}]},
        "three-column": {
            "columns": [
                {"heading": "A", "body": "説明"},
                {"heading": "B", "body": "説明"},
                {"heading": "C", "body": "説明"},
            ]
        },
        "three-step-column": {
            "steps": [
                {"title": "分析", "description": "現状"},
                {"title": "設計", "description": "方針"},
                {"title": "実装", "description": "構築"},
            ]
        },
        "parallel-items": {
            "items": [
                {"heading": "要点1", "description": "説明"},
                {"heading": "要点2", "description": "説明"},
            ]
        },
        "numbered-feature-cards": {
            "items": [
                {"title": "機能1", "description": "説明"},
                {"title": "機能2", "description": "説明"},
            ]
        },
        "awards-parallel": {
            "items": [{"value": "1", "label": "実績", "description": "2025"}],
            "footerMessage": "注釈",
        },
        "fullscreen-photo": {
            "headline": "見出し",
            "subMessages": ["補足"],
        },
        "logo-wall": {"logos": [{"name": "組織A"}, {"name": "組織B"}]},
        "location-map": {
            "locations": [{"name": "本社", "posX": 40, "posY": 50, "isHQ": True}]
        },
        "case-two-col": {
            "companyName": "事例",
            "info": [{"key": "分野", "value": "行政"}],
            "metrics": [{"key": "効果", "value": "改善"}],
        },
        "qa-grid": {
            "items": [
                {"q": "質問1", "a": "回答1"},
                {"q": "質問2", "a": "回答2"},
            ]
        },
    }
    return dict(fixtures.get(layout) or fixtures[DEFAULT_LAYOUT])
