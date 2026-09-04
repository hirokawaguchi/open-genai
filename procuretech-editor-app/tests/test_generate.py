"""外部「文書生成」API クライアント／テーマレジストリのテスト。"""

import asyncio

import httpx
import pytest

from app import generate

BASE = "http://generate.test"


def test_default_theme_present():
    ids = [t["id"] for t in generate.THEMES]
    assert "procurement_spec" in ids
    theme = generate.get_theme("procurement_spec")
    assert theme is not None
    keys = [i["key"] for i in theme["inputs"]]
    assert keys == ["systemplan", "global"]


def test_public_themes_hides_secrets(monkeypatch):
    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", BASE)
    pub = generate.public_themes()
    assert pub and pub[0]["id"] == "procurement_spec"
    assert pub[0]["configured"] is True
    # 秘匿情報は含めない
    assert "api_url" not in pub[0]
    assert "api_key" not in pub[0]


def test_is_configured_reflects_url(monkeypatch):
    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "")
    assert generate.is_configured() is False
    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", BASE)
    assert generate.is_configured() is True


def _install_mock(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient  # パッチ前の実クラスを退避（自己再帰防止）

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(generate.httpx, "AsyncClient", factory)


def test_start_generation_sends_files_and_key(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        seen["key"] = request.headers.get("x-api-key")
        return httpx.Response(202, json={"request_id": "gen-1"})

    _install_mock(monkeypatch, handler)
    res = asyncio.run(
        generate.start_generation(
            {"systemplan": b"sp", "global": b"gl"},
            base_url=BASE,
            api_key="secret",
            username="user-a",
            doc_type="specification",
        )
    )
    assert res["request_id"] == "gen-1"
    assert seen["path"] == "/generate"
    assert seen["key"] == "secret"
    assert b"systemplan" in seen["body"]
    assert b"global" in seen["body"]
    assert b"specification" in seen["body"]


def test_start_generation_requires_base_url():
    with pytest.raises(generate.GenerateError):
        asyncio.run(
            generate.start_generation({"a": b"x"}, base_url="", username="u")
        )


def test_get_status_and_result(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/status/gen-9":
            return httpx.Response(200, json={"status": "success", "progress": 100})
        if request.url.path == "/result/gen-9":
            return httpx.Response(200, content=b"PK\x03\x04zip")
        return httpx.Response(404)

    _install_mock(monkeypatch, handler)
    st = asyncio.run(generate.get_status("gen-9", base_url=BASE))
    assert st["status"] == "success"
    data = asyncio.run(generate.fetch_result("gen-9", base_url=BASE))
    assert data == b"PK\x03\x04zip"
