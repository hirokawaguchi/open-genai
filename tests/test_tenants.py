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
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "teams-tenants.db"))
    from app import teams_store as ts

    importlib.reload(ts)
    ts.init_db(seed_exapps=[])
    return ts


def test_seed_default_and_shared(store) -> None:
    tenants = {t["tenantId"]: t for t in store.list_tenants()}
    assert store.DEFAULT_TENANT_ID in tenants
    assert store.SHARED_TENANT_ID in tenants
    assert tenants[store.DEFAULT_TENANT_ID]["kind"] == "org"
    assert tenants[store.SHARED_TENANT_ID]["kind"] == "shared"

    common = store.get_team(store.COMMON_TEAM_ID)
    admin = store.get_team(store.ADMIN_TEAM_ID)
    assert common["tenantId"] == store.DEFAULT_TENANT_ID
    assert admin["tenantId"] is None


def test_create_team_gets_default_tenant_without_shared_key(store) -> None:
    team = store.create_team("企画課", "a@example.com")
    assert team["tenantId"] == store.DEFAULT_TENANT_ID
    keys = {t["tenantId"]: t for t in store.list_tenants_for_user("a@example.com")}
    assert keys[store.DEFAULT_TENANT_ID]["role"] == "primary"
    assert store.SHARED_TENANT_ID not in keys
    assert store.get_active_tenant_id("a@example.com") == store.DEFAULT_TENANT_ID


def test_child_inherits_parent_tenant(store) -> None:
    other = store.create_tenant("さいたま市")
    bureau = store.create_team(
        "企画局", "chief@example.com", tenant_id=other["tenantId"]
    )
    ka = store.create_team(
        "企画課", "staff@example.com", parent_team_id=bureau["teamId"]
    )
    assert bureau["tenantId"] == other["tenantId"]
    assert ka["tenantId"] == other["tenantId"]
    assert store.get_primary_tenant_id("staff@example.com") == other["tenantId"]


def test_parent_rejected_across_tenants(store) -> None:
    home = store.create_team("川口企画", "k@example.com")
    other = store.create_tenant("さいたま市")
    err = store.validate_parent_team_id(
        None, home["teamId"], tenant_id=other["tenantId"]
    )
    assert err is not None


def test_invite_guest_and_active_tenant(store) -> None:
    store.create_team("企画課", "kawaguchi@example.com")
    other = store.create_tenant("さいたま市")
    store.create_team(
        "情報政策課", "saitama@example.com", tenant_id=other["tenantId"]
    )
    invited = store.upsert_tenant_membership(
        other["tenantId"], "kawaguchi@example.com", role="guest"
    )
    assert invited["role"] == "guest"
    assert store.can_access_tenant(other["tenantId"], "kawaguchi@example.com")

    assert (
        store.set_active_tenant_id("kawaguchi@example.com", other["tenantId"])
        is None
    )
    assert store.get_active_tenant_id("kawaguchi@example.com") == other["tenantId"]

    stranger = store.set_active_tenant_id("stranger@example.com", other["tenantId"])
    assert stranger is not None


def test_team_visible_is_active_tenant_only(store) -> None:
    home = store.create_team("企画課", "a@example.com")
    other = store.create_tenant("さいたま市")
    far = store.create_team(
        "別課", "b@example.com", tenant_id=other["tenantId"]
    )
    assert store.team_visible_in_tenant(home["teamId"], store.DEFAULT_TENANT_ID)
    assert store.team_visible_in_tenant(store.COMMON_TEAM_ID, store.DEFAULT_TENANT_ID)
    assert not store.team_visible_in_tenant(far["teamId"], store.DEFAULT_TENANT_ID)
    assert not store.team_visible_in_tenant(store.ADMIN_TEAM_ID, store.DEFAULT_TENANT_ID)
    assert not store.team_visible_in_tenant(store.COMMON_TEAM_ID, store.SHARED_TENANT_ID)
    assert not store.team_visible_in_tenant(home["teamId"], store.SHARED_TENANT_ID)


def test_filter_team_ids_for_tenant(store) -> None:
    home = store.create_team("企画課", "a@example.com")
    other = store.create_tenant("さいたま市")
    far = store.create_team(
        "別課", "b@example.com", tenant_id=other["tenantId"]
    )
    filtered = store.filter_team_ids_for_tenant(
        [home["teamId"], far["teamId"], store.COMMON_TEAM_ID, store.ADMIN_TEAM_ID],
        store.DEFAULT_TENANT_ID,
    )
    assert home["teamId"] in filtered
    assert store.COMMON_TEAM_ID in filtered
    assert far["teamId"] not in filtered
    assert store.ADMIN_TEAM_ID not in filtered


