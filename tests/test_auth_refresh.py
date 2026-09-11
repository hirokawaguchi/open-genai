"""アプリ JWT の再発行（サイレントセッション延長）のテスト。

`backend/app/auth.py` は onelogin(python3-saml) を import するが、ここで検証するのは
JWT の発行・検証・再発行のみ。テスト依存を軽くするため、onelogin 未導入時は
ダミーモジュールを差し込んでから import する。
"""

from __future__ import annotations

import sys
import time
import types

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

from app import auth  # noqa: E402

_SECRET = "unit-test-app-jwt-secret-0123456789"


@pytest.fixture(autouse=True)
def _stable_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth, "APP_JWT_SECRET", _SECRET)
    monkeypatch.setattr(auth, "JWT_LEEWAY_SECONDS", 60)
    monkeypatch.setattr(auth, "JWT_REFRESH_GRACE_SECONDS", 300)


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


def test_default_ttl_is_12_hours() -> None:
    assert auth.JWT_TTL_SECONDS == 43200


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


def test_refresh_valid_token_preserves_claims_and_extends_exp() -> None:
    old = _make_token(3600)
    old_claims = auth.verify_token(old)

    new = auth.refresh_token(old)
    new_claims = auth.verify_token(new)

    assert new_claims["sub"] == old_claims["sub"]
    assert new_claims["email"] == old_claims["email"]
    assert new_claims["name"] == old_claims["name"]
    assert new_claims["groups"] == old_claims["groups"]
    assert new_claims["sidx"] == old_claims["sidx"]
    # 再発行後は有効期限が（既定 12 時間先に）延びている
    assert new_claims["exp"] > old_claims["exp"]


def test_refresh_expired_within_grace_succeeds() -> None:
    # leeway(60s) は超えるが grace(300s) 以内 → 再発行を許可する
    token = _make_token(-120)
    new = auth.refresh_token(token)
    claims = auth.verify_token(new)
    assert claims["sub"] == "user@example.com"
    assert claims["exp"] > int(time.time())


def test_refresh_expired_beyond_grace_raises() -> None:
    token = _make_token(-400)
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.refresh_token(token)


def test_refresh_tampered_signature_raises() -> None:
    token = _make_token(3600) + "tampered"
    with pytest.raises(jwt.InvalidTokenError):
        auth.refresh_token(token)


def test_verify_allows_small_clock_skew() -> None:
    # 期限を 30 秒だけ過ぎたトークンは leeway(60s) 内なので有効扱い
    token = _make_token(-30)
    claims = auth.verify_token(token)
    assert claims["sub"] == "user@example.com"
