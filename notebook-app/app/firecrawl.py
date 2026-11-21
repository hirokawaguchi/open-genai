"""Web 検索・取得（Firecrawl Local）。

`FIRECRAWL_URL` が空なら無効（カタログでは非接続になる）。
検索は Firecrawl Local 経由で Firecrawl Cloud にクエリが出る。scrape は手元で動く。
閉域（LGWAN 等）では `FIRECRAWL_URL` を空のままにする。
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

REQUEST_TIMEOUT = 30.0
DEFAULT_LIMIT = 5
MAX_RESULTS = 8
MAX_SNIPPET_CHARS = 1500
MAX_SCRAPE_CHARS = 6000


def base_url() -> str:
    return (os.environ.get("FIRECRAWL_URL") or "").strip().rstrip("/")


def enabled() -> bool:
    return bool(base_url())


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = (os.environ.get("FIRECRAWL_API_KEY") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _result_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        for key in ("web", "results"):
            rows = data.get(key)
            if isinstance(rows, list):
                return [r for r in rows if isinstance(r, dict)]
    return []


async def search(query: str, limit: int = DEFAULT_LIMIT) -> str:
    q = (query or "").strip()
    if not q:
        return json.dumps({"error": "query が空です"}, ensure_ascii=False)
    if not enabled():
        return json.dumps(
            {"error": "Web 検索は無効です（FIRECRAWL_URL 未設定）"}, ensure_ascii=False
        )
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_RESULTS))
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{base_url()}/v2/search",
            json={"query": q[:2000], "limit": limit},
            headers=_headers(),
        )
        res.raise_for_status()
        body = res.json()
    data = body.get("data") if isinstance(body, dict) else None
    if data is None:
        data = body
    rows = _result_rows(data)[:limit]
    results = []
    for row in rows:
        text = str(
            row.get("markdown") or row.get("description") or row.get("content") or ""
        ).strip()
        results.append(
            {
                "title": str(row.get("title") or ""),
                "url": str(row.get("url") or ""),
                "snippet": text[:MAX_SNIPPET_CHARS],
            }
        )
    if not results:
        return json.dumps(
            {"query": q, "error": "該当する結果がありませんでした。", "source": "Firecrawl"},
            ensure_ascii=False,
        )
    return json.dumps(
        {"query": q, "results": results, "source": "Firecrawl"},
        ensure_ascii=False,
    )


async def scrape(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return json.dumps({"error": "url が空です"}, ensure_ascii=False)
    if not enabled():
        return json.dumps(
            {"error": "Web 検索は無効です（FIRECRAWL_URL 未設定）"}, ensure_ascii=False
        )
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{base_url()}/v2/scrape",
            json={"url": u, "formats": ["markdown"]},
            headers=_headers(),
        )
        res.raise_for_status()
        body = res.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        data = body if isinstance(body, dict) else {}
    markdown = str(data.get("markdown") or "").strip()
    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    title = str((metadata or {}).get("title") or "")
    if not markdown:
        return json.dumps(
            {"url": u, "error": "本文を取得できませんでした。", "source": "Firecrawl"},
            ensure_ascii=False,
        )
    return json.dumps(
        {
            "url": u,
            "title": title,
            "markdown": markdown[:MAX_SCRAPE_CHARS],
            "source": "Firecrawl",
        },
        ensure_ascii=False,
    )
