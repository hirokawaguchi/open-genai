"""API レベルのテスト（LLM はスタブ化）。

- ユーザー分離
- 4分野の独立履歴
- 先行セルのコンテキスト注入
- finalize によるセル書き戻し・再ダウンロード・元ファイル非破壊
"""

import base64
import importlib
import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("PROCURETECH_DB_PATH", "/tmp/pt_api_test.db")
os.environ.setdefault("INTERNAL_SIGNING_SECRET", "")  # 開発時: 署名検証スキップ

from fastapi.testclient import TestClient  # noqa: E402

from app import intauth, llm, main, sections, store  # noqa: E402

TEMPLATE = Path(__file__).resolve().parent / "fixtures" / "systemplan.xlsx"


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    db_path = tmp_path / "pt.db"
    monkeypatch.setattr(store, "_db", None)
    monkeypatch.setattr(store, "DB_PATH", str(db_path))
    store.init_db()
    yield
    monkeypatch.setattr(store, "_db", None)


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _stub_llm(monkeypatch):
    captured = {}

    finalize_prompts = {s.finalize_prompt for s in sections.SECTIONS}

    def _reply_for(messages):
        last = messages[-1]["content"]
        return "まとめられた本文" if last in finalize_prompts else "AIの返答です"

    async def fake_chat(messages, **kwargs):
        captured["messages"] = messages
        return _reply_for(messages)

    async def fake_chat_stream(messages, **kwargs):
        captured["messages"] = messages
        for ch in _reply_for(messages):
            yield ch

    monkeypatch.setattr(llm, "chat", fake_chat)
    monkeypatch.setattr(llm, "chat_stream", fake_chat_stream)
    return captured


def _parse_events(res) -> list[dict]:
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


def _done_event(res) -> dict:
    return next(e for e in _parse_events(res) if e.get("event") == "done")


def _headers(uid: str) -> dict[str, str]:
    # INTERNAL_SIGNING_SECRET が設定されていても通るよう、正しい署名を付与する。
    groups, scope, tags = "", "common", ""
    return {
        "x-api-key": main.API_KEY,
        "x-user-id": uid,
        "x-user-groups": groups,
        "x-scope": scope,
        "x-user-tags": tags,
        **intauth.signed_headers(uid, groups, scope, tags),
    }


def _upload(client, uid: str):
    b64 = base64.b64encode(TEMPLATE.read_bytes()).decode("ascii")
    return client.post(
        "/sessions",
        headers=_headers(uid),
        json={"filename": "systemplan.xlsx", "content": b64},
    )


def test_create_session_and_detail(client):
    res = _upload(client, "u1")
    assert res.status_code == 201, res.text
    detail = res.json()
    assert len(detail["sections"]) == 4
    # 記入済みテンプレートなので各分野の cell_value が入っている
    bg = next(s for s in detail["sections"] if s["key"] == "background")
    assert "デジタルデバイド" in bg["cell_value"]
    assert bg["messages"] == []
    assert bg["finalized"] is False


def test_rejects_non_xlsx(client):
    res = client.post(
        "/sessions", headers=_headers("u1"), json={"filename": "a.txt", "content": "x"}
    )
    assert res.status_code == 400


def test_user_isolation(client):
    sid = _upload(client, "u1").json()["id"]
    # 別ユーザーはアクセス不可
    res = client.get(f"/sessions/{sid}", headers=_headers("u2"))
    assert res.status_code == 404
    # 一覧も分離
    assert client.get("/sessions", headers=_headers("u2")).json()["sessions"] == []
    assert len(client.get("/sessions", headers=_headers("u1")).json()["sessions"]) == 1


def test_chat_appends_history_per_section(client):
    sid = _upload(client, "u1").json()["id"]
    r1 = client.post(
        f"/sessions/{sid}/chat",
        headers=_headers("u1"),
        json={"section": "background", "message": "こんにちは"},
    )
    assert r1.status_code == 200, r1.text
    events = _parse_events(r1)
    # delta が逐次流れ、最後に done で確定する
    assert any(e["event"] == "delta" for e in events)
    done = _done_event(r1)
    assert done["reply"] == "AIの返答です"
    assert done["finalized"] is False

    detail = client.get(f"/sessions/{sid}", headers=_headers("u1")).json()
    bg = next(s for s in detail["sections"] if s["key"] == "background")
    biz = next(s for s in detail["sections"] if s["key"] == "business")
    assert [m["role"] for m in bg["messages"]] == ["user", "assistant"]
    # 他分野の履歴は独立
    assert biz["messages"] == []


