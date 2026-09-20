"""登録時に棟を必須にする（自動付与の停止・棟の解決）。"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "teams-signup.db"))
    from app import teams_store as ts

    importlib.reload(ts)
    ts.init_db(seed_exapps=[])
    return ts


def test_login_only_user_gets_no_tenant(store) -> None:
    # チームにも棟にも属していない利用者（Keycloak だけ）
    assert store.get_active_tenant_id("newcomer@example.com") == store.NO_TENANT_ID
    assert store.list_tenants_for_user("newcomer@example.com") == []


def test_active_tenant_is_not_default_without_key(store) -> None:
    # デフォルト棟へ自動で落とさない
    active = store.get_active_tenant_id("stranger@example.com")
    assert active != store.DEFAULT_TENANT_ID
    assert active == store.NO_TENANT_ID


def test_find_org_tenant_by_name_and_id(store) -> None:
    t = store.create_tenant("能代市役所")
    assert store.find_org_tenant(t["tenantId"])["tenantId"] == t["tenantId"]
    assert store.find_org_tenant("能代市役所")["tenantId"] == t["tenantId"]
    assert store.find_org_tenant("  能代市役所 ")["tenantId"] == t["tenantId"]
    assert store.find_org_tenant("存在しない棟") is None


def test_find_org_tenant_rejects_shared(store) -> None:
    assert store.find_org_tenant(store.SHARED_TENANT_ID) is None
    assert store.find_org_tenant(store.SHARED_TENANT_NAME) is None


def test_register_assigns_primary_key(store) -> None:
    t = store.create_tenant("能代市役所")
    m = store.upsert_tenant_membership(
        t["tenantId"], "yamada@example.com", role=store.TENANT_ROLE_PRIMARY
    )
    assert m["role"] == "primary"
    assert store.get_active_tenant_id("yamada@example.com") == t["tenantId"]
    assert store.get_primary_tenant_name("yamada@example.com") == "能代市役所"


def test_primary_tenant_name_none_when_unaffiliated(store) -> None:
    assert store.get_primary_tenant_name("nobody@example.com") is None


def test_ensure_user_home_tenant_is_migration_only(store) -> None:
    # 移行用途では従来どおりデフォルト棟の主鍵を付けられる
    store.ensure_user_home_tenant("legacy@example.com")
    keys = {t["tenantId"] for t in store.list_tenants_for_user("legacy@example.com")}
    assert store.DEFAULT_TENANT_ID in keys
