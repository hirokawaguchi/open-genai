"""画像生成結果の永続化テスト。"""

import json
import os
import sqlite3
import tempfile

import pytest

from app import storage


@pytest.fixture
def db_path(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(storage, "DB_PATH", path)
    storage.init_db()
    yield path
    os.unlink(path)


def test_update_message_extra_data(db_path):
    user = "user-1"
    chat = storage.create_chat(user, "/image")
    chat_id = chat["chatId"].replace("chat#", "")
    recorded = storage.create_messages(
        chat_id,
        user,
        [
            {
                "messageId": "msg-1",
                "role": "assistant",
                "content": "{}",
                "usecase": "/image",
            }
        ],
    )
    assert recorded

    extra = [
        {
            "type": "json",
            "name": "open-genai-generated-image",
            "source": {
                "type": "json",
                "mediaType": "application/json",
                "data": "{}",
            },
        }
    ]
    updated = storage.update_message_extra_data(chat_id, user, "msg-1", extra)
    assert updated is not None
    assert updated["extraData"] == extra

    row = (
        sqlite3.connect(db_path)
        .execute("SELECT extraData FROM messages WHERE messageId = ?", ("msg-1",))
        .fetchone()
    )
    assert json.loads(row[0]) == extra
