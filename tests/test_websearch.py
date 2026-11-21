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


def test_sanitize_query_extracts_tag(monkeypatch):
    ws = _reload_websearch(monkeypatch, "http://firecrawl-local:3002")
    # タグの中身を優先
    assert ws.sanitize_query("了解しました。<q>量子コンピュータ 仕組み</q>") == "量子コンピュータ 仕組み"
    # 前置き除去
    assert ws.sanitize_query("検索クエリ: 為替 最新") == "為替 最新"
    # 箇条書き・引用符除去、最初の非空行のみ
    assert ws.sanitize_query('- "東京 天気"\n2行目') == "東京 天気"
    # 空出力
    assert ws.sanitize_query("") == ""


def test_is_bad_query(monkeypatch):
    ws = _reload_websearch(monkeypatch, "http://firecrawl-local:3002")
    assert ws.is_bad_query("") is True
    assert ws.is_bad_query("x" * (ws.MAX_SANE_QUERY_CHARS + 1)) is True
    assert ws.is_bad_query("申し訳ありませんが対応できません") is True
    assert ws.is_bad_query("量子コンピュータ 詳細") is False


def test_heuristic_query_prepends_previous_user_turn(monkeypatch):
    ws = _reload_websearch(monkeypatch, "http://firecrawl-local:3002")
    history = [
        {"role": "user", "content": "クアッドという国際協力枠組みについて"},
        {"role": "assistant", "content": "クアッドは…"},
    ]
    # 追い質問語を含むと直前のユーザー発話を前置
    assert ws.heuristic_query(history, "もっと詳しく") == (
        "クアッドという国際協力枠組みについて もっと詳しく"
    )
    # 追い質問でなければそのまま
    assert ws.heuristic_query(history, "東京の天気") == "東京の天気"
    # 履歴が無ければそのまま
    assert ws.heuristic_query([], "もっと詳しく") == "もっと詳しく"
