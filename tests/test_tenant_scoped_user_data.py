"""チャット履歴・保存プロンプト・ピン・アプリ実行履歴を棟で分ける。"""

from __future__ import annotations

import importlib
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def storage(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "chats.db"))
    from app import storage as st

    importlib.reload(st)
    st.init_db()
    return st


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "teams.db"))
    from app import teams_store as ts

    importlib.reload(ts)
    ts.init_db(seed_exapps=[])
    return ts


OTHER_TENANT = "aaaaaaaa-0000-0000-0000-0000000000t2"


def test_chats_are_listed_only_in_their_tenant(storage) -> None:
    user = "a@example.com"
    home = storage.create_chat(user, "/chat", storage.DEFAULT_TENANT_ID)
    other = storage.create_chat(user, "/chat", OTHER_TENANT)

    home_ids = {c["chatId"] for c in storage.list_chats(user, storage.DEFAULT_TENANT_ID)}
    other_ids = {c["chatId"] for c in storage.list_chats(user, OTHER_TENANT)}
    assert home["chatId"] in home_ids
    assert other["chatId"] not in home_ids
    assert other["chatId"] in other_ids
    assert home["chatId"] not in other_ids


def test_chat_from_other_tenant_is_inaccessible(storage) -> None:
    user = "a@example.com"
    chat = storage.create_chat(user, "/chat", storage.DEFAULT_TENANT_ID)
    chat_id = chat["chatId"].replace("chat#", "")

    assert storage.find_chat(chat_id, user, OTHER_TENANT) is None
    assert storage.list_messages(chat_id, user, OTHER_TENANT) == []
    assert storage.create_messages(
        chat_id, user, [{"role": "user", "content": "x"}], OTHER_TENANT
    ) is None
    assert storage.update_title(chat_id, user, "題", OTHER_TENANT) is None
    assert storage.delete_chat(chat_id, user, OTHER_TENANT) is False
    assert storage.find_chat(chat_id, user, storage.DEFAULT_TENANT_ID) is not None


def test_legacy_chats_move_to_default_tenant(tmp_path, monkeypatch) -> None:
    db = tmp_path / "legacy-chats.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE chats (
            chatId TEXT PRIMARY KEY,
            id TEXT NOT NULL,
            usecase TEXT NOT NULL DEFAULT '/chat',
            title TEXT NOT NULL DEFAULT '',
            userId TEXT NOT NULL DEFAULT '',
            createdDate TEXT NOT NULL,
            updatedDate TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO chats VALUES (?,?,?,?,?,?,?)",
        ("c1", "chat#c1", "/chat", "旧", "a@example.com", "1", "1"),
    )
    conn.commit()
    conn.close()

    monkeypatch.setenv("DB_PATH", str(db))
    from app import storage as st

    importlib.reload(st)
    st.init_db()
    listed = st.list_chats("a@example.com", st.DEFAULT_TENANT_ID)
    assert [c["chatId"] for c in listed] == ["chat#c1"]
    assert st.list_chats("a@example.com", OTHER_TENANT) == []


def test_own_system_contexts_are_per_tenant(storage) -> None:
    user = "a@example.com"
    storage.create_system_context(
        user, "本庁", "p1", tenant_id=storage.DEFAULT_TENANT_ID
    )
    storage.create_system_context(user, "能代", "p2", tenant_id=OTHER_TENANT)
    storage.create_system_context(
        user, "公開本庁", "p3", is_public=True, tenant_id=storage.DEFAULT_TENANT_ID
    )

    home = {c["systemContextTitle"] for c in storage.list_system_contexts(user, [], storage.DEFAULT_TENANT_ID)}
    other = {c["systemContextTitle"] for c in storage.list_system_contexts(user, [], OTHER_TENANT)}
    guest = {
        c["systemContextTitle"]
        for c in storage.list_system_contexts("b@example.com", [], storage.DEFAULT_TENANT_ID)
    }
    assert home == {"本庁", "公開本庁"}
    assert other == {"能代"}
    assert guest == {"公開本庁"}


def test_pins_and_histories_are_per_tenant(store) -> None:
    user = "a@example.com"
    store.create_team("企画課", user, tenant_id=store.DEFAULT_TENANT_ID)
    other = store.create_tenant("能代役所")
    store.upsert_tenant_membership(other["tenantId"], user, role="guest")

    pins, err = store.add_user_app_pin(
        user, store.COMMON_TEAM_ID, "chat", False, store.DEFAULT_TENANT_ID
    )
    assert err is None
    assert len(pins) == 1
    assert store.list_user_app_pins(user, other["tenantId"]) == []

    other_pins, other_err = store.add_user_app_pin(
        user, store.COMMON_TEAM_ID, "chat", False, other["tenantId"]
    )
    assert other_err is None
    assert len(other_pins) == 1
    assert len(store.list_user_app_pins(user, store.DEFAULT_TENANT_ID)) == 1

    store.create_exapp_history(
        {
            "teamId": store.COMMON_TEAM_ID,
            "exAppId": "rag",
            "userId": user,
            "tenantId": store.DEFAULT_TENANT_ID,
            "outputs": "本庁",
        }
    )
    store.create_exapp_history(
        {
            "teamId": store.COMMON_TEAM_ID,
            "exAppId": "rag",
            "userId": user,
            "tenantId": other["tenantId"],
            "outputs": "能代",
        }
    )
    home_h = store.list_exapp_histories(
        store.COMMON_TEAM_ID, "rag", user, store.DEFAULT_TENANT_ID
    )
    other_h = store.list_exapp_histories(
        store.COMMON_TEAM_ID, "rag", user, other["tenantId"]
    )
    assert [h["outputs"] for h in home_h] == ["本庁"]
    assert [h["outputs"] for h in other_h] == ["能代"]


def test_new_writes_without_tenant_do_not_use_default(storage, store) -> None:
    user = "a@example.com"
    with pytest.raises(ValueError, match="棟が指定されていません"):
        storage.create_chat(user, "/chat")
    assert storage.list_chats(user, storage.DEFAULT_TENANT_ID) == []
    with pytest.raises(ValueError, match="棟が指定されていません"):
        storage.list_chats(user, None)
    with pytest.raises(ValueError, match="棟が指定されていません"):
        storage.create_system_context(user, "無指定", "p")
    assert storage.list_system_contexts(user, [], storage.DEFAULT_TENANT_ID) == []

    with pytest.raises(ValueError, match="棟が指定されていません"):
        store.add_user_app_pin(user, store.COMMON_TEAM_ID, "chat", False)
    assert store.list_user_app_pins(user, store.DEFAULT_TENANT_ID) == []
    with pytest.raises(ValueError, match="棟が指定されていません"):
        store.create_exapp_history(
            {
                "teamId": store.COMMON_TEAM_ID,
                "exAppId": "rag",
                "userId": user,
                "outputs": "無指定",
            }
        )
    assert (
        store.list_exapp_histories(
            store.COMMON_TEAM_ID, "rag", user, store.DEFAULT_TENANT_ID
        )
        == []
    )
