"""SAML 認証 (backend = SAML Service Provider) と アプリ JWT。

- Keycloak (SAML IdP) のメタデータを取得して SP 設定を構築する（遅延・キャッシュ）。
- SAML アサーション検証後、アプリ用の JWT(HS256) を発行する。
- 各 API はこの JWT を Bearer トークンで検証する。
"""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse, urlunparse

import jwt
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from onelogin.saml2.settings import OneLogin_Saml2_Settings

from . import sessions

APP_JWT_SECRET = os.environ.get("APP_JWT_SECRET", "change-me-open-genai-secret")
JWT_ALG = "HS256"
JWT_TTL_SECONDS = int(os.environ.get("APP_JWT_TTL", "43200"))  # 12 時間。絶対期限内だけ再発行で延びる
# 時計ずれで作業中に 401 にならないよう、検証時に許す猶予（秒）。
JWT_LEEWAY_SECONDS = int(os.environ.get("APP_JWT_LEEWAY", "60"))
# 互換のため残す。再発行の上限はこちらではなく、セッションの絶対期限。
JWT_REFRESH_GRACE_SECONDS = int(os.environ.get("APP_JWT_REFRESH_GRACE", "300"))

SP_ENTITY_ID = os.environ.get(
    "SAML_SP_ENTITY_ID", "http://localhost:8000/auth/saml/metadata"
)
SP_ACS_URL = os.environ.get("SAML_SP_ACS_URL", "http://localhost:8000/auth/saml/acs")
SP_SLS_URL = os.environ.get("SAML_SP_SLS_URL", "http://localhost:8000/auth/saml/sls")
IDP_METADATA_URL = os.environ.get(
    "SAML_IDP_METADATA_URL",
    "http://keycloak:8080/kc/realms/open-genai/protocol/saml/descriptor",
)
# IdP メタデータの URL に proxy context path (/kc) が欠ける場合の補正
IDP_URL_PREFIX = os.environ.get("SAML_IDP_URL_PREFIX", "/kc")

_settings_cache: dict[str, Any] | None = None


def _fix_idp_urls(idp: dict[str, Any]) -> dict[str, Any]:
    """Keycloak メタデータの SSO/SLO URL に /kc が付いていない場合に付与する。"""
    prefix = IDP_URL_PREFIX.rstrip("/")
    if not prefix:
        return idp

    for key in ("singleSignOnService", "singleLogoutService"):
        services = idp.get(key)
        if not isinstance(services, dict):
            continue
        fixed: dict[str, str] = {}
        for binding, url in services.items():
            if not isinstance(url, str):
                fixed[binding] = url
                continue
            parsed = urlparse(url)
            path = parsed.path or ""
            if path.startswith("/realms/") and not path.startswith(f"{prefix}/"):
                path = f"{prefix}{path}"
                fixed[binding] = urlunparse(parsed._replace(path=path))
            else:
                fixed[binding] = url
        idp[key] = fixed
    return idp


# ---------------------------------------------------------------------------
# SAML 設定（IdP メタデータを取得して構築・キャッシュ）
# ---------------------------------------------------------------------------
def get_saml_settings() -> dict[str, Any]:
    global _settings_cache
    if _settings_cache is not None:
        return _settings_cache

    idp_data = OneLogin_Saml2_IdPMetadataParser.parse_remote(
        IDP_METADATA_URL, validate_cert=False
    )
    idp_data["idp"] = _fix_idp_urls(idp_data["idp"])

    settings: dict[str, Any] = {
        "strict": True,
        "debug": False,
        "sp": {
            "entityId": SP_ENTITY_ID,
            "assertionConsumerService": {
                "url": SP_ACS_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            },
            "singleLogoutService": {
                "url": SP_SLS_URL,
                "binding": "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect",
            },
            "NameIDFormat": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            "x509cert": "",
            "privateKey": "",
        },
        "idp": idp_data["idp"],
        "security": {
            "wantAssertionsSigned": True,
            "authnRequestsSigned": False,
            "wantMessagesSigned": False,
            "wantNameId": False,
            "requestedAuthnContext": False,
            # InResponseTo を保存しないため未要求応答を許可
            "rejectUnsolicitedResponsesWithInResponseTo": False,
            # Keycloak の role_list は Role 属性を Name 重複で送ることがある。
            # アプリ認可は groups マッパーを使うため、重複 Attribute を許容する。
            "allowRepeatAttributeName": True,
        },
    }
    _settings_cache = settings
    return settings


