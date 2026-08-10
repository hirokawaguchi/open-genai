"""添付ファイル URL の短命 HMAC 署名。

`/files/{key}` は img タグ等のため Authorization ヘッダを付けられない。
代わりにクエリ `exp` / `sig` で method+key を署名し、漏洩した key だけでは
読み書きできないようにする。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

# 未設定時は APP_JWT_SECRET を流用（auth モジュールは重い依存のためここでは import しない）
FILES_URL_SECRET = os.environ.get("FILES_URL_SECRET") or os.environ.get(
    "APP_JWT_SECRET", "change-me-open-genai-secret"
)

TTL_PUT = int(os.environ.get("FILES_URL_TTL_PUT", "900"))  # 15 分
TTL_GET = int(os.environ.get("FILES_URL_TTL_GET", "3600"))  # 1 時間
TTL_DELETE = int(os.environ.get("FILES_URL_TTL_DELETE", "900"))

_METHOD_TTL = {
    "PUT": TTL_PUT,
    "GET": TTL_GET,
    "DELETE": TTL_DELETE,
}


def _sign_payload(method: str, key: str, exp: int) -> str:
    msg = f"{method.upper()}\n{key}\n{exp}".encode("utf-8")
    return hmac.new(FILES_URL_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def sign_query(method: str, key: str, ttl: int | None = None) -> dict[str, str]:
    """署名クエリ (exp, sig) を返す。"""
    method_u = method.upper()
    if ttl is None:
        ttl = _METHOD_TTL.get(method_u, TTL_GET)
    exp = int(time.time()) + max(1, int(ttl))
    return {"exp": str(exp), "sig": _sign_payload(method_u, key, exp)}


def build_signed_url(base_url: str, key: str, method: str, ttl: int | None = None) -> str:
    """`{base}/files/{key}?exp=...&sig=...` を組み立てる。"""
    q = urlencode(sign_query(method, key, ttl=ttl))
    return f"{base_url.rstrip('/')}/files/{key}?{q}"


def verify(method: str, key: str, exp: str | None, sig: str | None) -> bool:
    """署名と有効期限を検証する。"""
    if not exp or not sig:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expected = _sign_payload(method.upper(), key, exp_i)
    return hmac.compare_digest(expected, sig)
