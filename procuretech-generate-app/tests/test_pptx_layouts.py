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


def test_plan_deck_invalid_json_returns_none(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://example.invalid")

    def fake_complete(messages, **kwargs):
        return "これは JSON ではありません"

    assert plan_deck("文書", [{"filename": "a.md", "content": "# 背景\n本文\n"}], complete=fake_complete) is None


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
                    {"type": "cover", "title": "文書"},
                    {
                        "type": "content",
                        "title": "背景",
                        "layout": "parallel-items",
                        "source": {"filename": "a.md", "heading": "背景"},
                    },
                ]
            },
            ensure_ascii=False,
        )

    deck = plan_deck("文書", sections, complete=fake_complete)
    assert deck is not None
    contents = [s for s in deck["slides"] if s["type"] == "content"]
    assert contents
    assert contents[0]["layout"] == "parallel-items"
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
                    {"type": "cover", "title": "文書"},
                    {
                        "type": "content",
                        "title": "構成",
                        "layout": "venn-diagram",
                        "source": {"filename": "a.md", "heading": "構成"},
                    },
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
                    {"type": "cover", "title": "文書"},
                    {
                        "type": "content",
                        "title": "業務の手順",
                        "layout": "fullscreen-photo",
                        "source": {"filename": "section2.md", "heading": "業務の手順"},
                    },
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
                    {"type": "cover", "title": "文書"},
                    {
                        "type": "content",
                        "title": "背景",
                        "layout": "parallel-items",
                        "source": {"filename": "a.md", "heading": "背景"},
                        "content": {"items": [{"heading": long_a, "description": long_a}]},
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


def test_plan_three_pass_applies_adopted_title_only(monkeypatch):
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    monkeypatch.setenv("GENERATE_PPTX_REVIEW", "1")
    calls: list[str] = []

    def fake_complete(messages, **kwargs):
        blob = messages[-1]["content"]
        calls.append(blob[:40])
        if "layout だけ" in messages[0]["content"]:
            return json.dumps(
                {
                    "slides": [
                        {
                            "type": "content",
                            "title": "検索が遅く重複がある",
                            "layout": "axis-table",
                            "source": {"filename": "a.md", "heading": "背景"},
                        }
                    ]
                },
                ensure_ascii=False,
            )
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
                    {"type": "cover", "title": "更改の論点"},
                    {
                        "type": "content",
                        "title": "検索が遅く重複がある",
                        "source": {"filename": "a.md", "heading": "背景"},
                    },
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
    assert len(calls) == 3
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
                    {"type": "cover", "title": "文書"},
                    {
                        "type": "content",
                        "title": "スタンス",
                        "layout": "parallel-items",
                        "source": {"filename": "a.md", "heading": "スタンス"},
                    },
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