def reset_settings_cache() -> None:
    global _settings_cache
    _settings_cache = None


def build_saml_auth(req: dict[str, Any]) -> OneLogin_Saml2_Auth:
    return OneLogin_Saml2_Auth(req, get_saml_settings())


def get_sp_metadata() -> str:
    settings = OneLogin_Saml2_Settings(get_saml_settings(), sp_validation_only=True)
    metadata = settings.get_sp_metadata()
    errors = settings.validate_metadata(metadata)
    if errors:
        raise ValueError(f"SP メタデータが不正です: {errors}")
    return metadata.decode("utf-8") if isinstance(metadata, bytes) else metadata


# ---------------------------------------------------------------------------
# アプリ JWT
# ---------------------------------------------------------------------------
def read_token(token: str, *, allow_expired: bool = False) -> dict[str, Any]:
    """署名を検証して claims を返す。セッション台帳は見ない。

    ログアウトは、すでに切れたトークンからでも NameID とセッション ID を
    読む必要がある。API の認可には verify_token を使う。
    """
    return jwt.decode(
        token,
        APP_JWT_SECRET,
        algorithms=[JWT_ALG],
        leeway=JWT_LEEWAY_SECONDS,
        options={"verify_exp": not allow_expired},
    )


def _require_live_session(claims: dict[str, Any]) -> dict[str, Any]:
    """サーバ側セッションが生きていて、絶対期限内であることを確かめる。"""
    sid = claims.get("sid")
    if not isinstance(sid, str) or not sid:
        raise jwt.InvalidTokenError("session required")
    row = sessions.get(sid)
    if row is None or row.get("revoked_at") is not None:
        raise jwt.InvalidTokenError("session revoked")
    auth_time = row.get("auth_time")
    if not isinstance(auth_time, int):
        raise jwt.InvalidTokenError("session revoked")
    if int(time.time()) > sessions.deadline(auth_time) + JWT_LEEWAY_SECONDS:
        raise jwt.ExpiredSignatureError("absolute session lifetime exceeded")
    return row


def mint_token(
    *,
    sub: str,
    email: str,
    name: str,
    groups: list[str],
    session_index: str | None = None,
    sid: str | None = None,
    auth_time: int | None = None,
) -> str:
    """ログイン JWT を発行する。

    sid を渡さない呼び出しは新しいログインで、サーバ側セッションを作る。
    再発行は同じ sid と最初の auth_time を渡し、リセット時刻を超える exp は出さない。
    """
    now = int(time.time())
    if sid is None:
        auth_time = now
        sid = sessions.create(sub=sub, email=email, auth_time=now)
    elif auth_time is None:
        raise jwt.InvalidTokenError("auth_time required")
    absolute_end = sessions.deadline(int(auth_time))
    exp = min(now + JWT_TTL_SECONDS, absolute_end)
    if exp <= now:
        raise jwt.ExpiredSignatureError("absolute session lifetime exceeded")
    payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "groups": groups,
        # SAML シングルログアウト(SLO) 用のセッションインデックス
        "sidx": session_index,
        "sid": sid,
        "auth_time": int(auth_time),
        "iat": now,
        "exp": exp,
    }
    return jwt.encode(payload, APP_JWT_SECRET, algorithm=JWT_ALG)


def verify_token(token: str) -> dict[str, Any]:
    """署名・期限に加え、サーバ側セッションが有効であることを確かめる。"""
    claims = read_token(token)
    _require_live_session(claims)
    return claims


def refresh_token(token: str) -> str:
    """同じログインのまま JWT を再発行する。

    Keycloak への再認証は行わない。画面を閉じて JWT の期限が切れても、
    リセット時刻の前であり、セッションが切られていなければ延長する。
    署名不正・失効・リセット時刻の超過は例外（呼び出し側で 401）。
    """
    try:
        claims = read_token(token)
    except jwt.ExpiredSignatureError:
        claims = read_token(token, allow_expired=True)
    row = _require_live_session(claims)
    groups = claims.get("groups")
    sidx = claims.get("sidx")
    return mint_token(
        sub=str(claims.get("sub") or row["sub"]),
        email=str(claims.get("email") or row["email"] or ""),
        name=str(claims.get("name") or ""),
        groups=list(groups) if isinstance(groups, list) else [],
        session_index=sidx if isinstance(sidx, str) else None,
        sid=str(row["sid"]),
        auth_time=int(row["auth_time"]),
    )
