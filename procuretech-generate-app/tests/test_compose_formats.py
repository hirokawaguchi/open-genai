from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.compose_formats import markdown_to_html, markdown_to_md, markdown_to_txt
from app.main import app

SECTIONS = [
    {"filename": "a.md", "content": "# 背景\n\n本文です。\n\n```mermaid\ngraph TD\nA-->B\n```\n"},
    {"filename": "b.md", "content": "## 目的\n\n- 項目1\n- 項目2\n\n![図](images/z.png)\n"},
]


def test_markdown_to_md_joins_and_keeps_mermaid():
    body = markdown_to_md(SECTIONS).decode("utf-8")
    assert "# 背景" in body
    assert "```mermaid" in body
    assert "![図](images/z.png)" in body


def test_markdown_to_txt_strips_and_placeholders():
    body = markdown_to_txt(SECTIONS).decode("utf-8")
    assert "背景" in body
    assert "```" not in body
    assert "[図]" in body
    assert "[画像: images/z.png]" in body
    assert "・ 項目1" in body


def test_markdown_to_html_embeds_css_and_data_uri():
    html = markdown_to_html("文書", SECTIONS, {"images/z.png": b"PNG"}).decode("utf-8")
    assert "<style>" in html
    assert "data:image/png;base64," in html
    assert "本文です。" in html
    assert "#0017C1" in html
    assert "Noto Sans JP" in html


def test_markdown_to_html_renders_gfm_table():
    sections = [
        {
            "filename": "t.md",
            "content": (
                "# 概要\n\n"
                "| 記事 | 主張 |\n"
                "|------|------|\n"
                "| 20260904 | **離職＝卒業** |\n"
                "| 20260701 | データ主権 |\n"
            ),
        }
    ]
    body = markdown_to_html("文書", sections, {}).decode("utf-8")
    assert "<table>" in body
    assert "<th>記事</th>" in body
    assert "<th>主張</th>" in body
    assert "<td>20260904</td>" in body
    assert "<strong>離職＝卒業</strong>" in body
    assert "|------|" not in body
    assert "<p>| 記事" not in body


def test_compose_zip_respects_format():
    client = TestClient(app)
    res = client.post(
        "/compose",
        json={
            "outputs": [
                {"name": "文書", "format": "md", "sections": SECTIONS},
                {"name": "メモ", "format": "txt", "sections": SECTIONS},
            ]
        },
    )
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = set(zf.namelist())
        assert "文書.md" in names
        assert "メモ.txt" in names
        assert "```mermaid" in zf.read("文書.md").decode("utf-8")


def test_compose_unknown_format_is_422():
    client = TestClient(app)
    res = client.post(
        "/compose",
        json={"outputs": [{"name": "x", "format": "pdf", "sections": SECTIONS}]},
    )
    assert res.status_code == 422


def test_markdown_to_pptx_renders_gfm_table_as_native_table():
    pytest.importorskip("pptx")
    from app.compose_formats import markdown_to_pptx

    sections = [
        {
            "filename": "t.md",
            "content": (
                "# 著者のスタンス概要\n\n"
                "| 記事 | 主張 |\n"
                "|------|------|\n"
                "| 20260904 | 離職＝卒業 |\n"
                "| 20260701 | データ主権 |\n"
            ),
        }
    ]
    data = markdown_to_pptx("文書", sections, {})
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = "\n".join(
            zf.read(name).decode("utf-8", errors="replace")
            for name in zf.namelist()
            if name.startswith("ppt/slides/slide") and name.endswith(".xml")
        )
    assert "<a:tbl>" in xml or "<a:tbl " in xml
    assert "20260904" in xml
    assert "データ主権" in xml
    assert "|------|" not in xml


def test_markdown_to_pptx_if_available():
    pytest.importorskip("pptx")
    from app.compose_formats import markdown_to_pptx

    data = markdown_to_pptx("文書", SECTIONS, {})
    assert data[:2] == b"PK"


def test_compose_html_without_llm_uses_article_path():
    client = TestClient(app)
    res = client.post(
        "/compose",
        json={"outputs": [{"name": "文書", "format": "html", "sections": SECTIONS}]},
    )
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        body = zf.read("文書.html").decode("utf-8")
    assert "class=\"slide\"" not in body
    assert "本文です。" in body
    assert "#0017C1" in body


def test_compose_pptx_without_llm_uses_deterministic_path():
    pytest.importorskip("pptx")
    client = TestClient(app)
    res = client.post(
        "/compose",
        json={"outputs": [{"name": "文書", "format": "pptx", "sections": SECTIONS}]},
    )
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert "文書.pptx" in zf.namelist()
        assert zf.read("文書.pptx")[:2] == b"PK"


def test_markdown_to_docx_uses_dads():
    pytest.importorskip("docx")
    from app.dads import FONT, hex_of, ACCENT
    from app.main import _markdown_to_docx

    data = _markdown_to_docx("文書", SECTIONS, {})
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        styles = zf.read("word/styles.xml").decode("utf-8")
        header = zf.read("word/header1.xml").decode("utf-8")
    assert FONT in styles
    assert hex_of(ACCENT) in header
