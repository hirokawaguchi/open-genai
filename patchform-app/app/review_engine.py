"""所見の呼び出し先。手続きごとに OpenAI 互換か Dify かを持つ。

Dify の API ベースと鍵は手続きのサーバ側設定である。スタブにすると、
同じ形の JSON をネットワークなしで返す。dify-app の居場所だけ環境変数である。
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import httpx

from . import llm

ENGINE_OPENAI = "openai"
ENGINE_DIFY = "dify"
STUB_DETAIL = "Dify のスタブです。人が確認します。"
_DIFY_TIMEOUT = 30.0


def empty_call() -> dict[str, Any]:
    return {"engine": ENGINE_OPENAI, "base_url": "", "api_key": "", "stub": False}


def normalize_call(
    raw: Any, *, previous: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """手続きの所見の呼び出し。鍵を空で渡したときは、保存済みの鍵を残す。"""
    prev = previous or empty_call()
    if raw is None:
        return dict(prev), None
    if not isinstance(raw, dict):
        return None, "所見の呼び出しを読めません"
    engine = str(raw.get("engine") if "engine" in raw else prev.get("engine") or ENGINE_OPENAI)
    engine = engine.strip().lower()
    if engine not in (ENGINE_OPENAI, ENGINE_DIFY):
        return None, "所見の呼び出し先が不正です"
    base = str(raw["base_url"] if "base_url" in raw else prev.get("base_url") or "").strip()
    if base:
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None, "Dify の URL は http か https で書いてください"
        if parsed.username or parsed.password:
            return None, "Dify の URL にパスワードは含めないでください"
        if len(base) > 500:
            return None, "Dify の URL が長すぎます"
    key = str(prev.get("api_key") or "")
    if "api_key" in raw:
        given = str(raw.get("api_key") or "").strip()
        if given:
            if len(given) > 200:
                return None, "Dify の鍵が長すぎます"
            key = given
    stub = bool(prev.get("stub"))
    if "stub" in raw:
        stub = bool(raw.get("stub"))
    if engine != ENGINE_DIFY:
        stub = False
    return {"engine": engine, "base_url": base, "api_key": key, "stub": stub}, None


def public_call(stored: dict[str, Any]) -> dict[str, Any]:
    engine = str(stored.get("engine") or ENGINE_OPENAI)
    stub = bool(stored.get("stub")) and engine == ENGINE_DIFY
    if engine != ENGINE_DIFY:
        label = "OpenAI 互換"
    elif stub:
        label = "Dify（スタブ）"
    else:
        label = "Dify"
    return {
        "engine": ENGINE_DIFY if engine == ENGINE_DIFY else ENGINE_OPENAI,
        "base_url": str(stored.get("base_url") or ""),
        "key_set": bool(str(stored.get("api_key") or "").strip()),
        "stub": stub,
        "label": label,
    }


def stub_rows(checks: list[dict[str, str]]) -> list[dict[str, str]]:
    return [
        {"id": str(item.get("id") or ""), "result": "unknown", "detail": STUB_DETAIL}
        for item in checks
        if str(item.get("id") or "")
    ]


def rows_from_dify(payload: Any) -> list[Any]:
    """dify-app の応答、または workflow の outputs から findings を取る。"""
    body = payload
    if isinstance(body, dict) and "outputs" in body:
        body = body.get("outputs")
    if isinstance(body, str):
        body = llm.extract_json(body)
    if isinstance(body, dict) and "findings" in body:
        body = body.get("findings")
    if isinstance(body, dict):
        for key in ("findings", "text", "result"):
            value = body.get(key)
            if isinstance(value, str):
                parsed = llm.extract_json(value)
                if isinstance(parsed, dict):
                    body = parsed.get("findings")
                elif isinstance(parsed, list):
                    body = parsed
                break
            if isinstance(value, list):
                body = value
                break
    if not isinstance(body, list):
        raise ValueError("Dify の応答を所見として読めません")
    return body


async def ask_findings(
    checks: list[dict[str, str]],
    submitted: str,
    call: dict[str, Any] | None = None,
) -> tuple[list[Any], str]:
    chosen = call or empty_call()
    if chosen.get("engine") == ENGINE_DIFY:
        if chosen.get("stub"):
            return stub_rows(checks), "dify"
        return await _call_dify(checks, submitted, chosen), "dify"
    return await _call_openai(checks, submitted), "model"


async def _call_openai(checks: list[dict[str, str]], submitted: str) -> list[Any]:
    raw = await llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "あなたは受付の下見です。合否は決めません。"
                    "各確認文について、提出内容から言えることだけを result にします。"
                    "資料が足りなければ unknown です。"
                    "result は pass、fail、unknown のいずれかです。"
                    "detail は40字以内です。JSON だけを返します。"
                    '形は {"findings":[{"id":"","result":"unknown","detail":""}]} です。'
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {"checks": checks, "submitted": submitted}, ensure_ascii=False
                ),
            },
        ],
        temperature=0,
        think=False,
        max_tokens=1200,
    )
    parsed = llm.extract_json(raw)
    rows = parsed.get("findings") if isinstance(parsed, dict) else parsed
    if not isinstance(rows, list):
        raise ValueError("所見を作れませんでした。確認中のままです。")
    return rows


async def _call_dify(
    checks: list[dict[str, str]], submitted: str, call: dict[str, Any]
) -> list[Any]:
    key = str(call.get("api_key") or "").strip()
    if not key:
        raise ValueError("Dify の鍵が未設定です")
    url = (
        os.environ.get("PATCHFORM_DIFY_APP_URL") or "http://dify-app:8004/invoke"
    ).strip()
    config = {
        "dify_app_type": "workflow",
        "response_field": "findings",
    }
    base = str(call.get("base_url") or "").strip()
    if base:
        config["dify_base_url"] = base
    try:
        async with httpx.AsyncClient(timeout=_DIFY_TIMEOUT) as client:
            res = await client.post(
                url,
                json={
                    "inputs": {
                        "checks": json.dumps(checks, ensure_ascii=False),
                        "submitted": submitted,
                    }
                },
                headers={
                    "x-api-key": key,
                    "x-app-config": json.dumps(config, ensure_ascii=False),
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as exc:
        raise ValueError("Dify に接続できませんでした") from exc
    if res.status_code >= 400:
        raise ValueError(f"Dify が {res.status_code} を返しました")
    try:
        data = res.json()
    except ValueError as exc:
        raise ValueError("Dify の応答を所見として読めません") from exc
    return rows_from_dify(data)
