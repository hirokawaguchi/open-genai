"""スキャン PDF 向けの任意 OCR（RapidOCR）。doccheck と同じ系統。"""

from __future__ import annotations

import os
from typing import Any

OCR_ENABLED = os.environ.get("NOTEBOOK_OCR", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)
MAX_OCR_PAGES = int(os.environ.get("NOTEBOOK_OCR_MAX_PAGES", "40"))
OCR_SCALE = float(os.environ.get("NOTEBOOK_OCR_SCALE", "1.8"))
EMPTY_PAGE_CHARS = 8

_engine: Any | None = None
_engine_failed = False


def enabled() -> bool:
    return OCR_ENABLED and not _engine_failed


def status() -> dict[str, Any]:
    return {
        "enabled": enabled(),
        "engine": "rapidocr" if enabled() else "",
        "max_pages": MAX_OCR_PAGES,
    }


def needs_ocr(pages: list[dict[str, Any]]) -> bool:
    if not pages:
        return True
    empty = 0
    for p in pages:
        if len(str(p.get("text") or "").strip()) < EMPTY_PAGE_CHARS:
            empty += 1
    return empty * 2 >= len(pages)


def _get_engine() -> Any | None:
    global _engine, _engine_failed
    if _engine is not None:
        return _engine
    if _engine_failed:
        return None
    try:
        from rapidocr_onnxruntime import RapidOCR

        _engine = RapidOCR()
        return _engine
    except Exception as e:  # noqa: BLE001
        _engine_failed = True
        print(f"[notebook-ocr] RapidOCR を初期化できません: {e}")
        return None


def _lines_from_result(result: Any) -> list[str]:
    out: list[str] = []
    rows = result[0] if isinstance(result, tuple) else result
    if not isinstance(rows, list):
        return out
    for row in rows:
        text = ""
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            rec = row[1]
            if isinstance(rec, (list, tuple)) and rec:
                text = str(rec[0] or "")
            else:
                text = str(rec or "")
        elif isinstance(row, dict):
            text = str(row.get("text") or row.get("rec_text") or "")
        cleaned = " ".join(str(text).split())
        if cleaned:
            out.append(cleaned)
    return out


def ocr_pdf(raw: bytes, *, only_pages: set[int] | None = None) -> dict[int, str]:
    """ページ番号(1始まり) → OCR テキスト。失敗したページは載せない。"""
    if not enabled():
        return {}
    engine = _get_engine()
    if engine is None:
        return {}
    try:
        import pypdfium2 as pdfium
    except Exception as e:  # noqa: BLE001
        print(f"[notebook-ocr] pypdfium2 が使えません: {e}")
        return {}
    try:
        doc = pdfium.PdfDocument(raw)
    except Exception as e:  # noqa: BLE001
        print(f"[notebook-ocr] PDF を開けません: {e}")
        return {}
    found: dict[int, str] = {}
    total = len(doc)
    done = 0
    try:
        for i in range(total):
            page_no = i + 1
            if only_pages is not None and page_no not in only_pages:
                continue
            if done >= MAX_OCR_PAGES:
                break
            try:
                page = doc[i]
                bitmap = page.render(scale=OCR_SCALE)
                image = bitmap.to_numpy()
                result, _elapse = engine(image)
                lines = _lines_from_result(result)
                if lines:
                    found[page_no] = "\n".join(lines)
            except Exception as e:  # noqa: BLE001
                print(f"[notebook-ocr] {page_no} ページの読取に失敗: {e}")
            done += 1
    finally:
        try:
            doc.close()
        except Exception:  # noqa: BLE001
            pass
    return found


def merge_ocr(pages: list[dict[str, Any]], ocr_pages: dict[int, str]) -> list[dict[str, Any]]:
    if not ocr_pages:
        return pages
    by_no = {int(p.get("page") or 0): dict(p) for p in pages}
    for no, text in ocr_pages.items():
        cur = by_no.get(no) or {"page": no, "text": ""}
        if len(str(cur.get("text") or "").strip()) < EMPTY_PAGE_CHARS:
            cur["text"] = text
            cur["ocr"] = True
        by_no[no] = cur
    return [by_no[k] for k in sorted(by_no) if k > 0]
