"""対話用の短い tool loop。OpenAI 互換 tools と JSON フォールバック。"""

from __future__ import annotations

import json
import re
from typing import Any

from . import llm, retrieve, store, tools

MAX_STEPS = 6
HISTORY_LIMIT = 8
MAX_ANSWER_REFS = 5
ANSWER_REF_CHARS = 4000
_ANSWER_REF = re.compile(r"\[\[回答\s*(\d+)\]\]")


def _catalog_for_prompt(
    catalog: list[dict[str, Any]],
    source_ids: list[str],
) -> list[dict[str, Any]]:
    if not source_ids:
        return catalog
    wanted = set(source_ids)
    return [s for s in catalog if str(s.get("id") or "") in wanted]


def _system_prompt(
    skill: dict[str, Any] | None,
    instruction: str,
    enabled_mcps: list[dict[str, Any]],
    *,
    source_labels: list[str],
    catalog: list[dict[str, Any]],
    designated: list[dict[str, Any]] | None = None,
) -> str:
    lines = [
        "あなたはノートの参考資料と、接続中の MCP を根拠にするアシスタントです。",
        "日本語で答えてください。参照したソースには [1] のように番号を付けてください。",
        "参考資料にも MCP にも無いことは断定せず、『資料から判断できない』と述べてください。",
        "項目（ヒアリングシートの行）は人が採用します。あなたは下書きを提案するだけです。",
        "接続中の MCP は、質問に少しでも関係があれば答える前に呼んでください。",
        "推測で日時・天気・Wikipedia にある用語を埋めないでください。",
        "参考資料だけで足りないときは、使える MCP を当たってから答えてください。",
        "共有ナレッジ MCP のヒットは参照です。項目の根拠にするには、"
        "人が参考資料タブからナレッジを追加する必要があります。",
    ]
    extra = (instruction or "").strip()
    if extra:
        lines.append(f"\n# ノートの生成指示\n{extra}")
    if enabled_mcps:
        lines.append("\n# このノートで有効な MCP")
        for mcp in enabled_mcps:
            name = str(mcp.get("name") or "").strip() or "MCP"
            prompt = str(mcp.get("prompt") or "").strip()
            tool_names = "、".join(str(t) for t in (mcp.get("tools") or []) if t)
            lines.append(f"\n## {name}")
            if tool_names:
                lines.append(f"ツール: {tool_names}")
            if prompt:
                lines.append(prompt)
    if skill:
        name = str(skill.get("name") or "").strip()
        personality = str(skill.get("personality") or "").strip()
        custom = str(skill.get("instructions") or "").strip()
        if name:
            lines.append(f"\n# AIタイプ: {name}")
        if personality:
            lines.append(f"性格: {personality}")
        if custom:
            lines.append(custom)
    lines.append("\n# この送信の資料範囲")
    if source_labels:
        lines.append("指定された資料だけを検索する: " + "、".join(source_labels))
    else:
        lines.append("未指定のため、ノートの参考資料すべてを検索する。")
    lines.append("\n# 資料と見出し")
    if not catalog:
        lines.append("参考資料はまだありません。")
    else:
        shown = catalog[:20]
        for src in shown:
            heads = [str(h).strip() for h in (src.get("outline") or []) if str(h).strip()][:8]
            head = "、".join(heads) if heads else "見出しなし"
            lines.append(f"- {src.get('name')}: {head}")
        rest = len(catalog) - len(shown)
        if rest > 0:
            lines.append(f"- ほか {rest} 件")
    lines.append(
        "資料名・節・項目のどれも質問が指しておらず、"
        "search_sources が本文を返さないときは、見出しを示してどの節かを1つだけ聞く。"
        "そのときは下書きしない。"
        "AIタイプの型で下書きするのは、見る資料と節が決まってから。"
    )
    if designated:
        lines.append("\n" + _designated_section(designated))
    return "\n".join(lines)


