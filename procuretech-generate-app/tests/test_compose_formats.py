from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.compose_formats import markdown_to_docx, markdown_to_html, markdown_to_md, markdown_to_txt
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


def test_markdown_to_html_is_vertical_document():
    """庁内文書向けの縦スクロール文書（スライドではない）で自己完結する。"""
    html = markdown_to_html("報告書", SECTIONS, {"images/z.png": b"PNG"}).decode("utf-8")
    assert 'class="slide"' not in html
    assert '<main class="doc">' in html
    assert '<header class="doc-header">' in html
    assert "<h1>報告書</h1>" in html
    assert 'name="viewport"' in html
    assert "@media print" in html


def test_markdown_to_html_renders_inline_and_blocks():
    sections = [
        {
            "filename": "a.md",
            "content": (
                "# 概要\n\n"
                "本文に *斜体* と ~~取消~~ と [公式](https://example.com) を含む。\n\n"
                "1. 最初\n2. 次\n\n"
                "---\n\n"
                "## 詳細\n\n"
                "本文。\n\n"
                "# まとめ\n\n"
                "```mermaid\ngraph TD\nA-->B\n```\n"
            ),
        }
    ]
    html = markdown_to_html("文書", sections, {}).decode("utf-8")
    assert "<em>斜体</em>" in html
    assert "<s>取消</s>" in html
    assert '<a href="https://example.com" rel="noopener noreferrer">公式</a>' in html
    assert "<ol>" in html and "<li>最初</li>" in html
    assert "<hr>" in html
    assert 'id="sec-1"' in html
    assert 'class="toc"' in html  # 見出しが3以上で目次が出る
    assert "Mermaid 図" in html  # 画像未変換のソース表示注記


def test_markdown_to_html_sanitizes_javascript_links():
    sections = [{"filename": "a.md", "content": "[危険](javascript:alert(1))\n"}]
    html = markdown_to_html("文書", sections, {}).decode("utf-8")
    assert "javascript:" not in html
    assert "危険" in html


def test_markdown_to_html_skips_toc_when_few_headings():
    sections = [{"filename": "a.md", "content": "## 唯一\n\n本文。\n"}]
    html = markdown_to_html("文書", sections, {}).decode("utf-8")
    assert 'class="toc"' not in html


def test_compose_html_never_uses_slides_even_with_llm(monkeypatch):
    """html は LLM デッキを通さないので、GENERATE_PPTX_LLM=1 でもスライドにならない。"""
    monkeypatch.setenv("GENERATE_PPTX_LLM", "1")
    client = TestClient(app)
    res = client.post(
        "/compose",
        json={"outputs": [{"name": "文書", "format": "html", "sections": SECTIONS}]},
    )
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        body = zf.read("文書.html").decode("utf-8")
    assert 'class="slide"' not in body
    assert '<main class="doc">' in body


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


def test_compose_job_lifecycle_and_progress():
    import time as _t

    client = TestClient(app)
    started = client.post(
        "/compose/jobs",
        json={"outputs": [{"name": "文書", "format": "md", "sections": SECTIONS}]},
    )
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    progresses = []
    status = ""
    for _ in range(100):
        st = client.get(f"/compose/jobs/{job_id}")
        assert st.status_code == 200
        body = st.json()
        progresses.append(int(body.get("progress") or 0))
        status = body.get("status")
        if status in ("success", "error"):
            break
        _t.sleep(0.05)
    assert status == "success"
    # 進捗は単調非減少で最後は 100
    assert progresses == sorted(progresses)
    assert progresses[-1] == 100
    res = client.get(f"/compose/jobs/{job_id}/result")
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        assert "文書.md" in zf.namelist()


def test_compose_job_result_not_ready_is_409():
    client = TestClient(app)
    st = client.get("/compose/jobs/does-not-exist")
    assert st.status_code == 404


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
    from app.dads import ACCENT, DOCX_FONT, hex_of

    data = markdown_to_docx("文書", SECTIONS, {})
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        styles = zf.read("word/styles.xml").decode("utf-8")
        header = zf.read("word/header1.xml").decode("utf-8")
    # docx は置換回避のためプリインストールの游ゴシックを使う（HTML/PPTX は Noto）。
    assert DOCX_FONT in styles
    assert hex_of(ACCENT) in header


def test_markdown_to_docx_renders_gfm_table():
    pytest.importorskip("docx")
    sections = [
        {
            "filename": "t.md",
            "content": (
                "# 概要\n\n"
                "前文です。\n\n"
                "| 記事 | 主張 |\n"
                "|------|------|\n"
                "| 20260904 | **離職＝卒業** |\n"
                "| 20260701 | データ主権 |\n"
            ),
        }
    ]
    data = markdown_to_docx("文書", sections, {})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:tbl>" in xml
    assert "20260904" in xml
    assert "離職＝卒業" in xml
    assert "データ主権" in xml
    assert "|------|" not in xml
    assert "| 記事 |" not in xml
    assert "| 20260904 |" not in xml


def test_markdown_to_docx_inline_lists_and_quote():
    pytest.importorskip("docx")
    sections = [
        {
            "filename": "t.md",
            "content": (
                "これは **太字** と *斜体* と `code` です。\n\n"
                "- 項目A\n"
                "1. 番号付き\n\n"
                "> 引用です\n\n"
                "---\n"
            ),
        }
    ]
    data = markdown_to_docx("文書", sections, {})
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "太字" in xml
    assert "斜体" in xml
    assert "code" in xml
    assert "**太字**" not in xml
    assert "*斜体*" not in xml
    assert "`code`" not in xml
    assert "項目A" in xml
    assert "番号付き" in xml
    assert "引用です" in xml
