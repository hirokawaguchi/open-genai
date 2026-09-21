"""ノートブックが扱う MCP のカタログ。シードとプロンプトの既定値。"""

from __future__ import annotations

import os
from typing import Any

def knowledge_mcp_url() -> str:
    return (os.environ.get("KNOWLEDGE_MCP_URL") or "").strip()


KNOWLEDGE_PROMPT = (
    "これは庁内の共有ナレッジ（共通チームに置いた資料）を対話のその場で検索する MCP です。"
    "ノートの参考資料には自動では入りません。"
    "庁内の規程・事例・用語が必要なら、先に knowledge_list_tags でタグを確認し、"
    "knowledge_search で当たってください。ヒットは参照です。"
    "項目の根拠にするには、人に参考資料タブからナレッジを追加してもらってください。"
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

CATALOG: list[dict[str, Any]] = [
    {
        "catalog_id": "knowledge",
        "name": "共有ナレッジ",
        "kind": "remote",
        "description": (
            "庁内の共有ナレッジ（共通チーム）を対話中に検索します。"
            "参考資料タブで選ぶナレッジ追加とは別で、ノートには取り込みません。"
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
    return {"url": "", "available": True, "connected_default": True}
