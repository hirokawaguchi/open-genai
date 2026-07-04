from __future__ import annotations

import base64
import io

import pytest
from pypdf import PdfWriter

import docextract


def test_strip_base64_prefix_removes_data_uri() -> None:
    raw = base64.b64encode(b"hello").decode("ascii")
    assert docextract.strip_base64_prefix(f"data:text/plain;base64,{raw}") == raw


def test_b64_to_bytes_decodes_payload() -> None:
    raw = base64.b64encode(b"sample").decode("ascii")
    assert docextract.b64_to_bytes(raw) == b"sample"


def test_extract_doc_text_from_plain_text() -> None:
    payload = base64.b64encode("hello world".encode()).decode("ascii")
    assert docextract.extract_doc_text("note.txt", "text/plain", payload) == "hello world"


def test_extract_doc_text_from_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    payload = base64.b64encode(buf.getvalue()).decode("ascii")
    result = docextract.extract_doc_text("doc.pdf", "application/pdf", payload)
    assert result is not None
    assert "doc.pdf" in result


def test_extract_doc_text_truncates_long_content(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(docextract, "MAX_DOC_CHARS", 10)
    payload = base64.b64encode("01234567890123456789".encode()).decode("ascii")
    result = docextract.extract_doc_text("long.txt", "text/plain", payload)
    assert result is not None
    assert result.endswith("…(以下省略)")
    assert len(result) <= 10 + len("\n…(以下省略)")
