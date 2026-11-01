from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

from conftest import load_service_module


def _mod(**env: str):
    for key in (
        "PORTAL_LOGIN_HOSTS",
        "APP_TITLE",
        "FRONTEND_URL",
        "PUBLIC_URL",
        "KEYCLOAK_URL",
    ):
        os.environ.pop(key, None)
    os.environ.update(env)
    return load_service_module("backend/app/portal_login.py")


def _req(host: str, *, xf_host: str | None = None, proto: str = "https"):
    headers = {"host": host, "x-forwarded-proto": proto}
    if xf_host:
        headers["x-forwarded-host"] = xf_host
    return SimpleNamespace(
        headers=headers,
        query_params={},
        url=SimpleNamespace(scheme=proto),
    )


def test_disabled_without_hosts() -> None:
    mod = _mod()
    assert mod.enabled(_req("portal.example.jp")) is False


def test_enabled_only_on_portal_host() -> None:
    mod = _mod(PORTAL_LOGIN_HOSTS="portal.example.jp")
    assert mod.enabled(_req("portal.example.jp")) is True
    assert mod.enabled(_req("app.example.jp")) is False
    assert mod.enabled(_req("portal.example.jp", xf_host="portal.example.jp")) is True


def test_app_home_prefers_frontend_url() -> None:
    mod = _mod(
        PORTAL_LOGIN_HOSTS="portal.example.jp",
        FRONTEND_URL="https://app.example.jp",
    )
    assert mod.app_home() == "https://app.example.jp"


def test_login_form_is_not_operator() -> None:
    mod = _mod(PORTAL_LOGIN_HOSTS="portal.example.jp", APP_TITLE="Open GENAI")
    body = mod.login_form(_req("portal.example.jp"))
    assert "運用者" not in body
    assert "インターネットからのログイン" not in body
    assert "/api/auth/portal" in body


def test_groups_from_kc_keeps_admin() -> None:
    mod = _mod()
    assert mod.groups_from_kc([{"name": "SystemAdminGroup"}]) == ["SystemAdminGroup"]
    assert mod.groups_from_kc([{"name": "/UserGroup"}]) == ["UserGroup"]
    assert mod.groups_from_kc([]) == ["UserGroup"]
    assert mod.groups_from_kc(
        [{"name": "UserGroup"}, {"name": "SystemAdminGroup"}]
    ) == ["UserGroup", "SystemAdminGroup"]


def test_handle_post_redirects_to_frontend_as_usergroup(monkeypatch) -> None:
    mod = _mod(
        PORTAL_LOGIN_HOSTS="portal.example.jp",
        FRONTEND_URL="https://app.example.jp",
    )

    async def fake_auth(ident: str, password: str):
        assert ident == "user@example.com"
        assert password == "password"
        return {
            "sub": "user",
            "email": "user@example.com",
            "name": "一般",
            "groups": ["UserGroup"],
        }

    monkeypatch.setattr(mod, "authenticate", fake_auth)
    audit = SimpleNamespace(record=lambda *a, **k: None)
    req = SimpleNamespace(
        headers={"host": "portal.example.jp"},
        url=SimpleNamespace(scheme="https"),
        form=AsyncMock(
            return_value={"ident": "user@example.com", "password": "password"}
        ),
    )
    error, location, user, ident = asyncio.run(
        mod.handle_post(req, mint_token=lambda **k: "tok", audit=audit)
    )
    assert error is None
    assert ident == "user@example.com"
    assert user["groups"] == ["UserGroup"]
    assert location == "https://app.example.jp/#token=tok"


def test_logout_sessions_posts_user_logout(monkeypatch) -> None:
    mod = _mod(KEYCLOAK_URL="http://kc.example/kc", KEYCLOAK_REALM="open-genai")
    calls: list[tuple[str, str]] = []

    class FakeResp:
        def __init__(self, status: int, payload: object | None = None) -> None:
            self.status_code = status
            self._payload = payload if payload is not None else {}

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError("http")

        def json(self) -> object:
            return self._payload

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, data: object = None, headers: object = None) -> FakeResp:
            del data, headers
            calls.append(("POST", url))
            if url.endswith("/protocol/openid-connect/token"):
                return FakeResp(200, {"access_token": "t"})
            if url.endswith("/users/uid-1/logout"):
                return FakeResp(204)
            return FakeResp(500)

        async def get(self, url: str, params: object = None, headers: object = None) -> FakeResp:
            del url, headers
            calls.append(("GET", str(params)))
            return FakeResp(200, [{"id": "uid-1", "username": "a", "email": "a@example.com"}])

    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)
    assert asyncio.run(mod.logout_sessions("a@example.com")) is True
    assert any(url.endswith("/users/uid-1/logout") for method, url in calls if method == "POST")


def test_logout_sessions_missing_user_is_false(monkeypatch) -> None:
    mod = _mod(KEYCLOAK_URL="http://kc.example/kc")

    class FakeResp:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> object:
            return {"access_token": "t"}

    class FakeClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, data: object = None, headers: object = None) -> FakeResp:
            del url, data, headers
            return FakeResp()

        async def get(self, url: str, params: object = None, headers: object = None) -> FakeResp:
            del url, params, headers
            empty = FakeResp()
            empty.json = lambda: []  # type: ignore[method-assign]
            return empty

    monkeypatch.setattr(mod.httpx, "AsyncClient", FakeClient)
    assert asyncio.run(mod.logout_sessions("nobody@example.com")) is False
