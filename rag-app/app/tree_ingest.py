"""構造化／全文索引へのドキュメント取込（切り捨てなし）。"""

from __future__ import annotations

import hashlib
from typing import Any

from shared.docextract import (
    MAX_DOC_PAGES,
    DocExtractError,
    extract_doc_pages,
    text_to_pages,
)

from . import docstore, tree_builder, vectorstore
from .embeddings import embed


def _chunk_text(text: str, size: int = 600, overlap: int = 80) -> list[str]:
    text = text.strip()
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        if len(para) <= size:
            chunks.append(para)
            continue
        start = 0
        while start < len(para):
            chunks.append(para[start : start + size])
            start += size - overlap
    return chunks


def _make_chunk_id(scope: str, source: str, text: str) -> str:
    import uuid

    ns = uuid.UUID("6f1e0c2a-9b4d-5e7a-8c3f-0a1b2c3d4e5f")
    return str(uuid.uuid5(ns, f"{scope}\n{source}\n{text}"))


async def _upsert_vector_chunks(
    *,
    scope: str,
    source: str,
    full: str,
    tags: list[str] | None,
    doc_id: str,
) -> int:
    await vectorstore.delete_by_source(source, scope)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chunk in _chunk_text(full):
        cid = _make_chunk_id(scope, source, chunk)
        if cid in seen:
            continue
        seen.add(cid)
        vector = await embed(chunk)
        items.append(
            {
                "id": cid,
                "vector": vector,
                "payload": {
                    "text": chunk,
                    "source": source,
                    "scope": scope,
                    "tags": tags or [],
                    "doc_id": doc_id,
                },
            }
        )
    if not items:
        return 0
    return await vectorstore.upsert(items)


async def _save_pages(
    *,
    scope: str,
    source: str,
    pages: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
    tags: list[str] | None,
    index_kind: str,
    also_vector: bool,
) -> dict[str, Any]:
    from . import textnorm

    source = textnorm.normalize_source(source) or "unknown"
    full = "\n\n".join(p.get("text") or "" for p in pages)
    content_hash = hashlib.sha256(full.encode("utf-8", "ignore")).hexdigest()
    doc_id = docstore.upsert_document(
        scope=scope,
        source=source,
        pages=pages,
        nodes=nodes,
        tags=tags,
        content_hash=content_hash,
        truncated=False,
        index_kind=index_kind,
    )
    vector_chunks = 0
    if also_vector:
        vector_chunks = await _upsert_vector_chunks(
            scope=scope,
            source=source,
            full=full,
            tags=tags,
            doc_id=doc_id,
        )
    return {
        "doc_id": doc_id,
        "source": source,
        "page_count": len(pages),
        "char_count": len(full),
        "node_count": len(nodes),
        "truncated": False,
        "index_kind": index_kind,
        "vector_chunks": vector_chunks,
    }


async def ingest_structured_file(
    *,
    scope: str,
    filename: str,
    media_type: str,
    content_b64: str,
    tags: list[str] | None = None,
    also_vector: bool = True,
) -> dict[str, Any]:
    """1ファイルをページ抽出→ツリー構築→保存。任意でベクトルも併用登録。"""
    pages = extract_doc_pages(filename, media_type, content_b64)
    if not pages:
        raise DocExtractError(f"未対応のファイル形式です: {filename}")

    nodes = await tree_builder.build_tree_nodes(pages)
    return await _save_pages(
        scope=scope,
        source=filename,
        pages=pages,
        nodes=nodes,
        tags=tags,
        index_kind="tree",
        also_vector=also_vector,
    )


async def ingest_fulltext_file(
    *,
    scope: str,
    filename: str,
    media_type: str,
    content_b64: str,
    tags: list[str] | None = None,
    also_vector: bool = True,
) -> dict[str, Any]:
    """1ファイルをページ全文保存＋ベクトル登録（ツリーなし／簡易登録）。"""
    pages = extract_doc_pages(filename, media_type, content_b64)
    if not pages:
        raise DocExtractError(f"未対応のファイル形式です: {filename}")

    return await _save_pages(
        scope=scope,
        source=filename,
        pages=pages,
        nodes=[],
        tags=tags,
        index_kind="fulltext",
        also_vector=also_vector,
    )


async def ingest_fulltext_text(
    *,
    scope: str,
    source: str,
    text: str,
    tags: list[str] | None = None,
    also_vector: bool = True,
) -> dict[str, Any]:
    """プレーンテキストを全文保存（URL 取込など）。任意でベクトルも登録。"""
    pages = text_to_pages(text)
    if not pages:
        raise DocExtractError(f"本文が空です: {source}")
    if len(pages) > MAX_DOC_PAGES:
        raise DocExtractError(
            f"合成ページ数が上限（{MAX_DOC_PAGES}）を超えています"
            f"（{len(pages)} ページ相当）"
        )
    return await _save_pages(
        scope=scope,
        source=source,
        pages=pages,
        nodes=[],
        tags=tags,
        index_kind="fulltext",
        also_vector=also_vector,
    )
