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

APP_JWT_SECRET = os.environ.get("APP_JWT_SECRET", "change-me-open-genai-secret")
JWT_ALG = "HS256"
JWT_TTL_SECONDS = int(os.environ.get("APP_JWT_TTL", "28800"))  # 8 時間

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
def mint_token(
    *,
    sub: str,
    email: str,
    name: str,
    groups: list[str],
    session_index: str | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": sub,
        "email": email,
        "name": name,
        "groups": groups,
        # SAML シングルログアウト(SLO) 用のセッションインデックス
        "sidx": session_index,
        "iat": now,
        "exp": now + JWT_TTL_SECONDS,
    }
    return jwt.encode(payload, APP_JWT_SECRET, algorithm=JWT_ALG)


def verify_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, APP_JWT_SECRET, algorithms=[JWT_ALG])
