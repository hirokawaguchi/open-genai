"""文字の少ない PDF ページへ、Vision の画像説明を足す。動画のフレームは扱わない。"""

from __future__ import annotations

import base64
import os
import re
from collections.abc import Callable

MIN_TEXT_LENGTH = 50
PROMPT = """この画像は文書のページです。表示されている内容を説明してください。

注目する点:
- 見出し
- 本文、表、図
- 読み取れる数値や要点

ルール:
- 読み取れない部分は「読み取れない」と書く
- 推測で情報を補わない
- 固有名詞と数値は、明確に読めるときだけ書く
- ページ番号には触れない
- 読み取れた事実だけを簡潔に書く
"""


def needs_vision(text: str) -> bool:
    """埋め込み文字が少ないページは、画像の説明が要る。"""
    clean = re.sub(r"[#\-\|>*\s]+", "", (text or "").strip())
    return len(clean) < MIN_TEXT_LENGTH


def configured() -> bool:
    return bool((os.environ.get("OPENAI_BASE_URL") or os.environ.get("OLLAMA_BASE_URL") or "").strip())


def _merge(text: str, description: str) -> str:
    body = (text or "").strip()
    block = f"画像の説明:\n{description.strip()}"
    if not body:
        return block
    return f"{body}\n\n{block}"


def describe_png(png: bytes) -> str:
    """1ページの画像を説明させる。失敗したら空文字。"""
    if not png or not configured():
        return ""
    from shared.llm_fallback import post_chat_sync, primary_endpoint

    base = (
        os.environ.get("OPENAI_BASE_URL")
        or (os.environ.get("OLLAMA_BASE_URL", "").rstrip("/") + "/v1")
    ).rstrip("/")
    api_key = os.environ.get("OPENAI_API_KEY") or "ollama"
    model = (
        os.environ.get("LMS_VISION_MODEL")
        or os.environ.get("DOCCHECK_VISION_MODEL")
        or "gemma4:cloud"
    )
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode("ascii")},
                    },
                ],
            }
        ],
        "max_tokens": 800,
        "temperature": 0,
    }
    timeout = float(os.environ.get("LMS_VISION_TIMEOUT", "120"))
    response = post_chat_sync(primary_endpoint(base, api_key), payload, timeout)
    response.raise_for_status()
    data = response.json()
    message = (data.get("choices") or [{}])[0].get("message") or {}
    return str(message.get("content") or "").strip()


def enrich_sparse_pages(
    pages: list[str],
    images: list[bytes],
    on_status: Callable[[str], None] | None = None,
) -> tuple[list[str], str]:
    """文字の少ないページに画像説明を足して返す。説明できなければ元の文字のまま。"""
    needed = [index for index, text in enumerate(pages) if needs_vision(text)]
    if not needed:
        return pages, ""
    if not configured():
        return pages, "画像の多いページの説明には、Vision のモデル設定が必要です"
    cap = int(os.environ.get("LMS_VISION_MAX_PAGES", "30"))
    chosen = needed[:cap]
    skipped = len(needed) - len(chosen)
    updated = list(pages)
    failed = 0
    for offset, index in enumerate(chosen, start=1):
        if on_status:
            on_status(f"画像の多いページを説明しています {offset}/{len(chosen)}")
        png = images[index] if index < len(images) else b""
        try:
            description = describe_png(png)
        except Exception:
            description = ""
        if not description:
            failed += 1
            continue
        updated[index] = _merge(pages[index], description)
    notes: list[str] = []
    if failed:
        notes.append("一部のページは画像の説明を付けられませんでした")
    if skipped:
        notes.append(f"画像の説明は {cap} ページまでです")
    return updated, "。".join(notes)
