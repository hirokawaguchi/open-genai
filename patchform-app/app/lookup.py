"""郵便番号・法人番号の照会。入力は数字だけ受け、外部 URL は固定する。"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

LOOKUP_TIMEOUT = float(os.environ.get("PATCHFORM_LOOKUP_TIMEOUT", "8"))
ZIPCLOUD_URL = "https://zipcloud.ibsnet.co.jp/api/search"
GBIZ_URL = "https://info.gbiz.go.jp/hojin/v1/hojin/{number}"
GBIZ_USER_AGENT = "OpenGENAI-patchform/1.0"

_DIGITS_RE = re.compile(r"\D+")


def digits_only(value: str) -> str:
    return _DIGITS_RE.sub("", value or "")


def corporate_check_digit_ok(digits: str) -> bool:
    """法人番号13桁。先頭1桁が検査用数字。"""
    if len(digits) != 13 or not digits.isdigit():
        return False
    body = digits[1:]
    total = 0
    for i, ch in enumerate(reversed(body), start=1):
        total += int(ch) * (2 if i % 2 == 0 else 1)
    remainder = total % 9
    check = 0 if remainder == 0 else 9 - remainder
    return check == int(digits[0])


def yuucho_to_branch(symbol: str, number: str = "") -> dict[str, str]:
    """記号・番号から店番と口座番号（7桁）へ換算する。"""
    symbol_d = digits_only(symbol)
    number_d = digits_only(number)
    out: dict[str, str] = {
        "bank_code": "9900",
        "bank_name": "ゆうちょ銀行",
    }
    if len(symbol_d) == 5:
        out["branch_code"] = symbol_d[1:4]
    elif len(symbol_d) == 3:
        out["branch_code"] = symbol_d
    if number_d:
        out["account_number"] = number_d[-7:].zfill(7)
    return out


async def lookup_postal(zipcode: str) -> tuple[dict[str, Any] | None, str | None]:
    zip_d = digits_only(zipcode)
    if len(zip_d) != 7:
        return None, "郵便番号は7桁です"
    try:
        async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT) as client:
            res = await client.get(ZIPCLOUD_URL, params={"zipcode": zip_d})
            res.raise_for_status()
            data = res.json()
    except Exception as e:  # noqa: BLE001
        return None, f"郵便番号の検索に失敗しました: {e}"
    results = data.get("results") if isinstance(data, dict) else None
    if data.get("status") != 200 or not results:
        return None, "該当する住所が見つかりません"
    first = results[0]
    return {
        "postal_code": f"{zip_d[:3]}-{zip_d[3:]}",
        "prefecture": str(first.get("address1") or ""),
        "city": str(first.get("address2") or ""),
        "street": str(first.get("address3") or ""),
    }, None


def _gbiz_token() -> str:
    return (os.environ.get("PATCHFORM_GBIZ_TOKEN") or "").strip()


def _gbiz_headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": GBIZ_USER_AGENT}
    token = _gbiz_token()
    if token:
        headers["X-hojinInfo-api-token"] = token
    return headers


def _corporate_empty(corp: str) -> dict[str, str]:
    return {"corporate_number": corp, "company_name": ""}


async def lookup_corporate(number: str) -> tuple[dict[str, Any] | None, str | None]:
    corp = digits_only(number)
    if len(corp) != 13:
        return None, "法人番号は13桁です"
    if not corporate_check_digit_ok(corp):
        return None, "法人番号の検査数字が正しくありません"
    # gBizINFO は利用申請したトークン必須。無いと 500 になるので呼ばない。
    if not _gbiz_token():
        return _corporate_empty(corp), None
    try:
        async with httpx.AsyncClient(timeout=LOOKUP_TIMEOUT) as client:
            res = await client.get(GBIZ_URL.format(number=corp), headers=_gbiz_headers())
            if res.status_code >= 400:
                return _corporate_empty(corp), None
            data = res.json()
    except Exception:  # noqa: BLE001
        return _corporate_empty(corp), None
    infos = data.get("hojin-infos") if isinstance(data, dict) else None
    if not infos:
        return _corporate_empty(corp), None
    first = infos[0] if isinstance(infos[0], dict) else {}
    return {
        "corporate_number": corp,
        "company_name": str(first.get("name") or ""),
    }, None
