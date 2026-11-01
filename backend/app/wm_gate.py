"""World Monitor 画面用の入場クッキー。

ブラウザの iframe は Authorization を付けられない。ログイン済みの
`/worldmonitor/config` が HttpOnly クッキーを出し、nginx の auth_request が
`/worldmonitor/gate` で検証する。クッキーはアプリのセッション ID を含み、
そのセッションを切ると入場できなくなる。
"""

from __future__ import annotations

import hashlib
import hmac
import time

COOKIE = "og_wm"
TTL_SECONDS = 8 * 60 * 60


def sign(secret: str, sid: str, *, now: int | None = None) -> str:
    """入場クッキーはアプリのセッション ID に紐づける。切れるとクッキーも無効。"""
    session_id = (sid or "").strip()
    if not session_id or "." in session_id or not secret:
        raise ValueError("sid と secret が必要です")
    exp = (int(time.time()) if now is None else now) + TTL_SECONDS
    body = f"{session_id}.{exp}"
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def session_id_from_token(secret: str, token: str, *, now: int | None = None) -> str | None:
    """正しければセッション ID。期限切れ・改ざん・空は None。"""
    if not secret or not token:
        return None
    sid, exp_s, sig = (token.rsplit(".", 2) + ["", ""])[:3]
    if token.count(".") < 2 or not sid or "." in sid or not exp_s or not sig:
        return None
    try:
        exp = int(exp_s)
    except ValueError:
        return None
    current = int(time.time()) if now is None else now
    if exp < current:
        return None
    body = f"{sid}.{exp_s}"
    expected = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    return sid