def answer_ref_numbers(text: str) -> list[int]:
    """質問文中の [[回答 N]] を、出てきた順・重複なしで返す。"""
    seen: list[int] = []
    for match in _ANSWER_REF.finditer(text or ""):
        n = int(match.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def numbered_assistant_answers(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """アシスタント回答を出てきた順に 1 始まりで番号付けする。空文は数えない。"""
    numbered: list[dict[str, Any]] = []
    prompt = ""
    n = 0
    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role == "user":
            if content.strip():
                prompt = content.strip()
            continue
        if role != "assistant" or not content.strip():
            continue
        n += 1
        names: list[str] = []
        cites = message.get("citations")
        if isinstance(cites, list):
            for cite in cites:
                if not isinstance(cite, dict):
                    continue
                name = str(cite.get("display_name") or "").strip()
                if name and name not in names:
                    names.append(name)
        numbered.append(
            {
                "n": n,
                "id": str(message.get("id") or ""),
                "content": content,
                "prompt": prompt,
                "sources": names[:8],
            }
        )
    return numbered


def resolve_answer_refs(
    question: str, messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    wanted = answer_ref_numbers(question)
    if not wanted:
        return [], None
    if len(wanted) > MAX_ANSWER_REFS:
        return [], "指定できる過去の回答は5件までです"
    by_n = {item["n"]: item for item in numbered_assistant_answers(messages)}
    missing = [n for n in wanted if n not in by_n]
    if missing:
        labels = "、".join(f"回答 {n}" for n in missing)
        return [], f"{labels} はこのノートにありません"
    return [by_n[n] for n in wanted], None


def _one_line(text: str, limit: int = 80) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    line = re.sub(r"\s+", " ", raw.splitlines()[0].strip())
    if len(line) <= limit:
        return line
    return line[:limit] + "…"


def _clip_answer(text: str) -> str:
    body = (text or "").strip()
    if len(body) <= ANSWER_REF_CHARS:
        return body
    return body[:ANSWER_REF_CHARS] + "\n（以下略）"


def _designated_section(answers: list[dict[str, Any]]) -> str:
    lines = [
        "# この送信で指定した過去の回答",
        "次の指示は、ここで挙げる回答を対象にする。",
        "『これ』『その回答』は、履歴全体ではなく、この番号を指す。",
        "指定が複数のときは、指示がどれかを言っていなければすべてを対象にする。",
        "指定に無い事実を、指定回答の内容であるかのように扱わない。",
    ]
    for answer in answers:
        lines.append(f"\n## 回答 {answer['n']}")
        prompt = _one_line(str(answer.get("prompt") or ""))
        if prompt:
            lines.append(f"きっかけ: {prompt}")
        sources = [str(s) for s in (answer.get("sources") or []) if str(s).strip()]
        if sources:
            lines.append("出典: " + "、".join(sources))
        lines.append(_clip_answer(str(answer.get("content") or "")))
    return "\n".join(lines)


def _history(
    messages: list[dict[str, Any]],
    designated: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_id = {
        str(item.get("id") or ""): int(item["n"])
        for item in (designated or [])
        if str(item.get("id") or "")
    }
    usable = [
        m
        for m in messages
        if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()
    ]
    clipped = usable[-HISTORY_LIMIT * 2 :]
    out: list[dict[str, Any]] = []
    for message in clipped:
        content = str(message.get("content") or "")
        mid = str(message.get("id") or "")
        if message.get("role") == "assistant" and mid in by_id:
            content = (
                f"（回答 {by_id[mid]}。全文は「この送信で指定した過去の回答」を参照）"
            )
        out.append({"role": str(message["role"]), "content": content})
    return out


def _json_objects(text: str) -> list[str]:
    """本文に埋まった JSON オブジェクトを、入れ子を含めて切り出す。"""
    out: list[str] = []
    i = 0
    n = len(text or "")
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        escape = False
        start = i
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start : j + 1])
                    i = j + 1
                    break
        else:
            break
    return out


def _parse_json_tool(text: str, allowed: list[str]) -> dict[str, Any] | None:
    for raw in _json_objects(text or ""):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("tool") or "").strip()
        if name not in allowed:
            continue
        args = data.get("arguments")
        if args is None:
            args = {k: v for k, v in data.items() if k != "tool"}
        return {"name": name, "arguments": args if isinstance(args, dict) else {}}
    return None


async def run(
    *,
    session_id: str,
    user_id: str,
    scope: str,
    question: str,
    history: list[dict[str, Any]],
    instruction: str = "",
    skill: dict[str, Any] | None = None,
    enabled_mcps: list[dict[str, Any]] | None = None,
    source_ids: list[str] | None = None,
    source_labels: list[str] | None = None,
    designated_answers: list[dict[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, str]]]:
    mcps = enabled_mcps
    if mcps is None:
        mcps = store.enabled_session_mcps(session_id, user_id)
    allowed, extra_specs = tools.allowed_from_mcps(skill, mcps)
    if not allowed:
        allowed = list(tools.CORE_TOOL_NAMES)
    scoped = [str(s).strip() for s in (source_ids or []) if str(s).strip()]
    labels = [str(s).strip() for s in (source_labels or []) if str(s).strip()]
    designated = list(designated_answers or [])
    catalog = _catalog_for_prompt(store.list_source_index(session_id, user_id) or [], scoped)
    ctx = tools.ToolContext(
        session_id=session_id,
        user_id=user_id,
        scope=scope,
        remote_mcps=[m for m in mcps if m.get("kind") == "remote" and m.get("url")],
        source_ids=scoped,
    )
    traces: list[dict[str, str]] = []
    openai_tools = tools.openai_tools(allowed, extra_specs)
    model_question = question
    notes: list[str] = []
    if labels:
        notes.append("この発言で指定した資料: " + "、".join(labels))
    if designated:
        notes.append(
            "この発言で指定した過去の回答: "
            + "、".join(f"回答 {item['n']}" for item in designated)
        )
    if notes:
        model_question = f"{question}\n\n（{'。'.join(notes)}）"
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": _system_prompt(
                skill,
                instruction,
                mcps,
                source_labels=labels,
                catalog=catalog,
                designated=designated,
            ),
        },
        *_history(history, designated),
        {"role": "user", "content": model_question},
    ]
    fallback_hint = (
        "ツールを使うときは次の JSON だけを返す。"
        '{"tool":"search_sources","arguments":{"query":"..."}}'
        " 使わないときは通常の日本語で答える。"
        " 日時・天気・Wikipedia にある用語は推測せず、使えるツールを先に呼ぶ。"
    )

    for _step in range(MAX_STEPS):
        try:
            reply = await llm.chat_completion(messages, tools=openai_tools or None)
        except Exception:  # noqa: BLE001
            reply = await llm.chat_completion(
                [
                    *messages,
                    {"role": "system", "content": fallback_hint},
                ]
            )
        tool_calls = reply.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(llm.without_meta(reply))
            for call in tool_calls:
                fn = call.get("function") if isinstance(call, dict) else None
                if not isinstance(fn, dict):
                    continue
                name = str(fn.get("name") or "")
                if name not in allowed:
                    result = json.dumps(
                        {"error": f"このノートでは {name} を使えません"},
                        ensure_ascii=False,
                    )
                else:
                    result = await tools.dispatch(name, fn.get("arguments"), ctx)
                traces.append({"name": name, "result": result[:1200]})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or name),
                        "content": result,
                    }
                )
            continue

        text = llm.message_text(reply)
        parsed = _parse_json_tool(text, allowed)
        if parsed:
            result = await tools.dispatch(parsed["name"], parsed["arguments"], ctx)
            traces.append({"name": parsed["name"], "result": result[:1200]})
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"# ツール結果\n{result}"})
            continue

        if not text.strip():
            raise ValueError("モデルの応答本文が空です")
        text = await llm.continue_if_length(messages, reply)
        cites = retrieve.filter_used_citations(text, ctx.citations)
        return text, cites, traces

    raise ValueError("ツール実行の上限に達しました。質問を短くしてやり直してください。")
