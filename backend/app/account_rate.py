"""ログイン済みアカウントごとの API 回数。

接続元 IP を分けても、同じアカウントの予算は増えない。
エディタは 1.5 秒ごとに状態を見るので、既定は 1 分に 300 件。
0 以下で無効。カウントはプロセス内のメモリ（ワーカーが複数なら枠も分かれる）。
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any

# 1.5 秒間隔の確認に、もう一つの確認と画面を開いたときのまとめての取得が重なっても通る量。
DEFAULT_LIMIT = 300
DEFAULT_WINDOW_SEC = 60


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default


class AccountRateLimiter:
    def __init__(self, limit: int, window_sec: float) -> None:
        self.limit = limit
        self.window_sec = window_sec
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        if self.limit <= 0 or self.window_sec <= 0 or not key:
            return True
        moment = time.monotonic() if now is None else now
        cutoff = moment - self.window_sec
        with self._lock:
            bucket = self._hits.get(key)
            if bucket is None:
                bucket = deque()
                self._hits[key] = bucket
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if not bucket:
                self._hits.pop(key, None)
                bucket = deque()
                self._hits[key] = bucket
            if len(bucket) >= self.limit:
                return False
            bucket.append(moment)
            return True

    def retry_after(self, key: str, now: float | None = None) -> int:
        if self.window_sec <= 0:
            return 1
        moment = time.monotonic() if now is None else now
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return 1
            wait = bucket[0] + self.window_sec - moment
        return max(1, int(wait + 0.999))


_limiter: AccountRateLimiter | None = None
_limiter_lock = threading.Lock()


def limiter() -> AccountRateLimiter:
    global _limiter
    if _limiter is not None:
        return _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = AccountRateLimiter(
                _int_env("API_ACCOUNT_RATE_LIMIT", DEFAULT_LIMIT),
                float(_int_env("API_ACCOUNT_RATE_WINDOW_SEC", DEFAULT_WINDOW_SEC)),
            )
        return _limiter


def reset_limiter() -> None:
    """テストが環境変数を変えたあと、次の limiter() で読み直す。"""
    global _limiter
    with _limiter_lock:
        _limiter = None


def account_key(claims: dict[str, Any] | None) -> str:
    if not claims:
        return ""
    email = str(claims.get("email") or "").strip().lower()
    if email:
        return email
    return str(claims.get("sub") or "").strip().lower()
