"""OpenAI 互換 API (/v1/chat/completions, /v1/models) へのプロキシ。

Ollama の OpenAI 互換エンドポイント(http://host:11434/v1)を既定とするが、
OPENAI_BASE_URL を変えれば vLLM / LM Studio / OpenAI など任意の
OpenAI 互換サーバに向けられる（ベンダーロックインを避ける）。

源内 Web が要求する「改行区切り JSON (StreamingChunk)」を生成するための
ヘルパも提供する。
"""

from __future__ import annotations

import json
import os
from typing import Any, AsyncIterator

import httpx

from shared.docextract import extract_doc_text

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
# OpenAI 互換のベース URL（未指定/空なら Ollama の /v1 を使う）
OPENAI_BASE_URL = (
    os.environ.get("OPENAI_BASE_URL") or f"{OLLAMA_BASE_URL.rstrip('/')}/v1"
).rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "ollama"
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen2.5:7b")
REQUEST_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "600"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


def _resolve_model(model: dict[str, Any] | None) -> str:
    if model and model.get("modelId"):
        return str(model["modelId"])
    return DEFAULT_MODEL


def resolve_model(model: dict[str, Any] | None) -> str:
    """リクエストの model 指定から実際に使うモデル ID を解決する（公開版）。"""
    return _resolve_model(model)


def _data_url(media_type: str, data: str) -> str:
    """base64(prefix有無どちらでも)を data URL に正規化する。"""
    if data.startswith("data:"):
        return data
    mt = media_type or "image/png"
    return f"data:{mt};base64,{data}"


def _extract_image_urls(message: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    for extra in message.get("extraData") or []:
        if not isinstance(extra, dict) or extra.get("type") != "image":
            continue
        source = extra.get("source") or {}
        data = source.get("data")
        if data:
            urls.append(_data_url(source.get("mediaType", "image/png"), data))
    return urls


def _extract_doc_texts(message: dict[str, Any]) -> list[tuple[str, str]]:
    """extraData の file 添付からテキストを抽出する（共通モジュールを利用）。"""
    out: list[tuple[str, str]] = []
    for extra in message.get("extraData") or []:
        if not isinstance(extra, dict) or extra.get("type") != "file":
            continue
        source = extra.get("source") or {}
        data = source.get("data")
        if not data:
            continue
        name = extra.get("name", "file")
        text = extract_doc_text(name, source.get("mediaType", ""), data)
        if text:
            out.append((name, text))
    return out


def _to_openai_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """UnrecordedMessage[] を OpenAI Chat Completions のメッセージへ変換する。

    - 画像付き(extraData image)は OpenAI Vision 形式の content 配列に変換（gemma3 等）。
    - ドキュメント(extraData file: PDF/Word/Excel/テキスト)はテキスト抽出して本文に注入。
    """
    result: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role", "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        text = m.get("content", "") or ""

        # 添付ドキュメントのテキストを本文に追記
        doc_texts = _extract_doc_texts(m)
        if doc_texts:
            parts = [text] if text else []
            for name, t in doc_texts:
                parts.append(f"\n\n--- 添付ファイル: {name} ---\n{t}")
            text = "".join(parts)

        image_urls = _extract_image_urls(m)
        if image_urls:
            content: list[dict[str, Any]] = [{"type": "text", "text": text}]
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
            result.append({"role": role, "content": content})
        else:
            result.append({"role": role, "content": text})
    return result


async def chat_once(
    messages: list[dict[str, Any]], model: dict[str, Any] | None
) -> str:
    """ストリームなしでチャット補完を取得する。"""
    payload = {
        "model": _resolve_model(model),
        "messages": _to_openai_messages(messages),
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions", json=payload, headers=_headers()
        )
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or [{}]
    return (choices[0].get("message") or {}).get("content", "") or ""


async def chat_stream(
    messages: list[dict[str, Any]], model: dict[str, Any] | None
) -> AsyncIterator[str]:
    """源内 Web 互換の改行区切り JSON (StreamingChunk) を yield する。

    OpenAI 互換の SSE(`data: {...}`) を読み、各行を {"text": "..."} 形式に変換する。
    最後に stopReason を付与した行を流す。
    """
    payload = {
        "model": _resolve_model(model),
        "messages": _to_openai_messages(messages),
        "stream": True,
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{OPENAI_BASE_URL}/chat/completions",
                json=payload,
                headers=_headers(),
            ) as res:
                if res.status_code != 200:
                    body = (await res.aread()).decode("utf-8", "ignore")
                    yield json.dumps(
                        {"text": f"[LLM エラー {res.status_code}] {body}", "stopReason": "error"},
                        ensure_ascii=False,
                    ) + "\n"
                    return

                finish_reason = "stop"
                async for line in res.aiter_lines():
                    line = line.strip()
                    if not line or not line.startswith("data:"):
                        continue
                    payload_str = line[len("data:") :].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    choice = (chunk.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    text = delta.get("content") or ""
                    if text:
                        yield json.dumps({"text": text}, ensure_ascii=False) + "\n"
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                yield json.dumps(
                    {"text": "", "stopReason": finish_reason or "stop"},
                    ensure_ascii=False,
                ) + "\n"
    except httpx.HTTPError as e:
        yield json.dumps(
            {
                "text": (
                    "[ローカル LLM に接続できませんでした] "
                    f"{OPENAI_BASE_URL} を確認してください: {e}"
                ),
                "stopReason": "error",
            },
            ensure_ascii=False,
        ) + "\n"


async def list_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(f"{OPENAI_BASE_URL}/models", headers=_headers())
            res.raise_for_status()
            data = res.json()
        return [m["id"] for m in data.get("data", [])]
    except httpx.HTTPError:
        return []
