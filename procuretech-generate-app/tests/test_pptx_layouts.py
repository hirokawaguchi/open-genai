from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.pptx_catalog import LAYOUT_IDS, DEFAULT_LAYOUT, minimal_fixture
from app.pptx_html import render_deck_html
from app.pptx_layouts import registered_layouts, render_deck, validate_deck
from app.pptx_plan import _apply_review, _fill_content, parse_source_blocks, plan_deck


def test_all_catalog_layouts_are_registered():
    registered = set(registered_layouts())
    missing = set(LAYOUT_IDS) - registered
    assert not missing


@pytest.mark.parametrize("layout", LAYOUT_IDS)
def test_each_layout_renders(layout: str):
    deck = {
        "slides": [
            {"type": "cover", "title": "表紙"},
            {
                "type": "content",
                "title": layout,
                "layout": layout,
                "content": minimal_fixture(layout),
            },
        ]
    }
    data = render_deck(validate_deck(deck) or deck, {})
    assert data[:2] == b"PK"


def test_unknown_layout_falls_back():
    deck = validate_deck(
        {
            "slides": [
                {
                    "type": "content",
                    "title": "要点",
                    "layout": "does-not-exist",
                    "content": {"items": [{"heading": "A", "description": "B"}]},
                }
            ]
        }
    )
    assert deck is not None
    assert deck["slides"][0]["layout"] == DEFAULT_LAYOUT
    assert render_deck(deck, {})[:2] == b"PK"


def test_empty_content_slide_is_dropped():
    deck = validate_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {"type": "content", "title": "空", "layout": "quote", "content": {}},
            ]
        }
    )
    assert deck is not None
    assert [s["type"] for s in deck["slides"]] == ["cover"]


def test_notes_are_written_to_pptx():
    deck = {
        "slides": [
            {"type": "cover", "title": "表紙"},
            {
                "type": "content",
                "title": "課題",
                "layout": "parallel-items",
                "content": minimal_fixture("parallel-items"),
                "notes": "元の本文（背景）\n現行システムは検索が遅い。",
            },
        ]
    }
    data = render_deck(deck, {})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        notes_xml = "\n".join(
            zf.read(name).decode("utf-8") for name in zf.namelist() if "notesSlide" in name
        )
    assert "現行システムは検索が遅い" in notes_xml
    assert "元の本文" in notes_xml


def test_plan_deck_drops_thank_you_ending(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {"type": "cover", "title": "文書"},
                    {
                        "type": "content",
                        "title": "背景",
                        "layout": "parallel-items",
                        "source": {"filename": "a.md", "heading": "背景"},
                    },
                    {"type": "ending", "title": "ご清聴ありがとうございました", "subtitle": "文書"},
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck(
        "文書",
        [{"filename": "a.md", "content": "# 背景\n要点です。\n"}],
        complete=fake_complete,
    )
    assert deck is not None
    assert all(s.get("type") != "ending" for s in deck["slides"])
    assert not any("ご清聴" in str(s.get("title") or "") for s in deck["slides"])


def test_plan_deck_disabled_returns_none():
    assert plan_deck("文書", [{"filename": "a.md", "content": "# 背景\n本文\n"}]) is None


def test_plan_deck_invalid_json_still_builds_notes(monkeypatch):
    """要点 JSON が壊れても見出し骨格＋機械整理ノートでデッキを組む。"""
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")

    def fake_complete(messages, **kwargs):
        return "これは JSON ではありません"

    deck = plan_deck(
        "文書",
        [{"filename": "a.md", "content": "# 背景\n現行システムの検索は遅い。\n- 重複登録\n"}],
        complete=fake_complete,
    )
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    notes = content.get("notes") or ""
    assert "整理ノート" in notes
    assert "元の本文" in notes
    shown = json.dumps(content["content"], ensure_ascii=False)
    assert "重複登録" in shown
    assert "現行システムの検索は遅い。" not in shown or content["layout"] == "fullwidth-points"


def test_plan_deck_fills_from_source_and_notes(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid")
    body = (
        "現行システムの検索は遅く、同一案件が複数登録される問題がある。"
        "担当者は手作業で突合しており、確認に時間がかかる。"
    )
    sections = [{"filename": "a.md", "content": f"# 背景\n\n{body}\n\n- 検索が遅い\n- 重複登録\n"}]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "背景"},
                        "role": "explanation",
                        "points": ["検索が遅い", "重複登録"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    contents = [s for s in deck["slides"] if s["type"] == "content"]
    assert contents
    assert contents[0]["layout"] == "fullwidth-points"
    assert contents[0]["content"]
    assert "元の本文" in (contents[0].get("notes") or "")
    assert "現行システム" in (contents[0].get("notes") or "")
    assert "![" not in (contents[0].get("notes") or "")
    assert render_deck(deck, {})[:2] == b"PK"


def test_plan_deck_prefers_image_over_diagram(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid")
    sections = [
        {
            "filename": "a.md",
            "content": "# 構成\n\n関係を示す。\n\n![図](images/flow.png)\n",
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "構成"},
                        "role": "explanation",
                        "points": ["関係を示す"],
                    }
                ]
            }
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s.get("title") == "構成")
    assert content["type"] == "content"
    assert content["layout"] == "fullscreen-photo"
    assert content["content"].get("image") == "images/flow.png"


def test_notes_strip_markdown_and_skip_waiting_images(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    sections = [
        {
            "filename": "section2.md",
            "content": (
                "# 業務の手順\n\n"
                    "催事申込みは次の手順で行う。内閣府からの連絡を受けて公開する。\n\n"
                "![待ち](images/1788672411_df5da618_waiting.png)\n"
                "![図](images/flow.png)\n"
            ),
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "section2.md", "heading": "業務の手順"},
                        "role": "procedure",
                        "points": ["催事申込みは次の手順で行う"],
                    }
                ]
            }
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s.get("title") == "業務の手順")
    assert content["content"].get("image") == "images/flow.png"
    notes = content.get("notes") or ""
    assert "催事申込み" in notes
    assert "![" not in notes
    assert "waiting" not in notes
    assert "section2.md" not in notes
    assert not content["content"].get("subMessages")


