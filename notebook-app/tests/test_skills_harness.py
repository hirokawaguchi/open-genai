import asyncio

from app import harness, llm, store, tools


def test_skill_seed_and_crud(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()

    first = store.list_skills("u1")
    assert len(first) == 4
    assert {s["name"] for s in first} == {"議事録係", "進行管理担当", "秘書", "参謀"}
    again = store.list_skills("u1")
    assert len(again) == 4

    created = store.create_skill("u1", name="点検", tool_names=["search_sources"])
    assert created["name"] == "点検"
    assert created["tools"] == ["search_sources"]
    assert store.get_skill(created["id"], "other") is None

    updated = store.update_skill(created["id"], "u1", instructions="短く")
    assert updated and updated["instructions"] == "短く"
    assert store.delete_skill(created["id"], "u1")
    assert store.get_skill(created["id"], "u1") is None


def test_message_tool_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1")["id"]
    store.add_message(sid, "u1", role="user", content="Q")
    detail = store.add_message(
        sid,
        "u1",
        role="assistant",
        content="A",
        tool_trace=[{"name": "search_sources", "result": "hit"}],
    )
    assert detail["messages"][-1]["tool_trace"][0]["name"] == "search_sources"


def test_search_sources_and_list_items(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1")["id"]
    store.add_file(
        sid,
        "u1",
        filename="note.md",
        raw="# 決定\n予算を増やす\n".encode(),
        error="",
        nodes=[{"title": "決定", "text": "予算を増やす", "source": "note.md"}],
        briefing={},
    )
    store.add_item(sid, "u1", label="課題")
    ctx = tools.ToolContext(session_id=sid, user_id="u1", scope="team-1")
    found = asyncio.run(tools.dispatch("search_sources", {"query": "予算"}, ctx))
    assert "予算" in found
    listed = asyncio.run(tools.dispatch("list_items", {}, ctx))
    assert "課題" in listed


def test_knowledge_scope_is_server_fixed():
    ctx = tools.ToolContext(session_id="s", user_id="u", scope="fixed-team")
    out = tools._knowledge_args(ctx, {"query": "q", "tags": "規程", "scope": "evil"})
    assert out["scope"] == "fixed-team"
    assert out["query"] == "q"


def test_parse_json_tool_fallback():
    parsed = harness._parse_json_tool(
        '前置き\n{"tool":"search_sources","arguments":{"query":"期限"}}\n',
        ["search_sources"],
    )
    assert parsed == {"name": "search_sources", "arguments": {"query": "期限"}}
    assert harness._parse_json_tool('{"tool":"rm","arguments":{}}', ["search_sources"]) is None


def test_harness_openai_tool_loop(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1")["id"]
    store.add_file(
        sid,
        "u1",
        filename="note.md",
        raw="# 決定\n予算を増やす\n".encode(),
        error="",
        nodes=[{"title": "決定", "text": "予算を増やす", "source": "note.md"}],
        briefing={},
    )
    replies = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {
                        "name": "search_sources",
                        "arguments": {"query": "予算"},
                    },
                }
            ],
        },
        {"role": "assistant", "content": "予算を増やすと書かれています [1]"},
    ]

    async def fake_chat(messages, temperature=0.2, tools=None):
        assert replies
        return replies.pop(0)

    monkeypatch.setattr("app.llm.chat_completion", fake_chat)
    answer, cites, traces = asyncio.run(
        harness.run(
            session_id=sid,
            user_id="u1",
            scope="team-1",
            question="何が決まった？",
            history=[],
        )
    )
    assert "予算" in answer
    assert traces[0]["name"] == "search_sources"
    assert cites[0]["n"] == 1


