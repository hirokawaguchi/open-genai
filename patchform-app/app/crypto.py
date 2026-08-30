"""機微項目（マイナンバー）の保存時暗号化。"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

_fernet: Fernet | None = None


def _key() -> bytes:
    raw = os.environ.get("PATCHFORM_ENCRYPT_KEY") or ""
    if raw:
        try:
            return raw.encode("ascii")
        except UnicodeEncodeError:
            pass
    secret = os.environ.get("INTERNAL_SIGNING_SECRET") or "dev-patchform-encrypt"
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_key())
    return _fernet


def reset() -> None:
    global _fernet
    _fernet = None


def encrypt_value(plain: str) -> str:
    return fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_value(token: str) -> str:
    try:
        return fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""


def mask_mynumber(plain: str) -> str:
    digits = "".join(ch for ch in plain if ch.isdigit())
    if len(digits) < 4:
        return "************"
    return "*" * 8 + digits[-4:]


def protect_answers(definition: dict[str, Any], answers: dict[str, Any]) -> dict[str, Any]:
    out = dict(answers)
    for comp in definition.get("components") or []:
        if comp.get("type") != "mynumber":
            continue
        cid = comp["id"]
        raw = out.get(cid)
        if isinstance(raw, str) and raw and not raw.startswith("gAAAA"):
            out[cid] = encrypt_value(raw)
    return out


def reveal_answers(
    definition: dict[str, Any],
    answers: dict[str, Any],
    *,
    mask: bool,
) -> dict[str, Any]:
    out = dict(answers)
    for comp in definition.get("components") or []:
        if comp.get("type") != "mynumber":
            continue
        cid = comp["id"]
        raw = out.get(cid)
        if not isinstance(raw, str) or not raw:
            continue
        plain = decrypt_value(raw) if raw.startswith("gAAAA") else raw
        out[cid] = mask_mynumber(plain) if mask else plain
    return out
