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
DEFAULT_MAX_TOKENS = int(os.environ.get("HEARING_LLM_MAX_TOKENS", "8192"))
CONTINUE_ROUNDS = int(os.environ.get("HEARING_LLM_CONTINUE", "2"))
LENGTH_NOTE = (
    "\n\n（長さの上限で途中までです。続きが必要なら「続きを書いて」と送ってください。）"
)
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


def without_meta(message: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in message.items() if not str(k).startswith("_")}


def is_length_stop(message: dict[str, Any]) -> bool:
    return str(message.get("_finish_reason") or "") in {
        "length",
        "max_tokens",
        "max_token",
    }


def message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return content.strip() if isinstance(content, str) else ""


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.2,
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not LLM_ENABLED:
        raise RuntimeError("LLM は無効です（HEARING_LLM=0）")
    payload: dict[str, Any] = {
        "model": PROCURETECH_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": DEFAULT_MAX_TOKENS,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
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
    message = choices[0].get("message") or {}
    if not isinstance(message, dict):
        raise ValueError("モデルの応答が不正です")
    out = dict(message)
    out["_finish_reason"] = str(choices[0].get("finish_reason") or "")
    return out


async def continue_if_length(
    messages: list[dict[str, Any]],
    first: dict[str, Any],
    *,
    temperature: float = 0.2,
) -> str:
    """max_tokens で切れた本文を続き生成でつなぐ。"""
    text = message_text(first)
    if not text:
        return ""
    current = first
    working = list(messages)
    chunks = [text]
    rounds = 0
    while is_length_stop(current) and rounds < CONTINUE_ROUNDS:
        working.append({**without_meta(current), "content": message_text(current)})
        working.append(
            {
                "role": "user",
                "content": (
                    "回答が途中で切れています。続きだけを書いてください。"
                    "表や番号付きの説明なら、切れた行の続きから完成させてください。"
                    "見出しからやり直さないでください。"
                ),
            }
        )
        current = await chat_completion(working, temperature=temperature)
        piece = message_text(current)
        if piece:
            chunks.append(piece)
        rounds += 1
        if not piece:
            break
    out = "".join(chunks)
    if is_length_stop(current):
        out += LENGTH_NOTE
    return out


async def chat(messages: list[dict[str, str]], *, temperature: float = 0.2) -> str:
    packed = list(messages)
    message = await chat_completion(packed, temperature=temperature)
    text = await continue_if_length(packed, message, temperature=temperature)
    if not text:
        raise ValueError("モデルの応答本文が空です")
    return text
