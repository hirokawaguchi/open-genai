"""Qdrant への薄いラッパ（REST API を httpx で直接叩く）。"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "open_genai_rag")
VECTOR_SIZE = int(os.environ.get("EMBED_DIM", "1024"))  # mxbai-embed-large = 1024


async def ensure_collection() -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.get(f"{QDRANT_URL}/collections/{COLLECTION}")
        if res.status_code == 200:
            return
        await client.put(
            f"{QDRANT_URL}/collections/{COLLECTION}",
            json={"vectors": {"size": VECTOR_SIZE, "distance": "Cosine"}},
        )


async def count() -> int:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/count",
            json={"exact": True},
        )
        if res.status_code != 200:
            return 0
        return res.json().get("result", {}).get("count", 0)


async def upsert(items: list[dict[str, Any]]) -> int:
    """items: [{"id"?: str, "vector": [...], "payload": {...}}] を登録する。

    id を指定すると、同一 id の点は上書きされる（重複排除に利用）。
    id 省略時はランダム UUID。
    """
    points = [
        {
            "id": it.get("id") or str(uuid.uuid4()),
            "vector": it["vector"],
            "payload": it["payload"],
        }
        for it in items
    ]
    if not points:
        return 0
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.put(
            f"{QDRANT_URL}/collections/{COLLECTION}/points?wait=true",
            json={"points": points},
        )
        res.raise_for_status()
    return len(points)


def _scope_filter(
    scope: str,
    extra: list[dict[str, Any]] | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """scope(teamId 等)でナレッジを分離するための Qdrant フィルタを作る。

    tags 指定時は、その**いずれか**のタグを持つドキュメントに限定する（OR）。
    payload.tags は配列（keyword）で、match.any で「いずれか一致」を表現する。
    """
    must: list[dict[str, Any]] = [{"key": "scope", "match": {"value": scope}}]
    if tags:
        must.append({"key": "tags", "match": {"any": list(tags)}})
    if extra:
        must.extend(extra)
    return {"must": must}


async def search(
    vector: list[float], limit: int, scope: str, tags: list[str] | None = None
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
            json={
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                "filter": _scope_filter(scope, tags=tags),
            },
        )
        res.raise_for_status()
        return res.json().get("result", [])


async def delete_by_source(source: str, scope: str) -> None:
    """指定スコープ内の出典(source=ファイル名/URL)のチャンクを全削除する。"""
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete?wait=true",
            json={
                "filter": _scope_filter(
                    scope, [{"key": "source", "match": {"value": source}}]
                )
            },
        )
        res.raise_for_status()


async def clear(scope: str) -> None:
    """指定スコープのナレッジのみ全消去する（他チームには影響しない）。"""
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete?wait=true",
            json={"filter": _scope_filter(scope)},
        )
        res.raise_for_status()


async def _scroll(scope: str, with_payload: list[str], tags: list[str] | None = None):
    """指定スコープの点を payload 付きで走査するジェネレータ。"""
    offset: Any = None
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            body: dict[str, Any] = {
                "limit": 256,
                "with_payload": with_payload,
                "with_vector": False,
                "filter": _scope_filter(scope, tags=tags),
            }
            if offset is not None:
                body["offset"] = offset
            res = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll", json=body
            )
            if res.status_code != 200:
                return
            result = res.json().get("result", {})
            for p in result.get("points", []):
                yield p.get("payload") or {}
            offset = result.get("next_page_offset")
            if offset is None:
                return


async def list_sources(scope: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
    """指定スコープ(＋任意でタグ絞り込み)のドキュメント(source)と各チャンク数を返す。"""
    counts: dict[str, int] = {}
    async for payload in _scroll(scope, ["source"], tags=tags):
        src = payload.get("source", "unknown")
        counts[src] = counts.get(src, 0) + 1
    return [
        {"source": s, "chunks": c}
        for s, c in sorted(counts.items(), key=lambda x: x[0])
    ]


async def list_tags(scope: str) -> list[dict[str, Any]]:
    """指定スコープで使用中のタグと、各タグの付いたチャンク数を返す。"""
    counts: dict[str, int] = {}
    async for payload in _scroll(scope, ["tags"]):
        for t in payload.get("tags") or []:
            if t:
                counts[t] = counts.get(t, 0) + 1
    return [
        {"tag": t, "chunks": c}
        for t, c in sorted(counts.items(), key=lambda x: x[0])
    ]
