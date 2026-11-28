"""画像を別の画像対応モデルに説明させ、文章にする。エージェント自身は画像を見ない。"""

from __future__ import annotations

import base64
import os

from shared.llm_fallback import post_chat, primary_endpoint

from . import llm

_OFF = {"", "0", "off", "false", "no"}
_PROMPT = """この画像に写っていることを、日本語で説明してください。

書いてほしいこと:
- 見出しや図のラベル
- 読める文字
- 手順や関係

ルール:
- 読み取れない部分は「読み取れない」と書く
- 推測で情報を補わない
- 説明だけを書く
"""


def model_name() -> str:
    raw = os.environ.get("NOTEBOOK_VISION_MODEL", "gemma4:cloud").strip()
    if raw.lower() in _OFF:
        return ""
    return raw


def enabled() -> bool:
    return bool(model_name())


def description_name(filename: str) -> str:
    """画像ファイル名から、説明文の Markdown 名を作る。"""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    stem = base.rsplit(".", 1)[0] if "." in base else base
    stem = stem.strip() or "画像"
    return f"{stem}-説明.md"


async def describe_image(raw: bytes, *, media: str = "image/png") -> str:
    """画像の説明文。失敗したら空文字。"""
    model = model_name()
    if not model or not raw:
        return ""
    encoded = base64.b64encode(raw).decode("ascii")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media};base64,{encoded}"},
                    },
                ],
            }
        ],
        "max_tokens": 800,
        "temperature": 0,
    }
    timeout = float(os.environ.get("NOTEBOOK_VISION_TIMEOUT", "120"))
    try:
        response = await post_chat(
            primary_endpoint(llm.OPENAI_BASE_URL, llm.OPENAI_API_KEY),
            payload,
            timeout,
        )
        response.raise_for_status()
        data = response.json()
        message = ((data.get("choices") or [{}])[0].get("message") or {})
        return llm.message_text(message).strip()
    except Exception as exc:  # noqa: BLE001
        print(f"[notebook-vision] 説明に失敗: {exc}")
        return ""
