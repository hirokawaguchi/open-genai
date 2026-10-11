"""アカウント単位の API 回数。"""

from __future__ import annotations

from app.account_rate import AccountRateLimiter, account_key, limiter, reset_limiter


def test_blocks_after_limit() -> None:
    gate = AccountRateLimiter(limit=2, window_sec=60)
    assert gate.allow("a@example.com", now=0)
    assert gate.allow("a@example.com", now=1)
    assert not gate.allow("a@example.com", now=2)
    assert gate.retry_after("a@example.com", now=2) == 58


def test_other_account_has_its_own_budget() -> None:
    gate = AccountRateLimiter(limit=1, window_sec=60)
    assert gate.allow("a@example.com", now=0)
    assert gate.allow("b@example.com", now=0)
    assert not gate.allow("a@example.com", now=1)


def test_window_slides() -> None:
    gate = AccountRateLimiter(limit=1, window_sec=10)
    assert gate.allow("a@example.com", now=0)
    assert not gate.allow("a@example.com", now=9.9)
    assert gate.allow("a@example.com", now=10)


def test_disabled_when_limit_is_zero() -> None:
    gate = AccountRateLimiter(limit=0, window_sec=60)
    assert gate.allow("a@example.com", now=0)
    assert gate.allow("a@example.com", now=0)


def test_account_key_prefers_email() -> None:
    assert account_key({"email": "A@Example.com", "sub": "id"}) == "a@example.com"
    assert account_key({"sub": "User-1"}) == "user-1"
    assert account_key({}) == ""


def test_env_defaults(monkeypatch) -> None:
    monkeypatch.delenv("API_ACCOUNT_RATE_LIMIT", raising=False)
    monkeypatch.delenv("API_ACCOUNT_RATE_WINDOW_SEC", raising=False)
    reset_limiter()
    gate = limiter()
    assert gate.limit == 300
    assert gate.window_sec == 60
    reset_limiter()


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("API_ACCOUNT_RATE_LIMIT", "4")
    monkeypatch.setenv("API_ACCOUNT_RATE_WINDOW_SEC", "15")
    reset_limiter()
    gate = limiter()
    assert gate.limit == 4
    assert gate.window_sec == 15
    reset_limiter()
