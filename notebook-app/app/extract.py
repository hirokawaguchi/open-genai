"""参考ファイルの本文化。ナレッジと同じ shared.docextract を使う。"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

from . import ocr

_ACCEPT = (".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".html", ".json")


def _ensure_shared() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "shared" / "docextract.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return


_ensure_shared()
from shared.docextract import DocExtractError, extract_doc_pages  # noqa: E402


def accept_exts() -> tuple[str, ...]:
    return _ACCEPT


def allowed_name(filename: str) -> bool:
    name = filename.rsplit("/", 1)[-1].lower()
    return any(name.endswith(ext) for ext in _ACCEPT)


def _is_pdf(filename: str) -> bool:
    return filename.lower().endswith(".pdf")


def extract_pages(filename: str, raw: bytes) -> list[dict]:
    pages: list[dict] = []
    extract_error: DocExtractError | None = None
    try:
        pages = extract_doc_pages(filename, "", base64.b64encode(raw).decode("ascii"))
    except DocExtractError as e:
        msg = str(e)
        if "上限" in msg:
            raise
        extract_error = e
        pages = []

    if _is_pdf(filename) and ocr.enabled():
        empty_nos = {
            int(p.get("page") or 0)
            for p in pages
            if len(str(p.get("text") or "").strip()) < ocr.EMPTY_PAGE_CHARS
        }
        want = empty_nos if pages else None
        if extract_error or ocr.needs_ocr(pages) or empty_nos:
            ocr_pages = ocr.ocr_pdf(raw, only_pages=want)
            pages = ocr.merge_ocr(pages, ocr_pages)

    if not any(str(p.get("text") or "").strip() for p in pages):
        if extract_error:
            raise extract_error
        raise DocExtractError(f"{filename} からテキストを抽出できませんでした")
    return pages


def extract_file(filename: str, raw: bytes) -> str:
    pages = extract_pages(filename, raw)
    parts = [str(p.get("text") or "").strip() for p in pages if p.get("text")]
    return "\n\n".join(parts).strip()


__all__ = [
    "DocExtractError",
    "accept_exts",
    "allowed_name",
    "extract_file",
    "extract_pages",
]
