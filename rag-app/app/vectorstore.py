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
    *,
    require_tags: bool = False,
) -> dict[str, Any]:
    """scope(teamId 等)でナレッジを分離するための Qdrant フィルタを作る。

    tags 指定時は、その**いずれか**のタグを持つドキュメントに限定する（OR）。
    require_tags=True かつ tags 未指定のときはタグ未付与を除外する。
    """
    from . import textnorm

    must: list[dict[str, Any]] = [{"key": "scope", "match": {"value": scope}}]
    if tags:
        # NFD/NFC 混在に備え、正規化形＋生値の両方でマッチさせる
        tag_any: list[str] = []
        for t in tags:
            for form in (t, textnorm.normalize_tag(t)):
                if form and form not in tag_any:
                    tag_any.append(form)
        must.append({"key": "tags", "match": {"any": tag_any}})
    if extra:
        must.extend(extra)
    filt: dict[str, Any] = {"must": must}
    if require_tags and not tags:
        filt["must_not"] = [{"is_empty": {"key": "tags"}}]
    return filt


def _source_filter_clause(source: str | None) -> list[dict[str, Any]] | None:
    """source フィルタ。NFC/NFD 混在に備え候補形を any で渡す。"""
    from . import textnorm

    forms = textnorm.source_match_forms(source)
    if not forms:
        return None
    if len(forms) == 1:
        return [{"key": "source", "match": {"value": forms[0]}}]
    return [{"key": "source", "match": {"any": forms}}]


async def search(
    vector: list[float],
    limit: int,
    scope: str,
    tags: list[str] | None = None,
    *,
    require_tags: bool = True,
    source: str | None = None,
) -> list[dict[str, Any]]:
    extra = _source_filter_clause(source)
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/search",
            json={
                "vector": vector,
                "limit": limit,
                "with_payload": True,
                "filter": _scope_filter(
                    scope, extra, tags=tags, require_tags=require_tags
                ),
            },
        )
        res.raise_for_status()
        return res.json().get("result", [])


async def delete_by_source(source: str, scope: str) -> None:
    """指定スコープ内の出典(source=ファイル名/URL)のチャンクを全削除する。"""
    extra = _source_filter_clause(source) or [
        {"key": "source", "match": {"value": (source or "").strip()}}
    ]
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete?wait=true",
            json={"filter": _scope_filter(scope, extra)},
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


async def count_scope(scope: str) -> int:
    """指定スコープのチャンク数を返す。"""
    async with httpx.AsyncClient(timeout=30) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/count",
            json={"filter": _scope_filter(scope), "exact": True},
        )
        if res.status_code != 200:
            return 0
        return int(res.json().get("result", {}).get("count", 0) or 0)


async def reassign_scope(from_scope: str, to_scope: str) -> int:
    """payload.scope を一括書き換えする（誤登録スコープの移行用）。

    戻り値は移行対象だったチャンク数。to_scope 側に既にある点はそのまま残る。
    """
    if from_scope == to_scope:
        return 0
    n = await count_scope(from_scope)
    if n <= 0:
        return 0
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/payload?wait=true",
            json={
                "payload": {"scope": to_scope},
                "filter": _scope_filter(from_scope),
            },
        )
        res.raise_for_status()
    return n


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
    tag_map: dict[str, set[str]] = {}
    async for payload in _scroll(scope, ["source", "tags"], tags=tags):
        src = payload.get("source", "unknown")
        counts[src] = counts.get(src, 0) + 1
        tag_map.setdefault(src, set())
        for t in payload.get("tags") or []:
            if t:
                tag_map[src].add(str(t))
    return [
        {
            "source": s,
            "chunks": c,
            "tags": sorted(tag_map.get(s) or []),
        }
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


async def set_tags_by_source(scope: str, source: str, tags: list[str]) -> None:
    """指定ドキュメントの全チャンクの tags を置き換える。"""
    extra = _source_filter_clause(source) or [
        {"key": "source", "match": {"value": (source or "").strip()}}
    ]
    async with httpx.AsyncClient(timeout=60) as client:
        res = await client.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/payload?wait=true",
            json={
                "payload": {"tags": list(tags)},
                "filter": _scope_filter(scope, extra),
            },
        )
        res.raise_for_status()


async def rename_source_in_payloads(scope: str, old: str, new: str) -> int:
    """スコープ内のチャンク payload.source を old→new に置換する。"""
    if not old or not new or old == new:
        return 0
    updated = 0
    offset: Any = None
    extra = _source_filter_clause(old) or [
        {"key": "source", "match": {"value": old}}
    ]
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            body: dict[str, Any] = {
                "limit": 128,
                "with_payload": ["source"],
                "with_vector": False,
                "filter": _scope_filter(scope, extra),
            }
            if offset is not None:
                body["offset"] = offset
            res = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll", json=body
            )
            if res.status_code != 200:
                break
            result = res.json().get("result", {})
            points = result.get("points") or []
            for p in points:
                pid = p.get("id")
                payload = p.get("payload") or {}
                if payload.get("source") == new:
                    continue
                await client.post(
                    f"{QDRANT_URL}/collections/{COLLECTION}/points/payload?wait=true",
                    json={"payload": {"source": new}, "points": [pid]},
                )
                updated += 1
            offset = result.get("next_page_offset")
            if offset is None:
                break
    return updated


async def rename_tag_in_payloads(scope: str, old: str, new: str) -> int:
    """スコープ内のチャンク payload.tags で old→new に置換する。"""
    updated = 0
    offset: Any = None
    async with httpx.AsyncClient(timeout=60) as client:
        while True:
            body: dict[str, Any] = {
                "limit": 128,
                "with_payload": ["tags", "source"],
                "with_vector": False,
                "filter": _scope_filter(scope, tags=[old]),
            }
            if offset is not None:
                body["offset"] = offset
            res = await client.post(
                f"{QDRANT_URL}/collections/{COLLECTION}/points/scroll", json=body
            )
            if res.status_code != 200:
                break
            result = res.json().get("result", {})
            points = result.get("points") or []
            for p in points:
                pid = p.get("id")
                payload = p.get("payload") or {}
                cur = [str(t) for t in (payload.get("tags") or [])]
                if old not in cur:
                    continue
                nxt = [new if t == old else t for t in cur]
                # 重複除去（順序維持）
                seen: list[str] = []
                for t in nxt:
                    if t not in seen:
                        seen.append(t)
                await client.post(
                    f"{QDRANT_URL}/collections/{COLLECTION}/points/payload?wait=true",
                    json={"payload": {"tags": seen}, "points": [pid]},
                )
                updated += 1
            offset = result.get("next_page_offset")
            if offset is None:
                break
    return updated
