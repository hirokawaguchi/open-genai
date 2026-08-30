"""画像認識・文書読取。文書は rag-app と同じ shared.docextract で抽出する。"""

from __future__ import annotations

import base64
import binascii
import re
import sys
from pathlib import Path
from typing import Any

from . import llm

MAX_BYTES = 4 * 1024 * 1024
MAX_CHARS = 80_000
MERGE_PAGE_CHARS = 400
_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def _ensure_shared() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "shared" / "docextract.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return


_ensure_shared()
from shared.docextract import DocExtractError, extract_doc_pages  # noqa: E402


_IMAGE_PROMPT = (
    "画像に書かれている文字や内容を日本語で読み取ってください。"
    "読み取った内容だけを返し、説明や前置きは不要です。"
    "読めない場合は空文字だけを返してください。"
)


def decode_payload(data: str) -> tuple[bytes, str]:
    raw = (data or "").strip()
    mime = "application/octet-stream"
    if raw.startswith("data:"):
        header, _, b64 = raw.partition(",")
        mime = header[5:].split(";")[0] or mime
        raw = b64
    try:
        blob = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError("ファイルデータを解読できません") from e
    if not blob:
        raise ValueError("ファイルが空です")
    if len(blob) > MAX_BYTES:
        raise ValueError("ファイルが大きすぎます（4MBまで）")
    return blob, mime


def pages_to_guide_text(pages: list[dict[str, Any]]) -> str:
    """ページ配列を、見出し付きの手引き本文にする（rag-app の木構造と同じ方針）。"""
    ordered = sorted(pages, key=lambda x: int(x.get("page") or 0))
    texts = [(p.get("text") or "").strip() for p in ordered]
    nonempty = [t for t in texts if t]
    if not nonempty:
        return ""
    joined = "\n\n".join(nonempty)
    if len(nonempty) == 1 and len(joined) < 3000 and not _MD_HEADING.search(joined):
        return joined

    headings = list(_MD_HEADING.finditer(joined))
    if len(headings) >= 2:
        parts: list[str] = []
        for i, match in enumerate(headings):
            end = headings[i + 1].start() if i + 1 < len(headings) else len(joined)
            title = match.group(2).strip()
            body = joined[match.end() : end].strip()
            parts.append(f"## {title}\n{body}".strip())
        return "\n\n".join(parts)

    groups: list[tuple[int, int, str]] = []
    cur_start = int(ordered[0].get("page") or 1)
    cur_end = cur_start
    cur_parts = [ordered[0].get("text") or ""]

    def flush() -> None:
        text = "\n\n".join(p for p in cur_parts if p).strip()
        if text:
            groups.append((cur_start, cur_end, text))

    for page in ordered[1:]:
        pg = int(page.get("page") or cur_end + 1)
        so_far = sum(len(x) for x in cur_parts)
        if so_far < MERGE_PAGE_CHARS:
            cur_end = pg
            cur_parts.append(page.get("text") or "")
        else:
            flush()
            cur_start = pg
            cur_end = pg
            cur_parts = [page.get("text") or ""]
    flush()

    out: list[str] = []
    for start, end, text in groups:
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        title = first if 0 < len(first) <= 40 else (f"p.{start}" if start == end else f"p.{start}-{end}")
        body = text[len(first) :].strip() if first and title == first else text
        out.append(f"## {title}\n{body}".strip())
    return "\n\n".join(out)


async def extract_payload(
    *,
    kind: str,
    filename: str,
    data: str,
) -> dict[str, Any]:
    kind = (kind or "").strip()
    if kind not in ("image", "document"):
        raise ValueError("kind は image または document です")
    name = filename or "upload"

    if kind == "document":
        mime = "application/octet-stream"
        if (data or "").startswith("data:"):
            mime = data[5:].split(";", 1)[0] or mime
        try:
            pages = extract_doc_pages(name, mime, data)
        except DocExtractError as e:
            return {
                "extracted": "",
                "source": "unavailable",
                "filename": name,
                "notes": str(e),
            }
        if not pages:
            return {
                "extracted": "",
                "source": "unavailable",
                "filename": name,
                "notes": (
                    "この形式は自動読取できません。"
                    "txt / md / pdf / docx / xlsx / pptx / xls を選んでください。"
                    "古い Word（doc）と PowerPoint（ppt）は取れる範囲だけ読みます。"
                    "スキャン画像だけの PDF は読めません。"
                ),
            }
        text = pages_to_guide_text(pages)
        if not text.strip():
            return {
                "extracted": "",
                "source": "unavailable",
                "filename": name,
                "notes": f"{name} から本文を取れませんでした。スキャン画像だけの PDF は読めません。",
            }
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS] + "\n\n…（以降を省略しました）"
        return {
            "extracted": text,
            "source": "docextract",
            "filename": name,
            "page_count": len(pages),
            }

    blob, mime = decode_payload(data)
    data_url = data if data.startswith("data:image/") else f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"
    if not data_url.startswith("data:image/"):
        data_url = f"data:image/png;base64,{base64.b64encode(blob).decode('ascii')}"
    try:
        text = await llm.chat_vision(_IMAGE_PROMPT, data_url)
    except Exception as e:  # noqa: BLE001
        return {
            "extracted": "",
            "source": "unavailable",
            "filename": name,
            "notes": f"画像の自動読取に失敗しました。内容を手入力してください（{e}）。",
        }
    return {
        "extracted": (text or "").strip()[:MAX_CHARS],
        "source": "llm",
        "filename": name,
        "model": llm.PATCHFORM_VISION_MODEL,
    }
