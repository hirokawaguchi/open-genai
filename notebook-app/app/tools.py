"""ハーネスが呼んでよいツール。項目の確定はしない。"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

from . import firecrawl, mcp_catalog, mcp_knowledge, retrieve, sample_mcp, schedule, store

# 対話が自分で項目を書き、揃ったらエディタへ渡す。
FLOW_TOOLS = (
    "set_goal",
    "commit_items",
    "ask_user",
    "write_manuscript",
    "fact_check",
    "revise_manuscript",
    "deliver",
    "open_draft",
    "write_office_draft",
    "propose_schedule",
)
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


def _manuscript_of(detail: dict[str, Any]) -> dict[str, Any]:
    raw = detail.get("manuscript")
    return raw if isinstance(raw, dict) else {}


def _chapters(args: dict[str, Any]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for chapter in args.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        label = str(chapter.get("label") or "").strip()
        value = str(chapter.get("value") or "").strip()
        if label and value:
            out.append({"label": label, "value": value})
    return out


def _form_name(raw: str) -> str:
    text = raw.strip()
    if text in ("document", "文書"):
        return "document"
    if text in ("slides", "スライド"):
        return "slides"
    return ""


def _editor_payload(detail: dict[str, Any]) -> dict[str, Any]:
    project_id = str(detail.get("editor_project_id") or "").strip()
    return {
        "open_editor": True,
        "instruction": str(detail.get("instruction") or "").strip(),
        "mode": "existing" if project_id else "new",
        "name": detail.get("title") or "",
        "project_id": project_id,
    }


async def _write_manuscript(ctx: ToolContext, args: dict[str, Any]) -> str:
    """クリップを優先した原稿を、クリップとは別の章として残す。"""
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    if not str(detail.get("instruction") or "").strip():
        return json.dumps(
            {"error": "ゴールがまだありません。先に set_goal を呼んでください。"},
            ensure_ascii=False,
        )
    form = _form_name(str(args.get("form") or ""))
    if not form:
        return json.dumps(
            {"error": "文書かスライドかを form に指定してください。"},
            ensure_ascii=False,
        )
    chapters = _chapters(args)
    if not chapters:
        return json.dumps(
            {"error": "見出しと本文のある章がありません。"},
            ensure_ascii=False,
        )
    saved = store.save_manuscript(
        ctx.session_id,
        ctx.user_id,
        {
            "form": form,
            "chapters": chapters,
            "fact": "",
            "revised": False,
            "findings": [],
        },
    )
    if not saved:
        return json.dumps({"error": "原稿を書けませんでした。"}, ensure_ascii=False)
    return json.dumps(
        {"written": [chapter["label"] for chapter in chapters], "form": form},
        ensure_ascii=False,
    )


async def _fact_check(ctx: ToolContext, args: dict[str, Any]) -> str:
    """原稿の主張を記録する。食い違えばその文を返してターンを止める。"""
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    manuscript = _manuscript_of(detail)
    if not manuscript.get("chapters"):
        return json.dumps(
            {"error": "原稿がまだありません。先に write_manuscript を呼んでください。"},
            ensure_ascii=False,
        )
    findings: list[dict[str, str]] = []
    for item in args.get("findings") or []:
        if not isinstance(item, dict):
            continue
        claim = str(item.get("claim") or "").strip()
        status = str(item.get("status") or "").strip()
        note = str(item.get("note") or "").strip()
        if not claim or status not in ("supported", "missing", "contradicted"):
            continue
        findings.append({"claim": claim, "status": status, "note": note})
    if not findings:
        return json.dumps(
            {"error": "主張と、supported、missing、contradicted のどれかが必要です。"},
            ensure_ascii=False,
        )
    held = [item for item in findings if item["status"] != "supported"]
    saved = store.save_manuscript(
        ctx.session_id,
        ctx.user_id,
        {
            "form": manuscript.get("form") or "",
            "chapters": manuscript.get("chapters") or [],
            "fact": "hold" if held else "clean",
            "revised": False,
            "findings": findings,
        },
    )
    if not saved:
        return json.dumps({"error": "確認結果を残せませんでした。"}, ensure_ascii=False)
    if not held:
        labels = [str(chapter.get("label") or "") for chapter in manuscript.get("chapters") or []]
        return json.dumps({"fact": "clean", "headings": labels}, ensure_ascii=False)
    lines = ["資料と食い違う箇所があります。"]
    for item in held:
        label = "資料に無い" if item["status"] == "missing" else "資料と違う"
        extra = f"（{item['note']}）" if item["note"] else ""
        lines.append(f"- {label}: {item['claim']}{extra}")
    lines.append("直すか、このまま書き出すか、選んでください。")
    ctx.ask_text = "\n".join(lines)
    return json.dumps({"fact": "hold", "stopped": True}, ensure_ascii=False)


async def _revise_manuscript(ctx: ToolContext, args: dict[str, Any]) -> str:
    """見出しは保ったまま、言い回しと章の形だけを差し替える。"""
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    manuscript = _manuscript_of(detail)
    current = manuscript.get("chapters") or []
    if not current:
        return json.dumps(
            {"error": "原稿がまだありません。先に write_manuscript を呼んでください。"},
            ensure_ascii=False,
        )
    if manuscript.get("fact") != "clean":
        return json.dumps(
            {"error": "事実が合うと確認できてから、言い回しを整えてください。"},
            ensure_ascii=False,
        )
    chapters = _chapters(args)
    labels = [chapter["label"] for chapter in current]
    if [chapter["label"] for chapter in chapters] != labels:
        return json.dumps(
            {
                "error": "見出しは変えず、足さず、削らず、言い回しだけ変えてください。",
                "headings": labels,
            },
            ensure_ascii=False,
        )
    saved = store.save_manuscript(
        ctx.session_id,
        ctx.user_id,
        {
            "form": manuscript.get("form") or "",
            "chapters": chapters,
            "fact": "clean",
            "revised": True,
            "findings": manuscript.get("findings") or [],
        },
    )
    if not saved:
        return json.dumps({"error": "原稿を整えられませんでした。"}, ensure_ascii=False)
    return json.dumps({"revised": labels}, ensure_ascii=False)


async def _deliver(ctx: ToolContext, _args: dict[str, Any]) -> str:
    """事実が合い、言い回しを整えた原稿をプロジェクトへ書き出す。画面は開かない。"""
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    goal = str(detail.get("instruction") or "").strip()
    if not goal:
        return json.dumps(
            {"error": "ゴールがまだありません。先に set_goal を呼んでください。"},
            ensure_ascii=False,
        )
    manuscript = _manuscript_of(detail)
    if not manuscript.get("chapters"):
        return json.dumps(
            {"error": "原稿がまだありません。先に write_manuscript を呼んでください。"},
            ensure_ascii=False,
        )
    if manuscript.get("fact") == "hold":
        return json.dumps(
            {"error": "資料と食い違っています。直すか、このまま書き出すかを選んでください。"},
            ensure_ascii=False,
        )
    if manuscript.get("fact") != "clean" or not manuscript.get("revised"):
        return json.dumps(
            {"error": "事実を確かめ、言い回しを整えてから開いてください。"},
            ensure_ascii=False,
        )
    ctx.open_editor = True
    _queue_composed_file(ctx, detail)
    return json.dumps(_editor_payload(detail), ensure_ascii=False)


async def _open_draft(ctx: ToolContext, _args: dict[str, Any]) -> str:
    """人がこのまま書き出すと選んだ原稿を、推敲せずプロジェクトへ書き出す。"""
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    manuscript = _manuscript_of(detail)
    if not manuscript.get("chapters"):
        return json.dumps({"error": "原稿がまだありません。"}, ensure_ascii=False)
    if manuscript.get("fact") not in ("hold", "clean"):
        return json.dumps(
            {"error": "先に事実を確かめてください。"},
            ensure_ascii=False,
        )
    ctx.open_editor = True
    _queue_composed_file(ctx, detail)
    return json.dumps(_editor_payload(detail), ensure_ascii=False)


def _queue_composed_file(ctx: ToolContext, detail: dict[str, Any]) -> None:
    """書き出した原稿を、画面が合成して台帳の下書きへ置く合図にする。"""
    form = str(_manuscript_of(detail).get("form") or "")
    kind = "pptx" if form == "slides" else "docx" if form == "document" else ""
    if not kind:
        return
    store.update_session(
        ctx.session_id, ctx.user_id, slide_compose=kind, office_file="", office_ref=""
    )


def _ledger_url() -> str:
    return os.environ.get("LEDGER_URL", "").strip().rstrip("/")


def _office_ext(raw: str, form: str) -> str:
    text = raw.strip().lower()
    if text in ("pptx", "スライド"):
        return "pptx"
    if text in ("xlsx", "表"):
        return "xlsx"
    if text in ("docx", "文書"):
        return "docx"
    return "pptx" if form == "slides" else "docx"


def _office_filename(title: str, ext: str) -> str:
    kind = {"pptx": "スライド", "xlsx": "表", "docx": "文書"}.get(ext, "文書")
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', " ", title or "")
    stem = re.sub(r"\s+", " ", stem).strip(" .")[:40] or "原稿"
    return f"{stem}-{kind}.{ext}"


def is_office_package(data: bytes) -> bool:
    """中身のある Office ファイルか。空の ZIP は受け取らない。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as package:
            return "[Content_Types].xml" in package.namelist()
    except zipfile.BadZipFile:
        return False


