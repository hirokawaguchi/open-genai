"""OpenAI 互換 API (/v1/chat/completions, /v1/models) へのプロキシ。

複数の OpenAI 互換プロバイダ（Ollama / さくら / OpenAI / Azure OpenAI / Gemini 等）を
`LLM_PROVIDERS`(JSON) で登録し、リクエストの modelId からプロバイダを逆引きして
呼び分ける。`LLM_PROVIDERS` 未設定時は従来どおり単一の `OPENAI_BASE_URL`
（未指定なら Ollama の /v1）を使う（後方互換）。

源内 Web が要求する「改行区切り JSON (StreamingChunk)」を生成するための
ヘルパも提供する。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from shared.docextract import extract_doc_text_full

from .doc_mapreduce import CHAT_DOC_INLINE_CHARS, condense_document

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
# OpenAI 互換のベース URL（未指定/空なら Ollama の /v1 を使う）
OPENAI_BASE_URL = (
    os.environ.get("OPENAI_BASE_URL") or f"{OLLAMA_BASE_URL.rstrip('/')}/v1"
).rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "ollama"
DEFAULT_MODEL = os.environ.get("DEFAULT_MODEL", "qwen2.5:7b")
REQUEST_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "600"))


@dataclass
class Provider:
    """OpenAI 互換 API 1 系統ぶんの接続情報。"""

    name: str
    base_url: str
    api_key: str | None = None
    # 認証ヘッダ名と値の接頭辞。既定は `Authorization: Bearer <key>`。
    # Azure OpenAI は `api-key: <key>`（接頭辞なし）。
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    # クエリ文字列（Azure の api-version 等）。
    query: dict[str, str] = field(default_factory=dict)
    # 明示モデル一覧（空なら /models を照会）。
    models: list[str] = field(default_factory=list)

    def headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h[self.auth_header] = f"{self.auth_prefix}{self.api_key}"
        return h


def _build_providers() -> tuple[list[Provider], dict[str, Provider]]:
    """`LLM_PROVIDERS` からプロバイダ一覧と model→provider 索引を作る。

    未設定/空/不正時は従来の単一プロバイダ（OPENAI_BASE_URL）へフォールバック。
    """
    providers: list[Provider] = []
    raw = os.environ.get("LLM_PROVIDERS", "").strip()
    if raw:
        try:
            entries = json.loads(raw)
            if not isinstance(entries, list):
                raise ValueError("LLM_PROVIDERS must be a JSON array")
            for e in entries:
                if not isinstance(e, dict) or not e.get("base_url"):
                    continue
                key = None
                if e.get("api_key_env"):
                    key = os.environ.get(str(e["api_key_env"])) or None
                elif e.get("api_key"):
                    key = str(e["api_key"]) or None
                providers.append(
                    Provider(
                        name=str(e.get("name") or e["base_url"]),
                        base_url=str(e["base_url"]).rstrip("/"),
                        api_key=key,
                        auth_header=str(e.get("auth_header") or "Authorization"),
                        auth_prefix=(
                            e["auth_prefix"]
                            if e.get("auth_prefix") is not None
                            else "Bearer "
                        ),
                        query={str(k): str(v) for k, v in (e.get("query") or {}).items()},
                        models=[str(m) for m in (e.get("models") or [])],
                    )
                )
        except (ValueError, TypeError) as exc:  # noqa: BLE001
            print(f"[llm] LLM_PROVIDERS の解析に失敗、単一プロバイダにフォールバック: {exc}")
            providers = []

    if not providers:
        # 後方互換: 単一の OpenAI 互換プロバイダ。
        providers = [
            Provider(name="default", base_url=OPENAI_BASE_URL, api_key=OPENAI_API_KEY)
        ]

    index: dict[str, Provider] = {}
    for p in providers:
        for mid in p.models:
            if mid in index:
                print(
                    f"[llm] モデルID重複 '{mid}': '{index[mid].name}' を優先し "
                    f"'{p.name}' の割当は無視"
                )
                continue
            index[mid] = p
    return providers, index


_PROVIDERS, _MODEL_INDEX = _build_providers()
# 索引に無いモデル（request 指定・DEFAULT_MODEL）用の既定プロバイダ。
_DEFAULT_PROVIDER = _PROVIDERS[0]

for _p in _PROVIDERS:
    print(
        f"[llm] provider '{_p.name}' base={_p.base_url} "
        f"auth={'yes' if _p.api_key else 'none'} models={_p.models or '(query /models)'}"
    )


def _resolve_model(model: dict[str, Any] | None) -> str:
    if model and model.get("modelId"):
        return str(model["modelId"])
    return DEFAULT_MODEL


def resolve_model(model: dict[str, Any] | None) -> str:
    """リクエストの model 指定から実際に使うモデル ID を解決する（公開版）。"""
    return _resolve_model(model)


def _provider_for(model_id: str) -> Provider:
    """modelId からプロバイダを逆引き。未登録は既定プロバイダ。"""
    return _MODEL_INDEX.get(model_id, _DEFAULT_PROVIDER)


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


async def _complete(
    messages: list[dict[str, Any]], model_id: str, *, temperature: float = 0.0
) -> str:
    """内部利用の非ストリーム補完（添付の要約/読み計画に使う）。"""
    provider = _provider_for(model_id)
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{provider.base_url}/chat/completions",
            json=payload,
            headers=provider.headers(),
            params=provider.query or None,
        )
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or [{}]
    return (choices[0].get("message") or {}).get("content", "") or ""


def _extract_doc_texts_full(message: dict[str, Any]) -> list[tuple[str, str]]:
    """extraData の file 添付から全文抽出する（30k 切り捨てを行わない）。"""
    out: list[tuple[str, str]] = []
    for extra in message.get("extraData") or []:
        if not isinstance(extra, dict) or extra.get("type") != "file":
            continue
        source = extra.get("source") or {}
        data = source.get("data")
        if not data:
            continue
        name = extra.get("name", "file")
        text = extract_doc_text_full(name, source.get("mediaType", ""), data)
        if text:
            out.append((name, text))
    return out


async def _prepare_openai_messages(
    messages: list[dict[str, Any]], model: dict[str, Any] | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """OpenAI 形式へ変換しつつ、大きい添付はその場マップリデュースで圧縮する。

    小さい添付は全文注入。大きい添付は抜粋/要約に圧縮し、どう参照したかの注記を集約する。
    戻り値: (openai_messages, notes)
    """
    model_id = _resolve_model(model)

    async def _llm(oai_messages: list[dict[str, Any]]) -> str:
        return await _complete(oai_messages, model_id)

    result: list[dict[str, Any]] = []
    notes: list[str] = []
    for m in messages:
        role = m.get("role", "user")
        if role not in ("system", "user", "assistant"):
            role = "user"
        text = m.get("content", "") or ""

        doc_texts = _extract_doc_texts_full(m)
        if doc_texts:
            parts = [text] if text else []
            for name, full_text in doc_texts:
                ctx, note = await condense_document(name, full_text, text, _llm)
                if note:
                    notes.append(note)
                parts.append(f"\n\n--- 添付ファイル: {name} ---\n{ctx}")
            text = "".join(parts)

        image_urls = _extract_image_urls(m)
        if image_urls:
            content: list[dict[str, Any]] = [{"type": "text", "text": text}]
            for url in image_urls:
                content.append({"type": "image_url", "image_url": {"url": url}})
            result.append({"role": role, "content": content})
        else:
            result.append({"role": role, "content": text})

    # 重複注記は畳む（同名ファイルが複数ターンに出た場合など）
    deduped: list[str] = []
    for n in notes:
        if n not in deduped:
            deduped.append(n)
    return result, deduped


def _notes_prefix(notes: list[str]) -> str:
    if not notes:
        return ""
    return "※ " + " / ".join(notes) + "\n\n"


async def chat_once(
    messages: list[dict[str, Any]], model: dict[str, Any] | None
) -> str:
    """ストリームなしでチャット補完を取得する。"""
    model_id = _resolve_model(model)
    provider = _provider_for(model_id)
    openai_messages, notes = await _prepare_openai_messages(messages, model)
    payload = {
        "model": model_id,
        "messages": openai_messages,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{provider.base_url}/chat/completions",
            json=payload,
            headers=provider.headers(),
            params=provider.query or None,
        )
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or [{}]
    answer = (choices[0].get("message") or {}).get("content", "") or ""
    return _notes_prefix(notes) + answer


async def chat_stream(
    messages: list[dict[str, Any]], model: dict[str, Any] | None
) -> AsyncIterator[str]:
    """源内 Web 互換の改行区切り JSON (StreamingChunk) を yield する。

    OpenAI 互換の SSE(`data: {...}`) を読み、各行を {"text": "..."} 形式に変換する。
    最後に stopReason を付与した行を流す。
    大きい添付はマップリデュース完了後に本編ストリームを開始する。
    """
    model_id = _resolve_model(model)
    provider = _provider_for(model_id)
    # 大きい添付のマップリデュースは初回 yield まで時間がかかるため、進捗を先に流す
    # （プロキシ/UI が無応答に見えるのを防ぐ）
    try:
        has_large_docs = False
        for m in messages:
            for name, full_text in _extract_doc_texts_full(m):
                if len(full_text) > CHAT_DOC_INLINE_CHARS:
                    has_large_docs = True
                    break
            if has_large_docs:
                break
        if has_large_docs:
            yield json.dumps(
                {
                    "text": "※ 添付資料が大きいため、内容を整理してから回答します…\n\n",
                },
                ensure_ascii=False,
            ) + "\n"
        openai_messages, notes = await _prepare_openai_messages(messages, model)
    except Exception as e:  # noqa: BLE001 - ストリームでユーザ向けに返す
        yield json.dumps(
            {
                "text": (
                    "添付ファイルの処理中にエラーが発生しました。"
                    "ファイルを分割するか、指示を具体にして再度お試しください。"
                    f"（詳細: {type(e).__name__}）"
                ),
                "stopReason": "error",
            },
            ensure_ascii=False,
        ) + "\n"
        return
    prefix = _notes_prefix(notes)
    if prefix:
        yield json.dumps({"text": prefix}, ensure_ascii=False) + "\n"
    payload = {
        "model": model_id,
        "messages": openai_messages,
        "stream": True,
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            async with client.stream(
                "POST",
                f"{provider.base_url}/chat/completions",
                json=payload,
                headers=provider.headers(),
                params=provider.query or None,
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
                    "[LLM に接続できませんでした] "
                    f"provider '{provider.name}' ({provider.base_url}) を確認してください: {e}"
                ),
                "stopReason": "error",
            },
            ensure_ascii=False,
        ) + "\n"


async def _list_provider_models(provider: Provider) -> list[str]:
    """明示 models があればそれを、無ければ provider の /models を照会する。"""
    if provider.models:
        return list(provider.models)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"{provider.base_url}/models",
                headers=provider.headers(),
                params=provider.query or None,
            )
            res.raise_for_status()
            data = res.json()
        return [m["id"] for m in data.get("data", [])]
    except httpx.HTTPError:
        return []


async def list_models() -> list[str]:
    """全プロバイダのモデルを統合して返す（重複は登録順で除外）。"""
    seen: set[str] = set()
    out: list[str] = []
    for provider in _PROVIDERS:
        for mid in await _list_provider_models(provider):
            if mid not in seen:
                seen.add(mid)
                out.append(mid)
    return out
