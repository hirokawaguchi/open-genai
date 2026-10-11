"""チャット回答の補足画像。画像 API は呼ばない。"""

import os
import tempfile

import pytest

from app import image_supplement, storage


def test_parse_image_prompt():
    assert image_supplement.parse_image_prompt("NONE") == {"status": "none"}
    got = image_supplement.parse_image_prompt("a bicycle on a quiet street, morning light")
    assert got["status"] == "ready"
    assert "bicycle" in got["prompt"]


@pytest.fixture
def db_path(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    monkeypatch.setattr(storage, "DB_PATH", path)
    storage.init_db()
    yield path
    os.unlink(path)


def test_saved_image_is_removed_with_the_message(db_path, monkeypatch, tmp_path):
    monkeypatch.setattr(image_supplement, "FILES_DIR", str(tmp_path))
    user = "user-1"
    chat = storage.create_chat(user, "/chat", storage.DEFAULT_TENANT_ID)
    chat_id = chat["chatId"].replace("chat#", "")
    storage.create_messages(
        chat_id,
        user,
        [
            {
                "messageId": "msg-1",
                "role": "assistant",
                "content": "自転車の絵です。",
                "usecase": "/chat",
            }
        ],
        storage.DEFAULT_TENANT_ID,
    )
    key = image_supplement._write_png(chat_id, "msg-1", "aGVsbG8=")
    storage.save_message_image(
        chat_id,
        user,
        "msg-1",
        {"status": "ready", "prompt": "a bicycle", "fileKey": key},
    )
    assert os.path.isfile(tmp_path / key)
    assert storage.get_message_image(chat_id, "msg-1")["status"] == "ready"

    storage.create_messages(
        chat_id,
        user,
        [
            {
                "messageId": "msg-1",
                "role": "assistant",
                "content": "書き直した回答",
                "usecase": "/chat",
            }
        ],
        storage.DEFAULT_TENANT_ID,
    )
    assert storage.get_message_image(chat_id, "msg-1") is None
    assert not os.path.isfile(tmp_path / key)
