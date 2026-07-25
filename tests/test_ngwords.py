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
                    "check_mynumber": True,
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


def test_check_blocks_valid_mynumber(ngword_db) -> None:
    blocked, message = ngwords.check("番号 123456789018 です")
    assert blocked
    assert message is not None
    assert "マイナンバー" in message


def test_check_allows_invalid_twelve_digits(ngword_db) -> None:
    """検査数字が合わない 12 桁は、委譲された \\d{12} だけではブロックしない。"""
    blocked, message = ngwords.check("番号 123456789012 です")
    assert not blocked
    assert message is None


def test_check_allows_clean_text(ngword_db) -> None:
    blocked, message = ngwords.check("問題ない入力です")
    assert not blocked
    assert message is None


def test_check_ignores_digits_inside_uuid(ngword_db) -> None:
    """共通チーム ID 等の UUID 末尾 12 桁が誤ヒットしないこと。"""
    blocked, message = ngwords.check(
        "議事録\n8\n00000000-0000-0000-0000-000000000000"
    )
    assert not blocked
    assert message is None


def test_check_mynumber_can_be_disabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "ngwords2.db"
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
                    "check_mynumber": False,
                    "words": [],
                    "patterns": [],
                }
            ),
            "1",
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setattr(ngwords, "NGWORD_DB_PATH", str(db_path))
    ngwords._cache["mtime"] = None
    blocked, _ = ngwords.check("123456789018")
    assert not blocked
    ngwords._cache["mtime"] = None
