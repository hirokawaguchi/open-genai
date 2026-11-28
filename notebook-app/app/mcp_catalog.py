"""ノートブックが扱う MCP のカタログ。シードとプロンプトの既定値。"""

from __future__ import annotations

import os
from typing import Any

def knowledge_mcp_url() -> str:
    return (os.environ.get("KNOWLEDGE_MCP_URL") or "").strip()


def firecrawl_url() -> str:
    return (os.environ.get("FIRECRAWL_URL") or "").strip()


KNOWLEDGE_PROMPT = (
    "これは庁内の共有ナレッジ（共通チームに置いた資料）です。"
    "On のあいだ、共通チームの資料はすべてこの対話の対象です。"
    "タグや文書があるときだけ knowledge_list_tags で確認し、knowledge_search で当たってください。"
    "ヒットは参考資料と同じ根拠にします。"
    "タグや文書が無いときは、共有ナレッジへの登録を求めません。ノートの参考資料を調べて答えます。"
    "一部のタグだけを対象にしたいときだけ、この MCP を Off にしてもらい、"
    "必要なタグを参考資料へ登録してもらってください。"
)

CLOCK_PROMPT = (
    "現在の日付と時刻（日本時間）を返すサンプル MCP です。"
    "『今日』『今』『期限』『何曜日』など日時が関係する質問では、"
    "推測せず get_current_time を先に呼んでください。"
)

WEATHER_PROMPT = (
    "都市名から現在の天気を返すサンプル MCP です（Open-Meteo）。"
    "天気・気温・傘の話では get_weather を呼んでください。都市が無ければ東京とします。"
)

WIKIPEDIA_PROMPT = (
    "日本語 Wikipedia を検索するサンプル MCP です。ウェブ全体は検索しません。"
    "百科事典にある用語・人物・制度の概要が必要なときに wikipedia_search を呼んでください。"
    "記事が無い会社名や個別の公式サイトは見つかりません。"
)

WEB_SEARCH_PROMPT = (
    "Firecrawl でウェブ全体を検索・取得する MCP です（検索クエリは外部へ出ます）。"
    "最新の動向や公式サイトの情報など、ナレッジや Wikipedia で足りないときに firecrawl_search を呼んでください。"
    "検索結果だけでは足りなければ、その URL を firecrawl_scrape に渡して本文を読んでください。"
    "得た情報は参照です。項目の根拠にするには、人に参考資料タブから資料を追加してもらってください。"
)

CATALOG: list[dict[str, Any]] = [
    {
        "catalog_id": "knowledge",
        "name": "共有ナレッジ",
        "kind": "remote",
        "description": (
            "庁内の共有ナレッジ（共通チーム）を対話の対象にします。"
            "On のあいだは、共通チームの資料がすべて対象です。"
        ),
        "prompt": KNOWLEDGE_PROMPT,
        "tools": [
            "knowledge_list_tags",
            "knowledge_list_docs",
            "knowledge_search",
        ],
    },
    {
        "catalog_id": "clock",
        "name": "時刻",
        "kind": "builtin",
        "description": "現在の日付と時刻（日本時間）を返します。",
        "prompt": CLOCK_PROMPT,
        "tools": ["get_current_time"],
    },
    {
        "catalog_id": "weather",
        "name": "天気",
        "kind": "builtin",
        "description": "都市名から現在の天気を返します（Open-Meteo。API キー不要）。",
        "prompt": WEATHER_PROMPT,
        "tools": ["get_weather"],
    },
    {
        "catalog_id": "web_search",
        "name": "Wikipedia",
        "kind": "builtin",
        "description": "日本語 Wikipedia を検索します。ウェブ全体や公式サイトは対象外です。",
        "prompt": WIKIPEDIA_PROMPT,
        "tools": ["wikipedia_search"],
    },
    {
        "catalog_id": "firecrawl",
        "name": "Web検索",
        "kind": "builtin",
        "description": (
            "Firecrawl でウェブ全体を検索し、必要なら URL の本文を取得します。"
            "検索クエリは外部（Firecrawl Cloud）へ出ます。"
        ),
        "prompt": WEB_SEARCH_PROMPT,
        "tools": ["firecrawl_search", "firecrawl_scrape"],
    },
]

CATALOG_BY_ID = {str(s["catalog_id"]): s for s in CATALOG}

CORE_TOOLS = ("search_sources", "list_items")


def spec_for(catalog_id: str) -> dict[str, Any] | None:
    return CATALOG_BY_ID.get((catalog_id or "").strip())


def default_prompt(catalog_id: str) -> str:
    spec = spec_for(catalog_id)
    return str(spec["prompt"]) if spec else ""


def catalog_tools(catalog_id: str) -> list[str]:
    spec = spec_for(catalog_id)
    if not spec:
        return []
    return [str(t) for t in spec.get("tools") or []]


def catalog_runtime(catalog_id: str) -> dict[str, Any]:
    spec = spec_for(catalog_id)
    if not spec:
        return {
            "url": "",
            "available": False,
            "connected_default": False,
        }
    if catalog_id == "knowledge":
        url = knowledge_mcp_url()
        return {"url": url, "available": bool(url), "connected_default": bool(url)}
    if catalog_id == "firecrawl":
        url = firecrawl_url()
        return {"url": url, "available": bool(url), "connected_default": bool(url)}
    return {"url": "", "available": True, "connected_default": True}