def _chapter_lines(value: str) -> list[str]:
    lines: list[str] = []
    for raw in (value or "").splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ")):
            line = line[2:].strip()
        if line:
            lines.append(line)
    return lines


def office_bytes(chapters: list[dict[str, str]], ext: str) -> bytes:
    """原稿の章から、文書・表・スライドのファイルを作る。"""
    buf = io.BytesIO()
    if ext == "pptx":
        from pptx import Presentation

        deck = Presentation()
        layout = deck.slide_layouts[1] if len(deck.slide_layouts) > 1 else deck.slide_layouts[0]
        for chapter in chapters:
            slide = deck.slides.add_slide(layout)
            slide.shapes.title.text = chapter["label"]
            lines = _chapter_lines(chapter["value"])
            frame = slide.placeholders[1].text_frame
            frame.text = lines[0] if lines else ""
            for line in lines[1:]:
                frame.add_paragraph().text = line
        deck.save(buf)
    elif ext == "xlsx":
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.title = "原稿"
        sheet.append(["見出し", "本文"])
        for chapter in chapters:
            sheet.append([chapter["label"], chapter["value"]])
        book.save(buf)
    else:
        from docx import Document

        doc = Document()
        for chapter in chapters:
            doc.add_heading(chapter["label"], level=1)
            lines = _chapter_lines(chapter["value"])
            if not lines:
                doc.add_paragraph("")
            for line in lines:
                doc.add_paragraph(line)
        doc.save(buf)
    return buf.getvalue()


