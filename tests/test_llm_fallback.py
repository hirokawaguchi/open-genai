"""LLM フォールバック。対応表は環境変数、接続先は LLM_PROVIDERS。"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from shared import llm_fallback as fb


def _providers() -> str:
    return json.dumps(
        [
            {
                "name": "sakura",
                "base_url": "https://sakura.example/v1",
                "api_key": "sakura-key",
                "models": ["gpt-oss-120b", "preview/gemma-4-31B-it"],
            }
        ]
    )


def _fallbacks() -> str:
    return json.dumps(
        [
            {"from": "gpt-oss:120b-cloud", "to": "gpt-oss-120b"},
            {"from": "gemma4:cloud", "to": "preview/gemma-4-31B-it"},
            {"from": "loop", "to": "loop"},
        ]
    )


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    fb.reset_state()
    monkeypatch.setenv("LLM_PROVIDERS", _providers())
    monkeypatch.setenv("LLM_FALLBACKS", _fallbacks())
    monkeypatch.setenv("LLM_FALLBACK_COOLDOWN", "30")
    monkeypatch.setenv("LLM_FALLBACK_PRIMARY_TIMEOUT", "30")


def test_map_drops_self_reference() -> None:
    mapped = fb.fallback_map()
    assert mapped["gpt-oss:120b-cloud"] == "gpt-oss-120b"
    assert mapped["gemma4:cloud"] == "preview/gemma-4-31B-it"
    assert "loop" not in mapped


def test_unavailable_status_only() -> None:
    assert fb.is_unavailable_status(503)
    assert fb.is_unavailable_status(429)
    assert not fb.is_unavailable_status(400)
    assert not fb.is_unavailable_status(401)


def test_switches_to_provider_of_target_model() -> None:
    asyncio.run(_switches_to_provider_of_target_model())


async def _switches_to_provider_of_target_model() -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        auth = request.headers.get("authorization", "")
        seen.append((str(request.url), body["model"], auth))
        if "ollama.example" in str(request.url):
            return httpx.Response(503, json={"error": "busy"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = factory  # type: ignore[misc]
    try:
        res = await fb.post_chat(
            fb.primary_endpoint("http://ollama.example/v1", "ollama"),
            {"model": "gpt-oss:120b-cloud", "messages": [{"role": "user", "content": "hi"}]},
            60,
        )
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]

    assert res.status_code == 200
    assert seen[0][0].startswith("http://ollama.example/v1/")
    assert seen[0][1] == "gpt-oss:120b-cloud"
    assert seen[1][0].startswith("https://sakura.example/v1/")
    assert seen[1][1] == "gpt-oss-120b"
    assert seen[1][2] == "Bearer sakura-key"


def test_client_error_does_not_switch() -> None:
    asyncio.run(_client_error_does_not_switch())


async def _client_error_does_not_switch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad"})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = factory  # type: ignore[misc]
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc:
            await fb.post_chat(
                fb.primary_endpoint("http://ollama.example/v1", "ollama"),
                {"model": "gemma4:cloud", "messages": []},
                60,
            )
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]
    assert exc.value.response.status_code == 400


def test_cooldown_skips_primary() -> None:
    asyncio.run(_cooldown_skips_primary())


async def _cooldown_skips_primary() -> None:
    fb._mark_down("gpt-oss:120b-cloud")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    transport = httpx.MockTransport(handler)
    original = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        return original(*args, **kwargs)

    httpx.AsyncClient = factory  # type: ignore[misc]
    try:
        await fb.post_chat(
            fb.primary_endpoint("http://ollama.example/v1", "ollama"),
            {"model": "gpt-oss:120b-cloud", "messages": []},
            60,
        )
    finally:
        httpx.AsyncClient = original  # type: ignore[misc]
    assert seen == ["https://sakura.example/v1/chat/completions"]


def test_one_hop_only() -> None:
    routes = fb._routes(
        "gpt-oss:120b-cloud",
        fb.primary_endpoint("http://ollama.example/v1", "ollama"),
    )
    assert [model for model, _ in routes] == ["gpt-oss:120b-cloud", "gpt-oss-120b"]
