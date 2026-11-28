"""ハーネスが呼んでよいツール。項目の確定はしない。"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from . import firecrawl, mcp_catalog, mcp_knowledge, retrieve, sample_mcp, store

# 対話が自分で項目を書き、揃ったらエディタへ渡す。
FLOW_TOOLS = ("set_goal", "commit_items", "ask_user", "deliver", "write_office_draft")
_CITE_NUM = re.compile(r"\[(\d+)\]")

CORE_TOOL_NAMES = mcp_catalog.CORE_TOOLS
BUILTIN_MCP_TOOLS = (
    "knowledge_list_tags",
    "knowledge_list_docs",
    "knowledge_search",
    "get_current_time",
    "get_weather",
    "wikipedia_search",
    "web_search",
    "firecrawl_search",
    "firecrawl_scrape",
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
    source_ids: list[str] = field(default_factory=list)
    drafts: list[dict[str, Any]] = field(default_factory=list)
    open_editor: bool = False
    ask_text: str = ""
    forward_headers: dict[str, str] = field(default_factory=dict)


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
    for name in FLOW_TOOLS:
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


def _miss_outline(nodes: list[dict[str, Any]]) -> str:
    """節に当たらないとき。本文は返さず、見出しだけを渡す。"""
    return json.dumps(
        {
            "matched": False,
            "note": (
                "本文は返していません。見出しを示して、どの節かを1つ聞いてください。"
                "下書きはしないでください。"
            ),
            "sources": store.source_outline(nodes),
        },
        ensure_ascii=False,
    )


async def _search_sources(ctx: ToolContext, args: dict[str, Any]) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return json.dumps({"error": "query が空です"}, ensure_ascii=False)
    nodes = store.list_material_nodes(
        ctx.session_id,
        ctx.user_id,
        source_ids=ctx.source_ids or None,
    )
    if nodes is None:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    readable = [n for n in nodes if str(n.get("text") or "").strip()]
    if not readable:
        return json.dumps(
            {
                "error": "読めるソースがありません。ファイルをアップロードするか、"
                "登録済みナレッジをソースに追加してください。"
            },
            ensure_ascii=False,
        )
    picked = retrieve.select_nodes(query, readable, unmatched_fallback=False)
    if not picked:
        return _miss_outline(readable)
    material, cites = retrieve.format_material(picked)
    offset = len(ctx.citations)
    for c in cites:
        n = int(c.get("n") or 0)
        ctx.citations.append({**c, "n": offset + n})
    return material


def _citation_numbers(raw: Any, text: str) -> list[int]:
    found: list[int] = []

    def add(value: Any) -> None:
        try:
            n = int(value)
        except (TypeError, ValueError):
            return
        if n > 0 and n not in found:
            found.append(n)

    if isinstance(raw, list):
        for item in raw:
            add(item)
    elif isinstance(raw, (int, str)) and str(raw).strip():
        for part in re.split(r"[,、\s]+", str(raw).strip()):
            add(part)
    if not found:
        for match in _CITE_NUM.finditer(text or ""):
            add(match.group(1))
    return found


async def _set_goal(ctx: ToolContext, args: dict[str, Any]) -> str:
    """対話で決まった一文を、画面に出さないゴールとして残す。"""
    goal = str(args.get("goal") or "").strip()
    if not goal:
        return json.dumps({"error": "ゴールの文が空です。"}, ensure_ascii=False)
    if len(goal) > 4000:
        return json.dumps({"error": "ゴールは4000字以内にしてください。"}, ensure_ascii=False)
    detail = store.update_session(ctx.session_id, ctx.user_id, instruction=goal)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    return json.dumps(
        {"goal": goal, "note": "この文が、エディタへ渡す生成指示です。別の文は作りません。"},
        ensure_ascii=False,
    )


async def _commit_items(ctx: ToolContext, args: dict[str, Any]) -> str:
    """見出しごとに項目へ書く。ゴールが無いあいだは書かない。"""
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    if not str(detail.get("instruction") or "").strip():
        return json.dumps(
            {"error": "ゴールがまだありません。先に set_goal を呼んでください。"},
            ensure_ascii=False,
        )
    raw = args.get("chapters")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = []
    if not isinstance(raw, list) or not raw:
        return json.dumps(
            {"error": "chapters に、見出しと本文の配列を渡してください。"},
            ensure_ascii=False,
        )
    by_n = {int(c.get("n") or 0): c for c in ctx.citations if c.get("n")}
    written: list[str] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or item.get("heading") or "").strip()[:200]
        value = str(item.get("value") or item.get("body") or "").strip()
        if not label or not value:
            continue
        cites = []
        for n in _citation_numbers(item.get("citations"), value):
            src = by_n.get(n)
            if src and src not in cites:
                cites.append(src)
        if not store.upsert_labeled_item(
            ctx.session_id,
            ctx.user_id,
            label=label,
            value=value,
            citations=cites,
        ):
            return json.dumps({"error": "項目を書けませんでした。"}, ensure_ascii=False)
        written.append(label)
    if not written:
        return json.dumps(
            {"error": "見出しと本文が揃った章がありません。"},
            ensure_ascii=False,
        )
    return json.dumps({"written": written}, ensure_ascii=False)


async def _ask_user(ctx: ToolContext, args: dict[str, Any]) -> str:
    question = str(args.get("question") or "").strip()
    if not question:
        return json.dumps({"error": "質問が空です。"}, ensure_ascii=False)
    ctx.ask_text = question
    return json.dumps({"stopped": True}, ensure_ascii=False)


def _filled_items(detail: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for item in detail.get("items") or []:
        if str(item.get("label") or "").strip() and str(item.get("value") or "").strip():
            out.append(item)
    return out


async def _deliver(ctx: ToolContext, _args: dict[str, Any]) -> str:
    """ゴールの文を生成指示として、エディタ引き渡しの合図を出す。"""
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    goal = str(detail.get("instruction") or "").strip()
    if not goal:
        return json.dumps(
            {"error": "ゴールがまだありません。先に set_goal を呼んでください。"},
            ensure_ascii=False,
        )
    filled = _filled_items(detail)
    if not filled:
        return json.dumps(
            {"error": "見出しと本文のある項目がありません。先に commit_items を呼んでください。"},
            ensure_ascii=False,
        )
    project_id = str(detail.get("editor_project_id") or "").strip()
    ctx.open_editor = True
    mode = "existing" if project_id else "new"
    return json.dumps(
        {
            "open_editor": True,
            "instruction": goal,
            "mode": mode,
            "name": detail.get("title") or "",
            "project_id": project_id,
        },
        ensure_ascii=False,
    )


def _ledger_url() -> str:
    return os.environ.get("LEDGER_URL", "").strip().rstrip("/")


async def _write_office_draft(ctx: ToolContext, args: dict[str, Any]) -> str:
    """文書台帳へ下書きの本体を書く。確定と削除はしない。"""
    if args.get("status") or args.get("delete") or args.get("finalize"):
        return json.dumps(
            {"error": "確定と削除はできません。下書きのファイルだけ書けます。"},
            ensure_ascii=False,
        )
    filename = str(args.get("filename") or "").strip()
    if not filename.lower().endswith((".docx", ".xlsx", ".pptx")):
        return json.dumps(
            {"error": "文書、表計算、スライドのファイルだけ書けます。"},
            ensure_ascii=False,
        )
    raw_b64 = str(args.get("content_base64") or "").strip()
    if not raw_b64:
        return json.dumps({"error": "ファイルの中身がありません。"}, ensure_ascii=False)
    base = _ledger_url()
    if not base:
        return json.dumps(
            {"error": "台帳が止まっています。ファイルは置けません。"},
            ensure_ascii=False,
        )
    try:
        data = base64.b64decode(raw_b64, validate=True)
    except Exception:  # noqa: BLE001
        return json.dumps({"error": "ファイルの中身を読めませんでした。"}, ensure_ascii=False)
    if not data:
        return json.dumps({"error": "ファイルが空です。"}, ensure_ascii=False)
    headers = {
        k: v
        for k, v in (ctx.forward_headers or {}).items()
        if k.lower().startswith("x-")
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.put(
                f"{base}/office/files",
                params={"name": filename},
                content=data,
                headers=headers,
            )
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"error": f"台帳が止まっています。ファイルは置けません。{e}"},
            ensure_ascii=False,
        )
    if res.status_code >= 400:
        return json.dumps(
            {"error": "台帳へ書けませんでした。確定や削除はしていません。"},
            ensure_ascii=False,
        )
    return json.dumps({"saved": filename, "draft": True}, ensure_ascii=False)


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
            "note": "項目と、対話で決まったゴールです。ゴールは画面の欄ではありません。",
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
            args = {**args, "tags": ",".join(found)}
        else:
            return (
                listed
                + "\n\n注意: 共有ナレッジの検索にはタグが必要です。"
                "タグが一覧に無いときは、検索できません。"
            )
    text = await _call_knowledge("knowledge_search", ctx, args)
    extra = mcp_knowledge.citations_from_payload(text)
    if extra:
        offset = len(ctx.citations)
        for i, c in enumerate(extra, start=1):
            ctx.citations.append({**c, "n": offset + i})
    return text


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


async def _firecrawl_search(_ctx: ToolContext, args: dict[str, Any]) -> str:
    query = str(args.get("query") or args.get("q") or "")
    try:
        limit = int(args.get("limit") or firecrawl.DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = firecrawl.DEFAULT_LIMIT
    try:
        return await firecrawl.search(query, limit)
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"error": f"Web 検索に失敗しました: {e}"},
            ensure_ascii=False,
        )


async def _firecrawl_scrape(_ctx: ToolContext, args: dict[str, Any]) -> str:
    url = str(args.get("url") or args.get("link") or "")
    try:
        return await firecrawl.scrape(url)
    except Exception as e:  # noqa: BLE001
        return json.dumps(
            {"error": f"ページの取得に失敗しました: {e}"},
            ensure_ascii=False,
        )


_HANDLERS: dict[str, Callable[[ToolContext, dict[str, Any]], Awaitable[str]]] = {
    "search_sources": _search_sources,
    "list_items": _list_items,
    "set_goal": _set_goal,
    "commit_items": _commit_items,
    "ask_user": _ask_user,
    "deliver": _deliver,
    "write_office_draft": _write_office_draft,
    "knowledge_list_tags": _knowledge_list_tags,
    "knowledge_list_docs": _knowledge_list_docs,
    "knowledge_search": _knowledge_search,
    "get_current_time": _get_current_time,
    "get_weather": _get_weather,
    "wikipedia_search": _wikipedia_search,
    "web_search": _wikipedia_search,
    "firecrawl_search": _firecrawl_search,
    "firecrawl_scrape": _firecrawl_scrape,
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
            "description": "このノートの項目と、対話で決まったゴールを見る。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_goal",
            "description": "対話で決まった一文をゴールとして残す。この文が生成指示になる。画面の欄にはしない。",
            "parameters": {
                "type": "object",
                "properties": {"goal": {"type": "string"}},
                "required": ["goal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "commit_items",
            "description": "見出しと本文を項目へ書く。ゴールが決まってから呼ぶ。節の選び方は自分で決める。",
            "parameters": {
                "type": "object",
                "properties": {
                    "chapters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                                "citations": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                },
                            },
                            "required": ["label", "value"],
                        },
                    }
                },
                "required": ["chapters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": "資料の矛盾か、ゴールに必要な事実が資料に無いときだけ、一つ聞いて止める。",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deliver",
            "description": "項目が揃ったら、ゴールの文を生成指示として Markdown エディタへ渡す。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_office_draft",
            "description": "docx、xlsx、pptx を文書台帳の下書きとして書く。確定と削除はできない。台帳が止まっていれば書かない。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {"type": "string"},
                    "content_base64": {"type": "string"},
                },
                "required": ["filename", "content_base64"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_list_tags",
            "description": "共有ナレッジ（共通チーム）のタグ一覧。On のあいだ、これらの資料は対話の対象です。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_list_docs",
            "description": "共有ナレッジ（共通チーム）の文書一覧。On のあいだ、これらの資料は対話の対象です。",
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
                "共有ナレッジ（共通チーム）を検索する。On のあいだ、ヒットは対話の根拠に使える。"
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
    {
        "type": "function",
        "function": {
            "name": "firecrawl_search",
            "description": (
                "Firecrawl でウェブ全体を検索する。最新の動向や公式サイトなど、"
                "ナレッジや Wikipedia で足りないとき向き。検索クエリは外部へ出る。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "検索クエリ"},
                    "limit": {
                        "type": "integer",
                        "description": "取得する件数（既定5、最大8）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "firecrawl_scrape",
            "description": (
                "指定した URL の本文を Markdown で取得する。"
                "検索結果だけでは足りないとき、その URL を渡して読む。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "取得するページの URL"},
                },
                "required": ["url"],
            },
        },
    },
]
