"""Web 検索（Firecrawl Local）。

`FIRECRAWL_URL` が空なら機能ごと無効にする（チャットのスイッチも出さない）。
検索は Firecrawl Local 経由で Firecrawl Cloud にクエリが出る点に注意する。
閉域（LGWAN 等）では `FIRECRAWL_URL` を空のままにし、サイドカーも起動しない。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

FIRECRAWL_URL = (os.environ.get("FIRECRAWL_URL") or "").strip().rstrip("/")
# firecrawl-local に 0.0.0.0 で待受させる場合、クライアントは Bearer トークンが要る。
# サイドカーの FIRECRAWL_LOCAL_TOKEN と同じ値を渡す。
FIRECRAWL_TOKEN = (
    os.environ.get("FIRECRAWL_TOKEN") or os.environ.get("FIRECRAWL_API_KEY") or ""
).strip()

DEFAULT_LIMIT = 5
MAX_RESULTS = 8
MAX_SNIPPET_CHARS = 1500
REQUEST_TIMEOUT = 30.0


def enabled() -> bool:
    """FIRECRAWL_URL が設定されていれば Web 検索を使える。"""
    return bool(FIRECRAWL_URL)


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if FIRECRAWL_TOKEN:
        headers["Authorization"] = f"Bearer {FIRECRAWL_TOKEN}"
    return headers


def _result_rows(data: Any) -> list[dict[str, Any]]:
    """Firecrawl v2 search の応答から結果の配列を取り出す。

    `data` が配列の場合と、`data.web` に入る場合の両方に対応する。
    """
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        web = data.get("web")
        if isinstance(web, list):
            return [r for r in web if isinstance(r, dict)]
        # 稀に results キーのこともある
        results = data.get("results")
        if isinstance(results, list):
            return [r for r in results if isinstance(r, dict)]
    return []


def _passage(row: dict[str, Any]) -> dict[str, str]:
    url = str(row.get("url") or "")
    title = str(row.get("title") or "")
    body = str(row.get("markdown") or row.get("description") or row.get("content") or "").strip()
    return {
        "title": title,
        "url": url,
        "text": body[:MAX_SNIPPET_CHARS],
    }


async def search(query: str, *, limit: int = DEFAULT_LIMIT) -> list[dict[str, str]]:
    """Firecrawl v2 search を呼び、{title, url, text} の配列を返す。

    呼び出し側が無効時に呼ばないようにするため、無効なら RuntimeError。
    """
    if not enabled():
        raise RuntimeError("Web 検索は無効です")
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_RESULTS))
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{FIRECRAWL_URL}/v2/search",
            json={"query": q[:2000], "limit": limit},
            headers=_headers(),
        )
    res.raise_for_status()
    body = res.json()
    data = body.get("data") if isinstance(body, dict) else None
    if data is None:
        data = body
    rows = _result_rows(data)
    passages = [_passage(r) for r in rows[:limit]]
    return [p for p in passages if p["url"] or p["text"]]
