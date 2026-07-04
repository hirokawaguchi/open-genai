from __future__ import annotations

from conftest import load_service_module


def test_ngrules_parse_and_validate_accepts_valid_rules() -> None:
    ngrules = load_service_module("ngword-app/app/ngrules.py")
    rules, error = ngrules.parse_and_validate(
        '{"enabled": true, "words": ["bad"], "patterns": ["\\\\d+"]}'
    )
    assert error is None
    assert rules is not None
    assert rules["enabled"] is True
    assert rules["words"] == ["bad"]


def test_ngrules_parse_and_validate_rejects_invalid_regex() -> None:
    ngrules = load_service_module("ngword-app/app/ngrules.py")
    rules, error = ngrules.parse_and_validate('{"enabled": true, "patterns": ["("]}')
    assert rules is None
    assert error is not None
    assert "正規表現" in error


def test_policystore_parse_and_validate_accepts_team_policy() -> None:
    policystore = load_service_module("modelpolicy-app/app/policystore.py")
    policy, error = policystore.parse_and_validate(
        '{"enabled": true, "default": ["gpt-oss:20b"], "teams": {"team-a": ["gemma3:27b"]}}'
    )
    assert error is None
    assert policy is not None
    assert policy["teams"]["team-a"] == ["gemma3:27b"]


def test_policystore_parse_and_validate_rejects_invalid_default() -> None:
    policystore = load_service_module("modelpolicy-app/app/policystore.py")
    policy, error = policystore.parse_and_validate('{"enabled": true, "default": "not-a-list"}')
    assert policy is None
    assert error is not None
    assert "default" in error
