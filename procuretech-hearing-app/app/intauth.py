"""内部サービス間認証（backend → exApp）。navigator と同内容。"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

SECRET = os.environ.get("INTERNAL_SIGNING_SECRET", "")
MAX_AGE = int(os.environ.get("INTERNAL_SIG_MAX_AGE", "300"))


def _norm(values: str | None) -> str:
    return ",".join(sorted(x.strip() for x in (values or "").split(",") if x.strip()))


def _canonical(
    user_id: str | None,
    groups: str | None,
    scope: str | None,
    ts: str,
    tags: str | None = None,
) -> str:
    return f"{user_id or ''}\n{_norm(groups)}\n{scope or ''}\n{_norm(tags)}\n{ts}"


def _compute(
    user_id: str | None,
    groups: str | None,
    scope: str | None,
    ts: str,
    tags: str | None = None,
) -> str:
    return hmac.new(
        SECRET.encode("utf-8"),
        _canonical(user_id, groups, scope, ts, tags).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify(
    user_id: str | None,
    groups: str | None,
    scope: str | None,
    ts: str | None,
    sig: str | None,
    tags: str | None = None,
) -> bool:
    if not SECRET:
        return True
    if not ts or not sig:
        return False
    try:
        if abs(int(time.time()) - int(ts)) > MAX_AGE:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(_compute(user_id, groups, scope, ts, tags), sig)