async def _write_office_draft(ctx: ToolContext, args: dict[str, Any]) -> str:
    """今の原稿から文書台帳の下書きを作る。確定と削除はしない。"""
    store.update_session(ctx.session_id, ctx.user_id, office_file="", office_ref="")
    if args.get("status") or args.get("delete") or args.get("finalize"):
        return json.dumps(
            {"error": "確定と削除はできません。下書きのファイルだけ書けます。"},
            ensure_ascii=False,
        )
    detail = store.get_session(ctx.session_id, ctx.user_id)
    if not detail:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    manuscript = _manuscript_of(detail)
    chapters = [
        {"label": str(chapter.get("label") or ""), "value": str(chapter.get("value") or "")}
        for chapter in (manuscript.get("chapters") or [])
        if isinstance(chapter, dict)
    ]
    raw_b64 = str(args.get("content_base64") or "").strip()
    ext = _office_ext(str(args.get("format") or ""), str(manuscript.get("form") or ""))
    if ext in ("pptx", "docx") and not raw_b64:
        if not chapters:
            return json.dumps(
                {"error": "原稿がまだありません。先に原稿を書いてください。"},
                ensure_ascii=False,
            )
        store.update_session(ctx.session_id, ctx.user_id, slide_compose=ext)
        return json.dumps({"compose": ext, "open": "office"}, ensure_ascii=False)
    store.update_session(ctx.session_id, ctx.user_id, slide_compose="")
    filename = str(args.get("filename") or "").strip()
    if filename and not filename.lower().endswith((".docx", ".xlsx", ".pptx")):
        return json.dumps(
            {"error": "文書、表計算、スライドのファイルだけ書けます。"},
            ensure_ascii=False,
        )
    if raw_b64:
        try:
            data = base64.b64decode(raw_b64, validate=True)
        except Exception:  # noqa: BLE001
            return json.dumps({"error": "ファイルの中身を読めませんでした。"}, ensure_ascii=False)
        if not filename:
            filename = _office_filename(str(detail.get("title") or ""), ext)
    else:
        if not chapters:
            return json.dumps(
                {"error": "原稿がまだありません。先に原稿を書いてください。"},
                ensure_ascii=False,
            )
        try:
            data = office_bytes(chapters, ext)
        except Exception as e:  # noqa: BLE001
            return json.dumps(
                {"error": f"ファイルを作れませんでした。{e}"},
                ensure_ascii=False,
            )
        if not filename:
            filename = _office_filename(str(detail.get("title") or ""), ext)
    base = _ledger_url()
    if not base:
        return json.dumps(
            {"error": "台帳が止まっています。ファイルは置けません。"},
            ensure_ascii=False,
        )
    if not is_office_package(data):
        return json.dumps(
            {"error": "ファイルの中身が文書になっていません。保存していません。"},
            ensure_ascii=False,
        )
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
    store.update_session(ctx.session_id, ctx.user_id, office_file=filename)
    return json.dumps(
        {"saved": filename, "draft": True, "ledger": "文書"},
        ensure_ascii=False,
    )


