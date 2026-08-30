"""全角数字・Mac 由来のハイフン類を、検証前に半角へ寄せる。"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Mac IME / 全角で混ざりやすいハイフン類（ASCII '-' 以外）
_HYPHENS = (
    "\u2010\u2011\u2012\u2013\u2014\u2015"  # hyphen, en/em dash, horizontal bar
    "\u2212\u2043\uFE58\uFE63\uFF0D"  # minus, hyphen bullet, small/fullwidth
)
_CHOON = "\u30FC\uFF70"  # ー ｰ （番地・電話でハイフン代わりに打たれやすい）

_HYPHEN_RE = re.compile(f"[{_HYPHENS}]")
_HYPHEN_OR_CHOON_RE = re.compile(f"[{_HYPHENS}{_CHOON}]")
_MULTI_HYPHEN_RE = re.compile(r"-{2,}")
_MULTI_SPACE_RE = re.compile(r" {2,}")
_POSTAL_DIGITS_RE = re.compile(r"^\d{7}$")


def _nfkc(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip()


def _hyphens(value: str, *, choon: bool) -> str:
    value = (_HYPHEN_OR_CHOON_RE if choon else _HYPHEN_RE).sub("-", value)
    return _MULTI_HYPHEN_RE.sub("-", value)


def normalize_digits(value: str) -> str:
    """数字だけ残す（法人番号・マイナンバー・金融機関コード）。"""
    value = _hyphens(_nfkc(value), choon=True)
    return re.sub(r"\D", "", value)


def normalize_postal(value: str) -> str:
    value = _hyphens(_nfkc(value), choon=True)
    value = re.sub(r"[^\d-]", "", value)
    digits = value.replace("-", "")
    if _POSTAL_DIGITS_RE.match(digits):
        return f"{digits[:3]}-{digits[3:]}"
    return value


def normalize_phone(value: str) -> str:
    value = _hyphens(_nfkc(value), choon=True)
    value = re.sub(r"[^\d+\-() ]", "", value)
    return _MULTI_SPACE_RE.sub(" ", value).strip()


def normalize_street(value: str) -> str:
    """番地: 数字は半角、ハイフン類は '-'。丁目・番・号はそのまま。"""
    value = _hyphens(_nfkc(value), choon=True)
    return _MULTI_SPACE_RE.sub(" ", value).strip()


def normalize_numeric(value: str) -> str:
    value = _hyphens(_nfkc(value), choon=False)
    return value.replace(",", "")


def normalize_nfkc(value: str) -> str:
    """建物名など。長音「ー」はハイフンにしない。"""
    return _nfkc(value)


_COMPOSITE_KIND: dict[str, dict[str, str]] = {
    "address_composite": {
        "postal_code": "postal",
        "street": "street",
        "building": "nfkc",
        "city": "nfkc",
        "prefecture": "nfkc",
    },
    "company_info_composite": {"corporate_number": "digits"},
    "financial_institution_composite": {
        "bank_code": "digits",
        "branch_code": "digits",
        "account_number": "digits",
        "yuucho_symbol": "digits",
        "yuucho_number": "digits",
    },
}

_KIND_FN = {
    "digits": normalize_digits,
    "postal": normalize_postal,
    "phone": normalize_phone,
    "street": normalize_street,
    "numeric": normalize_numeric,
    "nfkc": normalize_nfkc,
}


def apply_kind(value: str, kind: str) -> str:
    fn = _KIND_FN.get(kind)
    return fn(value) if fn else value


def canonicalize(comp: dict[str, Any], raw: Any) -> Any:
    """検証・保存の前に入力を寄せる。"""
    ctype = comp.get("type")
    if isinstance(raw, str):
        if ctype == "phone":
            return normalize_phone(raw)
        if ctype == "mynumber":
            return normalize_digits(raw)
        if ctype == "number":
            return normalize_numeric(raw)
        if ctype == "email":
            return normalize_nfkc(raw)
        return raw
    if isinstance(raw, dict) and ctype in _COMPOSITE_KIND:
        kinds = _COMPOSITE_KIND[ctype]
        out = dict(raw)
        for key, kind in kinds.items():
            if key in out and out[key] is not None:
                out[key] = apply_kind(str(out[key]), kind)
        return out
    return raw
