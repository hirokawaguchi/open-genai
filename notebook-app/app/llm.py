"""OpenAI 互換 chat/completions（navigator と同じ環境変数）。"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

OLLAMA_BASE_URL = os.environ.get(
    "OLLAMA_BASE_URL", "http://host.docker.internal:11434"
).rstrip("/")
OPENAI_BASE_URL = (os.environ.get("OPENAI_BASE_URL") or f"{OLLAMA_BASE_URL}/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "ollama"
PROCURETECH_MODEL = (
    os.environ.get("PROCURETECH_MODEL") or os.environ.get("DEFAULT_MODEL") or "qwen2.5:7b"
)
REQUEST_TIMEOUT = float(os.environ.get("PROCURETECH_LLM_TIMEOUT", "180"))
DEFAULT_MAX_TOKENS = int(os.environ.get("HEARING_LLM_MAX_TOKENS", "2048"))
LLM_ENABLED = os.environ.get("HEARING_LLM", "1").strip().lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _extra_body() -> dict[str, Any]:
    raw = (os.environ.get("PROCURETECH_EXTRA_BODY") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            print(f"[hearing] PROCURETECH_EXTRA_BODY が不正な JSON です: {raw[:80]}")
    return {"chat_template_kwargs": {"enable_thinking": False}}


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    return content.strip() if isinstance(content, str) else ""


async def chat(messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
    if not LLM_ENABLED:
        raise RuntimeError("LLM は無効です（HEARING_LLM=0）")
    payload: dict[str, Any] = {
        "model": PROCURETECH_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }
    payload.update(_extra_body())
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json=payload,
            headers=_headers(),
        )
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or [{}]
    text = _message_text(choices[0].get("message") or {})
    if not text:
        raise ValueError("モデルの応答本文が空です")
    return text
