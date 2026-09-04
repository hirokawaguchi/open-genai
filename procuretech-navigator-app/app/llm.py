"""OpenAI 互換 chat/completions 呼び出し（Ollama 等）。

参考実装は OpenAI GPT-4o + 平文 API キーを直接叩いていたが、Open GENAI 規約に合わせて
環境変数の OpenAI 互換エンドポイント（既定は Ollama /v1）を使う。平文キーは移植しない。
"""

from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
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
DEFAULT_MAX_TOKENS = int(os.environ.get("PROCURETECH_LLM_MAX_TOKENS", "2048"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _extra_body() -> dict[str, Any]:
    """Qwen3.x 等は既定で思考モードになり応答が空のまま待たされるため無効化する。"""
    raw = (os.environ.get("PROCURETECH_EXTRA_BODY") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            print(f"[procuretech] PROCURETECH_EXTRA_BODY が不正な JSON です: {raw[:80]}")
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


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """メッセージ列を渡してアシスタント本文を返す（非ストリーミング）。"""
    payload: dict[str, Any] = {
        "model": model or PROCURETECH_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
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


def _delta_text(delta: dict[str, Any]) -> str:
    """ストリーミング delta から本文断片を取り出す（reasoning はスキップ）。"""
    content = delta.get("content")
    return content if isinstance(content, str) else ""


async def chat_stream(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    model: str | None = None,
    max_tokens: int | None = None,
) -> AsyncIterator[str]:
    """メッセージ列を渡してアシスタント本文を逐次（トークン断片）で返す。"""
    payload: dict[str, Any] = {
        "model": model or PROCURETECH_MODEL,
        "messages": messages,
        "stream": True,
        "temperature": temperature,
        "max_tokens": max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
    }
    payload.update(_extra_body())
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{OPENAI_BASE_URL}/chat/completions",
            json=payload,
            headers=_headers(),
        ) as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
                line = line.strip()
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[len("data:") :].strip()
                if data_str == "[DONE]":
                    break
                try:
                    obj = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or [{}]
                piece = _delta_text(choices[0].get("delta") or {})
                if piece:
                    yield piece