async def _propose_schedule(ctx: ToolContext, args: dict[str, Any]) -> str:
    """候補をノートに置く。案件の作成と招待はしない。"""
    if any(args.get(key) for key in ("invite", "send_invite", "delete", "event_password")):
        return json.dumps(
            {"error": "招待、暗証番号、削除はできません。候補を出すだけです。"},
            ensure_ascii=False,
        )
    built, err = schedule.proposal(
        str(args.get("title") or ""),
        str(args.get("description") or ""),
        args.get("dates"),
    )
    if err or built is None:
        return json.dumps(
            {"error": err or "候補を出せません。"},
            ensure_ascii=False,
        )
    saved = store.set_schedule(ctx.session_id, ctx.user_id, built)
    if not saved:
        return json.dumps({"error": "ノートが見つかりません"}, ensure_ascii=False)
    return json.dumps(
        {
            "proposed": True,
            "title": built["title"],
            "dates": built["dates"],
        },
        ensure_ascii=False,
    )


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
                + "\n\n共有ナレッジにはタグがありません。"
                "登録を求めず、ノートの参考資料を調べて答えてください。"
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
    "write_manuscript": _write_manuscript,
    "fact_check": _fact_check,
    "revise_manuscript": _revise_manuscript,
    "deliver": _deliver,
    "open_draft": _open_draft,
    "write_office_draft": _write_office_draft,
    "propose_schedule": _propose_schedule,
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
            "name": "write_manuscript",
            "description": "クリップの文を優先した原稿を、クリップとは別に一度書く。文書は見出しと段落、スライドは見出しごとの短い箇条書き。",
            "parameters": {
                "type": "object",
                "properties": {
                    "form": {
                        "type": "string",
                        "enum": ["document", "slides"],
                    },
                    "chapters": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "value": {"type": "string"},
                            },
                            "required": ["label", "value"],
                        },
                    },
                },
                "required": ["form", "chapters"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fact_check",
            "description": "原稿の主張が資料と合うかを記録する。食い違うか資料に無い断定があれば、そこで止まり人に選ばせる。原稿は書き換えない。",
            "parameters": {
                "type": "object",
                "properties": {
                    "findings": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "claim": {"type": "string"},
                                "status": {
                                    "type": "string",
                                    "enum": ["supported", "missing", "contradicted"],
                                },
                                "note": {"type": "string"},
                            },
                            "required": ["claim", "status"],
                        },
                    }
                },
                "required": ["findings"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "revise_manuscript",
            "description": "事実が合った原稿の言い回しと章の形だけを整える。見出しは変えず足さず、新しい事実も足さない。",
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
            "name": "deliver",
            "description": "事実が合い、言い回しを整えた原稿を Markdown エディタのプロジェクトへ書き出す。画面は開かない。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "open_draft",
            "description": "人がこのまま書き出すと選んだときだけ、推敲せず原稿をプロジェクトへ書き出す。画面は開かない。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_office_draft",
            "description": "原稿を書き出したあとに呼ぶ。画面が文書は docx、スライドは見出しどおりの pptx を文書台帳の下書きに置く。中身は渡さない。置いたかどうかは画面が案内する。",
            "parameters": {
                "type": "object",
                "properties": {
                    "format": {"type": "string", "description": "docx または pptx。省略すると原稿の形に合わせる。"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_schedule",
            "description": (
                "日程調整の候補を画面に出す。タイトルと候補日が決まっているときだけ呼ぶ。"
                "案件は作らず、招待も送らない。日付が曖昧なら呼ばず、一度だけ聞いて止まる。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "案件のタイトル。80文字まで。"},
                    "description": {"type": "string", "description": "参加者に見せる説明。空でもよい。"},
                    "dates": {
                        "type": "array",
                        "description": "候補日。YYYY-MM-DD は終日、YYYY-MM-DDTHH:MM は時刻あり。",
                        "items": {"type": "string"},
                    },
                },
                "required": ["title", "dates"],
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
