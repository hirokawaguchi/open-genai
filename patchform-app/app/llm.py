"""OpenAI 互換 chat/completions 呼び出し（Ollama 等）。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip(
    "/"
)
OPENAI_BASE_URL = (
    os.environ.get("OPENAI_BASE_URL") or f"{OLLAMA_BASE_URL}/v1"
).rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "ollama"
PATCHFORM_MODEL = (
    os.environ.get("PATCHFORM_MODEL") or os.environ.get("DEFAULT_MODEL") or "qwen2.5:7b"
)
PATCHFORM_VISION_MODEL = (
    os.environ.get("PATCHFORM_VISION_MODEL")
    or os.environ.get("DOCCHECK_VISION_MODEL")
    or "gemma3:12b"
)
REQUEST_TIMEOUT = float(os.environ.get("PATCHFORM_LLM_TIMEOUT", "120"))
DEFAULT_MAX_TOKENS = int(os.environ.get("PATCHFORM_LLM_MAX_TOKENS", "2048"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


async def chat(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model or PATCHFORM_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json=payload,
            headers=_headers(),
        )
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or [{}]
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _strip_fences(raw: str) -> str:
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


def extract_json(text: str) -> Any:
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空の応答です")
    body = _strip_fences(raw)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = body.find(open_c)
        end = body.rfind(close_c)
        if start >= 0 and end > start:
            try:
                return json.loads(body[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"JSON を解析できませんでした: {text[:240]}")


async def chat_vision(
    prompt: str,
    image_data_url: str,
    *,
    model: str | None = None,
    max_tokens: int = 512,
) -> str:
    """画像 + テキストの Vision 呼び出し。失敗時は例外。"""
    return await chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                ],
            }
        ],
        temperature=0,
        model=model or PATCHFORM_VISION_MODEL,
        max_tokens=max_tokens,
    )
