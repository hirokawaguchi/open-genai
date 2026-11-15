"""台帳用サービストークン。文字列は一度だけ返し、失効したら使えなくなる。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app import service_tokens  # noqa: E402


@pytest.fixture()
def token_db(tmp_path, monkeypatch):
    monkeypatch.setenv("SERVICE_TOKEN_DB_PATH", str(tmp_path / "tokens.db"))
    service_tokens._ready_path = None


def test_issue_is_shown_once_and_resolves(token_db):
    secret, row = service_tokens.issue("batch@example.jp", "tenant-1", "財務", "admin@example.jp")
    assert secret.startswith("ogst_")
    assert "token" not in row
    assert row["userId"] == "batch@example.jp"
    resolved = service_tokens.resolve(secret)
    assert resolved is not None
    assert resolved["userId"] == "batch@example.jp"
    assert resolved["tenantId"] == "tenant-1"
    assert resolved["lastUsedAt"] is not None
    listed = service_tokens.list_tokens("tenant-1")
    assert listed[0]["id"] == row["id"]
    assert secret not in str(listed)


def test_revoke_stops_the_token(token_db):
    secret, row = service_tokens.issue("batch@example.jp", "tenant-1", "財務", "admin@example.jp")
    assert service_tokens.revoke(row["id"], "tenant-1") is True
    assert service_tokens.resolve(secret) is None
    assert service_tokens.revoke(row["id"], "other") is False


def test_other_strings_do_not_resolve(token_db):
    assert service_tokens.resolve("not-a-token") is None
    assert service_tokens.resolve("ogst_missing") is None
