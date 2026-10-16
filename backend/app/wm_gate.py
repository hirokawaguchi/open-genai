"""World Monitor 画面用の入場クッキー。

ブラウザの iframe は Authorization を付けられない。ログイン済みの
`/worldmonitor/config` が HttpOnly クッキーを出し、nginx の auth_request が
`/worldmonitor/gate` で検証する。
"""

from __future__ import annotations

import hashlib
import hmac
import time

COOKIE = "og_wm"
TTL_SECONDS = 8 * 60 * 60


def sign(secret: str, user_id: str, *, now: int | None = None) -> str:
    uid = (user_id or "").strip()
    if not uid or not secret:
        raise ValueError("user_id と secret が必要です")
    exp = (int(time.time()) if now is None else now) + TTL_SECONDS
    body = f"{uid}.{exp}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def user_id_from_token(secret: str, token: str, *, now: int | None = None) -> str | None:
    """正しければ利用者 ID。期限切れ・改ざん・空は None。"""
    if not secret or not token:
        return None
    # 利用者 ID はドットを含みうる。期限と署名は末尾の 2 区切り。
    uid, exp_s, sig = (token.rsplit(".", 2) + ["", ""])[:3]
    if token.count(".") < 2 or not uid or not exp_s or not sig:
        return None
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    current = int(time.time()) if now is None else now
    if exp < current:
        return None
    body = f"{uid}.{exp_s}"
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    return uid
