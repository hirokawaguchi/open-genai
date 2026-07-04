from __future__ import annotations

import pytest

from app import intauth


@pytest.fixture(autouse=True)
def signing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intauth, "SECRET", "test-signing-secret")
    monkeypatch.setattr(intauth, "MAX_AGE", 300)


def test_sign_and_verify_accepts_valid_signature() -> None:
    ts, sig = intauth.sign("user-1", "team-b,team-a", "scope-1", "tag-b,tag-a")
    assert intauth.verify("user-1", "team-b,team-a", "scope-1", ts, sig, "tag-b,tag-a")


def test_verify_rejects_tampered_scope() -> None:
    ts, sig = intauth.sign("user-1", "team-a", "scope-1")
    assert not intauth.verify("user-1", "team-a", "scope-2", ts, sig)


def test_verify_rejects_expired_timestamp(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intauth, "MAX_AGE", 1)
    ts, sig = intauth.sign("user-1", "team-a", "scope-1")
    expired_ts = str(int(ts) - 10)
    assert not intauth.verify("user-1", "team-a", "scope-1", expired_ts, sig)


def test_verify_skips_when_secret_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(intauth, "SECRET", "")
    assert intauth.verify("user-1", "team-a", "scope-1", None, None)
