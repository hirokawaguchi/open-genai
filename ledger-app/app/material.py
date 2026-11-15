"""既存資料を、項目提案に渡す文章へ読み替える。"""

from __future__ import annotations

import base64
import io
import sys
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
DOCUMENT_EXTS = frozenset({"pdf", "docx", "xlsx", "xls", "csv", "txt"})
IMAGE_EXTS = frozenset({"png", "jpg", "jpeg", "webp"})
_FORMAT_ERROR = "資料は PDF、Word、Excel、CSV、テキスト、画像（PNG、JPEG）で選んでください。"


def extension(name: str) -> str:
    ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
    if ext not in DOCUMENT_EXTS and ext not in IMAGE_EXTS:
        raise ValueError(_FORMAT_ERROR)
    return ext


def text_from_bytes(name: str, raw: bytes) -> str:
    if len(raw) > MAX_BYTES:
        raise ValueError("ファイルが大きすぎます。8MB までの資料を選んでください。")
    ext = extension(name)
    if ext in IMAGE_EXTS:
        raise ValueError("画像は文字の取り込みで読んでください。")
    if ext == "xlsx":
        return _xlsx_digest(raw)
    if ext == "xls":
        return _xls_digest(raw)
    if ext in ("csv", "txt"):
        return _plain_sample(raw)
    return _doc_text(name, raw)


def _plain_sample(raw: bytes) -> str:
    text = _decode(raw)
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) > 20:
        lines = [*lines[:20], "…"]
    if not lines:
        raise ValueError("このファイルから文字を取れませんでした。")
    return "\n".join(lines)


def _xlsx_digest(raw: bytes) -> str:
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    try:
        return _sheet_digest(
            (ws.title, ws.iter_rows(values_only=True)) for ws in book.worksheets[:3]
        )
    finally:
        book.close()


def _xls_digest(raw: bytes) -> str:
    import xlrd

    book = xlrd.open_workbook(file_contents=raw)
    sheets = []
    for sheet in book.sheets()[:3]:
        rows = (sheet.row_values(r) for r in range(sheet.nrows))
        sheets.append((sheet.name, rows))
    return _sheet_digest(sheets)


def _sheet_digest(sheets) -> str:
    chunks: list[str] = []
    for title, rows in sheets:
        kept: list[str] = []
        seen = 0
        for row in rows:
            seen += 1
            if seen > 12:
                kept.append("…")
                break
            cells = ["" if cell is None else str(cell).strip() for cell in list(row)[:12]]
            if any(cells):
                kept.append("\t".join(cells))
        if kept:
            chunks.append(f"# {title}\n" + "\n".join(kept))
    text = "\n\n".join(chunks).strip()
    if not text:
        raise ValueError("このExcelから文字を取れませんでした。")
    return text


def _doc_text(name: str, raw: bytes) -> str:
    _ensure_shared()
    from shared.docextract import DocExtractError, extract_doc_pages

    encoded = base64.b64encode(raw).decode("ascii")
    try:
        pages = extract_doc_pages(name, "", encoded)
    except DocExtractError as exc:
        message = str(exc)
        if name.lower().endswith(".pdf") and "テキストを抽出できません" in message:
            raise ValueError(
                "このPDFから文字を取れませんでした。画像だけのPDFは、ページを PNG か JPEG で選んでください。"
            ) from exc
        raise ValueError("このファイルから文字を取れませんでした。") from exc
    text = "\n\n".join(str(page.get("text") or "").strip() for page in pages).strip()
    if not text:
        raise ValueError("このファイルから文字を取れませんでした。")
    return text


def _decode(raw: bytes) -> str:
    _ensure_shared()
    from shared.docextract import decode_text_bytes

    return decode_text_bytes(raw)


def _ensure_shared() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "shared" / "docextract.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