def test_finalize_writes_cell_and_download(client, _stub_llm):
    sid = _upload(client, "u1").json()["id"]
    # 書き戻しは対話後にのみ許可される
    client.post(
        f"/sessions/{sid}/chat",
        headers=_headers("u1"),
        json={"section": "goal", "message": "KPIを整理したい"},
    )
    res = client.post(
        f"/sessions/{sid}/finalize",
        headers=_headers("u1"),
        json={"section": "goal"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["finalized"] is True
    assert body["section"]["output"] == "まとめられた本文"
    assert body["section"]["cell_value"] == "まとめられた本文"
    # 整形指示・生成結果は会話履歴に残さない
    assert [m["role"] for m in body["section"]["messages"]] == ["user", "assistant"]
    assert all("まとめられた本文" != m["content"] for m in body["section"]["messages"])

    # 書き戻しに使ったメッセージは項番専用の整形指示
    assert _stub_llm["messages"][-1]["content"] == sections.get_section("goal").finalize_prompt

    # ダウンロードした xlsx に反映されている
    dl = client.get(f"/sessions/{sid}/download", headers=_headers("u1")).json()
    raw = base64.b64decode(dl["content"])
    from app import excel

    assert excel.read_cells(raw)["B23"] == "まとめられた本文"
    assert dl["filename"].startswith("systemplan_")


def test_finalize_requires_conversation(client):
    # 対話前の書き戻しは 400
    sid = _upload(client, "u1").json()["id"]
    res = client.post(
        f"/sessions/{sid}/finalize",
        headers=_headers("u1"),
        json={"section": "goal"},
    )
    assert res.status_code == 400, res.text


def test_chat_matomete_does_not_finalize(client):
    # トリガーワード廃止: チャットに「まとめて」と書いても書き戻さない。
    sid = _upload(client, "u1").json()["id"]
    original = client.get(f"/sessions/{sid}", headers=_headers("u1")).json()
    bg_before = next(s for s in original["sections"] if s["key"] == "background")["cell_value"]
    res = client.post(
        f"/sessions/{sid}/chat",
        headers=_headers("u1"),
        json={"section": "background", "message": "まとめて"},
    )
    assert res.status_code == 200, res.text
    done = _done_event(res)
    assert done["finalized"] is False
    # セルは書き換わらない
    assert done["section"]["cell_value"] == bg_before


def test_context_injection_includes_prior_cells(client, _stub_llm):
    sid = _upload(client, "u1").json()["id"]
    client.post(
        f"/sessions/{sid}/chat",
        headers=_headers("u1"),
        json={"section": "actualsystem", "message": "調査中"},
    )
    # actualsystem は B10/B14/B19 を注入する
    injected = " ".join(
        m["content"] for m in _stub_llm["messages"] if m["role"] == "user"
    )
    assert "事業の背景と目的" in injected
    assert "現在の業務の状況とその規模" in injected
    assert "現行システムの状況" in injected


def test_clear_section(client):
    sid = _upload(client, "u1").json()["id"]
    client.post(
        f"/sessions/{sid}/chat",
        headers=_headers("u1"),
        json={"section": "background", "message": "hi"},
    )
    res = client.post(
        f"/sessions/{sid}/sections/background/clear", headers=_headers("u1")
    )
    assert res.status_code == 200
    bg = next(s for s in res.json()["sections"] if s["key"] == "background")
    assert bg["messages"] == []


def test_delete_session(client):
    sid = _upload(client, "u1").json()["id"]
    assert client.delete(f"/sessions/{sid}", headers=_headers("u1")).status_code == 200
    assert client.get(f"/sessions/{sid}", headers=_headers("u1")).status_code == 404
