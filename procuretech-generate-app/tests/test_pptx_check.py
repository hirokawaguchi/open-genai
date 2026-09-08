from __future__ import annotations

from app.pptx_check import check_deck, check_html_bytes, check_pptx_bytes
from app.pptx_layouts import render_deck


def test_check_deck_flags_desumasu_and_count_title():
    issues = check_deck(
        {
            "slides": [
                {"type": "cover", "title": "これは結論です"},
                {"type": "content", "title": "3つの理由", "layout": "parallel-items", "content": {"items": [{"heading": "A"}]}},
            ]
        }
    )
    codes = {i.code for i in issues}
    assert "desumasu" in codes
    assert "count-title" in codes


def test_check_deck_ok_for_claim_title():
    issues = check_deck(
        {
            "slides": [
                {"type": "cover", "title": "検索遅延を索引で解消する"},
                {"type": "content", "title": "重複登録は一意制約で止める", "layout": "axis-table", "content": {"rows": [["a"]]}},
            ]
        }
    )
    assert not [i for i in issues if i.level == "FAIL"]


def test_check_html_flags_large_radius():
    issues = check_html_bytes("<style>.x{border-radius:8px}</style>")
    assert any(i.code == "border-radius" for i in issues)


def test_check_pptx_bytes_accepts_rectangles():
    data = render_deck(
        {
            "slides": [
                {"type": "cover", "title": "表紙"},
                {
                    "type": "content",
                    "title": "要点",
                    "layout": "axis-table",
                    "content": {"headers": ["項目", "内容"], "rows": [["検索", "遅い"]]},
                },
            ]
        },
        {},
    )
    assert data[:2] == b"PK"
    assert not [i for i in check_pptx_bytes(data) if i.code == "round-rect"]
