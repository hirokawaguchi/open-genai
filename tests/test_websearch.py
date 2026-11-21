"""Web 検索（Firecrawl Local）の backend ヘルパ。

FIRECRAWL_URL が空なら無効。あるときは Firecrawl の応答を整形して返す。
検索クエリは外部（Firecrawl Cloud）へ出る点に注意（ここでは httpx をモックする）。
"""

from __future__ import annotations

import asyncio

import pytest

from conftest import load_service_module


def _reload_websearch(monkeypatch, url: str | None):
    if url is None:
        monkeypatch.delenv("FIRECRAWL_URL", raising=False)
    else:
        monkeypatch.setenv("FIRECRAWL_URL", url)
    # FIRECRAWL_URL は import 時に読むため、env を設定してから読み込む。
    return load_service_module("backend/app/websearch.py")


def test_disabled_without_url(monkeypatch):
    ws = _reload_websearch(monkeypatch, None)
    assert ws.enabled() is False
    with pytest.raises(RuntimeError):
        asyncio.run(ws.search("花火"))


def test_result_rows_shapes(monkeypatch):
    ws = _reload_websearch(monkeypatch, "http://firecrawl-local:3002")
    # data が配列
    assert ws._result_rows([{"url": "a"}]) == [{"url": "a"}]
    # data.web
    assert ws._result_rows({"web": [{"url": "b"}]}) == [{"url": "b"}]
    # data.results
    assert ws._result_rows({"results": [{"url": "c"}]}) == [{"url": "c"}]
    assert ws._result_rows({"nope": 1}) == []


def test_search_formats_and_truncates(monkeypatch):
    ws = _reload_websearch(monkeypatch, "http://firecrawl-local:3002")

    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "success": True,
                "data": {
                    "web": [
                        {
                            "url": "https://example.jp/a",
                            "title": "記事A",
                            "markdown": "本文" * 2000,
                        },
                        {"url": "", "title": "", "markdown": ""},
                    ]
                },
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            assert url.endswith("/v2/search")
            return FakeResp()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    passages = asyncio.run(ws.search("花火"))
    # 空 URL かつ空本文の行は落ちる。
    assert len(passages) == 1
    assert passages[0]["url"] == "https://example.jp/a"
    assert len(passages[0]["text"]) <= ws.MAX_SNIPPET_CHARS


def test_empty_query_returns_empty(monkeypatch):
    ws = _reload_websearch(monkeypatch, "http://firecrawl-local:3002")
    assert asyncio.run(ws.search("   ")) == []
