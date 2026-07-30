"""OpenAI 互換 API による埋め込み / 生成。

Ollama の OpenAI 互換エンドポイント(/v1)を既定とするが、OPENAI_BASE_URL を
変えれば任意の OpenAI 互換サーバに向けられる。
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx

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
RAG_MODEL = os.environ.get("RAG_MODEL", "gpt-oss:20b")

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


async def embed(text: str, *, is_query: bool = False) -> list[float]:
    prompt = (QUERY_PREFIX + text) if is_query else (DOC_PREFIX + text)
    async with httpx.AsyncClient(timeout=120) as client:
        res = await client.post(
            f"{EMBED_BASE_URL}/embeddings",
            json={"model": EMBED_MODEL, "input": prompt},
            headers=_embed_headers(),
        )
        res.raise_for_status()
        data = res.json()
    return data["data"][0]["embedding"]


async def generate(messages: list[dict[str, Any]]) -> str:
    async with httpx.AsyncClient(timeout=600) as client:
        res = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json={"model": RAG_MODEL, "messages": messages, "stream": False},
            headers=_headers(),
        )
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or [{}]
    return (choices[0].get("message") or {}).get("content", "") or ""


async def generate_stream(messages: list[dict[str, Any]]) -> AsyncIterator[str]:
    async with httpx.AsyncClient(timeout=600) as client:
        async with client.stream(
            "POST",
            f"{OPENAI_BASE_URL}/chat/completions",
            json={"model": RAG_MODEL, "messages": messages, "stream": True},
            headers=_headers(),
        ) as res:
            res.raise_for_status()
            async for line in res.aiter_lines():
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
