from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import wm_gate

_SID = "11111111-2222-3333-4444-555555555555"


def test_sign_roundtrip() -> None:
    token = wm_gate.sign("secret", _SID, now=1_000)
    assert wm_gate.session_id_from_token("secret", token, now=1_000) == _SID


def test_sign_rejects_sid_with_dots() -> None:
    with pytest.raises(ValueError):
        wm_gate.sign("secret", "a.b@example.jp", now=1_000)


def test_expired_token_is_rejected() -> None:
    token = wm_gate.sign("secret", _SID, now=1_000)
    later = 1_000 + wm_gate.TTL_SECONDS + 1
    assert wm_gate.session_id_from_token("secret", token, now=later) is None


def test_tampered_token_is_rejected() -> None:
    token = wm_gate.sign("secret", _SID, now=1_000)
    assert wm_gate.session_id_from_token("other", token, now=1_000) is None
    assert wm_gate.session_id_from_token("secret", token + "x", now=1_000) is None