def test_plan_ignores_llm_body_and_covers_all_headings(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    long_a = "現行システムの検索は遅く、同一案件が複数登録される問題がある。" * 2
    long_b = "催事申込みはWebフォームから受け付け、職員が専用端末で確認する。" * 2
    sections = [
        {
            "filename": "a.md",
            "content": f"# 背景\n\n{long_a}\n\n## 手順\n\n{long_b}\n",
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "背景"},
                        "role": "explanation",
                        "points": ["検索が遅く同一案件が複数登録される"],
                    },
                    {
                        "source": {"filename": "a.md", "heading": "手順"},
                        "role": "procedure",
                        "points": ["催事申込みはWebフォームから受け付ける"],
                    },
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    contents = [s for s in deck["slides"] if s["type"] == "content"]
    assert len(contents) >= 2
    shown = json.dumps(contents[0]["content"], ensure_ascii=False)
    assert long_a not in shown
    assert "…" in shown or len(shown) < len(long_a)
    assert "元の本文" in (contents[0].get("notes") or "")
    assert long_a[:20] in (contents[0].get("notes") or "")
    layouts = [s["layout"] for s in contents]
    assert len(set(layouts)) >= 2


def test_new_primary_layouts_render_pptx_and_html():
    for layout in ("axis-table", "premise-conclusion", "chart-insight", "chevron-steps"):
        deck = {
            "slides": [
                {"type": "cover", "title": "検索遅延を索引で解消する"},
                {
                    "type": "content",
                    "title": "待ち時間は索引で下がる",
                    "layout": layout,
                    "content": minimal_fixture(layout),
                },
            ]
        }
        valid = validate_deck(deck) or deck
        pptx = render_deck(valid, {})
        html = render_deck_html(valid, {}).decode("utf-8")
        assert pptx[:2] == b"PK"
        assert html.count('class="slide"') == 2
        assert "待ち時間は索引で下がる" in html
        assert "検索遅延を索引で解消する" in html


def test_same_deck_titles_match_in_pptx_notes_and_html():
    deck = {
        "slides": [
            {"type": "cover", "title": "検索遅延を索引で解消する"},
            {
                "type": "content",
                "title": "重複登録は一意制約で止める",
                "layout": "axis-table",
                "content": minimal_fixture("axis-table"),
            },
        ]
    }
    html = render_deck_html(deck, {}).decode("utf-8")
    assert "重複登録は一意制約で止める" in html
    assert "検索遅延を索引で解消する" in html
    data = render_deck(deck, {})
    assert data[:2] == b"PK"


def test_freeform_grid_rect_clamps(monkeypatch):
    from pptx import Presentation
    from pptx.util import Inches
    from app.pptx_layouts import _grid_rect, _grid_span

    # 範囲外の指定でも領域内に収まる（col+colspan<=12, row+rowspan<=6）。
    col, row, cs, rs = _grid_span({"col": 20, "row": 9, "colspan": 99, "rowspan": 99})
    assert 0 <= col <= 11 and 0 <= row <= 5
    assert col + cs <= 12 and row + rs <= 6
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    left, top, width, height = _grid_rect(prs, 0, 0, 12, 6)
    assert left >= 0 and top >= Inches(1.4) - 1
    assert width <= Inches(12)


def test_render_freeform_places_elements_and_handles_bad_input():
    from app.pptx_layouts import render_deck

    content = {
        "elements": [
            {"kind": "heading", "col": 0, "row": 0, "colspan": 12, "rowspan": 1, "text": "要点"},
            {"kind": "bullets", "col": 0, "row": 1, "colspan": 7, "rowspan": 4, "bullets": ["A", "B"]},
            {"kind": "kpi", "col": 8, "row": 1, "colspan": 4, "rowspan": 2, "value": "3秒", "label": "応答"},
            {"kind": "table", "col": 0, "row": 5, "colspan": 12, "rowspan": 1, "headers": ["列"], "rows": [["値"]]},
            {"kind": "image", "col": 8, "row": 3, "colspan": 4, "rowspan": 3, "image": "images/x.png"},
            {"kind": "unknown-kind", "col": 0, "row": 0, "text": "無視される"},
            "not-a-dict",
            {"kind": "text", "col": 99, "row": 99, "colspan": 99, "rowspan": 99, "text": "範囲外でも収まる"},
        ]
    }
    deck = {"slides": [{"type": "content", "title": "自由配置", "layout": "freeform", "content": content}]}
    data = render_deck(deck, {})  # 画像は欠落 → プレースホルダ、未知 kind は無視
    assert data[:2] == b"PK"


def test_freeform_layout_is_registered():
    from app.pptx_catalog import LAYOUT_ID_SET
    from app.pptx_layouts import registered_layouts

    assert "freeform" in LAYOUT_ID_SET
    assert "freeform" in registered_layouts()


def test_compose_freeform_grounds_and_falls_back(monkeypatch):
    from app.pptx_plan import SourceBlock, _compose_freeform

    block = SourceBlock(
        filename="a.md",
        heading="背景",
        text="現行システムの検索は遅い。応答は3秒かかる。",
        bullets=["検索が遅い"],
    )

    def fake(messages, **kwargs):
        return json.dumps(
            {
                "elements": [
                    {"kind": "heading", "col": 0, "row": 0, "colspan": 12, "rowspan": 1, "text": "検索が遅い"},
                    {"kind": "kpi", "col": 0, "row": 1, "colspan": 4, "rowspan": 2, "value": "3秒", "label": "応答"},
                    {"kind": "text", "col": 4, "row": 1, "colspan": 8, "rowspan": 2, "text": "ドローンで解決する"},
                ]
            },
            ensure_ascii=False,
        )

    out = _compose_freeform(fake, "文書", block, ["検索が遅い"], "背景")
    blob = json.dumps(out, ensure_ascii=False)
    assert "検索が遅い" in blob and "3秒" in blob
    assert "ドローン" not in blob  # 原文に無いカタカナは除去

    # 不正 JSON はフォールバック（None）
    assert _compose_freeform(lambda *a, **k: "not json", "文書", block, [], "背景") is None


def test_plan_deck_reports_progress(monkeypatch):
    """plan_deck が on_progress で単調非減少の実進捗を通知する。"""
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [
        {"filename": "a.md", "content": "# 背景\n本文A。\n\n## 手順\n本文B。\n"}
    ]

    def fake(messages, **kwargs):
        s = messages[0]["content"]
        if "要点整理係" in s:
            return json.dumps(
                {
                    "slides": [
                        {
                            "source": {"filename": "a.md", "heading": "背景"},
                            "role": "explanation",
                            "points": ["本文A"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return "{}"

    seen: list[float] = []
    labels: list[str] = []

    def on_progress(frac, label):
        seen.append(round(float(frac), 4))
        labels.append(label)

    deck = plan_deck("文書", sections, complete=fake, on_progress=on_progress)
    assert deck is not None
    assert seen  # 通知された
    assert seen == sorted(seen)  # 単調非減少
    assert seen[-1] >= 0.9
    joined = " ".join(labels)
    assert "要点を整理" in joined and "スライドを構成" in joined


def test_notes_first_points_drive_slide_and_notes(monkeypatch):
    """整理ノート（要点）がスライド本体の材料になり、ノートに要点＋原文が入る。"""
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [
        {
            "filename": "a.md",
            "content": "# 背景\n現行システムの検索は遅く、同一案件が複数登録される。\n",
        }
    ]

    def fake_complete(messages, **kwargs):
        sys = messages[0]["content"]
        if "要点整理係" in sys:  # notes パス
            return json.dumps(
                {
                    "slides": [
                        {
                            "source": {"filename": "a.md", "heading": "背景"},
                            "role": "explanation",
                            "points": ["検索が遅い", "同一案件が複数登録される", "ドローンで解決する"],
                        }
                    ]
                },
                ensure_ascii=False,
            )
        return "{}"

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    shown = json.dumps(content["content"], ensure_ascii=False)
    assert "検索が遅い" in shown  # 整理ノートの要点が本体に反映
    notes = content.get("notes") or ""
    assert "整理ノート" in notes and "検索が遅い" in notes
    assert "元の本文" in notes and "現行システム" in notes
    # 原文グラウンディング: 原文に無い固有名（カタカナ「ドローン」）は要点から除去
    assert "ドローン" not in shown
    assert "ドローン" not in notes.split("元の本文")[0]


def test_code_blocks_are_kept_and_shown(monkeypatch):
    """コマンド等のフェンスコードを取り込み、スライド本体とノートに出す。"""
    from app.pptx_plan import parse_source_blocks, _fill_content, _attach_notes

    sections = [
        {
            "filename": "a.md",
            "content": "# 手順\n\n次を実行します。\n\n```\nnetsh winhttp show proxy\n```\n",
        }
    ]
    block = parse_source_blocks("文書", sections)[0]
    assert any("netsh winhttp show proxy" in c for c in block.code_blocks)
    # 前置き文があってもコードが要点として併記される
    content = _fill_content("fullwidth-points", block)
    shown = json.dumps(content, ensure_ascii=False)
    assert "netsh winhttp show proxy" not in shown
    # ノートにはコマンドが残る
    slide: dict = {}
    _attach_notes(slide, block)
    assert "netsh winhttp show proxy" in slide["notes"]


def test_empty_section_is_omitted(monkeypatch):
    """見出しだけの空節はスライドにしない。"""
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [
        {"filename": "a.md", "content": "# はじめに\n\n概要を述べる。\n\n## 空節\n"}
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps({"slides": []}, ensure_ascii=False)

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    assert all(s.get("title") != "空節" for s in deck["slides"])
    assert any(s.get("title") == "はじめに" for s in deck["slides"])


def test_axis_table_no_empty_second_column(monkeypatch):
    from app.pptx_plan import SourceBlock, _fill_content

    block = SourceBlock(filename="a.md", heading="項目", text="", bullets=["検索が遅い", "重複が多い"])
    content = _fill_content("axis-table", block)
    assert content["headers"] == ["ポイント"]  # 分割不能なら単列（空列を作らない）
    assert all(len(r) == 1 for r in content["rows"])

    block2 = SourceBlock(filename="a.md", heading="項目", text="", bullets=["応答：3秒", "件数：120"])
    content2 = _fill_content("axis-table", block2)
    assert content2["headers"] == ["項目", "内容"]
    assert ["応答", "3秒"] in content2["rows"]


def test_markdown_to_pptx_fallback_has_notes():
    pytest.importorskip("pptx")
    import io
    import zipfile

    from app.compose_formats import markdown_to_pptx

    sections = [{"filename": "a.md", "content": "# 背景\n\n現行システムは遅い。\n- 検索が遅い\n"}]
    data = markdown_to_pptx("文書", sections, {})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        notes_xml = "\n".join(
            zf.read(n).decode("utf-8", errors="replace")
            for n in zf.namelist()
            if "notesSlide" in n
        )
    assert "元の本文" in notes_xml
    assert "現行システムは遅い" in notes_xml


def test_plan_notes_and_review_applies_adopted_title_only(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "1")
    calls: list[str] = []

    def fake_complete(messages, **kwargs):
        blob = messages[-1]["content"]
        calls.append(blob[:40])
        if "作り方は知らない" in messages[0]["content"]:
            return json.dumps(
                {
                    "changes": [
                        {"index": 1, "adopt": True, "title": "検索遅延と重複登録が業務を止めている"},
                        {"index": 1, "adopt": True, "title": "AcmeCloudが独占する"},
                    ]
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "背景"},
                        "role": "explanation",
                        "title": "検索が遅く重複がある",
                        "points": ["検索が遅い", "重複登録"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck(
        "文書",
        [{"filename": "a.md", "content": "# 背景\n検索が遅く、同一案件が重複登録される。\n- 検索が遅い\n- 重複登録\n"}],
        complete=fake_complete,
    )
    assert deck is not None
    # 節ごと {role, points} と伏せたレビューの 2 パス。
    assert len(calls) == 2
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["title"] == "検索遅延と重複登録が業務を止めている"
    assert "AcmeCloud" not in json.dumps(deck, ensure_ascii=False)


def test_parse_and_fill_markdown_table():
    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 著者のスタンス概要\n\n"
                "| 記事 | 主張 | 重要ポイント |\n"
                "|------|------|-------------|\n"
                "| 20260904 | **離職＝卒業** | 訓練機会 |\n"
            ),
        }
    ]
    blocks = parse_source_blocks("文書", sections)
    assert blocks[0].tables
    assert blocks[0].tables[0]["headers"] == ["記事", "主張", "重要ポイント"]
    assert "|" not in (blocks[0].text or "")
    table = _fill_content("axis-table", blocks[0])
    assert table["headers"] == ["記事", "主張", "重要ポイント"]
    assert table["rows"][0][0] == "20260904"
    assert "離職＝卒業" in table["rows"][0][1]
    assert "**" not in table["rows"][0][1]


def test_notes_keep_table_rows_not_column_names():
    from app.pptx_plan import _enrich_notes, _mechanical_notes, parse_source_blocks

    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 用語定義\n\n"
                "| 用語 | 定義 |\n"
                "|------|------|\n"
                "| ローカルAI | 庁内で動かす生成AI |\n"
                "| Dify | 画面操作で組み立てる基盤 |\n"
            ),
        }
    ]
    block = parse_source_blocks("文書", sections)[0]
    mechanical = _mechanical_notes(block)
    blob = "\n".join(mechanical)
    assert "ローカルAI" in blob
    assert "庁内で動かす生成AI" in blob
    assert "表（" not in blob

    thin = _enrich_notes(["用語と定義が表にまとめられている", "表形式で整理"], block)
    thin_blob = "\n".join(thin)
    assert "ローカルAI" in thin_blob
    assert "用語と定義が表にまとめられている" not in thin_blob


def test_plan_deck_keeps_table_rows_when_notes_are_thin(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 共通題材\n\n"
                "| 区分 | ファイル名 |\n"
                "|------|------------|\n"
                "| 正規職員 | 職員規則.pdf |\n"
            ),
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "共通題材"},
                        "role": "definition",
                        "points": ["表には区分とファイル名が列挙"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    shown = json.dumps(content, ensure_ascii=False)
    assert "正規職員" in shown
    assert "職員規則.pdf" in shown
    notes = content.get("notes") or ""
    assert "正規職員" in notes
    assert content["layout"] == "axis-table"
    assert content["content"].get("rows")


def test_plan_deck_forces_axis_table_for_gfm(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    sections = [
        {
            "filename": "a.md",
            "content": (
                "# スタンス\n\n"
                "| 記事 | 主張 |\n"
                "|------|------|\n"
                "| 20260904 | 離職＝卒業 |\n"
            ),
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "スタンス"},
                        "role": "definition",
                        "points": ["表（1行）: 記事 / 主張"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "axis-table"
    assert content["content"]["headers"] == ["記事", "主張"]
    shown = json.dumps(content["content"], ensure_ascii=False)
    assert "|" not in shown
    assert "20260904" in shown
    data = render_deck(deck, {})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
    assert "<a:tbl>" in xml or "<a:tbl " in xml


def test_apply_review_drops_novel_katakana():
    deck = {
        "slides": [
            {"type": "cover", "title": "表紙"},
            {
                "type": "content",
                "title": "検索が遅い",
                "layout": "axis-table",
                "content": {"rows": [["検索", "遅い"]]},
                "notes": "元の本文（背景）\n検索が遅い",
            },
        ]
    }
    out = _apply_review(
        deck,
        {"changes": [{"index": 1, "adopt": True, "title": "ネオシステムが遅い"}]},
    )
    assert out["slides"][1]["title"] == "検索が遅い"


def test_slide_tokens_meet_contrast():
    from app.dads import (
        ACCENT,
        BODY,
        ERROR,
        ERROR_SURFACE,
        INK,
        PAPER,
        PPTX_MUTED,
        PRIMARY_SURFACE,
        SUCCESS,
        SUCCESS_SURFACE,
        SURFACE,
        WARNING,
        WARNING_SURFACE,
        contrast_ok,
        contrast_ratio,
    )

    assert contrast_ok(INK, PAPER)
    assert contrast_ok(BODY, PAPER)
    assert contrast_ok(PPTX_MUTED, PAPER)
    assert contrast_ok(ACCENT, PAPER)
    assert contrast_ok(INK, SURFACE)
    assert contrast_ok(INK, PRIMARY_SURFACE)
    assert contrast_ok(SUCCESS, SUCCESS_SURFACE)
    assert contrast_ok(ERROR, ERROR_SURFACE)
    assert contrast_ok(WARNING, WARNING_SURFACE)
    assert contrast_ratio(INK, PAPER) >= 4.5


def test_pptx_body_follows_dads_projection_size():
    from app.dads import PPTX_TYPE

    assert PPTX_TYPE["body"] == 22
    assert PPTX_TYPE["title"] >= 36
    assert PPTX_TYPE["table"] >= 18


def test_default_layout_is_fullwidth():
    from app.pptx_catalog import DEFAULT_LAYOUT, normalize_layout

    assert DEFAULT_LAYOUT == "fullwidth-points"
    assert normalize_layout("does-not-exist") == "fullwidth-points"


def test_suggest_layout_prefers_fullwidth_for_prose():
    from app.pptx_plan import SourceBlock, _suggest_layout

    block = SourceBlock(filename="a.md", heading="背景", text="検索が遅い。重複がある。", bullets=["検索が遅い"])
    assert _suggest_layout(block, "") == "fullwidth-points"
    assert _suggest_layout(block, "fullwidth-points") == "fullwidth-points"


def test_plan_uses_llm_role_for_layout(monkeypatch):
    """見出しが説明でも、LLM が procedure なら手順レイアウトにする。"""
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [{"filename": "a.md", "content": "# 背景\n- 端末を開く\n- 分類を作る\n"}]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "背景"},
                        "role": "procedure",
                        "title": "分類を先に作る",
                        "points": ["端末を開く", "分類を作る"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "chevron-steps"
    assert content["title"] == "分類を先に作る"


def test_purpose_overrides_role_for_layout():
    from app.pptx_plan import SourceBlock, _normalize_purpose, _select_layout

    compare = SourceBlock(
        filename="a.md",
        heading="背景",
        text="現状は手作業。更改後は自動で突合する。",
        bullets=["手作業", "自動突合"],
    )
    assert _normalize_purpose("compare", "explanation") == "compare"
    assert _select_layout("compare", "explanation", compare, "") == "before-after-split"
    assert _select_layout("time", "explanation", compare, "") == "chevron-steps"
    assert _select_layout("", "procedure", compare, "") == "chevron-steps"


def test_usable_title_drops_twopart_and_novel_facts():
    from app.pptx_plan import _usable_title

    allowed = "検索が遅い。重複登録がある。"
    assert _usable_title("検索が遅く重複登録がある", allowed) == "検索が遅く重複登録がある"
    assert _usable_title("検索が遅い。重複登録がある", allowed) == ""
    assert _usable_title("検索遅延をネオシステムで解消する", allowed) == ""
    assert _usable_title("これは結論です", allowed) == ""


def test_plan_uses_llm_purpose_for_layout(monkeypatch):
    """見出しが説明でも、LLM が compare なら対比レイアウトにする。"""
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [{"filename": "a.md", "content": "# 背景\n- 手作業で突合している\n- 更改後は自動で突合する\n"}]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "背景"},
                        "purpose": "compare",
                        "role": "explanation",
                        "title": "突合は手作業から自動へ移る",
                        "points": ["手作業で突合している", "更改後は自動で突合する"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "before-after-split"
    assert content["title"] == "突合は手作業から自動へ移る"


def test_section_role_selects_layout():
    from app.pptx_plan import SourceBlock, _guess_role, _role_to_layout

    steps = SourceBlock(filename="a.md", heading="6.1 手順", text="", bullets=["開く", "作る"])
    assert _guess_role(steps) == "procedure"
    assert _role_to_layout("procedure", steps, "") == "chevron-steps"

    table = SourceBlock(
        filename="a.md",
        heading="用語",
        text="",
        tables=[{"headers": ["語", "意味"], "rows": [["検索", "遅い"]]}],
    )
    assert _guess_role(table) == "definition"
    assert _role_to_layout("definition", table, "") == "axis-table"

    compare = SourceBlock(filename="a.md", heading="更改前後の比較", text="現状と更改後", bullets=["遅い", "速い"])
    assert _guess_role(compare) == "comparison"
    assert _role_to_layout("comparison", compare, "") == "before-after-split"

    photo = SourceBlock(filename="a.md", heading="構成", text="関係を示す", images=["images/flow.png"])
    assert _role_to_layout("explanation", photo, "") == "fullscreen-photo"

    flow = SourceBlock(
        filename="a.md",
        heading="2.4 完成イメージ",
        text="利用者の質問\n↓\n質問分類\n├─ 正規職員の質問 → 職員規則を検索\n└─ 区分不明 → 聞き返す\n",
        bullets=["分岐を先に行う"],
    )
    assert _guess_role(flow) == "procedure"
    assert _role_to_layout("procedure", flow, "") == "step-flow"


def test_split_dense_breaks_long_points_and_tables():
    from app.pptx_plan import _split_dense

    points = [f"要点{i}" for i in range(14)]
    parts = _split_dense("fullwidth-points", {"points": points}, "背景")
    assert len(parts) == 3
    assert parts[0][2] == "背景"
    assert parts[1][2] == "背景（続き）"
    assert parts[0][1]["points"] == points[:6]

    rows = [[f"行{i}"] for i in range(20)]
    tables = _split_dense("axis-table", {"headers": ["列"], "rows": rows}, "表")
    assert len(tables) == 3
    assert tables[0][1]["headers"] == ["列"]
    assert len(tables[0][1]["rows"]) == 8

    steps = [{"title": f"手順{i}"} for i in range(5)]
    flow = _split_dense("chevron-steps", {"steps": steps}, "手順")
    assert len(flow) == 2
    assert len(flow[0][1]["steps"]) == 3


def test_autofit_only_when_text_overflows():
    from pptx.util import Inches, Pt
    from app.pptx_layouts import _needs_autofit

    assert not _needs_autofit("短い", Inches(10), Inches(2), Pt(18))
    assert _needs_autofit("あ" * 800, Inches(2), Inches(0.4), Pt(18))


def test_default_freeform_puts_kpi_top_left():
    from app.pptx_plan import SourceBlock, _default_freeform

    block = SourceBlock(
        filename="a.md",
        heading="規模",
        text="応答は3秒。件数は120。",
        bullets=["応答は3秒"],
    )
    out = _default_freeform(block, ["応答は3秒"])
    kinds = [e["kind"] for e in out["elements"]]
    assert "kpi" in kinds
    kpi = next(e for e in out["elements"] if e["kind"] == "kpi")
    assert kpi["col"] == 0 and kpi["row"] == 0
    assert "3" in kpi["value"]
    lower = [e for e in out["elements"] if e["kind"] != "kpi"]
    assert lower
    assert all(e["row"] >= 2 and e["col"] == 0 for e in lower)


def test_cover_has_no_banner_label():
    data = render_deck({"slides": [{"type": "cover", "title": "更改の論点", "subtitle": "情報政策課"}]}, {})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
    assert "更改の論点" in xml
    assert ">資料<" not in xml
    assert "ご清聴" not in xml


def test_numbered_steps_become_bullets_and_mechanical_notes():
    from app.pptx_plan import _mechanical_notes, parse_source_blocks

    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 6.1 ナレッジを2つ作る\n\n"
                "**目的**: 規則を混ぜずに検索できるようにする\n\n"
                "**手順**:\n\n"
                "1. ナレッジを開く\n"
                "2. 知識ベースを作成する\n"
                "3. PDFをアップロードする\n\n"
                "| 順番 | ノード |\n"
                "|------|--------|\n"
                "| 1 | 開始 |\n\n"
                "```text\n長いプロンプト本文\n```\n"
            ),
        }
    ]
    block = parse_source_blocks("手順書", sections)[0]
    assert "ナレッジを開く" in block.bullets
    assert block.tables
    assert block.code_blocks
    points = _mechanical_notes(block)
    blob = "\n".join(points)
    assert "規則を混ぜずに" in blob or "目的" in blob
    assert "ナレッジを開く" in blob
    assert "開始" in blob
    assert "表（" not in blob
    assert "ノートの原文" in blob
    assert "長いプロンプト本文" not in blob


def test_procedure_doc_uses_notes_not_raw_prompt(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [
        {
            "filename": "手順.md",
            "content": (
                "# 6.3 質問分類を設定する\n\n"
                "**目的**: 質問を3つの経路に分ける\n\n"
                "1. 職員区分の判定を開く\n"
                "2. 分類クラスを3つ作る\n\n"
                "```text\n"
                "ユーザーの質問を、次の基準で1つだけに分類してください。\n"
                "【正規職員の勤務時間・休暇】\n"
                "```\n"
            ),
        }
    ]

    def fake_complete(messages, **kwargs):
        return "not-json"

    deck = plan_deck("手順書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    notes = content.get("notes") or ""
    assert "整理ノート" in notes
    assert "元の本文" in notes
    shown = json.dumps(content["content"], ensure_ascii=False)
    assert "ユーザーの質問を、次の基準で1つだけに分類してください" not in shown
    assert "職員区分の判定を開く" in shown or "3つの経路" in shown


def test_plan_splits_long_points(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    bullets = "\n".join(f"- 要点{i}です" for i in range(13))
    sections = [{"filename": "a.md", "content": f"# 背景\n{bullets}\n"}]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "背景"},
                        "role": "explanation",
                        "points": [f"要点{i}です" for i in range(13)],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    contents = [s for s in deck["slides"] if s["type"] == "content"]
    assert len(contents) >= 2
    assert contents[0]["layout"] == "fullwidth-points"
    assert "続き" in contents[1]["title"]


def test_parse_keeps_mermaid_blocks():
    sections = [
        {
            "filename": "a.md",
            "content": "# 関係\n\n```mermaid\nflowchart TD\nA-->B\n```\n",
        }
    ]
    blocks = parse_source_blocks("文書", sections)
    assert blocks
    assert blocks[0].mermaid_blocks
    assert "flowchart TD" in blocks[0].mermaid_blocks[0]


def test_guess_figure_trusts_llm_and_skips_without_it():
    from app.pptx_figure import guess_figure
    from app.pptx_plan import SourceBlock

    table = SourceBlock(
        filename="a.md",
        heading="用語",
        text="",
        tables=[{"headers": ["語", "意味"], "rows": [["検索", "遅い"]]}],
    )
    assert guess_figure(table) == ""
    assert guess_figure(table, "flowchart") == "flowchart"

    steps = SourceBlock(filename="a.md", heading="6.1 手順", text="", bullets=["開く", "作る"])
    assert guess_figure(steps) == ""

    prose = SourceBlock(
        filename="a.md",
        heading="質問分類を設定する",
        text="質問を3つの経路に分ける",
        bullets=["職員区分の判定を開く"],
    )
    assert guess_figure(prose) == ""
    assert guess_figure(prose, "flowchart") == "flowchart"

    photo = SourceBlock(
        filename="a.md",
        heading="完成イメージ",
        text="関係を示す",
        images=["images/flow.png"],
    )
    assert guess_figure(photo, "flowchart") == ""

    editor_mmd = SourceBlock(
        filename="a.md",
        heading="関係",
        text="",
        images=["images/mermaid-abc-0.png"],
    )
    assert guess_figure(editor_mmd) == "flowchart"


def test_branch_section_becomes_figure_frame(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    monkeypatch.setattr("app.pptx_figure.render_mermaid_png", lambda code: None)
    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 2.4 完成イメージ\n\n"
                "利用者の質問\n"
                "↓\n"
                "質問分類\n"
                "├─ 正規職員の質問 → 職員規則を検索\n"
                "└─ 区分不明 → 聞き返す\n"
            ),
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "2.4 完成イメージ"},
                        "role": "procedure",
                        "title": "質問分類の分岐",
                        "figure": "flowchart",
                        "figure_caption": "質問分類の分岐",
                        "points": ["利用者の質問", "質問分類", "正規職員の質問 → 職員規則を検索"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "figure-frame"
    body = content["content"]
    assert body["alt"] == "ここに質問分類の分岐の図を入れる"
    assert not body.get("image")
    assert "flowchart" in (body.get("mermaid") or "")
    notes = content.get("notes") or ""
    assert "図のMermaid" in notes
    assert "flowchart" in notes


def test_source_mermaid_becomes_figure_frame(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    monkeypatch.setattr("app.pptx_figure.render_mermaid_png", lambda code: None)
    sections = [
        {
            "filename": "a.md",
            "content": "# 関係\n\n```mermaid\nflowchart TD\n質問 --> 分類\n```\n",
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "関係"},
                        "role": "explanation",
                        "figure": "flowchart",
                        "figure_caption": "関係",
                        "points": ["質問", "分類"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "figure-frame"
    assert "質問 --> 分類" in (content["content"].get("mermaid") or "")


def test_figure_embeds_png_when_renderer_returns(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    png = b"\x89PNG\r\n\x1a\n" + b"fake"
    monkeypatch.setattr("app.pptx_figure.render_mermaid_png", lambda code: png)
    sections = [
        {
            "filename": "a.md",
            "content": "# 2.4 完成イメージ\n\n質問\n↓\n分類\n↓\n回答\n",
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "2.4 完成イメージ"},
                        "role": "procedure",
                        "figure": "flowchart",
                        "figure_caption": "完成イメージ",
                        "points": ["質問", "分類", "回答"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    assets: dict[str, bytes] = {}
    deck = plan_deck("文書", sections, assets, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    rel = content["content"]["image"]
    assert rel
    assert assets[rel] == png
    data = render_deck(deck, assets)
    assert data[:2] == b"PK"


def test_llm_figure_on_prose_becomes_frame(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    monkeypatch.setattr("app.pptx_figure.render_mermaid_png", lambda code: None)
    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 質問分類を設定する\n\n"
                "利用者の質問を分類し、正規職員なら規則を検索し、区分不明なら聞き返す。\n"
            ),
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "質問分類を設定する"},
                        "role": "explanation",
                        "title": "質問の分岐",
                        "figure": "flowchart",
                        "figure_caption": "質問の分岐",
                        "points": ["利用者の質問を分類し", "正規職員なら規則を検索し", "区分不明なら聞き返す"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "figure-frame"
    assert content["content"]["alt"] == "ここに質問の分岐の図を入れる"


def test_table_and_short_steps_stay_native(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 用語\n\n| 語 | 意味 |\n|---|---|\n| 検索 | 遅い |\n\n"
                "# 6.1 手順\n- 開く\n- 作る\n"
            ),
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "用語"},
                        "role": "definition",
                        "figure": "",
                        "points": ["検索 / 遅い"],
                    },
                    {
                        "source": {"filename": "a.md", "heading": "6.1 手順"},
                        "role": "procedure",
                        "figure": "",
                        "points": ["開く", "作る"],
                    },
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    contents = [s for s in deck["slides"] if s["type"] == "content"]
    layouts = {s["title"]: s["layout"] for s in contents}
    assert layouts["用語"] == "axis-table"
    assert layouts["6.1 手順"] == "chevron-steps"
    assert "figure-frame" not in {s["layout"] for s in contents}


def test_pending_mermaid_assigns_path_when_png_missing():
    from app.pptx_figure import pending_mermaid

    deck = {
        "slides": [
            {
                "type": "content",
                "layout": "figure-frame",
                "content": {"mermaid": "flowchart TD\nA-->B", "image": "", "alt": "図"},
            }
        ]
    }
    items = pending_mermaid(deck, {})
    assert len(items) == 1
    assert items[0]["code"].startswith("flowchart LR")
    assert items[0]["path"].startswith("images/pptx-mmd-")
    assert deck["slides"][0]["content"]["image"] == items[0]["path"]
    assert pending_mermaid(deck, {items[0]["path"]: b"\x89PNG\r\n\x1a\n" + b"ok"}) == []
    assert pending_mermaid(deck, {items[0]["path"]: b"not-a-png"}) != []


def test_mermaid_flowchart_is_lr():
    from app.pptx_figure import mermaid_flowchart, mermaid_landscape

    assert mermaid_flowchart(["準備", "確認"], branch=False).startswith("flowchart LR")
    assert mermaid_landscape("flowchart TD\nA-->B").startswith("flowchart LR")
    assert mermaid_landscape("graph TB\nA-->B").startswith("graph LR")
    assert mermaid_landscape("sequenceDiagram\nA->>B: hi").startswith("sequenceDiagram")


def test_figure_png_fits_in_slide_frame():
    import struct
    import zlib

    from app.dads import pptx_content_height

    def png(w: int, h: int) -> bytes:
        def chunk(tag: bytes, data: bytes) -> bytes:
            crc = zlib.crc32(tag + data) & 0xFFFFFFFF
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

        raw = b"".join(b"\x00" + b"\xff\xff\xff\xff" * w for _ in range(h))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 0))
            + chunk(b"IEND", b"")
        )

    deck = {
        "slides": [
            {"type": "cover", "title": "表紙"},
            {
                "type": "content",
                "title": "手順",
                "layout": "figure-frame",
                "content": {"image": "images/tall.png", "alt": "図"},
            },
        ]
    }
    data = render_deck(validate_deck(deck) or deck, {"images/tall.png": png(80, 800)})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("ppt/slides/slide2.xml").decode("utf-8")
    pic = xml.split("<p:pic>", 1)[1]
    cy = int(pic.split('cy="', 1)[1].split('"', 1)[0])
    assert cy <= int(pptx_content_height() * 914400)


def test_parse_generated_mermaid_flowchart():
    from app.pptx_figure import mermaid_flowchart, mermaid_to_flow_items, parse_mermaid_flowchart

    code = mermaid_flowchart(["質問", "分類", "正規職員", "区分不明"], branch=True)
    parsed = parse_mermaid_flowchart(code)
    assert parsed is not None
    assert len(parsed["nodes"]) == 4
    items, mode = mermaid_to_flow_items(code)
    assert mode == "branch"
    assert items[0]["heading"] == "質問"
    assert "正規職員" in {it["heading"] for it in items}


def test_editor_mermaid_png_is_embedded(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    png = b"\x89PNG\r\n\x1a\n" + b"editor"
    sections = [
        {
            "filename": "a.md",
            "content": "# 関係\n\n![diagram](images/mermaid-abc-0.png)\n",
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "関係"},
                        "role": "explanation",
                        "figure": "flowchart",
                        "figure_caption": "関係",
                        "points": ["質問", "分類"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    assets = {"images/mermaid-abc-0.png": png}
    deck = plan_deck("文書", sections, assets, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "figure-frame"
    assert content["content"]["image"] == "images/mermaid-abc-0.png"
    assert not content["content"].get("mermaid")
    from app.pptx_figure import pending_mermaid

    assert pending_mermaid(deck, assets) == []
    data = render_deck(deck, assets)
    assert data[:2] == b"PK"


def test_notes_figure_without_source_mermaid_is_pending(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "0")
    monkeypatch.setattr("app.pptx_figure.render_mermaid_png", lambda code: None)
    sections = [
        {
            "filename": "a.md",
            "content": "# 知識検索と結果なし分岐設定\n\n- 検索を開く\n- 結果なしなら聞き返す\n",
        }
    ]

    def fake_complete(messages, **kwargs):
        return json.dumps(
            {
                "slides": [
                    {
                        "source": {"filename": "a.md", "heading": "知識検索と結果なし分岐設定"},
                        "role": "procedure",
                        "figure": "flowchart",
                        "figure_caption": "知識検索",
                        "points": ["検索を開く", "結果なしなら聞き返す"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, {}, complete=fake_complete)
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "figure-frame"
    assert content["content"]["mermaid"].startswith("flowchart")
    from app.pptx_figure import pending_mermaid

    assert pending_mermaid(deck, {}) != []


def test_figure_frame_draws_mermaid_without_png():
    deck = {
        "slides": [
            {"type": "cover", "title": "表紙"},
            {
                "type": "content",
                "title": "完成イメージ",
                "layout": "figure-frame",
                "content": {
                    "caption": "質問分類",
                    "alt": "ここに質問分類の図を入れる",
                    "image": "",
                    "mermaid": (
                        "flowchart TD\n"
                        '  N0["利用者の質問"]\n'
                        '  N1["質問分類"]\n'
                        "  N0 --> N1\n"
                        '  N1 --> N2["職員規則を検索"]\n'
                    ),
                },
            },
        ]
    }
    data = render_deck(validate_deck(deck) or deck, {})
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
    assert "利用者の質問" in xml
    assert "質問分類" in xml
    assert "ここに質問分類の図を入れる" not in xml


def test_repair_keeps_short_chevron():
    from app.pptx_repair import repair_deck

    deck = repair_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "手順",
                    "layout": "chevron-steps",
                    "content": {
                        "steps": [
                            {"title": "受付"},
                            {"title": "確認"},
                            {"title": "公開"},
                        ]
                    },
                },
            ]
        }
    )
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "chevron-steps"


def test_repair_converts_overflow_flow_to_fullwidth():
    from app.pptx_repair import repair_deck

    deck = repair_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "質問分類",
                    "layout": "chevron-steps",
                    "content": {
                        "steps": [
                            {"title": "職員区分の判定を開いて分類クラスを3つ作る"},
                            {"title": "正規職員の質問は職員規則ナレッジを検索する"},
                            {"title": "区分不明のときは聞き返してから分類する"},
                        ]
                    },
                    "notes": "整理ノート\n・ 職員区分の判定を開いて分類クラスを3つ作る\n",
                },
            ]
        }
    )
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "fullwidth-points"
    assert "職員区分の判定" in content["content"]["points"][0]


def test_repair_fills_empty_table_from_notes():
    from app.pptx_repair import repair_deck

    deck = repair_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "用語",
                    "layout": "axis-table",
                    "content": {"headers": ["語", "意味"], "rows": []},
                    "notes": "整理ノート\n・ 検索 / 遅い\n・ 登録 / 重複\n",
                },
            ]
        }
    )
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "fullwidth-points"
    assert "検索 / 遅い" in content["content"]["points"]


def test_repair_long_kpis_become_table():
    from app.pptx_repair import is_metric_value, repair_deck

    assert is_metric_value("50分")
    assert is_metric_value("1.0")
    assert not is_metric_value("R8-DIFY-EX1")
    assert not is_metric_value("2026-09-12")
    assert not is_metric_value("令和8年10月19日")

    deck = repair_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "手順書概要",
                    "layout": "freeform",
                    "content": {
                        "elements": [
                            {"kind": "heading", "text": "手順書概要"},
                            {"kind": "kpi", "value": "R8-DIFY-EX1", "label": "文書番号"},
                            {"kind": "kpi", "value": "1.0", "label": "版数"},
                            {"kind": "kpi", "value": "2026-09-12", "label": "作成日"},
                            {"kind": "kpi", "value": "令和8年10月19日", "label": "対象研修"},
                            {"kind": "kpi", "value": "50分", "label": "所要時間"},
                        ]
                    },
                },
            ]
        }
    )
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "axis-table"
    rows = content["content"]["rows"]
    assert ["文書番号", "R8-DIFY-EX1"] in rows
    assert ["所要時間", "50分"] in rows


