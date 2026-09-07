"""OpenAI 互換 chat/completions（PPTX プランナ用）。editor-app の llm.py と同型。"""

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
REQUEST_TIMEOUT = float(os.environ.get("GENERATE_LLM_TIMEOUT", "120"))
DEFAULT_MAX_TOKENS = int(os.environ.get("GENERATE_LLM_MAX_TOKENS", "4096"))


def llm_enabled() -> bool:
    """未指定時は ON。テストとオフラインは GENERATE_PPTX_LLM=0。

    editor と同様、OPENAI_BASE_URL が空なら OLLAMA_BASE_URL /v1 を使う。
    以前は OPENAI_BASE_URL 必須にしていたため、Ollama だけの環境では
    決定論変換に落ちて見た目が変わらなかった。
    """
    flag = (os.environ.get("GENERATE_PPTX_LLM") or "1").strip().lower()
    return flag not in {"0", "false", "off", "no"}


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
            pass
    return {"chat_template_kwargs": {"enable_thinking": False}}


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return content.strip() if isinstance(content, str) else ""


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.1,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model or PROCURETECH_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
    }
    payload.update(_extra_body())
    with httpx.Client(timeout=REQUEST_TIMEOUT) as client:
        res = client.post(
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
