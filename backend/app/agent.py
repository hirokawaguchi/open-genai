"""手順書と有限回のツール実行の実験。製品の入口にはしない。

計画の正本は docs/agent.md。エージェントの画面はノートブックの対話で、
このモジュールから別チャットは作らない。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

MAX_STEPS = 8
HISTORY_LIMIT = 8
RESULT_CHARS = 6000
TRACE_CHARS = 1200
_NAME_RE = re.compile(r"^[A-Za-z0-9_\-\u3040-\u30ff\u4e00-\u9fff]{1,80}$")
_TOOL_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_ALLOWED_KEYS = frozenset({"name", "description", "tools"})

Complete = Callable[
    [list[dict[str, Any]], list[dict[str, Any]]],
    Awaitable[dict[str, Any]],
]
ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


class AgentSkillError(ValueError):
    """手順書の形式、または手順書とツール一覧の不一致。"""


class AgentLimitError(ValueError):
    """モデル呼び出しが上限に達し、本文が返らなかった。"""

    def __init__(self, message: str, steps: list[Step]) -> None:
        super().__init__(message)
        self.steps = steps


@dataclass(frozen=True)
class Skill:
    """SKILL.md 1 件。tools が None のときは実行側の一覧をそのまま使う。"""

    name: str
    description: str
    instructions: str
    tools: tuple[str, ...] | None = None


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler


@dataclass(frozen=True)
class Step:
    name: str
    ok: bool
    result: str


@dataclass(frozen=True)
class AgentResult:
    answer: str
    steps: tuple[Step, ...]
    skill_name: str


def parse_skill(text: str) -> Skill:
    """SKILL.md を読む。名前と本文は必須。"""
    raw = (text or "").replace("\r\n", "\n").strip()
    matched = _FRONTMATTER.match(raw)
    if not matched:
        raise AgentSkillError("SKILL.md は先頭の --- で始めてください")
    meta = _parse_frontmatter(matched.group(1))
    unknown = sorted(set(meta) - _ALLOWED_KEYS)
    if unknown:
        raise AgentSkillError("使えない項目です: " + "、".join(unknown))
    name = meta.get("name")
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise AgentSkillError("name は1行の短い名前にしてください")
    description = meta.get("description", "")
    if not isinstance(description, str):
        raise AgentSkillError("description は1行の文字列にしてください")
    description = description.strip()
    if len(description) > 400:
        raise AgentSkillError("description は400字以内にしてください")
    tools = _parse_tools(meta.get("tools"))
    instructions = matched.group(2).strip()
    if not instructions:
        raise AgentSkillError("手順の本文が空です")
    if len(instructions) > 20000:
        raise AgentSkillError("手順の本文は20000字以内にしてください")
    return Skill(
        name=name,
        description=description,
        instructions=instructions,
        tools=tools,
    )


def bind_tools(skill: Skill | None, tools: list[Tool]) -> list[Tool]:
    """手順書が名指ししたツールだけを残す。一覧に無い名前は拒否する。"""
    names = [tool.name for tool in tools]
    if len(names) != len(set(names)):
        raise AgentSkillError("ツール名が重複しています")
    for tool in tools:
        if not _TOOL_RE.match(tool.name):
            raise AgentSkillError(f"ツール名の形式が違います: {tool.name}")
    if skill is None or skill.tools is None:
        return list(tools)
    missing = [name for name in skill.tools if name not in set(names)]
    if missing:
        raise AgentSkillError(
            "スキルが許可されていないツールを指定しています: " + "、".join(missing)
        )
    by_name = {tool.name: tool for tool in tools}
    return [by_name[name] for name in skill.tools]


async def run(
    *,
    goal: str,
    complete: Complete,
    tools: list[Tool],
    skill: Skill | None = None,
    history: list[dict[str, Any]] | None = None,
    max_steps: int = MAX_STEPS,
) -> AgentResult:
    """依頼を受け、ツールを挟みながら本文が出るまでモデルを呼ぶ。"""
    question = (goal or "").strip()
    if not question:
        raise AgentSkillError("依頼が空です")
    if max_steps < 1:
        raise AgentSkillError("実行回数は1以上にしてください")
    allowed = bind_tools(skill, tools)
    allowed_names = [tool.name for tool in allowed]
    specs = openai_tools(allowed)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(skill, allowed_names)},
        *_history(history),
        {"role": "user", "content": question},
    ]
    steps: list[Step] = []
    for _ in range(max_steps):
        reply = await complete(messages, specs)
        tool_calls = reply.get("tool_calls") if isinstance(reply, dict) else None
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(_assistant_tool_message(reply, tool_calls))
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                step, tool_message = await _run_call(call, allowed)
                steps.append(step)
                messages.append(tool_message)
            continue
        text = _message_text(reply)
        parsed = _parse_json_tool(text, allowed_names)
        if parsed:
            step, result = await _invoke(parsed["name"], parsed["arguments"], allowed)
            steps.append(step)
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"# ツール結果\n{result}"})
            continue
        if not text.strip():
            raise ValueError("モデルの応答本文が空です")
        return AgentResult(
            answer=text.strip(),
            steps=tuple(steps),
            skill_name=skill.name if skill else "",
        )
    raise AgentLimitError("ツール実行の上限に達しました。依頼を短くしてやり直してください。", steps)


def openai_tools(tools: list[Tool]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for tool in tools:
        params = tool.parameters if isinstance(tool.parameters, dict) else {}
        if not params:
            params = {"type": "object", "properties": {}}
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or tool.name,
                    "parameters": params,
                },
            }
        )
    return specs


def _parse_frontmatter(block: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    lines = block.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue
        if line[:1].isspace():
            raise AgentSkillError("frontmatter の行を下げないでください")
        if ":" not in line:
            raise AgentSkillError(f"読めない行です: {line}")
        key, rest = line.split(":", 1)
        key = key.strip()
        rest = rest.strip()
        if not key:
            raise AgentSkillError("項目名が空です")
        if key in data:
            raise AgentSkillError(f"項目が重複しています: {key}")
        if rest == "":
            items: list[str] = []
            index += 1
            while index < len(lines) and lines[index].startswith("  - "):
                item = lines[index][4:].strip()
                if item:
                    items.append(_unquote(item))
                index += 1
            data[key] = items
            continue
        if rest.startswith("[") and rest.endswith("]"):
            data[key] = _parse_inline_list(rest)
        else:
            data[key] = _unquote(rest)
        index += 1
    return data


def _parse_inline_list(raw: str) -> list[str]:
    inner = raw[1:-1].strip()
    if not inner:
        return []
    return [_unquote(part.strip()) for part in inner.split(",") if part.strip()]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_tools(raw: Any) -> tuple[str, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or any(not isinstance(item, str) or not item for item in raw):
        raise AgentSkillError("tools はツール名の一覧にしてください")
    for name in raw:
        if not _TOOL_RE.match(name):
            raise AgentSkillError(f"ツール名の形式が違います: {name}")
    if len(raw) != len(set(raw)):
        raise AgentSkillError("tools の名前が重複しています")
    return tuple(raw)


def _system_prompt(skill: Skill | None, tool_names: list[str]) -> str:
    lines = [
        "あなたは利用者の依頼を、許可されたツールだけで進めるアシスタントです。",
        "日本語で答えてください。",
        "ツールが返していない事実は、調べた結果であるかのように書かないでください。",
        "最終的な確認は利用者が行います。あなたは下書きと作業結果を返します。",
    ]
    if tool_names:
        lines.append("使えるツール: " + "、".join(tool_names))
        lines.append("ツールが要るときはツールを呼び、要らなければ本文だけを返してください。")
    else:
        lines.append("この依頼ではツールを使えません。依頼文と手順だけで答えてください。")
    if skill:
        lines.append(f"\n# スキル: {skill.name}")
        if skill.description:
            lines.append(skill.description)
        lines.append(skill.instructions.strip())
    return "\n".join(lines)


def _history(messages: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    usable = [
        message
        for message in (messages or [])
        if message.get("role") in ("user", "assistant")
        and str(message.get("content") or "").strip()
    ]
    clipped = usable[-HISTORY_LIMIT * 2 :]
    return [
        {"role": str(message["role"]), "content": str(message["content"])}
        for message in clipped
    ]


def _message_text(reply: Any) -> str:
    if not isinstance(reply, dict):
        return ""
    content = reply.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict)
        ]
        return "".join(parts)
    return ""


def _assistant_tool_message(
    reply: dict[str, Any], tool_calls: list[Any]
) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        calls.append(
            {
                "id": str(call.get("id") or fn.get("name") or "tool"),
                "type": "function",
                "function": {
                    "name": str(fn.get("name") or ""),
                    "arguments": _arguments_text(fn.get("arguments")),
                },
            }
        )
    return {
        "role": "assistant",
        "content": _message_text(reply),
        "tool_calls": calls,
    }


async def _run_call(
    call: dict[str, Any], allowed: list[Tool]
) -> tuple[Step, dict[str, str]]:
    fn = call.get("function") if isinstance(call.get("function"), dict) else {}
    name = str(fn.get("name") or "")
    step, result = await _invoke(name, fn.get("arguments"), allowed)
    return step, {
        "role": "tool",
        "tool_call_id": str(call.get("id") or name or "tool"),
        "content": result,
    }


async def _invoke(
    name: str, raw_args: Any, allowed: list[Tool]
) -> tuple[Step, str]:
    args = _as_dict(raw_args)
    tool = next((item for item in allowed if item.name == name), None)
    if tool is None:
        result = json.dumps(
            {"error": f"この依頼では {name or '無名のツール'} を使えません"},
            ensure_ascii=False,
        )
        return Step(name=name or "unknown", ok=False, result=_clip(result, TRACE_CHARS)), result
    try:
        result = await tool.handler(args)
    except Exception as exc:  # noqa: BLE001 — モデルへ返して続行する
        result = json.dumps(
            {"error": f"{name} の実行に失敗しました: {exc}"},
            ensure_ascii=False,
        )
        return Step(name=name, ok=False, result=_clip(result, TRACE_CHARS)), result
    if not isinstance(result, str):
        result = json.dumps(result, ensure_ascii=False)
    return Step(name=name, ok=True, result=_clip(result, TRACE_CHARS)), _clip(result, RESULT_CHARS)


def _arguments_text(raw: Any) -> str:
    if isinstance(raw, str):
        return raw
    return json.dumps(_as_dict(raw), ensure_ascii=False)


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _json_objects(text: str) -> list[str]:
    out: list[str] = []
    index = 0
    length = len(text or "")
    while index < length:
        if text[index] != "{":
            index += 1
            continue
        depth = 0
        in_str = False
        escape = False
        start = index
        for cursor in range(index, length):
            ch = text[cursor]
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
                    out.append(text[start : cursor + 1])
                    index = cursor + 1
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
        if not isinstance(args, dict):
            args = {key: value for key, value in data.items() if key != "tool"}
        return {"name": name, "arguments": args}
    return None