def test_cannot_delete_fixed_or_occupied_tenant(store) -> None:
    store.create_team("企画課", "a@example.com")
    assert store.delete_tenant(store.DEFAULT_TENANT_ID) is not None
    assert store.delete_tenant(store.SHARED_TENANT_ID) is not None
    empty = store.create_tenant("空の市")
    assert store.delete_tenant(empty["tenantId"]) is None
    assert store.get_tenant(empty["tenantId"]) is None


def test_features_roundtrip(store) -> None:
    t = store.create_tenant("川口市", features={"notebook": True, "ssh": False})
    assert t["features"]["notebook"] is True
    updated = store.update_tenant(t["tenantId"], features={"ssh": True})
    assert updated["features"] == {"ssh": True}


def test_knowledge_scopes_hide_other_tenant(store) -> None:
    home = store.create_team("企画課", "a@example.com")
    other = store.create_tenant("さいたま市")
    far = store.create_team("別課", "b@example.com", tenant_id=other["tenantId"])
    store.upsert_tenant_membership(other["tenantId"], "a@example.com", role="guest")

    home_scopes = {
        s["scope"]
        for s in store.list_knowledge_scopes("a@example.com", False, store.DEFAULT_TENANT_ID)
    }
    assert home["teamId"] in home_scopes
    assert store.COMMON_TEAM_ID in home_scopes
    assert far["teamId"] not in home_scopes

    other_scopes = {
        s["scope"]
        for s in store.list_knowledge_scopes("a@example.com", False, other["tenantId"])
    }
    assert far["teamId"] not in other_scopes  # チーム所属が無いゲストは部屋が見えない
    assert store.COMMON_TEAM_ID not in other_scopes


def test_visible_exapps_respect_active_tenant(store) -> None:
    home = store.create_team("企画課", "a@example.com")
    store.create_exapp(
        home["teamId"],
        {
            "exAppName": "課アプリ",
            "endpoint": "http://example.com/invoke",
            "placeholder": "{}",
            "status": "published",
        },
    )
    store.create_exapp(
        store.COMMON_TEAM_ID,
        {
            "exAppName": "共通ナビ",
            "endpoint": "http://example.com/invoke",
            "placeholder": "{}",
            "status": "published",
        },
    )
    other = store.create_tenant("さいたま市")
    far = store.create_team("別課", "b@example.com", tenant_id=other["tenantId"])
    store.create_exapp(
        far["teamId"],
        {
            "exAppName": "別アプリ",
            "endpoint": "http://example.com/invoke",
            "placeholder": "{}",
            "status": "published",
        },
    )
    apps = store.list_visible_exapps("a@example.com", False, store.DEFAULT_TENANT_ID)
    names = {a["exAppName"] for a in apps}
    assert "課アプリ" in names
    assert "共通ナビ" in names
    assert "別アプリ" not in names

    other_apps = store.list_visible_exapps("a@example.com", False, other["tenantId"])
    other_names = {a["exAppName"] for a in other_apps}
    assert "共通ナビ" in other_names
    assert "課アプリ" not in other_names
    assert "別アプリ" not in other_names


def test_builtin_feature_flag(store) -> None:
    other = store.create_tenant(
        "川口市", features={"ssh": False, "procuretech-editor": False}
    )
    assert store.builtin_feature_enabled(other["tenantId"], "notebook") is True
    assert store.builtin_feature_enabled(other["tenantId"], "ssh") is False
    assert store.builtin_feature_enabled(other["tenantId"], "procuretech-editor") is False
    assert store.builtin_feature_enabled(store.DEFAULT_TENANT_ID, "ssh") is True
    assert store.builtin_feature_enabled(store.DEFAULT_TENANT_ID, "procuretech-editor") is True


def test_migrate_existing_users_get_keys(store, tmp_path, monkeypatch) -> None:
    # init 後に作った所属者は鍵を持つ。再 init しても壊れない。
    store.create_team("企画課", "a@example.com")
    store.init_db(seed_exapps=[])
    keys = {t["tenantId"] for t in store.list_tenants_for_user("a@example.com")}
    assert store.DEFAULT_TENANT_ID in keys
    assert store.SHARED_TENANT_ID not in keys


