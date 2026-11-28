"""Office ファイルを、モーダル用の文字・表・スライド文言にする。"""

from __future__ import annotations

import io

_NOTE = "文字と表だけを表示しています。図やレイアウトは含まれません。"
_MAX_BYTES = 20 * 1024 * 1024


def office_preview(name: str, raw: bytes) -> dict | None:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext not in {"docx", "xlsx", "pptx"}:
        return None
    if len(raw) > _MAX_BYTES:
        raise ValueError("ファイルが大きすぎて、画面では表示できません。")
    if ext == "xlsx":
        sheets = _xlsx_sheets(raw)
        if not sheets:
            raise ValueError("このファイルから文字を取れませんでした。")
        return {"kind": "sheets", "sheets": sheets, "note": _NOTE}
    if ext == "pptx":
        slides = _pptx_slides(raw)
        if not slides:
            raise ValueError("このファイルから文字を取れませんでした。")
        return {"kind": "slides", "slides": slides, "note": _NOTE}
    text = _docx_text(raw)
    if not text.strip():
        raise ValueError("このファイルから文字を取れませんでした。")
    if len(text) > 20000:
        text = text[:20000] + "\n…"
    return {"kind": "text", "text": text, "note": _NOTE}


def _docx_text(raw: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(raw))
    lines: list[str] = []
    for paragraph in doc.paragraphs:
        text = paragraph.text.strip()
        if text:
            lines.append(text)
    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                lines.append("\t".join(cells))
    return "\n".join(lines)


def _xlsx_sheets(raw: bytes) -> list[dict]:
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        sheets = []
        for ws in book.worksheets[:3]:
            rows = _limited_rows(ws.iter_rows(values_only=True))
            if rows:
                sheets.append({"name": ws.title, "rows": rows})
        return sheets
    finally:
        book.close()


def _limited_rows(source) -> list[list[str]]:
    rows: list[list[str]] = []
    extra = False
    for raw in source:
        cells = ["" if cell is None else str(cell).strip()[:200] for cell in list(raw)[:12]]
        while cells and not cells[-1]:
            cells.pop()
        if not cells:
            continue
        if len(rows) >= 40:
            extra = True
            break
        rows.append(cells)
    if extra:
        rows.append(["…"])
    return rows


def _pptx_slides(raw: bytes) -> list[dict]:
    from pptx import Presentation

    deck = Presentation(io.BytesIO(raw))
    slides = []
    for index, slide in enumerate(deck.slides, start=1):
        lines = []
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                text = (shape.text or "").strip()
                if text:
                    lines.append(text[:2000])
        if lines:
            slides.append({"title": f"スライド {index}", "lines": lines[:20]})
        if len(slides) >= 30:
            break
    return slides
