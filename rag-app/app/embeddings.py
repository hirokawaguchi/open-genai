"""OpenAI 互換 API による埋め込み / 生成。

Ollama の OpenAI 互換エンドポイント(/v1)を既定とするが、OPENAI_BASE_URL を
変えれば任意の OpenAI 互換サーバに向けられる。
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx

from shared.llm_fallback import iter_chat_lines, post_chat, primary_endpoint

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OPENAI_BASE_URL = (
    os.environ.get("OPENAI_BASE_URL") or f"{OLLAMA_BASE_URL.rstrip('/')}/v1"
).rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "ollama"
# 埋め込みは EMBED_BASE_URL（embed サイドカー等の OpenAI 互換）へ分離できる。
# 未設定なら OPENAI_BASE_URL / OPENAI_API_KEY にフォールバックし、従来と同じ挙動になる。
EMBED_BASE_URL = (os.environ.get("EMBED_BASE_URL") or OPENAI_BASE_URL).rstrip("/")
EMBED_API_KEY = os.environ.get("EMBED_API_KEY") or OPENAI_API_KEY
EMBED_MODEL = os.environ.get("EMBED_MODEL", "mxbai-embed-large")


def _positive_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


# ナレッジ登録はチャンクごとに 1 リクエストすると、CPU 埋め込みがコアを埋め続ける。
# この件数ずつまとめて送る。
EMBED_BATCH_SIZE = _positive_int("EMBED_BATCH_SIZE", 16)
EMBED_TIMEOUT = float(os.environ.get("EMBED_TIMEOUT", "180") or "180")
RAG_MODEL = os.environ.get("RAG_MODEL", "gpt-oss:20b")
# Qwen3.x は既定で思考モードになり、content が空のまま数分待たされる。
# 通常チャット (LLM_PROVIDERS.extra_body) と同じく、既定は思考オフ。
# 上書き例: RAG_EXTRA_BODY={"chat_template_kwargs":{"enable_thinking":true}}
def _rag_extra_body() -> dict[str, Any]:
    raw = (os.environ.get("RAG_EXTRA_BODY") or "").strip()
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            print(f"[rag-app] RAG_EXTRA_BODY が不正な JSON です: {raw[:80]}")
    return {"chat_template_kwargs": {"enable_thinking": False}}


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str):
        return reasoning
    return content if isinstance(content, str) else ""


def _chat_payload(messages: list[dict[str, Any]], *, stream: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": RAG_MODEL,
        "messages": messages,
        "stream": stream,
    }
    payload.update(_rag_extra_body())
    return payload

# 検索クエリ / 文書に付ける prefix はモデル依存（本プロジェクトは任意の埋め込みモデルを
# 差し替え可能）。既定は現行 mxbai-embed-large 互換（クエリのみ英語 prefix・文書は無し）で、
# 既存インデックスを壊さない。ほかのモデルでは env で上書きする。
#   例) Ruri v3: EMBED_QUERY_PREFIX="検索クエリ: " / EMBED_DOC_PREFIX="検索文書: "
#   例) prefix 不要なモデル: 両方に空文字を設定
QUERY_PREFIX = os.environ.get(
    "EMBED_QUERY_PREFIX", "Represent this sentence for searching relevant passages: "
)
DOC_PREFIX = os.environ.get("EMBED_DOC_PREFIX", "")


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _embed_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {EMBED_API_KEY}",
        "Content-Type": "application/json",
    }


def _with_prefix(text: str, *, is_query: bool) -> str:
    return (QUERY_PREFIX + text) if is_query else (DOC_PREFIX + text)


async def _post_embeddings(prompts: list[str]) -> list[list[float]]:
    async with httpx.AsyncClient(timeout=EMBED_TIMEOUT) as client:
        res = await client.post(
            f"{EMBED_BASE_URL}/embeddings",
            json={"model": EMBED_MODEL, "input": prompts},
            headers=_embed_headers(),
        )
        res.raise_for_status()
        rows = list(res.json().get("data") or [])
    rows.sort(key=lambda row: int(row.get("index") or 0))
    return [list(row["embedding"]) for row in rows]


async def embed_many(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
    """文書チャンクを EMBED_BATCH_SIZE 件ずつ埋め込む。"""
    if not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = [_with_prefix(text, is_query=is_query) for text in texts[start : start + EMBED_BATCH_SIZE]]
        vectors.extend(await _post_embeddings(batch))
    return vectors


async def embed(text: str, *, is_query: bool = False) -> list[float]:
    vectors = await embed_many([text], is_query=is_query)
    return vectors[0]


async def generate(messages: list[dict[str, Any]]) -> str:
    res = await post_chat(
        primary_endpoint(OPENAI_BASE_URL, OPENAI_API_KEY),
        _chat_payload(messages, stream=False),
        600,
    )
    data = res.json()
    choices = data.get("choices") or [{}]
    return _message_text((choices[0].get("message") or {}))


async def generate_stream(messages: list[dict[str, Any]]) -> AsyncIterator[str]:
    async for line in iter_chat_lines(
        primary_endpoint(OPENAI_BASE_URL, OPENAI_API_KEY),
        _chat_payload(messages, stream=True),
        600,
    ):
        line = line.strip()
        if not line or not line.startswith("data:"):
            continue
        payload = line[len("data:") :].strip()
        if payload == "[DONE]":
            return
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
        text = delta.get("content") or ""
        if text:
            yield text
