"""アプリ JWT の発行・再発行・失効のテスト。

`backend/app/auth.py` は onelogin(python3-saml) を import するが、ここで検証するのは
JWT とサーバ側セッションのみ。テスト依存を軽くするため、onelogin 未導入時は
ダミーモジュールを差し込んでから import する。
"""

from __future__ import annotations

import sqlite3
import sys
import time
import types
from datetime import datetime, timedelta, timezone

import jwt
import pytest


def _install_onelogin_stubs() -> None:
    try:
        import onelogin  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    onelogin_mod = types.ModuleType("onelogin")
    saml2 = types.ModuleType("onelogin.saml2")
    auth_mod = types.ModuleType("onelogin.saml2.auth")
    idp_mod = types.ModuleType("onelogin.saml2.idp_metadata_parser")
    settings_mod = types.ModuleType("onelogin.saml2.settings")
    auth_mod.OneLogin_Saml2_Auth = object
    idp_mod.OneLogin_Saml2_IdPMetadataParser = object
    settings_mod.OneLogin_Saml2_Settings = object
    onelogin_mod.saml2 = saml2
    saml2.auth = auth_mod
    saml2.idp_metadata_parser = idp_mod
    saml2.settings = settings_mod
    sys.modules.update(
        {
            "onelogin": onelogin_mod,
            "onelogin.saml2": saml2,
            "onelogin.saml2.auth": auth_mod,
            "onelogin.saml2.idp_metadata_parser": idp_mod,
            "onelogin.saml2.settings": settings_mod,
        }
    )


_install_onelogin_stubs()

from app import auth, sessions  # noqa: E402

_SECRET = "unit-test-app-jwt-secret-0123456789"


@pytest.fixture(autouse=True)
def _stable_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory) -> None:
    monkeypatch.setattr(auth, "APP_JWT_SECRET", _SECRET)
    monkeypatch.setattr(auth, "JWT_LEEWAY_SECONDS", 60)
    monkeypatch.setattr(auth, "JWT_REFRESH_GRACE_SECONDS", 300)
    monkeypatch.setattr(sessions, "DB_PATH", str(tmp_path / "sessions.db"))  # type: ignore[attr-defined]
    monkeypatch.setattr(sessions, "RESET_HOUR", 4)
    monkeypatch.setattr(sessions, "RESET_MIN_SECONDS", 4 * 60 * 60)


def _count() -> int:
    conn = sqlite3.connect(sessions.DB_PATH)
    try:
        return int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])
    finally:
        conn.close()


_JST = timezone(timedelta(hours=9))


def _jst(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=_JST).timestamp())


def _make_token(exp_offset: int, **overrides: object) -> str:
    now = int(time.time())
    payload: dict[str, object] = {
        "sub": "user@example.com",
        "email": "user@example.com",
        "name": "テスト利用者",
        "groups": ["UserGroup"],
        "sidx": "session-index-1",
        "iat": now,
        "exp": now + exp_offset,
    }
    payload.update(overrides)
    return jwt.encode(payload, _SECRET, algorithm=auth.JWT_ALG)


def _resign(claims: dict, **overrides: object) -> str:
    payload = dict(claims)
    payload.update(overrides)
    return jwt.encode(payload, _SECRET, algorithm=auth.JWT_ALG)


def test_default_ttl_is_12_hours() -> None:
    assert auth.JWT_TTL_SECONDS == 43200


def test_afternoon_login_expires_at_next_morning_reset() -> None:
    # 14時のログインは、翌日の14時ではなく翌朝4時に切れる。
    assert sessions.deadline(_jst(2026, 11, 2, 14)) == _jst(2026, 11, 3, 4)
    assert sessions.deadline(_jst(2026, 11, 2, 9)) == _jst(2026, 11, 3, 4)


def test_login_just_before_reset_skips_to_the_following_morning() -> None:
    assert sessions.deadline(_jst(2026, 11, 2, 3, 30)) == _jst(2026, 11, 3, 4)
    assert sessions.deadline(_jst(2026, 11, 2, 1)) == _jst(2026, 11, 3, 4)
    assert sessions.deadline(_jst(2026, 11, 2, 4)) == _jst(2026, 11, 3, 4)


def test_mint_and_verify_roundtrip() -> None:
    token = auth.mint_token(
        sub="a@example.com",
        email="a@example.com",
        name="A",
        groups=["UserGroup", "TeamAdminGroup"],
        session_index="idx-9",
    )
    claims = auth.verify_token(token)
    assert claims["sub"] == "a@example.com"
    assert claims["groups"] == ["UserGroup", "TeamAdminGroup"]
    assert claims["sidx"] == "idx-9"
    assert claims["sid"]
    assert claims["auth_time"] <= int(time.time())
    assert sessions.is_active(claims["sid"])