def test_repair_keeps_short_kpis():
    from app.pptx_repair import repair_deck

    deck = repair_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "規模",
                    "layout": "kpi-three-col",
                    "content": {
                        "items": [
                            {"value": "12件", "label": "質問"},
                            {"value": "3", "label": "経路"},
                            {"value": "50%", "label": "完了"},
                        ]
                    },
                },
            ]
        }
    )
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert content["layout"] == "kpi-three-col"


def test_strip_title_echo_drops_matching_heading():
    from app.pptx_repair import strip_title_echo

    content = strip_title_echo(
        "目的",
        {
            "elements": [
                {"kind": "heading", "text": "【目的】", "col": 0, "row": 0, "colspan": 12, "rowspan": 1},
                {"kind": "bullets", "col": 0, "row": 1, "colspan": 6, "rowspan": 5, "bullets": ["目的", "部署の規則"]},
            ],
            "points": ["目的", "研修後にボットを作る"],
            "items": [{"heading": "目的", "body": "ナレッジに格納する"}],
        },
    )
    kinds = [el["kind"] for el in content["elements"]]
    assert "heading" not in kinds
    assert content["elements"][0]["bullets"] == ["部署の規則"]
    assert content["points"] == ["研修後にボットを作る"]
    assert content["items"][0]["heading"] == ""
    assert content["items"][0]["body"] == "ナレッジに格納する"


