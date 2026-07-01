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
    folder: str | None = None,
) -> dict[str, Any]:
    """scope(teamId 等)でナレッジを分離するための Qdrant フィルタを作る。

    folder 指定時は、そのフォルダ配下（サブツリー）に限定する。各点は
    payload.folder_path に祖先を含むため、folder_path == folder のマッチで
    サブツリー全体（自身＋子孫）を対象にできる。
    """
    must: list[dict[str, Any]] = [{"key": "scope", "match": {"value": scope}}]
    if folder:
        must.append({"key": "folder_path", "match": {"value": folder}})
    if extra:
        must.extend(extra)
    return {"must": must}


async def search(
    vector: list[float], limit: int, scope: str, folder: str | None = None
) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
            json={
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                "filter": _scope_filter(scope, folder=folder),
            },
        )
        res.raise_for_status()
        return res.json().get("result", [])


async def delete_by_source(source: str, scope: str, folder: str | None = None) -> None:
    """指定スコープ(＋任意でフォルダ配下)内の出典(source)のチャンクを全削除する。"""
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete?wait=true",
            json={
                "filter": _scope_filter(
                    scope, [{"key": "source", "match": {"value": source}}], folder=folder
                )
            },
        )
        res.raise_for_status()


async def delete_folder(scope: str, folder: str) -> None:
    """指定スコープのフォルダ配下（サブツリー）のチャンクを全削除する。"""
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete?wait=true",
            json={"filter": _scope_filter(scope, folder=folder)},
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


async def list_sources(scope: str, folder: str | None = None) -> list[dict[str, Any]]:
    """指定スコープ(＋任意でフォルダ配下)の出典(ファイル名)と各チャンク数を返す。"""
    counts: dict[str, int] = {}
    offset: Any = None
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            body: dict[str, Any] = {
                "limit": 256,
                "with_payload": ["source", "folder"],
                "with_vector": False,
                "filter": _scope_filter(scope, folder=folder),
            }
            if offset is not None:
                body["offset"] = offset
            res = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll", json=body
            )
            if res.status_code != 200:
                break
            result = res.json().get("result", {})
            for p in result.get("points", []):
                src = (p.get("payload") or {}).get("source", "unknown")
                counts[src] = counts.get(src, 0) + 1
            offset = result.get("next_page_offset")
            if offset is None:
                break
    return [
        {"source": s, "chunks": c}
        for s, c in sorted(counts.items(), key=lambda x: x[0])
    ]