def test_mint_caps_exp_at_absolute_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sessions, "deadline", lambda auth_time: int(auth_time) + 1000)
    monkeypatch.setattr(auth, "JWT_TTL_SECONDS", 99999)
    token = auth.mint_token(
        sub="a@example.com",
        email="a@example.com",
        name="A",
        groups=["UserGroup"],
    )
    claims = auth.verify_token(token)
    assert claims["exp"] - claims["auth_time"] == 1000


def test_refresh_keeps_the_same_session_and_extends_exp() -> None:
    token = auth.mint_token(
        sub="a@example.com",
        email="a@example.com",
        name="A",
        groups=["UserGroup"],
        session_index="idx-1",
    )
    old = auth.verify_token(token)
    short = _resign(old, exp=int(time.time()) + 3600)

    new = auth.refresh_token(short)
    claims = auth.verify_token(new)

    assert claims["sid"] == old["sid"]
    assert claims["auth_time"] == old["auth_time"]
    assert claims["sub"] == old["sub"]
    assert claims["groups"] == old["groups"]
    assert claims["sidx"] == old["sidx"]
    assert claims["exp"] > int(time.time()) + 3600
    assert _count() == 1


def test_refresh_expired_token_within_absolute_lifetime_succeeds() -> None:
    token = auth.mint_token(
        sub="user@example.com",
        email="user@example.com",
        name="テスト利用者",
        groups=["UserGroup"],
        session_index="session-index-1",
    )
    claims = auth.verify_token(token)
    # JWT 自体は切れていても、ログインから 24 時間の内側なら延長できる。
    expired = _resign(claims, exp=int(time.time()) - 400)
    new = auth.refresh_token(expired)
    refreshed = auth.verify_token(new)
    assert refreshed["sub"] == "user@example.com"
    assert refreshed["sid"] == claims["sid"]
    assert refreshed["exp"] > int(time.time())


def test_refresh_tampered_signature_raises() -> None:
    token = auth.mint_token(
        sub="user@example.com",
        email="user@example.com",
        name="テスト利用者",
        groups=["UserGroup"],
    )
    with pytest.raises(jwt.InvalidTokenError):
        auth.refresh_token(token + "tampered")


def test_verify_allows_small_clock_skew() -> None:
    token = auth.mint_token(
        sub="user@example.com",
        email="user@example.com",
        name="テスト利用者",
        groups=["UserGroup"],
    )
    claims = auth.verify_token(token)
    skewed = _resign(claims, exp=int(time.time()) - 30)
    assert auth.verify_token(skewed)["sub"] == "user@example.com"


def test_token_without_session_is_rejected() -> None:
    token = _make_token(3600)
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_token(token)
    with pytest.raises(jwt.InvalidTokenError):
        auth.refresh_token(token)


def test_revoked_session_is_rejected() -> None:
    token = auth.mint_token(
        sub="user@example.com",
        email="user@example.com",
        name="テスト利用者",
        groups=["UserGroup"],
    )
    sid = auth.verify_token(token)["sid"]
    assert sessions.revoke(sid)
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_token(token)
    with pytest.raises(jwt.InvalidTokenError):
        auth.refresh_token(token)


def test_refresh_stops_at_absolute_lifetime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "JWT_LEEWAY_SECONDS", 0)
    token = auth.mint_token(
        sub="user@example.com",
        email="user@example.com",
        name="テスト利用者",
        groups=["UserGroup"],
    )
    claims = auth.verify_token(token)
    monkeypatch.setattr(sessions, "deadline", lambda auth_time: int(time.time()) - 5)
    fresh = _resign(claims, exp=int(time.time()) + 3600)
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.verify_token(fresh)
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.refresh_token(fresh)


def test_revoke_matching_keeps_current_and_other_users() -> None:
    current = auth.mint_token(
        sub="User@Example.com",
        email="User@Example.com",
        name="本人",
        groups=["UserGroup"],
    )
    other_browser = auth.mint_token(
        sub="User@Example.com",
        email="User@Example.com",
        name="本人",
        groups=["UserGroup"],
    )
    stranger = auth.mint_token(
        sub="other@example.com",
        email="other@example.com",
        name="他人",
        groups=["UserGroup"],
    )
    current_claims = auth.verify_token(current)
    revoked = sessions.revoke_matching(
        ["user@example.com"], keep_sid=current_claims["sid"]
    )
    assert revoked == 1
    assert auth.verify_token(current)["sid"] == current_claims["sid"]
    with pytest.raises(jwt.InvalidTokenError):
        auth.verify_token(other_browser)
    assert auth.verify_token(stranger)["sub"] == "other@example.com"
