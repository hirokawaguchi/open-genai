from __future__ import annotations

import asyncio

import pytest

from conftest import load_service_module


class _Response:
    def __init__(self, prompts: list[str]) -> None:
        self._rows = [
            {"index": len(prompts) - 1 - i, "embedding": [float(i)]}
            for i in range(len(prompts))
        ]

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"data": self._rows}


class _Client:
    posts: list[list[str]] = []

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs

    async def __aenter__(self) -> "_Client":
        return self

    async def __aexit__(self, *args) -> bool:
        del args
        return False

    async def post(self, url: str, json: dict, headers: dict) -> _Response:
        del url, headers
        prompts = list(json["input"])
        type(self).posts.append(prompts)
        return _Response(prompts)


@pytest.fixture()
def embeddings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("EMBED_BATCH_SIZE", "2")
    monkeypatch.setenv("EMBED_DOC_PREFIX", "文書:")
    monkeypatch.setenv("EMBED_QUERY_PREFIX", "検索:")
    monkeypatch.setenv("EMBED_BASE_URL", "http://embed:80/v1")
    mod = load_service_module("rag-app/app/embeddings.py")
    _Client.posts = []
    monkeypatch.setattr(mod.httpx, "AsyncClient", _Client)
    return mod


def test_embed_many_batches_and_keeps_order(embeddings) -> None:
    vectors = asyncio.run(embeddings.embed_many(["a", "b", "c"]))
    assert _Client.posts == [["文書:a", "文書:b"], ["文書:c"]]
    # 応答の index は逆順。呼び出し順へ戻す。
    assert vectors == [[1.0], [0.0], [0.0]]


def test_query_prefix(embeddings) -> None:
    asyncio.run(embeddings.embed("質問", is_query=True))
    assert _Client.posts == [["検索:質問"]]
