from __future__ import annotations

import json
import sqlite3

import pytest

from app import policy


@pytest.fixture
def policy_db(tmp_path, monkeypatch: pytest.MonkeyPatch):
    db_path = tmp_path / "policy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE model_policy ("
        " id INTEGER PRIMARY KEY CHECK (id = 1),"
        " policy TEXT NOT NULL,"
        " updatedDate TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO model_policy (id, policy, updatedDate) VALUES (1, ?, ?)",
        (
            json.dumps(
                {
                    "enabled": True,
                    "default": ["gpt-oss:20b"],
                    "teams": {"team-a": ["gemma3:27b"]},
                }
            ),
            "1",
        ),
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(policy, "POLICY_DB_PATH", str(db_path))
    policy._cache["mtime"] = None
    yield db_path
    policy._cache["mtime"] = None


def test_allowed_models_merges_default_and_team(policy_db) -> None:
    allowed = policy.allowed_models(["team-a"], is_admin=False)
    assert allowed == {"gpt-oss:20b", "gemma3:27b"}


def test_is_model_allowed_allows_admin_even_when_restricted(policy_db) -> None:
    assert policy.is_model_allowed(["team-a"], is_admin=True, model_id="blocked-model")


def test_is_model_allowed_rejects_unknown_model(policy_db) -> None:
    assert not policy.is_model_allowed(["team-a"], is_admin=False, model_id="unknown-model")
