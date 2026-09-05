from __future__ import annotations

import json
import os
from types import SimpleNamespace

import bcrypt
from conftest import load_service_module


def _mod(**env: str):
    for key in ("OPERATOR_LOGIN_HOSTS", "OPERATOR_USERS", "APP_TITLE"):
        os.environ.pop(key, None)
    os.environ.update(env)
    return load_service_module("backend/app/ops_login.py")


def _req(host: str, *, xf_host: str | None = None, proto: str = "https", redirect: str | None = None):
    headers = {"host": host, "x-forwarded-proto": proto}
    if xf_host:
        headers["x-forwarded-host"] = xf_host
    params = {"redirect": redirect} if redirect else {}
    return SimpleNamespace(
        headers=headers,
        query_params=params,
        url=SimpleNamespace(scheme=proto),
    )


def test_disabled_without_users_or_hosts() -> None:
    mod = _mod()
    assert mod.enabled(_req("paris.procuretech.jp")) is False


def test_enabled_only_on_operator_host() -> None:
    hashed = bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()
    users = json.dumps(
        [{"email": "Ops@Example.JP", "name": "運用", "password_hash": hashed, "groups": ["SystemAdminGroup"]}]
    )
    mod = _mod(OPERATOR_LOGIN_HOSTS="paris.procuretech.jp", OPERATOR_USERS=users)
    assert mod.enabled(_req("paris.procuretech.jp")) is True
    assert mod.enabled(_req("paris.procuretech.bhc.asp.lgwan.jp")) is False
    assert mod.find_user("ops@example.jp")["email"] == "ops@example.jp"


def test_safe_redirect_rejects_foreign_host() -> None:
    mod = _mod(OPERATOR_LOGIN_HOSTS="paris.procuretech.jp")
    req = _req("paris.procuretech.jp", redirect="https://evil.example/phish")
    assert mod.safe_redirect(req, "https://evil.example/phish") == "https://paris.procuretech.jp"
    assert mod.safe_redirect(req, "https://paris.procuretech.jp/") == "https://paris.procuretech.jp"


def test_verify_password() -> None:
    mod = _mod()
    hashed = bcrypt.hashpw(b"ok", bcrypt.gensalt()).decode()
    assert mod.verify_password("ok", hashed) is True
    assert mod.verify_password("ng", hashed) is False
