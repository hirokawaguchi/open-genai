"""OpenGENAI ナレッジ検索 MCP サーバ（Streamable HTTP）。

rag-app の機械向け API（/knowledge/tags, /knowledge/docs, /retrieve）を
MCP ツールとして公開する薄いラッパ。Dify Agent ノード等から利用する。
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

RAG_BASE_URL = os.environ.get("RAG_BASE_URL", "http://rag-app:8001").rstrip("/")
RAG_API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
DEFAULT_SCOPE = os.environ.get(
    "RAG_DEFAULT_SCOPE", "00000000-0000-0000-0000-000000000000"
)
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8002"))

mcp = FastMCP(
    "OpenGENAI Knowledge",
    instructions=(
        "OpenGENAI のチーム別ナレッジを検索する。ナレッジは scope(=teamId) と tags で識別される。"
        "検索前に knowledge_list_tags でタグを確認し、knowledge_search には tags を必ず渡すこと。"
        "タグ未付与の文書は検索対象外。"
    ),
    host=HOST,
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def _headers() -> dict[str, str]:
    return {"x-api-key": RAG_API_KEY, "Content-Type": "application/json"}


def _resolve_scope(scope: str | None) -> str:
    s = (scope or "").strip()
    return s or DEFAULT_SCOPE


def _parse_tags(tags: str | list[str] | None) -> list[str]:
    import unicodedata

    def _norm(t: str) -> str:
        return unicodedata.normalize("NFC", str(t)).strip()

    if tags is None:
        return []
    if isinstance(tags, list):
        out: list[str] = []
        for t in tags:
            n = _norm(t)
            if n and n not in out:
                out.append(n)
        return out
    s = _norm(tags)
    if not s:
        return []
    # JSON 配列文字列にも対応
    if s.startswith("["):
        try:
            data = json.loads(s)
            if isinstance(data, list):
                return _parse_tags(data)
        except json.JSONDecodeError:
            pass
    for sep in (",", "|", "、", ";"):
        if sep in s:
            out = []
            for p in s.split(sep):
                n = _norm(p)
                if n and n not in out:
                    out.append(n)
            return out
    return [s]


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{RAG_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.get(url, headers=_headers(), params=params or {})
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict[str, Any]) -> Any:
    url = f"{RAG_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(url, headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


def _as_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


@mcp.tool()
async def knowledge_list_tags(scope: str = "") -> str:
    """指定チーム(scope)のナレッジタグ一覧を返す。検索前に呼び出して候補タグを確認すること。

    Args:
        scope: ナレッジスコープ（teamId）。空なら既定スコープ。
    """
    resolved = _resolve_scope(scope)
    data = await _get(
        "/knowledge/tags",
        {"scope": resolved},
    )
    return _as_json(data)


@mcp.tool()
async def knowledge_list_docs(scope: str = "", tags: str = "") -> str:
    """指定チームの文書一覧。tags で絞り込み可能（カンマ区切り可）。

    Args:
        scope: ナレッジスコープ（teamId）。空なら既定スコープ。
        tags: 絞り込みタグ（例: \"議事録\" または \"議事録,規程\"）。空なら全件。
    """
    resolved = _resolve_scope(scope)
    tag_list = _parse_tags(tags)
    params: dict[str, Any] = {"scope": resolved}
    if tag_list:
        params["tags"] = ",".join(tag_list)
    data = await _get("/knowledge/docs", params)
    # エージェント向けに要点だけ整形（全文は載せない）
    import unicodedata

    docs = data.get("documents") or []
    slim = []
    for d in docs:
        if not isinstance(d, dict):
            continue
        src = d.get("source") or ""
        if isinstance(src, str):
            src = unicodedata.normalize("NFC", src)
        slim.append(
            {
                "doc_id": d.get("doc_id") or d.get("id"),
                "source": src,
                "tags": d.get("tags") or [],
                "index_kind": d.get("index_kind"),
            }
        )
    return _as_json({"scope": resolved, "documents": slim, "count": len(slim)})


def _citation_label(n: dict) -> str:
    """出典表示名: ファイル名 / 節タイトル / p.開始-終了。"""
    source = (n.get("source") or "").strip() or "unknown"
    title = (n.get("title") or "").strip()
    parts = [source]
    if title and title != source and title.lower() != "chunk":
        parts.append(title)
    ps, pe = n.get("page_start"), n.get("page_end")
    if ps is not None:
        try:
            ps_i = int(ps)
            pe_i = int(pe) if pe is not None else ps_i
            if pe_i != ps_i:
                parts.append(f"p.{ps_i}-{pe_i}")
            else:
                parts.append(f"p.{ps_i}")
        except (TypeError, ValueError):
            pass
    return " / ".join(parts)


@mcp.tool()
async def knowledge_search(
    query: str,
    tags: str,
    scope: str = "",
    top_k: int = 4,
    mode: str = "auto",
    source: str = "",
    doc_id: str = "",
) -> str:
    """ナレッジを検索して該当箇所（nodes）を返す。tags は必須（未付与文書は検索対象外）。

    特定資料に絞るときは source（ファイル名）または doc_id を渡す。
    mode=auto かつ資料指定時は、構造化文書なら tree（節・ページ）、なければ vector。

    Args:
        query: 検索クエリ（議題・質問文など）
        tags: 検索対象タグ（必須。例: \"議事録\" または \"議事録,規程\"）
        scope: ナレッジスコープ（teamId）。空なら既定スコープ。
        top_k: 取得件数（既定 4）
        mode: auto|full|vector|tree|hybrid（既定 auto）
        source: 対象ファイル名（任意。指定時はその文書内のみ）
        doc_id: 対象文書 ID（任意。knowledge_list_docs の値）
    """
    resolved = _resolve_scope(scope)
    tag_list = _parse_tags(tags)
    if not tag_list:
        return _as_json(
            {
                "error": "tags は必須です。先に knowledge_list_tags でタグを確認してください。",
                "scope": resolved,
            }
        )
    q = (query or "").strip()
    if not q:
        return _as_json({"error": "query は必須です。", "scope": resolved})

    body: dict = {
        "question": q,
        "scope": resolved,
        "tags": tag_list,
        "top_k": int(top_k or 4),
        "mode": (mode or "auto").strip().lower(),
    }
    # macOS NFD ファイル名と LLM の NFC 表記差を吸収
    import unicodedata

    src = unicodedata.normalize("NFC", (source or "").strip())
    did = (doc_id or "").strip()
    if src:
        body["source"] = src
    if did:
        body["doc_id"] = did
    data = await _post("/retrieve", body)
    nodes = data.get("nodes") or []
    citations = []
    slim_nodes = []
    for i, n in enumerate(nodes, start=1):
        if not isinstance(n, dict):
            continue
        text = (n.get("text") or "").strip()
        label = _citation_label(n)
        # アコーディオン本文にも節見出しを先頭に付ける（tree/hybrid）
        title = (n.get("title") or "").strip()
        body_text = text
        if title and n.get("mode") in ("tree", "hybrid", "full") and not text.startswith("【"):
            body_text = f"【{title}】\n{text}"
        display = f"[{i}] {label}"
        slim_nodes.append(
            {
                "ref": i,
                "id": n.get("id"),
                "title": title,
                "source": (n.get("source") or "").strip() or "unknown",
                "doc_id": n.get("doc_id"),
                "page_start": n.get("page_start"),
                "page_end": n.get("page_end"),
                "score": n.get("score"),
                "mode": n.get("mode"),
                "text": body_text,
            }
        )
        if body_text:
            citations.append(
                {
                    "display_name": display,
                    "source": label,
                    "text": body_text,
                    "mime_type": "text/x.open-genai.citation",
                }
            )
    return _as_json(
        {
            "scope": resolved,
            "query": q,
            "tags": tag_list,
            "source": src or None,
            "doc_id": did or None,
            "resolved_mode": data.get("resolved_mode"),
            "nodes": slim_nodes,
            "citation_artifacts": citations,
            "hit_count": len(slim_nodes),
        }
    )


def main() -> None:
    # Dify は Streamable HTTP のみ対応。エンドポイントは http://host:8002/mcp
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
