"""インターネット入口と庁内（SAML）公開面のログイン振り分け。

- PORTAL_LOGIN_HOSTS: Keycloak ID/PW フォーム
- PUBLIC_URL（または LGWAN_PUBLIC_URL / ACS URL）のホスト、あるいは
  OPERATOR_SAML_SOURCE_IPS: SAML
- SAML 出口 IP がインターネット本体ホストへ来た場合: PUBLIC_URL へリダイレクト
- それ以外のインターネット: 白紙。ログインは入口ホストからのみ
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from . import ops_login, portal_login


@dataclass(frozen=True)
class LoginDest:
    kind: str  # portal | saml | redirect | blank
    url: str = ""
    relay: str = ""


def _host_of(url: str) -> str:
    return (urlparse(url).hostname or "").strip().lower()


def lgwan_public() -> str:
    for key in ("PUBLIC_URL", "LGWAN_PUBLIC_URL"):
        raw = (os.environ.get(key) or "").rstrip("/")
        if raw:
            return raw
    acs = (os.environ.get("SAML_SP_ACS_URL") or "").strip()
    if "/api/auth/saml/acs" in acs:
        return acs.split("/api/auth/saml/acs", 1)[0].rstrip("/")
    return ""


def internet_app() -> str:
    return (
        os.environ.get("FRONTEND_URL")
        or os.environ.get("INTERNET_APP_URL")
        or ""
    ).rstrip("/")


def portal_public() -> str:
    explicit = (os.environ.get("PORTAL_PUBLIC_URL") or "").rstrip("/")
    if explicit:
        return explicit
    hosts = portal_login.portal_hosts()
    if hosts:
        return "https://" + sorted(hosts)[0]
    return ""


def lgwan_host() -> str:
    return _host_of(lgwan_public())


def internet_app_host() -> str:
    return _host_of(internet_app())


def is_lgwan_request(request: Any) -> bool:
    if ops_login.from_saml_source(request):
        return True
    host = portal_login.request_host(request)
    lgwan = lgwan_host()
    return bool(lgwan) and host == lgwan


def login_destination(request: Any) -> LoginDest:
    if portal_login.enabled(request):
        return LoginDest(kind="portal")

    lgwan = lgwan_public()
    host = portal_login.request_host(request)

    if is_lgwan_request(request):
        if lgwan and host and host != lgwan_host():
            return LoginDest(kind="redirect", url=f"{lgwan}/api/auth/login")
        return LoginDest(kind="saml", relay=lgwan)

    return LoginDest(kind="blank")
