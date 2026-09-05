"""運用者ホスト専用の ID/PW ログイン（Keycloak とは別経路）。

OPERATOR_LOGIN_HOSTS に含まれる Host かつ OPERATOR_USERS が空でないときだけ有効。
それ以外は呼び出し側が従来の SAML へ進む。
"""

from __future__ import annotations

import html
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import bcrypt

def normalize_email(email: str | None) -> str:
    return (email or "").strip().lower()


_FORM_ERROR = "メールアドレスまたはパスワードが正しくありません。"


def request_host(request: Any) -> str:
    forwarded = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    raw = forwarded or (request.headers.get("host") or "")
    return raw.split(":")[0].strip().lower()


def operator_hosts() -> set[str]:
    raw = os.environ.get("OPERATOR_LOGIN_HOSTS") or ""
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def load_users() -> list[dict[str, Any]]:
    raw = (os.environ.get("OPERATOR_USERS") or "").strip()
    users_file = (os.environ.get("OPERATOR_USERS_FILE") or "").strip()
    if users_file and Path(users_file).is_file():
        raw = Path(users_file).read_text(encoding="utf-8").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print("[ops-login] OPERATOR_USERS の JSON が不正です")
        return []
    if not isinstance(data, list):
        return []
    users: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        email = normalize_email(str(item.get("email") or ""))
        # compose の $$ エスケープや二重エスケープを吸収する
        password_hash = str(item.get("password_hash") or "").strip().replace("$$", "$")
        if not email or not password_hash:
            continue
        groups = item.get("groups") or ["SystemAdminGroup"]
        if not isinstance(groups, list):
            groups = ["SystemAdminGroup"]
        users.append(
            {
                "email": email,
                "name": str(item.get("name") or email).strip() or email,
                "password_hash": password_hash,
                "groups": [str(g) for g in groups if str(g).strip()],
            }
        )
    return users


def enabled(request: Any) -> bool:
    hosts = operator_hosts()
    if not hosts or not load_users():
        return False
    return request_host(request) in hosts


def request_origin(request: Any) -> str:
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    if proto not in ("http", "https"):
        proto = "https"
    host = request_host(request) or "localhost"
    return f"{proto}://{host}"


def safe_redirect(request: Any, relay: str | None) -> str:
    """オープンリダイレクト防止。同一 Host または運用者ホストのみ許可。"""
    fallback = request_origin(request)
    if not relay:
        return fallback
    parsed = urlparse(str(relay).strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        return fallback
    allowed = operator_hosts() | {request_host(request)}
    if host not in allowed:
        return fallback
    return f"{parsed.scheme}://{parsed.netloc}"


def signed_out_url(request: Any, claims: dict[str, Any] | None = None) -> str:
    del claims  # 戻り先はリクエストの Host。FRONTEND_URL（LGWAN）へ飛ばさない。
    return f"{request_origin(request)}/signed-out"


def verify_password(password: str, password_hash: str) -> bool:
    if not password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


def find_user(email: str) -> dict[str, Any] | None:
    want = normalize_email(email)
    if not want:
        return None
    for user in load_users():
        if user["email"] == want:
            return user
    return None


def login_form(request: Any, *, error: str = "", email: str = "") -> str:
    title = (os.environ.get("APP_TITLE") or os.environ.get("VITE_APP_TITLE") or "Oita GENAI").strip()
    title = title or "Oita GENAI"
    relay = safe_redirect(request, request.query_params.get("redirect"))
    err_html = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="robots" content="noindex" />
  <title>運用者ログイン | {html.escape(title)}</title>
  <style>
    body {{ margin: 0; font-family: sans-serif; background: #fff; color: #333; }}
    .wrap {{ max-width: 22rem; margin: 4rem auto; padding: 0 1rem; }}
    h1 {{ font-size: 1.1rem; font-weight: 700; letter-spacing: .04em; }}
    label {{ display: block; margin: 1rem 0 .3rem; font-size: .9rem; }}
    input {{ width: 100%; box-sizing: border-box; padding: .5rem .6rem; border: 1px solid #ccc; }}
    button {{ width: 100%; margin-top: 1.2rem; padding: .7rem; border: 0; background: #0066cc; color: #fff; font-size: 1rem; cursor: pointer; }}
    .err {{ color: #b00020; font-size: .9rem; }}
    .note {{ margin-top: 1.5rem; color: #666; font-size: .8rem; }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{html.escape(title.upper())}</h1>
    <p>運用者ログイン</p>
    {err_html}
    <form method="post" action="/api/auth/ops" autocomplete="on">
      <input type="hidden" name="redirect" value="{html.escape(relay, quote=True)}" />
      <label for="email">Username or email</label>
      <input id="email" name="email" type="email" required value="{html.escape(email)}" />
      <label for="password">Password</label>
      <input id="password" name="password" type="password" required />
      <button type="submit">Sign In</button>
    </form>
    <p class="note">この画面は運用者ホスト専用です。</p>
  </div>
</body>
</html>
"""


async def handle_post(
    request: Any,
    *,
    mint_token,
    audit,
) -> tuple[str | None, str, dict[str, Any] | None]:
    """成功時 (None, token_redirect, user)。失敗時 (error, '', None)。Host 不一致は呼び出し側で 404。"""
    form = await request.form()
    email = str(form.get("email") or "")
    password = str(form.get("password") or "")
    relay = safe_redirect(request, str(form.get("redirect") or "") or request.query_params.get("redirect"))
    user = find_user(email)
    if not user or not verify_password(password, user["password_hash"]):
        audit.record(
            request,
            action="auth.login",
            status=401,
            output_text="運用者ログイン失敗",
        )
        return _FORM_ERROR, "", None
    token = mint_token(
        sub=user["email"],
        email=user["email"],
        name=user["name"],
        groups=list(user["groups"]),
        session_index=None,
    )
    audit.record(
        request,
        action="auth.login",
        status=200,
        user_id=user["email"],
        user_email=user["email"],
        user_name=user["name"],
        groups=user["groups"],
    )
    return None, f"{relay.rstrip('/')}/#token={token}", user
