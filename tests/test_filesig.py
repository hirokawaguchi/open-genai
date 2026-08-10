"""添付 URL HMAC (filesig) と起動時秘密情報警告のテスト。"""

from __future__ import annotations

import time

import pytest

from app import filesig, security_warn


@pytest.fixture(autouse=True)
def file_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(filesig, "FILES_URL_SECRET", "unit-test-files-secret-0123456789")


def test_sign_and_verify_roundtrip() -> None:
    q = filesig.sign_query("PUT", "uuid/name.pdf", ttl=60)
    assert filesig.verify("PUT", "uuid/name.pdf", q["exp"], q["sig"])
    assert not filesig.verify("GET", "uuid/name.pdf", q["exp"], q["sig"])
    assert not filesig.verify("PUT", "other/key", q["exp"], q["sig"])


def test_expired_rejected() -> None:
    exp = str(int(time.time()) - 10)
    sig = filesig._sign_payload("GET", "k", int(exp))
    assert not filesig.verify("GET", "k", exp, sig)


def test_build_signed_url_contains_query() -> None:
    url = filesig.build_signed_url("http://localhost/api", "a/b.txt", "GET")
    assert url.startswith("http://localhost/api/files/a/b.txt?")
    assert "exp=" in url and "sig=" in url


def test_warn_detects_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_JWT_SECRET", "change-me-open-genai-secret")
    monkeypatch.setenv("INTERNAL_SIGNING_SECRET", "dev-internal-secret-change-me")
    monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "admin")
    monkeypatch.delenv("FILES_URL_SECRET", raising=False)
    security_warn.warn_insecure_defaults()
    err = capsys.readouterr().err
    assert "[SECURITY]" in err
    assert "APP_JWT_SECRET" in err
    assert "openssl rand -hex 32" in err


def test_warn_silent_when_strong(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_JWT_SECRET", "a" * 32)
    monkeypatch.setenv("INTERNAL_SIGNING_SECRET", "b" * 32)
    monkeypatch.setenv("KEYCLOAK_ADMIN_PASSWORD", "c" * 32)
    security_warn.warn_insecure_defaults()
    assert "[SECURITY]" not in capsys.readouterr().err
