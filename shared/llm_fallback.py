"""チャット補完のモデルフォールバック。

モデルの対応は `LLM_FALLBACKS`（JSON）で渡す。コードにはペアを持たない。
切り替え先の URL と認証は、そのモデル ID を `LLM_PROVIDERS` から引いて決める。

未設定、または切り替え先がプロバイダに無いときは、呼び出し元の接続先だけを使う。
切り替えるのは接続失敗・タイムアウト・408/429/5xx のときだけで、1段のみ。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

_UNAVAILABLE_STATUS = {408, 429, 500, 502, 503, 504}
_failures: dict[str, float] = {}


@dataclass
class Endpoint:
    """OpenAI 互換 chat/completions の接続先。"""

    base_url: str
    headers: dict[str, str]
    params: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)

    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


def reset_state() -> None:
    """テスト用。冷却の記録を消す。"""
    _failures.clear()


def fallback_map() -> dict[str, str]:
    """`from` モデル ID から、1段先のモデル ID。自己参照と空は捨てる。"""
    raw = os.environ.get("LLM_FALLBACKS", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[llm-fallback] LLM_FALLBACKS を読めません: {exc}")
        return {}
    pairs: list[tuple[str, str]] = []
    if isinstance(data, dict):
        pairs = [(str(k), str(v)) for k, v in data.items()]
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            pairs.append((str(item.get("from") or ""), str(item.get("to") or "")))
    else:
        print("[llm-fallback] LLM_FALLBACKS は配列かオブジェクトです")
        return {}
    out: dict[str, str] = {}
    for src, dst in pairs:
        src, dst = src.strip(), dst.strip()
        if not src or not dst or src == dst or src in out:
            continue
        out[src] = dst
    return out


def _cooldown() -> float:
    try:
        return max(0.0, float(os.environ.get("LLM_FALLBACK_COOLDOWN", "30")))
    except ValueError:
        return 30.0


def _primary_timeout(full: float) -> float:
    raw = os.environ.get("LLM_FALLBACK_PRIMARY_TIMEOUT", "30").strip()
    try:
        limit = float(raw) if raw else full
    except ValueError:
        limit = 30.0
    if limit <= 0:
        return full
    return min(full, limit)


def _provider_endpoints() -> dict[str, Endpoint]:
    """LLM_PROVIDERS の modelId → 接続先。不正な設定は空。"""
    raw = os.environ.get("LLM_PROVIDERS", "").strip()
    if not raw:
        return {}
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[llm-fallback] LLM_PROVIDERS を読めません: {exc}")
        return {}
    if not isinstance(entries, list):
        return {}
    index: dict[str, Endpoint] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("base_url"):
            continue
        key = None
        if entry.get("api_key_env"):
            key = os.environ.get(str(entry["api_key_env"])) or None
        elif entry.get("api_key"):
            key = str(entry["api_key"]) or None
        auth_header = str(entry.get("auth_header") or "Authorization")
        auth_prefix = (
            entry["auth_prefix"] if entry.get("auth_prefix") is not None else "Bearer "
        )
        headers = {"Content-Type": "application/json"}
        if key:
            headers[auth_header] = f"{auth_prefix}{key}"
        headers.update({str(k): str(v) for k, v in (entry.get("extra_headers") or {}).items()})
        endpoint = Endpoint(
            base_url=str(entry["base_url"]).rstrip("/"),
            headers=headers,
            params={str(k): str(v) for k, v in (entry.get("query") or {}).items()},
            extra_body=dict(entry.get("extra_body") or {}),
        )
        for mid in entry.get("models") or []:
            model_id = str(mid)
            if model_id and model_id not in index:
                index[model_id] = endpoint
    return index


def endpoint_for(model_id: str) -> Endpoint | None:
    return _provider_endpoints().get(model_id)


def primary_endpoint(base_url: str, api_key: str) -> Endpoint:
    """アプリが普段使っている OpenAI 互換エンドポイント。"""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return Endpoint(base_url=base_url.rstrip("/"), headers=headers)


def is_unavailable_status(status: int) -> bool:
    return status in _UNAVAILABLE_STATUS


def is_unavailable_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return is_unavailable_status(exc.response.status_code)
    return isinstance(exc, httpx.TransportError)


def _cooling(model_id: str) -> bool:
    failed_at = _failures.get(model_id)
    if failed_at is None:
        return False
    return (time.monotonic() - failed_at) < _cooldown()


def _mark_down(model_id: str) -> None:
    _failures[model_id] = time.monotonic()


def _mark_up(model_id: str) -> None:
    _failures.pop(model_id, None)


def _routes(model_id: str, primary: Endpoint) -> list[tuple[str, Endpoint]]:
    primary_route = (model_id, primary)
    target = fallback_map().get(model_id)
    if not target:
        return [primary_route]
    alt = endpoint_for(target)
    if alt is None:
        print(
            f"[llm-fallback] {model_id} の切り替え先 {target} が "
            "LLM_PROVIDERS に無いため、元の接続先だけを使います"
        )
        return [primary_route]
    if _cooling(model_id):
        print(f"[llm-fallback] {model_id} は冷却中のため {target} を使います")
        return [(target, alt)]
    return [primary_route, (target, alt)]


def _body(payload: dict[str, Any], model_id: str, endpoint: Endpoint) -> dict[str, Any]:
    body = dict(payload)
    body["model"] = model_id
    body.update(endpoint.extra_body)
    return body


def _timeout(full: float, *, shortened: bool) -> float:
    return _primary_timeout(full) if shortened else full


async def post_chat(
    primary: Endpoint,
    payload: dict[str, Any],
    timeout: float,
) -> httpx.Response:
    """非ストリームの chat/completions。失敗時は対応表の1段先を1回試す。"""
    model_id = str(payload.get("model") or "")
    routes = _routes(model_id, primary)
    last: BaseException | None = None
    for index, (used, endpoint) in enumerate(routes):
        shortened = index == 0 and len(routes) > 1
        try:
            async with httpx.AsyncClient(timeout=_timeout(timeout, shortened=shortened)) as client:
                res = await client.post(
                    endpoint.url(),
                    json=_body(payload, used, endpoint),
                    headers=endpoint.headers,
                    params=endpoint.params or None,
                )
        except httpx.HTTPError as exc:
            last = exc
            if shortened and is_unavailable_error(exc):
                _mark_down(model_id)
                print(f"[llm-fallback] {model_id} が応答できないため {routes[1][0]} へ切り替えます: {exc}")
                continue
            raise
        if shortened and is_unavailable_status(res.status_code):
            _mark_down(model_id)
            print(
                f"[llm-fallback] {model_id} が HTTP {res.status_code} のため "
                f"{routes[1][0]} へ切り替えます"
            )
            last = httpx.HTTPStatusError(
                f"HTTP {res.status_code}", request=res.request, response=res
            )
            continue
        if res.status_code < 400:
            _mark_up(model_id)
        res.raise_for_status()
        return res
    if last:
        raise last
    raise RuntimeError("llm fallback exhausted")


def post_chat_sync(
    primary: Endpoint,
    payload: dict[str, Any],
    timeout: float,
) -> httpx.Response:
    """`post_chat` の同期版（書類読取の Vision など）。"""
    model_id = str(payload.get("model") or "")
    routes = _routes(model_id, primary)
    last: BaseException | None = None
    for index, (used, endpoint) in enumerate(routes):
        shortened = index == 0 and len(routes) > 1
        try:
            with httpx.Client(timeout=_timeout(timeout, shortened=shortened)) as client:
                res = client.post(
                    endpoint.url(),
                    json=_body(payload, used, endpoint),
                    headers=endpoint.headers,
                    params=endpoint.params or None,
                )
        except httpx.HTTPError as exc:
            last = exc
            if shortened and is_unavailable_error(exc):
                _mark_down(model_id)
                print(f"[llm-fallback] {model_id} が応答できないため {routes[1][0]} へ切り替えます: {exc}")
                continue
            raise
        if shortened and is_unavailable_status(res.status_code):
            _mark_down(model_id)
            print(
                f"[llm-fallback] {model_id} が HTTP {res.status_code} のため "
                f"{routes[1][0]} へ切り替えます"
            )
            last = httpx.HTTPStatusError(
                f"HTTP {res.status_code}", request=res.request, response=res
            )
            continue
        if res.status_code < 400:
            _mark_up(model_id)
        res.raise_for_status()
        return res
    if last:
        raise last
    raise RuntimeError("llm fallback exhausted")


def _line_has_text(line: str) -> bool:
    text = line.strip()
    if not text.startswith("data:"):
        return False
    data = text[len("data:") :].strip()
    if not data or data == "[DONE]":
        return False
    try:
        chunk = json.loads(data)
    except json.JSONDecodeError:
        return False
    delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
    content = delta.get("content")
    return isinstance(content, str) and bool(content)


async def iter_chat_lines(
    primary: Endpoint,
    payload: dict[str, Any],
    timeout: float,
) -> AsyncIterator[str]:
    """SSE 行を返す。本文が1行も出る前の障害だけ、対応表の先へ切り替える。"""
    model_id = str(payload.get("model") or "")
    routes = _routes(model_id, primary)
    last: BaseException | None = None
    for index, (used, endpoint) in enumerate(routes):
        shortened = index == 0 and len(routes) > 1
        started = False
        try:
            async with httpx.AsyncClient(timeout=_timeout(timeout, shortened=shortened)) as client:
                async with client.stream(
                    "POST",
                    endpoint.url(),
                    json=_body(payload, used, endpoint),
                    headers=endpoint.headers,
                    params=endpoint.params or None,
                ) as res:
                    if shortened and is_unavailable_status(res.status_code):
                        _mark_down(model_id)
                        print(
                            f"[llm-fallback] {model_id} が HTTP {res.status_code} のため "
                            f"{routes[1][0]} へ切り替えます"
                        )
                        continue
                    res.raise_for_status()
                    async for line in res.aiter_lines():
                        if not started and _line_has_text(line):
                            started = True
                            _mark_up(model_id)
                        yield line
                    if not started:
                        _mark_up(model_id)
                    return
        except httpx.HTTPError as exc:
            last = exc
            if started or not (shortened and is_unavailable_error(exc)):
                raise
            _mark_down(model_id)
            print(f"[llm-fallback] {model_id} が応答できないため {routes[1][0]} へ切り替えます: {exc}")
            continue
    if last:
        raise last
    raise RuntimeError("llm fallback exhausted")
