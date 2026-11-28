import asyncio
import json

import pytest

from app import activity, agent_session, harness, hermes_client, hermes_mcp, mcp_knowledge, store, tools


def _session(tmp_path, monkeypatch) -> str:
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    return store.create_session(user_id="u1", title="評価書")["id"]


def test_delete_message_removes_only_that_row(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    store.add_message(sid, "u1", role="user", content="質問")
    detail = store.add_message(sid, "u1", role="assistant", content="回答")
    assert detail is not None
    answer_id = detail["messages"][-1]["id"]
    assert store.delete_message(sid, "u1", answer_id) is True
    left = store.get_session(sid, "u1")
    assert left is not None
    assert [m["content"] for m in left["messages"]] == ["質問"]
    assert store.delete_message(sid, "other", answer_id) is False


def test_clip_keeps_one_row_for_the_same_answer(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    store.add_message(sid, "u1", role="user", content="DX推進計画の\n対象期間は？")
    detail = store.add_message(
        sid,
        "u1",
        role="assistant",
        content="6年間です",
        citations=[{"display_name": "大分市DX推進計画", "n": 1}],
    )
    assert detail is not None
    message_id = detail["messages"][-1]["id"]
    first, err = store.clip_message(sid, "u1", message_id)
    assert err is None and first is not None
    second, err = store.clip_message(sid, "u1", message_id)
    assert err is None and second is not None
    assert len(second["items"]) == 1
    clip = second["items"][0]
    assert clip["message_id"] == message_id
    assert clip["label"] == "DX推進計画の 対象期間は？"
    assert clip["value"] == "6年間です"
    assert clip["citations"][0]["display_name"] == "大分市DX推進計画"
    missing, err = store.clip_message(sid, "u1", "absent")
    assert missing is None and err == "見つかりません"


def test_commit_requires_a_goal(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    raw = asyncio.run(
        tools.dispatch(
            "commit_items",
            {"chapters": [{"label": "背景", "value": "本文"}]},
            ctx,
        )
    )
    assert "ゴール" in raw
    assert store.get_session(sid, "u1")["items"] == []


def _write_checked_manuscript(ctx: tools.ToolContext) -> None:
    asyncio.run(
        tools.dispatch(
            "write_manuscript",
            {
                "form": "document",
                "chapters": [{"label": "結果", "value": "適合である"}],
            },
            ctx,
        )
    )
    asyncio.run(
        tools.dispatch(
            "fact_check",
            {"findings": [{"claim": "適合である", "status": "supported"}]},
            ctx,
        )
    )
    asyncio.run(
        tools.dispatch(
            "revise_manuscript",
            {"chapters": [{"label": "結果", "value": "結果は適合です。"}]},
            ctx,
        )
    )


def test_goal_is_the_instruction_and_deliver_matches_it(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    asyncio.run(tools.dispatch("set_goal", {"goal": "監査資料から評価書を作る"}, ctx))
    _write_checked_manuscript(ctx)
    blocked = json.loads(asyncio.run(tools.dispatch("deliver", {}, tools.ToolContext(
        session_id=sid, user_id="other", scope="team"
    ))))
    assert "見つかりません" in blocked["error"]
    opened = json.loads(asyncio.run(tools.dispatch("deliver", {}, ctx)))
    detail = store.get_session(sid, "u1")
    assert opened["instruction"] == detail["instruction"] == "監査資料から評価書を作る"
    assert opened["mode"] == "new"
    assert opened["name"] == "評価書"
    assert ctx.open_editor is True
    assert detail["items"] == []
    assert detail["manuscript"]["chapters"][0]["value"] == "結果は適合です。"


def test_fact_check_stops_before_the_editor(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    asyncio.run(tools.dispatch("set_goal", {"goal": "評価書を作る"}, ctx))
    asyncio.run(
        tools.dispatch(
            "write_manuscript",
            {"form": "文書", "chapters": [{"label": "結果", "value": "適合である"}]},
            ctx,
        )
    )
    checked = json.loads(
        asyncio.run(
            tools.dispatch(
                "fact_check",
                {
                    "findings": [
                        {
                            "claim": "適合である",
                            "status": "contradicted",
                            "note": "資料は不適合",
                        }
                    ]
                },
                ctx,
            )
        )
    )
    assert checked["fact"] == "hold"
    assert "不適合" in ctx.ask_text
    blocked = json.loads(asyncio.run(tools.dispatch("deliver", {}, ctx)))
    assert "食い違" in blocked["error"]
    assert ctx.open_editor is False
    opened = json.loads(asyncio.run(tools.dispatch("open_draft", {}, ctx)))
    assert opened["open_editor"] is True
    assert ctx.open_editor is True


def test_revise_keeps_the_same_headings(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    asyncio.run(tools.dispatch("set_goal", {"goal": "評価書を作る"}, ctx))
    asyncio.run(
        tools.dispatch(
            "write_manuscript",
            {"form": "slides", "chapters": [{"label": "結果", "value": "適合である"}]},
            ctx,
        )
    )
    early = json.loads(
        asyncio.run(
            tools.dispatch(
                "revise_manuscript",
                {"chapters": [{"label": "結果", "value": "結果は適合です。"}]},
                ctx,
            )
        )
    )
    assert "事実" in early["error"]
    asyncio.run(
        tools.dispatch(
            "fact_check",
            {"findings": [{"claim": "適合である", "status": "supported"}]},
            ctx,
        )
    )
    added = json.loads(
        asyncio.run(
            tools.dispatch(
                "revise_manuscript",
                {
                    "chapters": [
                        {"label": "結果", "value": "結果は適合です。"},
                        {"label": "補足", "value": "新しい章"},
                    ]
                },
                ctx,
            )
        )
    )
    assert "見出し" in added["error"]
    assert added["headings"] == ["結果"]
    detail = store.get_session(sid, "u1")
    assert [chapter["label"] for chapter in detail["manuscript"]["chapters"]] == ["結果"]


def test_empty_items_do_not_deliver(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    asyncio.run(tools.dispatch("set_goal", {"goal": "評価書を作る"}, ctx))
    raw = json.loads(asyncio.run(tools.dispatch("deliver", {}, ctx)))
    assert "原稿" in raw["error"]
    assert ctx.open_editor is False


def test_ask_user_stops_the_turn(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    asyncio.run(tools.dispatch("ask_user", {"question": "対象年度はどれですか。"}, ctx))
    assert ctx.ask_text == "対象年度はどれですか。"


def test_office_write_stops_when_ledger_is_down(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    monkeypatch.delenv("LEDGER_URL", raising=False)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    raw = json.loads(
        asyncio.run(
            tools.dispatch(
                "write_office_draft",
                {"filename": "評価書.docx", "content_base64": "YQ==", "finalize": True},
                ctx,
            )
        )
    )
    assert "確定" in raw["error"]
    missing = json.loads(
        asyncio.run(
            tools.dispatch(
                "write_office_draft",
                {"filename": "評価書.docx", "content_base64": "YQ=="},
                ctx,
            )
        )
    )
    assert "台帳が止まっています" in missing["error"]


def test_session_key_is_tenant_team_and_user():
    pool = agent_session.Pool()
    monkey_max = agent_session.MAX_SESSIONS
    assert monkey_max >= 1
    first = pool.acquire(agent_session.SessionKey("bld", "team-a", "u1"))
    again = pool.acquire(agent_session.SessionKey("bld", "team-a", "u1"))
    other = pool.acquire(agent_session.SessionKey("bld", "team-b", "u1"))
    assert first == again == "inprocess"
    assert other == "inprocess"
    assert len(pool._seen) == 2


def test_mounts_reject_work_and_file_server():
    agent_session.assert_mounts({})
    with pytest.raises(ValueError):
        agent_session.assert_mounts({"/data/work": {"bind": "/work/u1", "mode": "rw"}})
    with pytest.raises(ValueError):
        agent_session.assert_mounts({"/storage": {"bind": "/storage", "mode": "ro"}})
    spec = agent_session.container_spec(
        agent_session.SessionKey("bld", "team-a", "u1"), "hermes:latest"
    )
    assert spec["volumes"] == {}
    assert "/root/.hermes" in spec["tmpfs"]
    agent_session.assert_mounts(spec["volumes"])


def test_hermes_turn_can_set_the_goal(tmp_path, monkeypatch):
    sid = _session(tmp_path, monkeypatch)
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team")
    token = hermes_mcp.open_turn(ctx, ["set_goal"])
    listed = asyncio.run(
        hermes_mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token)
    )
    assert [item["name"] for item in listed["result"]["tools"]] == ["set_goal"]
    called = asyncio.run(
        hermes_mcp.handle(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "set_goal", "arguments": {"goal": "評価書を作る"}},
            },
            token,
        )
    )
    assert called["result"]["isError"] is False
    assert store.get_session(sid, "u1")["instruction"] == "評価書を作る"
    hermes_mcp.close_turn(token)
    gone = asyncio.run(
        hermes_mcp.handle(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "set_goal", "arguments": {"goal": "別の文"}},
            },
            token,
        )
    )
    assert "終わって" in gone["error"]["message"]


def test_greeting_does_not_start_a_document():
    text = harness._system_prompt("", [], source_labels=[], catalog=[])
    assert "あいさつ" in text
    assert "文書の話をこちらから始めません" in text
    assert "まだ一文にならないときは" not in text
    assert "引用番号は書かない" in text
    assert "AIタイプ" not in text
    assert "利用者は道具の英語名を書きません" in text
    assert "回答の本文には道具の英語名を書かない" in text
    assert "残りの手順を利用者に頼んで止めません" in text


def test_prompt_keeps_the_current_headings():
    text = harness._system_prompt(
        "",
        [],
        source_labels=[],
        catalog=[],
        manuscript={
            "form": "document",
            "fact": "clean",
            "revised": False,
            "chapters": [{"label": "背景", "value": "本文"}],
        },
    )
    assert "見出しは次のとおりです" in text
    assert "背景" in text


def test_activity_keeps_each_new_step():
    activity.begin("s-progress", "turn-a")
    activity.note("s-progress", "search_utterances")
    activity.note("s-progress", "search_utterances")
    activity.note("s-progress", "")
    activity.note("s-progress", "search_plans")
    assert activity.snapshot("s-progress", "turn-a") == ["search_utterances", "search_plans"]
    assert activity.snapshot("s-progress", "turn-b") == []
    activity.begin("s-progress", "turn-b")
    assert activity.snapshot("s-progress", "turn-a") == []
    assert activity.snapshot("s-progress", "turn-b") == []


def test_hermes_collapses_a_repeated_tool():
    traces: list[dict[str, str]] = []
    hermes_client.remember_tool(traces, "get_weather", "")
    hermes_client.remember_tool(traces, "get_weather", "晴れ")
    hermes_client.remember_tool(traces, "search_sources", "資料")
    assert [item["name"] for item in traces] == ["get_weather", "search_sources"]
    assert traces[0]["result"] == "晴れ"


def test_hermes_hides_internal_tool_names():
    assert hermes_client.notebook_tool_name("tool_describe: Reading tool details") is None
    assert hermes_client.notebook_tool_name("call_stz689oj") is None
    assert (
        hermes_client.notebook_tool_name("mcp__editor_notebook_4fce649b__ask_user")
        == "ask_user"
    )


def test_hermes_permission_prefers_once():
    chosen = hermes_client.allow_option(
        [
            {"id": "reject", "name": "Reject"},
            {"id": "allow_always", "name": "Always"},
            {"id": "allow_once", "name": "Once"},
        ]
    )
    assert chosen == "allow_once"


def test_sse_parser_skips_log_notification():
    text = """event: message
data: {"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info"}}

event: message
data: {"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"ok"}]}}
"""
    data = mcp_knowledge._parse_sse_json(text)
    assert data["id"] == 3
    assert data["result"]["content"][0]["text"] == "ok"
