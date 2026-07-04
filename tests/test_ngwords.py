from __future__ import annotations

import json
import sqlite3

import pytest

from app import ngwords


@pytest.fixture
def ngword_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "ngwords.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ngword_rules ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " rules TEXT NOT NULL,"
        " updatedDate TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO ngword_rules (id, rules, updatedDate) VALUES (1, ?, ?)",
        (
            json.dumps(
                {
                    "enabled": True,
                    "case_sensitive": False,
                    "words": ["禁止語"],
                    "patterns": [r"\d{12}"],
                }
            ),
            "1",
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(ngwords, "NGWORD_DB_PATH", str(db_path))
    ngwords._cache["mtime"] = None
    yield db_path
    ngwords._cache["mtime"] = None


def test_check_blocks_word(ngword_db) -> None:
    blocked, message = ngwords.check("これは禁止語を含みます")
    assert blocked
    assert message is not None
    assert "禁止語" in message


def test_check_blocks_pattern(ngword_db) -> None:
    blocked, message = ngwords.check("番号 123456789012")
    assert blocked
    assert message is not None


def test_check_allows_clean_text(ngword_db) -> None:
    blocked, message = ngwords.check("問題ない入力です")
    assert not blocked
    assert message is None
