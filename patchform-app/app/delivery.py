"""確定した申請を、手続きに書いた受け口へ送る。

鍵と URL は手続きのサーバ側設定である。応答と履歴には鍵を残さない。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

_TIMEOUT = 12.0


def empty_target() -> dict[str, Any]:
    return {"url": "", "key": "", "send_mynumber": False}


def normalize_target(
    raw: Any, *, previous: dict[str, Any] | None = None
) -> tuple[dict[str, Any] | None, str | None]:
    """URL と鍵。鍵を空で渡したときは、保存済みの鍵を残す。"""
    prev = previous or empty_target()
    if raw is None:
        return dict(prev), None
    if not isinstance(raw, dict):
        return None, "受け口の設定を読めません"
    url = str(raw["url"] if "url" in raw else prev.get("url") or "").strip()
    if url:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return None, "受け口の URL は http か https で書いてください"
        if parsed.username or parsed.password:
            return None, "受け口の URL にパスワードは含めないでください"
        if len(url) > 500:
            return None, "受け口の URL が長すぎます"
    key = str(prev.get("key") or "")
    if "key" in raw:
        given = str(raw.get("key") or "").strip()
        if given:
            if len(given) > 200:
                return None, "受け口の鍵が長すぎます"
            key = given
    send = bool(prev.get("send_mynumber"))
    if "send_mynumber" in raw:
        send = bool(raw.get("send_mynumber"))
    return {"url": url, "key": key, "send_mynumber": send}, None


def public_target(stored: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": str(stored.get("url") or ""),
        "key_set": bool(str(stored.get("key") or "").strip()),
        "send_mynumber": bool(stored.get("send_mynumber")),
    }


def post_confirmed(
    *,
    url: str,
    key: str,
    idempotency_key: str,
    body: dict[str, Any],
) -> dict[str, Any]:
    """確定版を1回送る。同じ冪等キーで送り直せる。"""
    if not (url or "").strip():
        return {"ok": False, "receipt_no": "", "detail": "受け口の URL が未設定です"}
    headers = {
        "Idempotency-Key": idempotency_key,
        "Content-Type": "application/json",
    }
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        res = httpx.post(
            url,
            json=body,
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=False,
        )
    except httpx.HTTPError:
        return {"ok": False, "receipt_no": "", "detail": "受け口に接続できませんでした"}
    if 200 <= res.status_code < 300 or res.status_code == 409:
        return {"ok": True, "receipt_no": _receipt_no(res), "detail": "送りました"}
    return {
        "ok": False,
        "receipt_no": "",
        "detail": f"受け口が {res.status_code} を返しました",
    }


def _receipt_no(res: httpx.Response) -> str:
    try:
        data = res.json()
    except ValueError:
        return ""
    if not isinstance(data, dict):
        return ""
    for name in ("receipt_no", "receipt", "acceptance_number", "id"):
        value = data.get(name)
        if isinstance(value, (str, int)) and str(value).strip():
            return str(value).strip()[:80]
    return ""