def test_continue_if_length_joins_chunks(monkeypatch):
    replies = [
        {"role": "assistant", "content": "後半です。", "_finish_reason": "stop"},
    ]

    async def fake_chat(messages, temperature=0.2, tools=None):
        assert "途中で切れています" in messages[-1]["content"]
        return replies.pop(0)

    monkeypatch.setattr("app.llm.chat_completion", fake_chat)
    text = asyncio.run(
        llm.continue_if_length(
            [{"role": "user", "content": "説明して"}],
            {
                "role": "assistant",
                "content": "前半、",
                "_finish_reason": "length",
            },
        )
    )
    assert text.startswith("前半、")
    assert "後半です。" in text
    assert llm.LENGTH_NOTE not in text


def test_mcp_citations_from_payload():
    from app import mcp_knowledge

    cites = mcp_knowledge.citations_from_payload(
        '{"nodes":[{"source":"規程.pdf","title":"第1章","text":"本文"}]}'
    )
    assert cites[0]["display_name"].startswith("規程.pdf")
    assert "共有ナレッジ" in cites[0]["display_name"]
    assert "未ソース" in cites[0]["display_name"]


def test_mcp_seed_connect_and_session_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    monkeypatch.delenv("KNOWLEDGE_MCP_URL", raising=False)
    store._db = None
    store.init_db()

    catalog = store.list_mcps("u1")
    names = {m["catalog_id"] for m in catalog}
    assert names == {"knowledge", "clock", "weather", "web_search"}
    clock = next(m for m in catalog if m["catalog_id"] == "clock")
    assert clock["connected"] is True
    knowledge = next(m for m in catalog if m["catalog_id"] == "knowledge")
    assert knowledge["connected"] is False
    assert "共有ナレッジ" in knowledge["description"]

    updated = store.update_mcp(clock["id"], "u1", connected=False)
    assert updated and updated["connected"] is False

    sid = store.create_session(user_id="u1")["id"]
    detail = store.get_session(sid, "u1")
    assert detail is not None
    weather = next(m for m in detail["mcps"] if m["catalog_id"] == "weather")
    assert weather["enabled"] is True
    detail = store.update_session(sid, "u1", mcp_enabled={weather["id"]: False})
    weather = next(m for m in detail["mcps"] if m["catalog_id"] == "weather")
    assert weather["enabled"] is False
    enabled = {m["catalog_id"] for m in store.enabled_session_mcps(sid, "u1")}
    assert "weather" not in enabled
    assert "web_search" in enabled


def test_sample_clock_and_allowed_tools():
    from app import sample_mcp, tools

    payload = sample_mcp.current_time_payload()
    assert payload["timezone"] == "Asia/Tokyo"
    assert payload["weekday"].endswith("曜日")

    allowed, extras = tools.allowed_from_mcps(
        {"tools": ["search_sources"]},
        [
            {
                "name": "時刻",
                "tools": ["get_current_time"],
                "prompt": "今を確認",
                "kind": "builtin",
            }
        ],
    )
    assert allowed == ["search_sources", "get_current_time"]
    assert extras == []


def test_weather_and_wikipedia_helpers(monkeypatch):
    from app import sample_mcp

    class FakeResp:
        def __init__(self, payload, ok=True):
            self._payload = payload
            self.is_success = ok
            self.content = b"{}" if payload is not None else b""

        def raise_for_status(self):
            if not self.is_success:
                raise RuntimeError("http error")

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, url, params=None):
            if "geocoding" in url:
                return FakeResp(
                    {"results": [{"name": "東京", "latitude": 35.6, "longitude": 139.7, "country": "日本"}]}
                )
            if "forecast" in url:
                return FakeResp(
                    {"current": {"temperature_2m": 20, "weather_code": 0, "wind_speed_10m": 3, "relative_humidity_2m": 40}}
                )
            if "wikipedia.org" in url:
                return FakeResp(["テスト", ["見出し"], ["要約です"], ["https://ja.wikipedia.org/wiki/見出し"]])
            return FakeResp({}, ok=False)

    monkeypatch.setattr(sample_mcp.httpx, "AsyncClient", FakeClient)
    weather = asyncio.run(sample_mcp.get_weather("東京"))
    assert "快晴" in weather
    search = asyncio.run(sample_mcp.wikipedia_search("テスト"))
    assert "要約です" in search
    assert "Wikipedia" in search
