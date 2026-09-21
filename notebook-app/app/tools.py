"""ハーネスが呼んでよいツール。項目の確定はしない。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from . import mcp_catalog, mcp_knowledge, retrieve, sample_mcp, store

CORE_TOOL_NAMES = mcp_catalog.CORE_TOOLS
BUILTIN_MCP_TOOLS = (
    "knowledge_list_tags",
    "knowledge_list_docs",
    "knowledge_search",
    "get_current_time",
    "get_weather",
    "wikipedia_search",
    "web_search",
)
ALL_TOOL_NAMES = (*CORE_TOOL_NAMES, *BUILTIN_MCP_TOOLS)

KNOWLEDGE_TOOLS = frozenset(
    {"knowledge_list_tags", "knowledge_list_docs", "knowledge_search"}
)


@dataclass
class ToolContext:
    session_id: str
    user_id: str
    scope: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    remote_mcps: list[dict[str, Any]] = field(default_factory=list)


def openai_tools(
    allowed: list[str],
    extra_specs: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    specs = {spec["function"]["name"]: spec for spec in _SPECS}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for name in allowed:
        if name in seen:
            continue
        spec = specs.get(name)
        if spec:
            out.append(spec)
            seen.add(name)
    for item in extra_specs or []:
        name = str(item.get("name") or "").strip()
        if not name or name in seen or name in CORE_TOOL_NAMES:
            continue
        params = item.get("parameters") if isinstance(item.get("parameters"), dict) else {}
        if not params:
            params = {"type": "object", "properties": {}}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": str(item.get("description") or name),
                    "parameters": params,
                },
            }
        )
        seen.add(name)
    return out


def allowed_from_mcps(
    skill: dict[str, Any] | None,
    enabled_mcps: list[dict[str, Any]],
) -> tuple[list[str], list[dict[str, Any]]]:
    core = list(CORE_TOOL_NAMES)
    if skill and isinstance(skill.get("tools"), list) and skill["tools"]:
        skill_core = [t for t in skill["tools"] if t in CORE_TOOL_NAMES]
        if skill_core:
            core = skill_core
    allowed = list(core)
    extras: list[dict[str, Any]] = []
    seen_extra: set[str] = set()
    for mcp in enabled_mcps:
        for name in mcp.get("tools") or []:
            n = str(name)
            if n not in allowed:
                allowed.append(n)
        if mcp.get("kind") == "remote" and not mcp.get("builtin"):
            for spec in mcp.get("tool_specs") or []:
                name = str(spec.get("name") or "")
                if name and name not in seen_extra and name not in CORE_TOOL_NAMES:
                    extras.append(spec)
                    seen_extra.add(name)
                    if name not in allowed:
                        allowed.append(name)
    return allowed, extras


async def dispatch(name: str, raw_args: Any, ctx: ToolContext) -> str:
    args = _as_dict(raw_args)
    handler = _HANDLERS.get(name)
    if handler is not None:
        return await handler(ctx, args)
    remote = next(
        (
            m
            for m in ctx.remote_mcps
            if name in (m.get("tools") or []) and m.get("url")
        ),
        None,
    )
    if remote:
        try:
            return await mcp_knowledge.call_tool_at(
                str(remote["url"]), name, args
            )
        except Exception as e:  # noqa: BLE001
            return json.dumps(
                {"error": f"MCP の呼び出しに失敗しました: {e}"},
                ensure_ascii=False,
            )
    return json.dumps({"error": f"未知のツールです: {name}"}, ensure_ascii=False)


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return {}
    return {}


async def _search_sources(ctx: ToolContext, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "query が空です"}, ensure_ascii=False)
    nodes = store.list_material_nodes(ctx.session_id, ctx.user_id)
    if nodes is None:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    picked = retrieve.select_nodes(query, nodes)
    if not picked:
        return json.dumps(
            {
                "error": "読めるソースがありません。ファイルをアップロードするか、"
                "登録済みナレッジをソースに追加してください。"
            },
            ensure_ascii=False,
        )
    material, cites = retrieve.format_material(picked)
    offset = len(ctx.citations)
    for c in cites:
        n = int(c.get("n") or 0)
        ctx.citations.append({**c, "n": offset + n})
    return material


async def _list_items(ctx: ToolContext, _args: dict[str, Any]) -> str:
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    items = [
        {
            "id": i.get("id"),
            "label": i.get("label") or "",
            "value": i.get("value") or "",
        }
        for i in detail.get("items") or []
    ]
    return json.dumps(
        {
            "items": items,
            "instruction": detail.get("instruction") or "",
            "note": "これは採用済みの項目です。対話の下書きは含まれません。",
        },
        ensure_ascii=False,
    )


def _knowledge_args(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in args.items() if k != "scope"}
    out["scope"] = ctx.scope
    return out


def _tag_names(payload: str) -> list[str]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return []

    def _from_list(items: list[Any]) -> list[str]:
        out: list[str] = []
        for item in items:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("tag") or item.get("id") or "").strip()
            else:
                name = str(item or "").strip()
            if name and name not in out:
                out.append(name)
        return out

    if isinstance(data, list):
        return _from_list(data)
    if isinstance(data, dict):
        tags = data.get("tags") or data.get("items") or data.get("tag")
        if isinstance(tags, list):
            return _from_list(tags)
        if isinstance(tags, dict):
            return [str(k).strip() for k in tags if str(k).strip()]
    return []


async def _knowledge_list_tags(ctx: ToolContext, args: dict[str, Any]) -> str:
    return await _call_knowledge("knowledge_list_tags", ctx, args)


async def _knowledge_list_docs(ctx: ToolContext, args: dict[str, Any]) -> str:
    return await _call_knowledge("knowledge_list_docs", ctx, args)


async def _knowledge_search(ctx: ToolContext, args: dict[str, Any]) -> str:
    tags = str(args.get("tags") or "").strip()
    if not tags:
        listed = await _call_knowledge("knowledge_list_tags", ctx, {})
        found = _tag_names(listed)
        if found:
            args = {**args, "tags": ",".join(found[:8])}
        else:
            return (
                listed
                + "\n\n注意: 共有ナレッジの検索にはタグが必要です。"
                "タグが一覧に無いときは、参考資料へナレッジを追加してください。"
            )
    text = await _call_knowledge("knowledge_search", ctx, args)
    extra = mcp_knowledge.citations_from_payload(text)
    if extra:
        offset = len(ctx.citations)
        for i, c in enumerate(extra, start=1):
            ctx.citations.append({**c, "n": offset + i})
    return (
        text
        + "\n\n注意: 共有ナレッジのヒットは参照です。項目の根拠にするには、"
        "人が参考資料タブから追加してください。"
    )


async def _call_knowledge(name: str, ctx: ToolContext, args: dict[str, Any]) -> str:
    if not mcp_knowledge.enabled():
        return json.dumps(
            {
                "error": "共有ナレッジ MCP は未接続です。"
                "ノートの参考資料に資料を追加してください。"
            },
            ensure_ascii=False,
        )
    if not ctx.scope:
        return json.dumps({"error": "検索スコープがありません"}, ensure_ascii=False)
    try:
        return await mcp_knowledge.call_tool(name, _knowledge_args(ctx, args))
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"error": f"共有ナレッジの検索に失敗しました: {e}"},
            ensure_ascii=False,
        )


async def _get_current_time(_ctx: ToolContext, _args: dict[str, Any]) -> str:
    return await sample_mcp.get_current_time()


async def _get_weather(_ctx: ToolContext, args: dict[str, Any]) -> str:
    city = str(args.get("city") or args.get("place") or args.get("query") or "")
    try:
        return await sample_mcp.get_weather(city)
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"error": f"天気の取得に失敗しました: {e}"},
            ensure_ascii=False,
        )


async def _wikipedia_search(_ctx: ToolContext, args: dict[str, Any]) -> str:
    query = str(args.get("query") or args.get("q") or "")
    try:
        return await sample_mcp.wikipedia_search(query)
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"error": f"Wikipedia の検索に失敗しました: {e}"},
            ensure_ascii=False,
        )


_HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], Awaitable[str]]] = {
    "search_sources": _search_sources,
    "list_items": _list_items,
    "knowledge_list_tags": _knowledge_list_tags,
    "knowledge_list_docs": _knowledge_list_docs,
    "knowledge_search": _knowledge_search,
    "get_current_time": _get_current_time,
    "get_weather": _get_weather,
    "wikipedia_search": _wikipedia_search,
    "web_search": _wikipedia_search,
}

_SPECS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_sources",
            "description": "このノートに人が追加した参考資料だけを検索する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "探したい内容（設問やキーワード）",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_items",
            "description": "人が採用済みの項目と生成指示を見る。下書きは含まない。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_list_tags",
            "description": "共有ナレッジ（共通チーム）のタグ一覧。参照用。参考資料には自動追加しない。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_list_docs",
            "description": "共有ナレッジ（共通チーム）の文書一覧。参照用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "tags": {
                        "type": "string",
                        "description": "絞り込みタグ（カンマ区切り可）",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": (
                "共有ナレッジ（共通チーム）を検索する。参照のみ。"
                "tags が分からなければ空でもよい（サーバ側でタグ一覧を使う）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索クエリ"},
                    "tags": {
                        "type": "string",
                        "description": "タグ（例: 規程）。不明なら省略可",
                    },
                    "source": {"type": "string", "description": "ファイル名で絞る"},
                    "doc_id": {"type": "string", "description": "文書IDで絞る"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "現在の日付と時刻（日本時間）。今日・今・期限の話では先に呼ぶ。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "都市の現在の天気（Open-Meteo）。都市が無ければ東京。",
            "parameters": {
                "type": "object",
                "properties": {
                    "city": {
                        "type": "string",
                        "description": "都市名（例: 東京、大阪）",
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia_search",
            "description": "日本語 Wikipedia を検索する。ウェブ全体や公式サイトは対象外。百科事典にある用語・人物向き。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索クエリ"},
                },
                "required": ["query"],
            },
        },
    },
]
