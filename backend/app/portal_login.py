"""インターネット入口ホスト専用ログイン（Keycloak の ID/PW）。

PORTAL_LOGIN_HOSTS に含まれる Host のときだけフォームを出す。
照合は Keycloak（SAML と同じアカウント）。権限は Keycloak の所属グループ
（UserGroup / SystemAdminGroup 等）。グループが空なら UserGroup。
成功後の戻り先は FRONTEND_URL（未設定なら PUBLIC_URL）。入口 FQDN ではアプリを開かない。
"""

from __future__ import annotations

import html
import os
from typing import Any
from urllib.parse import urlparse

import httpx

DEFAULT_GROUP = "UserGroup"
_FORM_ERROR = "ユーザー名またはパスワードが正しくありません。"


def request_host(request: Any) -> str:
    forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    raw = forwarded or (request.headers.get("host") or "")
    return raw.split(":")[0].strip().lower()


def portal_hosts() -> set[str]:
    raw = os.environ.get("PORTAL_LOGIN_HOSTS") or ""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def enabled(request: Any) -> bool:
    hosts = portal_hosts()
    if not hosts:
        return False
    return request_host(request) in hosts


def app_home() -> str:
    return (os.environ.get("FRONTEND_URL") or os.environ.get("PUBLIC_URL") or "").rstrip("/")


def _kc_url() -> str:
    return (
        os.environ.get("KEYCLOAK_URL")
        or os.environ.get("KEYCLOAK_INTERNAL_URL")
        or "http://keycloak:8080/kc"
    ).rstrip("/")


def _kc_realm() -> str:
    return os.environ.get("KEYCLOAK_REALM") or "open-genai"


def _kc_password_client() -> str:
    return os.environ.get("KEYCLOAK_PASSWORD_VERIFY_CLIENT") or "admin-cli"


async def _admin_token(client: httpx.AsyncClient) -> str:
    res = await client.post(
        f"{_kc_url()}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": os.environ.get("KEYCLOAK_ADMIN_CLIENT") or "admin-cli",
            "username": os.environ.get("KEYCLOAK_ADMIN") or "admin",
            "password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD") or "",
        },
    )
    res.raise_for_status()
    return str(res.json()["access_token"])


async def _password_ok(client: httpx.AsyncClient, username: str, password: str) -> bool:
    if not username or not password:
        return False
    try:
        res = await client.post(
            f"{_kc_url()}/realms/{_kc_realm()}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": _kc_password_client(),
                "username": username,
                "password": password,
            },
        )
    except httpx.HTTPError:
        return False
    return res.status_code == 200


def groups_from_kc(rows: Any) -> list[str]:
    names: list[str] = []
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        name = (item.get("name") or "").strip().lstrip("/")
        if name and name not in names:
            names.append(name)
    return names or [DEFAULT_GROUP]


async def _user_groups(client: httpx.AsyncClient, token: str, user_id: str) -> list[str]:
    res = await client.get(
        f"{_kc_url()}/admin/realms/{_kc_realm()}/users/{user_id}/groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    if res.status_code != 200:
        return [DEFAULT_GROUP]
    return groups_from_kc(res.json())


async def _lookup_user(client: httpx.AsyncClient, token: str, ident: str) -> dict[str, Any] | None:
    headers = {"Authorization": f"Bearer {token}"}
    base = f"{_kc_url()}/admin/realms/{_kc_realm()}/users"
    for param in ({"username": ident, "exact": "true"}, {"email": ident, "exact": "true"}):
        res = await client.get(base, params=param, headers=headers)
        if res.status_code != 200:
            continue
        rows = res.json()
        if isinstance(rows, list) and rows:
            return rows[0]
    return None


async def authenticate(ident: str, password: str) -> dict[str, Any] | None:
    ident = (ident or "").strip()
    if not ident or not password:
        return None
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            if not await _password_ok(client, ident, password):
                token = await _admin_token(client)
                found = await _lookup_user(client, token, ident)
                username = str((found or {}).get("username") or "")
                if not username or username == ident or not await _password_ok(client, username, password):
                    return None
            else:
                token = await _admin_token(client)
                found = await _lookup_user(client, token, ident)
            if not found:
                return None
            if found.get("enabled") is False:
                return None
            email = (found.get("email") or found.get("username") or ident).strip()
            first = (found.get("firstName") or "").strip()
            last = (found.get("lastName") or "").strip()
            name = f"{last}{first}".strip() or str(found.get("username") or email)
            groups = await _user_groups(client, token, str(found.get("id") or ""))
            try:
                from . import teams_store

                for ident_key in (email, str(found.get("username") or "")):
                    if (
                        teams_store.user_admins_any_team(ident_key)
                        and "TeamAdminGroup" not in groups
                    ):
                        groups.append("TeamAdminGroup")
                        break
            except Exception as exc:  # noqa: BLE001
                print(f"[portal-login] チーム管理者判定をスキップ: {exc}")
            return {
                "sub": str(found.get("username") or email),
                "email": email,
                "name": name,
                "groups": groups,
            }
    except Exception as exc:  # noqa: BLE001
        print(f"[portal-login] Keycloak 照合に失敗: {exc}")
        return None


def login_form(request: Any, *, error: str = "", ident: str = "") -> str:
    del request
    title = (os.environ.get("APP_TITLE") or os.environ.get("VITE_APP_TITLE") or "Open GENAI").strip()
    title = title or "Open GENAI"
    err_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="robots" content="noindex" />
  <title>ログイン | {html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: sans-serif; background: #fff; color: #333; }}
    .wrap {{ max-width: 22rem; margin: 4rem auto; padding: 0 1rem; }}
    h1 {{ font-size: 1.1rem; font-weight: 700; letter-spacing: .04em; }}
    label {{ display: block; margin: 1rem 0 .3rem; font-size: .9rem; }}
    input {{ width: 100%; box-sizing: border-box; padding: .5rem .6rem; border: 1px solid #ccc; }}
    button {{ width: 100%; margin-top: 1.2rem; padding: .7rem; border: 0; background: #0066cc; color: #fff; font-size: 1rem; cursor: pointer; }}
    .err {{ color: #b00020; font-size: .9rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(title)}</h1>
    <p>ログイン</p>
    {err_html}
    <form method="post" action="/api/auth/portal" autocomplete="on">
      <label for="ident">Username or email</label>
      <input id="ident" name="ident" type="text" required value="{html.escape(ident)}" />
      <label for="password">Password</label>
      <input id="password" name="password" type="password" required />
      <button type="submit">Sign In</button>
    </form>
  </div>
</body>
</html>
"""


async def handle_post(
    request: Any,
    *,
    mint_token,
    audit,
) -> tuple[str | None, str, dict[str, Any] | None, str]:
    form = await request.form()
    ident = str(form.get("ident") or form.get("email") or "")
    password = str(form.get("password") or "")
    home = app_home()
    if not home:
        parsed = urlparse(str(request.url))
        home = f"{parsed.scheme}://{request_host(request)}"
    user = await authenticate(ident, password)
    if not user:
        audit.record(
            request,
            action="auth.login",
            status=401,
            output_text="ポータルログイン失敗",
        )
        return _FORM_ERROR, "", None, ident
    token = mint_token(
        sub=user["sub"],
        email=user["email"],
        name=user["name"],
        groups=list(user["groups"]),
        session_index=None,
    )
    audit.record(
        request,
        action="auth.login",
        status=200,
        user_id=user["sub"],
        user_email=user["email"],
        user_name=user["name"],
        groups=user["groups"],
    )
    return None, f"{home}/#token={token}", user, ident
