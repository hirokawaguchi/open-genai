"""エージェントチャットの手順書と、有限回のツール実行。"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.agent import (
    AgentLimitError,
    AgentSkillError,
    Tool,
    bind_tools,
    parse_skill,
    run,
)

SKILL = """---
name: 議事録整理
description: 決定事項と検討課題を分ける
tools:
  - knowledge_search
---

会議資料の該当節を見て、決定事項と検討課題を箇条書きにする。
"""


def _search_tool(seen: list[dict]) -> Tool:
    async def handler(args: dict) -> str:
        seen.append(args)
        return json.dumps({"nodes": [{"title": "第3条", "text": "保存期間は無期限"}]}, ensure_ascii=False)

    return Tool(
        name="knowledge_search",
        description="登録済み文書を検索する",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
        handler=handler,
    )


def test_parse_skill_keeps_the_procedure_and_tools() -> None:
    skill = parse_skill(SKILL)
    assert skill.name == "議事録整理"
    assert skill.description == "決定事項と検討課題を分ける"
    assert skill.tools == ("knowledge_search",)
    assert "決定事項" in skill.instructions


def test_parse_skill_rejects_a_missing_preamble() -> None:
    with pytest.raises(AgentSkillError, match="---"):
        parse_skill("本文だけ")


def test_parse_skill_rejects_an_unknown_tool_name() -> None:
    text = SKILL.replace("knowledge_search", "Shell")
    with pytest.raises(AgentSkillError, match="ツール名"):
        parse_skill(text)


def test_bind_tools_rejects_a_skill_tool_outside_the_runtime() -> None:
    skill = parse_skill(SKILL)
    with pytest.raises(AgentSkillError, match="許可されていない"):
        bind_tools(skill, [])


def test_loop_calls_a_tool_then_returns_the_draft() -> None:
    seen: list[dict] = []
    prompts: list[str] = []

    async def complete(messages, specs):
        prompts.append(messages[0]["content"])
        assert specs[0]["function"]["name"] == "knowledge_search"
        if not any(message.get("role") == "tool" for message in messages):
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call-1",
                        "function": {
                            "name": "knowledge_search",
                            "arguments": {"query": "保存期間"},
                        },
                    }
                ],
            }
        assert "無期限" in messages[-1]["content"]
        return {"content": "保存期間は無期限です。出典は第3条です。"}

    result = asyncio.run(
        run(
            goal="ウェブサイト掲載情報の保存期間は？",
            complete=complete,
            tools=[_search_tool(seen)],
            skill=parse_skill(SKILL),
        )
    )
    assert seen == [{"query": "保存期間"}]
    assert result.answer.startswith("保存期間は無期限")
    assert result.skill_name == "議事録整理"
    assert result.steps[0].ok is True
    assert "第3条" in result.steps[0].result
    assert "スキル: 議事録整理" in prompts[0]
    assert "最終的な確認は利用者" in prompts[0]


def test_loop_accepts_a_json_tool_when_the_model_has_no_tool_calls() -> None:
    seen: list[dict] = []

    async def complete(messages, specs):
        del specs
        if not any(str(message.get("content") or "").startswith("# ツール結果") for message in messages):
            return {
                "content": '{"tool":"knowledge_search","arguments":{"query":"第3条"}}'
            }
        return {"content": "第3条では保存期間を無期限としています。"}

    result = asyncio.run(
        run(
            goal="第3条を確認して",
            complete=complete,
            tools=[_search_tool(seen)],
        )
    )
    assert seen == [{"query": "第3条"}]
    assert result.steps[0].name == "knowledge_search"
    assert "無期限" in result.answer


def test_loop_tells_the_model_when_a_tool_is_not_allowed() -> None:
    async def complete(messages, specs):
        del specs
        if not any(message.get("role") == "tool" for message in messages):
            return {
                "content": "",
                "tool_calls": [
                    {"id": "call-x", "function": {"name": "shell", "arguments": {}}}
                ],
            }
        assert "使えません" in messages[-1]["content"]
        return {"content": "コードの実行はこの依頼ではできません。"}

    result = asyncio.run(
        run(goal="スクリプトを実行して", complete=complete, tools=[_search_tool([])])
    )
    assert result.steps[0].ok is False
    assert result.steps[0].name == "shell"
    assert "できません" in result.answer


def test_loop_stops_at_the_step_limit() -> None:
    async def complete(messages, specs):
        del messages, specs
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "function": {"name": "knowledge_search", "arguments": {"query": "条"}},
                }
            ],
        }

    with pytest.raises(AgentLimitError, match="上限") as raised:
        asyncio.run(
            run(
                goal="全部見て",
                complete=complete,
                tools=[_search_tool([])],
                max_steps=2,
            )
        )
    assert len(raised.value.steps) == 2
