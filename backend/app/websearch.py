"""Web 検索（Firecrawl Local）。

`FIRECRAWL_URL` が空なら機能ごと無効にする（チャットのスイッチも出さない）。
検索は Firecrawl Local 経由で Firecrawl Cloud にクエリが出る点に注意する。
閉域（LGWAN 等）では `FIRECRAWL_URL` を空のままにし、サイドカーも起動しない。
"""

from __future__ import annotations

import os
import re
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
MAX_QUERY_CHARS = 200
# 妥当な検索語の上限（これを超えると文章と見なしフォールバック）。
MAX_SANE_QUERY_CHARS = 150

# 追い質問（単独では検索しづらい短い発話）を見分ける簡易パターン。
FOLLOWUP_RE = re.compile(
    r"(もっと|詳し|くわし|続き|つづき|続けて|もう少し|さらに|他に|ほかに|具体|"
    r"例を|理由|なぜ|どうして|まとめ|要約|比較|最新|同じ|それ|その|あの|この間|前の)"
)
# 言い換え失敗の兆候（拒否・説明文の混入）。
REWRITE_REJECT_RE = re.compile(
    r"(申し訳|できません|できかね|わかりません|不明です|as an ai|i (?:can|cannot|am)\b)",
    re.IGNORECASE,
)
# 「検索クエリ:」等の前置き。
_REWRITE_PREFIXES = (
    "検索クエリ",
    "検索語",
    "クエリ",
    "キーワード",
    "search query",
    "query",
    "keyword",
)


def _strip_query_prefix(text: str) -> str:
    """「検索クエリ: …」のような前置きと続く区切りを落とす。"""
    low = text.lower()
    for pref in _REWRITE_PREFIXES:
        if low.startswith(pref.lower()):
            rest = text[len(pref) :].lstrip(" :：-－=＝)】」>・\t")
            if rest:
                return rest.strip()
    return text


def sanitize_query(text: str) -> str:
    """LLM 出力から検索語だけを取り出し、1行・記号除去・長さ上限に整える。"""
    s = (text or "").strip()
    # <q>...</q> で囲まれていれば中身を優先。
    m = re.search(r"<q>\s*(.*?)\s*</q>", s, re.IGNORECASE | re.DOTALL)
    if m:
        s = m.group(1).strip()
    # 最初の非空行を採用。
    line = ""
    for raw in s.splitlines():
        if raw.strip():
            line = raw.strip()
            break
    if not line:
        return ""
    # 箇条書き記号・番号を落とす。
    line = re.sub(r"^\s*(?:[-*・•]+|\d+[.)、])\s*", "", line)
    line = _strip_query_prefix(line)
    # 前後の引用符・かぎ括弧を除く。
    line = line.strip().strip("\"'`“”「」『』【】").strip()
    return line[:MAX_QUERY_CHARS]


def is_bad_query(candidate: str) -> bool:
    """検索語として使えない（空 / 長すぎ / 拒否・説明文の混入）か。"""
    if not candidate:
        return True
    if len(candidate) > MAX_SANE_QUERY_CHARS:
        return True
    return bool(REWRITE_REJECT_RE.search(candidate))


def heuristic_query(history: list[dict[str, Any]], query: str) -> str:
    """LLM を使わない安全網。追い質問なら直前のユーザー発話を前置して検索語にする。"""
    user_turns = [
        str(m.get("content") or "").strip()
        for m in (history or [])
        if isinstance(m, dict)
        and m.get("role") == "user"
        and str(m.get("content") or "").strip()
    ]
    if user_turns and FOLLOWUP_RE.search(query or ""):
        prev = user_turns[-1][:120]
        if prev and prev != query:
            return f"{prev} {query}"[:MAX_QUERY_CHARS]
    return query


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