def test_select_running_official_exapp_ids(store) -> None:
    running = store.select_running_official_exapp_ids(
        image_up=False,
        service_up={"chosei": False, "whisper": True, "ssh": False},
    )
    assert "chat" in running
    assert "knowledge" in running
    assert "whisper" in running
    assert "image" not in running
    assert "chosei" not in running
    assert "ssh" not in running
    assert running == [i for i in store.OFFICIAL_CATALOG_EXAPP_IDS if i in set(running)]
    assert "rag" in running
    with_rag = store.select_running_official_exapp_ids(
        image_up=False,
        service_up={"whisper": True},
    )
    assert "rag" in with_rag


def test_recommended_apps_default_and_save(store) -> None:
    assert store.get_recommended_exapp_ids() == list(store.DEFAULT_RECOMMENDED_EXAPP_IDS)
    saved = store.set_recommended_exapp_ids(
        ["procuretech-editor", "unknown", "chat", "chat"]
    )
    assert saved == ["chat", "procuretech-editor"]
    assert store.get_recommended_exapp_ids() == ["chat", "procuretech-editor"]
    assert store.set_recommended_exapp_ids([]) == []


def test_recommended_apps_backfill_rag_once(store) -> None:
    store.set_recommended_exapp_ids(["chat", "knowledge"])
    with store._lock, store._connect() as conn:
        conn.execute(
            "DELETE FROM app_settings WHERE key = ?",
            (store.RECOMMENDED_BACKFILL_KEY,),
        )
        conn.execute(
            "UPDATE app_settings SET value = ? WHERE key = ?",
            ('["chat","knowledge"]', store.RECOMMENDED_SETTING_KEY),
        )
    filled = store.get_recommended_exapp_ids()
    assert "chat" in filled
    assert "knowledge" in filled
    assert "rag" in filled
    store.set_recommended_exapp_ids(["chat", "knowledge"])
    assert "rag" not in store.get_recommended_exapp_ids()


def test_ensure_home_tenant_without_team(store) -> None:
    store.ensure_user_home_tenant("admin@example.com")
    keys = {t["tenantId"]: t for t in store.list_tenants_for_user("admin@example.com")}
    assert store.DEFAULT_TENANT_ID in keys
    assert keys[store.DEFAULT_TENANT_ID]["role"] == "primary"
    assert store.SHARED_TENANT_ID not in keys


def test_tenant_admin_manages_own_tenant_only(store) -> None:
    other = store.create_tenant("さいたま市")
    home = store.create_team("企画課", "staff@example.com")
    far = store.create_team(
        "情報政策課", "other@example.com", tenant_id=other["tenantId"]
    )
    store.upsert_tenant_membership(
        store.DEFAULT_TENANT_ID, "tadmin@example.com", role="primary", is_admin=True
    )

    assert store.is_tenant_admin(store.DEFAULT_TENANT_ID, "tadmin@example.com")
    assert not store.is_tenant_admin(other["tenantId"], "tadmin@example.com")
    assert store.is_tenant_admin_of_team("tadmin@example.com", home["teamId"])
    assert store.is_tenant_admin_of_team("tadmin@example.com", store.COMMON_TEAM_ID)
    assert not store.is_tenant_admin_of_team("tadmin@example.com", far["teamId"])

    admin_teams = {t["teamId"] for t in store.list_teams_for_tenant_admin("tadmin@example.com")}
    assert home["teamId"] in admin_teams
    assert store.COMMON_TEAM_ID in admin_teams
    assert far["teamId"] not in admin_teams

    scopes = {
        s["scope"]: s
        for s in store.list_knowledge_scopes(
            "tadmin@example.com", False, store.DEFAULT_TENANT_ID
        )
    }
    assert scopes[store.COMMON_TEAM_ID]["canManage"] is True
    assert scopes[home["teamId"]]["canManage"] is True
    assert far["teamId"] not in scopes


def test_shared_tenant_is_opt_in(store) -> None:
    store.create_team("企画課", "a@example.com")
    assert not store.can_access_tenant(store.SHARED_TENANT_ID, "a@example.com")
    store.upsert_tenant_membership(
        store.SHARED_TENANT_ID, "a@example.com", role="shared"
    )
    assert store.can_access_tenant(store.SHARED_TENANT_ID, "a@example.com")
    assert (
        store.set_active_tenant_id("a@example.com", store.SHARED_TENANT_ID) is None
    )
    scopes = {
        s["scope"]
        for s in store.list_knowledge_scopes(
            "a@example.com", False, store.SHARED_TENANT_ID
        )
    }
    assert store.COMMON_TEAM_ID not in scopes
