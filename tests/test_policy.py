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
                    "teams": {"team-a": ["model-b"]},
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
    assert allowed == {"gpt-oss:20b", "model-b"}


def test_is_model_allowed_allows_admin_even_when_restricted(policy_db) -> None:
    assert policy.is_model_allowed(["team-a"], is_admin=True, model_id="blocked-model")


def test_is_model_allowed_rejects_unknown_model(policy_db) -> None:
    assert not policy.is_model_allowed(["team-a"], is_admin=False, model_id="unknown-model")


@pytest.fixture
def policy_db_v2(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """棟別(v2)テーブルを持つ DB。既定の棟と別の棟で異なる設定を入れる。"""
    db_path = tmp_path / "policy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE model_policy_v2 ("
        " tenantId TEXT PRIMARY KEY,"
        " policy TEXT NOT NULL,"
        " updatedDate TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO model_policy_v2 (tenantId, policy, updatedDate) VALUES (?, ?, ?)",
        (
            policy.DEFAULT_TENANT_ID,
            json.dumps(
                {"enabled": True, "default": ["gpt-oss:20b"], "teams": {"team-a": ["model-b"]}}
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


def test_default_tenant_uses_its_own_policy(policy_db_v2) -> None:
    allowed = policy.allowed_models(
        ["team-a"], is_admin=False, tenant_id=policy.DEFAULT_TENANT_ID
    )
    assert allowed == {"gpt-oss:20b", "model-b"}


def test_other_tenant_is_unrestricted_when_no_row(policy_db_v2) -> None:
    # 行の無い棟は制限なし（None = 無制限）。
    allowed = policy.allowed_models(
        ["team-a"], is_admin=False, tenant_id="00000000-0000-0000-0000-00000000ffff"
    )
    assert allowed is None
    assert policy.is_model_allowed(
        ["team-a"], is_admin=False, model_id="anything",
        tenant_id="00000000-0000-0000-0000-00000000ffff",
    )


def test_default_tenant_falls_back_to_legacy_single_row(policy_db) -> None:
    # v2 が無い（writer 未更新）場合、既定の棟は旧・単一行を読む。
    allowed = policy.allowed_models(
        ["team-a"], is_admin=False, tenant_id=policy.DEFAULT_TENANT_ID
    )
    assert allowed == {"gpt-oss:20b", "model-b"}
