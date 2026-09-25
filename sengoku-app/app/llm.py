"""OpenAI 互換 chat/completions 呼び出し（Ollama 等）。

敵対大名の 1 ターンぶんの命令を JSON で生成させるために使う。ゲームのルール解決・
資源増減は rules.py 側（決定的）に閉じ込め、ここでは「意思決定の文章化」だけを担う。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip(
    "/"
)
OPENAI_BASE_URL = (os.environ.get("OPENAI_BASE_URL") or f"{OLLAMA_BASE_URL}/v1").rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "ollama"
SENGOKU_MODEL = (
    os.environ.get("SENGOKU_MODEL") or os.environ.get("DEFAULT_MODEL") or "gpt-oss:20b"
)
REQUEST_TIMEOUT = float(os.environ.get("SENGOKU_LLM_TIMEOUT", "90"))
# 推論モデル（gpt-oss 等）は思考文を吐くため、最終 JSON まで届くよう余裕を持たせる。
# 観戦モードは最大 8 家ぶんを一度に決めるので、思考＋JSON が収まるよう多めに取る。
DEFAULT_MAX_TOKENS = int(os.environ.get("SENGOKU_LLM_MAX_TOKENS", "3600"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _extra_body() -> dict[str, Any]:
    """Qwen3.x は既定で思考モードになり、content が空のまま待たされることがある。"""
    raw = (os.environ.get("SENGOKU_EXTRA_BODY") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            print(f"[sengoku] SENGOKU_EXTRA_BODY が不正な JSON です: {raw[:80]}")
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
    temperature: float = 0.4,
    model: str | None = None,
    max_tokens: int | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model or SENGOKU_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
    }
    payload.update(_extra_body())
    if extra:
        payload.update(extra)
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
        raise ValueError("モデルの本文が空です")
    return text


def _strip_fences(raw: str) -> str:
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


def _balanced_spans(text: str, open_c: str, close_c: str) -> list[str]:
    """text 中で釣り合いの取れた open_c..close_c の部分文字列を、出現順に返す。

    推論モデル（gpt-oss 等）は思考文の中に JSON を混ぜることがあるため、
    文字列リテラル内の括弧は無視して、トップレベルの塊だけを拾う。
    """
    spans: list[str] = []
    depth = 0
    start = -1
    in_str = False
    escaped = False
    for i, ch in enumerate(text):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == open_c:
            if depth == 0:
                start = i
            depth += 1
        elif ch == close_c and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                spans.append(text[start : i + 1])
                start = -1
    return spans


def extract_json(text: str) -> Any:
    """モデル出力から JSON を取り出す（```json 囲み・推論モデルの思考文混じりにも対応）。

    推論モデルは JSON の前に思考文を出すことがあるため、釣り合いの取れた塊を
    「後ろにあるもの（＝最終回答である可能性が高いもの）」から順に試す。
    """
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空の応答です")
    body = _strip_fences(raw)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    spans = _balanced_spans(body, "{", "}") + _balanced_spans(body, "[", "]")
    parsed_all: list[Any] = []
    for span in spans:
        try:
            parsed_all.append(json.loads(span))
        except json.JSONDecodeError:
            continue
    # orders を含む dict を優先（最終回答らしさ）。後ろにあるものほど最終回答に近い。
    for parsed in reversed(parsed_all):
        if isinstance(parsed, dict) and "orders" in parsed:
            return parsed
    if parsed_all:
        return parsed_all[-1]
    raise ValueError(f"JSON を解析できませんでした: {text[:240]}")
