import asyncio
import json

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


def test_message_source_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1")["id"]
    detail = store.add_message(
        sid, "u1", role="user", content="抜き出して", source_labels=["審査.pdf"]
    )
    assert detail["messages"][-1]["content"] == "抜き出して"
    assert detail["messages"][-1]["source_labels"] == ["審査.pdf"]


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


def _add_note(sid: str, filename: str, title: str, text: str) -> str:
    store.add_file(
        sid,
        "u1",
        filename=filename,
        raw=f"# {title}\n{text}\n".encode(),
        error="",
        nodes=[{"title": title, "text": text, "source": filename}],
        briefing={"outline": [title]},
    )
    detail = store.get_session(sid, "u1")
    return next(f["id"] for f in detail["files"] if f["filename"] == filename)


def test_search_sources_scope_and_miss(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1")["id"]
    budget_id = _add_note(sid, "予算.pdf", "予算", "予算を増やす")
    _add_note(sid, "天気.pdf", "天気", "今日は晴れである")
    scoped = tools.ToolContext(
        session_id=sid, user_id="u1", scope="team-1", source_ids=[budget_id]
    )
    found = asyncio.run(tools.dispatch("search_sources", {"query": "予算"}, scoped))
    assert "予算を増やす" in found
    assert "晴れ" not in found
    widened = asyncio.run(
        tools.dispatch(
            "search_sources",
            {"query": "晴れ", "source_ids": []},
            scoped,
        )
    )
    assert "晴れ" not in widened
    assert "予算を増やす" not in widened
    payload = json.loads(widened)
    assert payload["matched"] is False
    assert payload["sources"][0]["name"] == "予算.pdf"
    assert "予算" in payload["sources"][0]["outline"]


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
    answer, cites, traces, drafts, open_editor = asyncio.run(
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
    assert drafts == []
    assert open_editor is False


def test_harness_mentions_selected_source(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1")["id"]
    file_id = _add_note(sid, "審査.pdf", "審査項目", "審査は書面で行う")
    seen: dict[str, str] = {}

    async def fake_chat(messages, temperature=0.2, tools=None):
        seen["system"] = messages[0]["content"]
        seen["user"] = messages[-1]["content"]
        return {"role": "assistant", "content": "どの節を抜き出しますか。見出しは審査項目です。"}

    monkeypatch.setattr("app.llm.chat_completion", fake_chat)
    answer, _, _, _, _ = asyncio.run(
        harness.run(
            session_id=sid,
            user_id="u1",
            scope="team-1",
            question="抜き出して",
            history=[],
            source_ids=[file_id],
            source_labels=["審査.pdf"],
        )
    )
    assert "審査.pdf" in seen["system"]
    assert "審査項目" in seen["system"]
    assert "抜き出して" in seen["user"]
    assert "指定した資料: 審査.pdf" in seen["user"]
    assert "どの節を抜き出しますか" in answer
    assert "書面で行う" not in answer


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
    assert "未ソース" not in cites[0]["display_name"]


def test_mcp_seed_connect_and_session_toggle(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    monkeypatch.delenv("KNOWLEDGE_MCP_URL", raising=False)
    monkeypatch.delenv("FIRECRAWL_URL", raising=False)
    store._db = None
    store.init_db()

    catalog = store.list_mcps("u1")
    names = {m["catalog_id"] for m in catalog}
    assert names == {"knowledge", "clock", "weather", "web_search", "firecrawl"}
    clock = next(m for m in catalog if m["catalog_id"] == "clock")
    assert clock["connected"] is True
    knowledge = next(m for m in catalog if m["catalog_id"] == "knowledge")
    assert knowledge["connected"] is False
    assert "共有ナレッジ" in knowledge["description"]
    # FIRECRAWL_URL 未設定なら Web 検索 MCP は非接続（閉域では使えない）。
    firecrawl_mcp = next(m for m in catalog if m["catalog_id"] == "firecrawl")
    assert firecrawl_mcp["connected"] is False
    assert firecrawl_mcp["available"] is False

    updated = store.update_mcp(clock["id"], "u1", connected=False)
    assert updated and updated["connected"] is False

    sid = store.create_session(user_id="u1")["id"]
    detail = store.get_session(sid, "u1")
    assert detail is not None
    weather = next(m for m in detail["mcps"] if m["catalog_id"] == "weather")
    assert weather["connected"] is True
    assert weather["enabled"] is True
    detail = store.update_session(sid, "u1", mcp_enabled={weather["id"]: False})
    weather = next(m for m in detail["mcps"] if m["catalog_id"] == "weather")
    assert weather["enabled"] is True
    store.update_mcp(weather["id"], "u1", connected=False)
    detail = store.get_session(sid, "u1")
    assert detail is not None
    weather = next(m for m in detail["mcps"] if m["catalog_id"] == "weather")
    assert weather["enabled"] is False
    enabled = {m["catalog_id"] for m in store.enabled_session_mcps(sid, "u1")}
    assert "weather" not in enabled
    assert "clock" not in enabled
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
    assert allowed == [
        "search_sources",
        "get_current_time",
        "set_goal",
        "commit_items",
        "ask_user",
        "write_manuscript",
        "fact_check",
        "revise_manuscript",
        "deliver",
        "open_draft",
        "write_office_draft",
    ]
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


def test_firecrawl_disabled_without_url(monkeypatch):
    from app import firecrawl

    monkeypatch.delenv("FIRECRAWL_URL", raising=False)
    assert firecrawl.enabled() is False
    out = asyncio.run(firecrawl.search("花火"))
    assert "無効" in out


def test_firecrawl_search_and_scrape(monkeypatch):
    import json as _json

    from app import firecrawl

    monkeypatch.setenv("FIRECRAWL_URL", "http://firecrawl-local:3002")

    class FakeResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None, headers=None):
            if url.endswith("/v2/search"):
                return FakeResp(
                    {
                        "success": True,
                        "data": {
                            "web": [
                                {
                                    "url": "https://example.jp/a",
                                    "title": "記事A",
                                    "markdown": "本文A" * 1000,
                                }
                            ]
                        },
                    }
                )
            if url.endswith("/v2/scrape"):
                return FakeResp(
                    {
                        "success": True,
                        "data": {
                            "markdown": "ページ本文",
                            "metadata": {"title": "タイトル"},
                        },
                    }
                )
            raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr(firecrawl.httpx, "AsyncClient", FakeClient)
    assert firecrawl.enabled() is True

    result = _json.loads(asyncio.run(firecrawl.search("花火", limit=3)))
    assert result["results"][0]["url"] == "https://example.jp/a"
    assert len(result["results"][0]["snippet"]) <= firecrawl.MAX_SNIPPET_CHARS

    scraped = _json.loads(asyncio.run(firecrawl.scrape("https://example.jp/a")))
    assert scraped["title"] == "タイトル"
    assert scraped["markdown"] == "ページ本文"


def test_answer_ref_resolution():
    messages = [
        {"id": "u", "role": "user", "content": "聞いて"},
        {"id": "blank", "role": "assistant", "content": "  "},
        {"id": "a1", "role": "assistant", "content": "一つ目"},
        {"id": "u2", "role": "user", "content": "もう一度"},
        {
            "id": "a2",
            "role": "assistant",
            "content": "二つ目",
            "citations": [{"display_name": "審査.pdf"}],
        },
    ]
    assert harness.answer_ref_numbers("[[回答 2]] と [[回答2]] と [[回答 1]]") == [2, 1]
    got, err = harness.resolve_answer_refs("[[回答 2]]を直して", messages)
    assert err is None
    assert got[0]["n"] == 2
    assert got[0]["id"] == "a2"
    assert got[0]["prompt"] == "もう一度"
    assert got[0]["sources"] == ["審査.pdf"]
    _, err = harness.resolve_answer_refs("[[回答 9]]", messages)
    assert err == "回答 9 はこのノートにありません"
    many = " ".join(f"[[回答 {i}]]" for i in range(1, 7))
    _, err = harness.resolve_answer_refs(many, messages)
    assert err == "指定できる過去の回答は5件までです"
    section = harness._designated_section(
        [{"n": 1, "content": "あ" * 4001, "prompt": "", "sources": []}]
    )
    assert "以下略" in section


def test_harness_pins_designated_answers(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1")["id"]
    history = []
    for i in range(1, 10):
        history.append({"id": f"u{i}", "role": "user", "content": f"質問{i}"})
        history.append(
            {
                "id": f"a{i}",
                "role": "assistant",
                "content": f"本文{i}はユニーク",
                "citations": [{"display_name": "審査.pdf"}] if i == 1 else [],
            }
        )
    question = "[[回答 1]] の結論を [[回答 2]] に合わせて"
    designated, err = harness.resolve_answer_refs(question, history)
    assert err is None
    seen: dict[str, object] = {}

    async def fake_chat(messages, temperature=0.2, tools=None):
        seen["system"] = messages[0]["content"]
        seen["rest"] = [
            (m["role"], m["content"]) for m in messages if m["role"] != "system"
        ]
        return {"role": "assistant", "content": "合わせました"}

    monkeypatch.setattr("app.llm.chat_completion", fake_chat)
    answer, _, _, _, _ = asyncio.run(
        harness.run(
            session_id=sid,
            user_id="u1",
            scope="team-1",
            question=question,
            history=history,
            designated_answers=designated,
        )
    )
    system = str(seen["system"])
    rest = seen["rest"]
    assert isinstance(rest, list)
    blob = "\n".join(content for _, content in rest)
    assert "本文1はユニーク" in system
    assert "本文2はユニーク" in system
    assert "きっかけ: 質問1" in system
    assert "出典: 審査.pdf" in system
    assert "本文1はユニーク" not in blob
    assert "本文2はユニーク" not in blob
    assert "（回答 2。全文は「この送信で指定した過去の回答」を参照）" in blob
    assert "指定した過去の回答: 回答 1、回答 2" in rest[-1][1]
    assert "合わせました" in answer


def test_agent_writes_items_and_delivers_the_goal(tmp_path, monkeypatch):
    monkeypatch.setenv("HEARING_DB_PATH", str(tmp_path / "hearing.db"))
    store._db = None
    store.init_db()
    sid = store.create_session(user_id="u1", title="評価書")["id"]
    _add_note(sid, "仕様書.pdf", "背景", "現行は紙である")
    replies = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c1",
                    "function": {
                        "name": "set_goal",
                        "arguments": {"goal": "監査資料から評価書を作る"},
                    },
                }
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c2",
                    "function": {"name": "search_sources", "arguments": {"query": "背景"}},
                }
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c3",
                    "function": {
                        "name": "write_manuscript",
                        "arguments": {
                            "form": "document",
                            "chapters": [
                                {"label": "背景", "value": "現行は紙である。"},
                            ],
                        },
                    },
                }
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c4",
                    "function": {
                        "name": "fact_check",
                        "arguments": {
                            "findings": [
                                {"claim": "現行は紙である", "status": "supported"}
                            ]
                        },
                    },
                }
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c5",
                    "function": {
                        "name": "revise_manuscript",
                        "arguments": {
                            "chapters": [
                                {"label": "背景", "value": "現行の手続きは紙です。"},
                            ]
                        },
                    },
                }
            ],
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"id": "c6", "function": {"name": "deliver", "arguments": {}}}
            ],
        },
        {"role": "assistant", "content": "評価書の原稿を書きました。"},
    ]

    async def fake_chat(messages, temperature=0.2, tools=None):
        names = [t["function"]["name"] for t in (tools or [])]
        assert "set_goal" in names
        assert "commit_items" in names
        assert "deliver" in names
        assert "propose_drafts" not in names
        return replies.pop(0)

    monkeypatch.setattr("app.llm.chat_completion", fake_chat)
    answer, _, traces, drafts, open_editor = asyncio.run(
        harness.run(
            session_id=sid,
            user_id="u1",
            scope="team-1",
            question="監査の評価書を作って",
            history=[],
        )
    )
    detail = store.get_session(sid, "u1")
    assert detail["instruction"] == "監査資料から評価書を作る"
    assert detail["items"] == []
    assert detail["manuscript"]["chapters"][0]["label"] == "背景"
    assert "紙" in detail["manuscript"]["chapters"][0]["value"]
    assert drafts == []
    assert open_editor is True
    assert [t["name"] for t in traces] == [
        "set_goal",
        "search_sources",
        "write_manuscript",
        "fact_check",
        "revise_manuscript",
        "deliver",
    ]
    assert "評価書" in answer
