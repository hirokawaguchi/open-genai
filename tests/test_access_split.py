from __future__ import annotations

import os
from types import SimpleNamespace

from conftest import load_service_module


def _mod(**env: str):
    keys = (
        "PORTAL_LOGIN_HOSTS",
        "PORTAL_PUBLIC_URL",
        "PUBLIC_URL",
        "LGWAN_PUBLIC_URL",
        "SAML_SP_ACS_URL",
        "FRONTEND_URL",
        "OPERATOR_SAML_SOURCE_IPS",
        "OPERATOR_LOGIN_HOSTS",
        "OPERATOR_USERS",
    )
    for key in keys:
        os.environ.pop(key, None)
    os.environ.update(env)
    return load_service_module("backend/app/access_split.py")


def _req(host: str, *, real_ip: str | None = None):
    headers = {"host": host, "x-forwarded-proto": "https"}
    if real_ip:
        headers["x-real-ip"] = real_ip
    return SimpleNamespace(
        headers=headers,
        query_params={},
        url=SimpleNamespace(scheme="https"),
        client=SimpleNamespace(host=real_ip or ""),
    )


ENV = dict(
    PORTAL_LOGIN_HOSTS="portal.example.jp",
    PORTAL_PUBLIC_URL="https://portal.example.jp",
    PUBLIC_URL="https://app.example.lg.jp",
    FRONTEND_URL="https://app.example.jp",
    OPERATOR_SAML_SOURCE_IPS="203.0.113.10",
)


def test_portal_host_stays_portal() -> None:
    mod = _mod(**ENV)
    dest = mod.login_destination(_req("portal.example.jp"))
    assert dest.kind == "portal"


def test_internet_app_host_is_blank() -> None:
    mod = _mod(**ENV)
    dest = mod.login_destination(_req("app.example.jp", real_ip="198.51.100.20"))
    assert dest.kind == "blank"


def test_saml_source_on_internet_app_redirects_to_public() -> None:
    mod = _mod(**ENV)
    dest = mod.login_destination(_req("app.example.jp", real_ip="203.0.113.10"))
    assert dest.kind == "redirect"
    assert dest.url == "https://app.example.lg.jp/api/auth/login"


def test_lgwan_from_acs_url_when_public_url_missing() -> None:
    mod = _mod(
        PORTAL_LOGIN_HOSTS="portal.example.jp",
        PORTAL_PUBLIC_URL="https://portal.example.jp",
        FRONTEND_URL="https://app.example.jp",
        SAML_SP_ACS_URL="https://app.example.lg.jp/api/auth/saml/acs",
    )
    dest = mod.login_destination(_req("app.example.lg.jp"))
    assert dest.kind == "saml"
    assert dest.relay == "https://app.example.lg.jp"


def test_public_host_uses_saml() -> None:
    mod = _mod(**ENV)
    dest = mod.login_destination(
        _req("app.example.lg.jp", real_ip="203.0.113.10")
    )
    assert dest.kind == "saml"
    assert dest.relay == "https://app.example.lg.jp"
