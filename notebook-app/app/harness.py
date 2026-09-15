"""対話用の短い tool loop。OpenAI 互換 tools と JSON フォールバック。"""

from __future__ import annotations

import json
from typing import Any

from . import llm, retrieve, store, tools

MAX_STEPS = 6
HISTORY_LIMIT = 8


def _system_prompt(
    skill: dict[str, Any] | None,
    instruction: str,
    enabled_mcps: list[dict[str, Any]],
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
    return "\n".join(lines)


def _history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    usable = [
        m
        for m in messages
        if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()
    ]
    clipped = usable[-HISTORY_LIMIT * 2 :]
    return [
        {"role": str(m["role"]), "content": str(m.get("content") or "")} for m in clipped
    ]


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
) -> tuple[str, list[dict[str, Any]], list[dict[str, str]]]:
    mcps = enabled_mcps
    if mcps is None:
        mcps = store.enabled_session_mcps(session_id, user_id)
    allowed, extra_specs = tools.allowed_from_mcps(skill, mcps)
    if not allowed:
        allowed = list(tools.CORE_TOOL_NAMES)
    ctx = tools.ToolContext(
        session_id=session_id,
        user_id=user_id,
        scope=scope,
        remote_mcps=[m for m in mcps if m.get("kind") == "remote" and m.get("url")],
    )
    traces: list[dict[str, str]] = []
    openai_tools = tools.openai_tools(allowed, extra_specs)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(skill, instruction, mcps)},
        *_history(history),
        {"role": "user", "content": question},
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
