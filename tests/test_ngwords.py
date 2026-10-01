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


@pytest.fixture
def ngword_db_v2(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """棟別(v2)テーブル。既定の棟だけに禁止語を入れる。"""
    db_path = tmp_path / "ngwords_v2.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ngword_rules_v2 ("
        " tenantId TEXT PRIMARY KEY,"
        " rules TEXT NOT NULL,"
        " updatedDate TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO ngword_rules_v2 (tenantId, rules, updatedDate) VALUES (?, ?, ?)",
        (
            ngwords.DEFAULT_TENANT_ID,
            json.dumps(
                {"enabled": True, "case_sensitive": False, "words": ["禁止語"], "patterns": []}
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


def test_tenant_rule_blocks_only_its_tenant(ngword_db_v2) -> None:
    # 既定の棟では禁止語でブロックする。
    blocked, _ = ngwords.check("これは禁止語です", ngwords.DEFAULT_TENANT_ID)
    assert blocked
    # 別の棟は行が無い＝制限なしなので、同じ入力でも止めない。
    blocked2, _ = ngwords.check(
        "これは禁止語です", "00000000-0000-0000-0000-00000000ffff"
    )
    assert not blocked2


def test_default_tenant_falls_back_to_legacy_single_row(ngword_db) -> None:
    # v2 が無い場合、既定の棟は旧・単一行のルールを読む。
    blocked, _ = ngwords.check("これは禁止語を含みます", ngwords.DEFAULT_TENANT_ID)
    assert blocked