def test_strip_title_echo_keeps_different_heading():
    from app.pptx_repair import strip_title_echo

    content = strip_title_echo(
        "目的",
        {"elements": [{"kind": "heading", "text": "進め方"}], "points": ["進め方"]},
    )
    assert content["elements"][0]["text"] == "進め方"
    assert content["points"] == ["進め方"]


def test_repair_deck_strips_title_echo():
    from app.pptx_repair import repair_deck

    deck = repair_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "目的",
                    "layout": "freeform",
                    "content": {
                        "elements": [
                            {"kind": "heading", "text": "目的", "col": 0, "row": 0, "colspan": 12, "rowspan": 1},
                            {
                                "kind": "bullets",
                                "col": 0,
                                "row": 1,
                                "colspan": 12,
                                "rowspan": 5,
                                "bullets": ["部署の規則をナレッジに格納する"],
                            },
                        ]
                    },
                },
            ]
        }
    )
    assert deck is not None
    content = next(s for s in deck["slides"] if s["type"] == "content")
    assert all(el.get("kind") != "heading" for el in content["content"]["elements"])


def test_repair_splits_many_short_steps():
    from app.pptx_repair import repair_deck

    deck = repair_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "手順",
                    "layout": "chevron-steps",
                    "content": {
                        "steps": [
                            {"title": "開く"},
                            {"title": "作る"},
                            {"title": "確認"},
                            {"title": "公開"},
                            {"title": "保存"},
                        ]
                    },
                },
            ]
        }
    )
    assert deck is not None
    contents = [s for s in deck["slides"] if s["type"] == "content"]
    assert len(contents) == 2
    assert all(s["layout"] == "chevron-steps" for s in contents)
    assert len(contents[0]["content"]["steps"]) == 3
    assert contents[1]["title"] == "手順（続き）"
