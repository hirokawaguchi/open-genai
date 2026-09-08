"""参考ファイルの本文化。ナレッジと同じ shared.docextract を使う。"""

from __future__ import annotations

import base64
import sys
from pathlib import Path

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


def extract_file(filename: str, raw: bytes) -> str:
    pages = extract_doc_pages(filename, "", base64.b64encode(raw).decode("ascii"))
    parts = [str(p.get("text") or "").strip() for p in pages if p.get("text")]
    text = "\n\n".join(parts).strip()
    if not text:
        raise DocExtractError(f"{filename} からテキストを抽出できませんでした")
    return text


__all__ = ["DocExtractError", "accept_exts", "allowed_name", "extract_file"]
