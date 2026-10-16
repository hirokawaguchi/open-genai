from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app import wm_gate


def test_sign_roundtrip() -> None:
    token = wm_gate.sign("secret", "user-1", now=1_000)
    assert wm_gate.user_id_from_token("secret", token, now=1_000) == "user-1"


def test_user_id_may_contain_dots() -> None:
    token = wm_gate.sign("secret", "a.b@example.jp", now=1_000)
    assert wm_gate.user_id_from_token("secret", token, now=1_000) == "a.b@example.jp"


def test_expired_token_is_rejected() -> None:
    token = wm_gate.sign("secret", "user-1", now=1_000)
    later = 1_000 + wm_gate.TTL_SECONDS + 1
    assert wm_gate.user_id_from_token("secret", token, now=later) is None


def test_tampered_token_is_rejected() -> None:
    token = wm_gate.sign("secret", "user-1", now=1_000)
    assert wm_gate.user_id_from_token("other", token, now=1_000) is None
    assert wm_gate.user_id_from_token("secret", token + "x", now=1_000) is None
