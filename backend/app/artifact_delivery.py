"""成果物の配信方式（直接ダウンロード / リンクファイル）。

ARTIFACT_DELIVERY_MODE:
  - open    : 常に署名付き URL を返す（直接ダウンロード）
  - carrier : 常にリンクファイルへ寄せる
  - auto    : アクセス Host が LGWAN FQDN（*.lgwan.jp）なら carrier、それ以外は open
"""

from __future__ import annotations

from typing import Any, Literal

Delivery = Literal["open", "carrier"]
Policy = Literal["open", "carrier", "auto"]

VALID_POLICIES: tuple[str, ...] = ("open", "carrier", "auto")


def _request_host(request: Any) -> str:
    headers = getattr(request, "headers", {}) or {}
    forwarded = (headers.get("x-forwarded-host") or "").split(",")[0].strip()
    raw = forwarded or (headers.get("host") or "")
    return raw.split(":")[0].strip().lower()


def normalize_mode(raw: str | None) -> Policy:
    mode = (raw or "open").strip().lower()
    if mode in VALID_POLICIES:
        return mode  # type: ignore[return-value]
    return "open"


def is_lgwan_fqdn(host: str) -> bool:
    """Host が LGWAN 面かどうか（サイト固有 FQDN に依存しない）。"""
    h = (host or "").strip().lower().split(":")[0].rstrip(".")
    return h == "lgwan.jp" or h.endswith(".lgwan.jp")


def resolve_delivery(mode: str, request: Any) -> Delivery:
    """このリクエストで UI に載せる配信（open / carrier）。"""
    policy = normalize_mode(mode)
    if policy == "carrier":
        return "carrier"
    if policy == "open":
        return "open"
    host = _request_host(request)
    return "carrier" if is_lgwan_fqdn(host) else "open"


def use_carrier(mode: str, request: Any) -> bool:
    return resolve_delivery(mode, request) == "carrier"
