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
def teams_store(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "teams-test.db"))
    from app import teams_store as store

    importlib.reload(store)
    store.init_db(seed_exapps=[])
    return store


def _fields(name: str, ex_app_id: str | None = None, config: str = "") -> dict:
    data = {
        "exAppName": name,
        "endpoint": "http://example.invalid/invoke",
        "placeholder": "",
        "description": name,
        "howToUse": "使う",
        "apiKey": "",
        "status": "published",
        "config": config,
    }
    if ex_app_id:
        data["exAppId"] = ex_app_id
        data["teamId"] = "00000000-0000-0000-0000-000000000000"
    return data


def _names(store) -> list[str]:
    return [app["exAppName"] for app in store.list_team_exapps(store.COMMON_TEAM_ID)]


def test_null_orders_follow_the_previous_public_list(teams_store) -> None:
    common = teams_store.COMMON_TEAM_ID
    teams_store.upsert_seed_exapp(_fields("チャット", "chat", '{"builtin": true, "route": "/chat"}'))
    teams_store.create_exapp(common, _fields("議会答弁"))
    teams_store.upsert_seed_exapp(_fields("ナレッジ検索", "rag"))
    teams_store.upsert_seed_exapp(_fields("日程調整", "chosei"))
    with teams_store._lock, teams_store._connect() as conn:
        conn.execute("UPDATE exapps SET displayOrder = NULL")
        teams_store._fill_missing_display_orders(conn)

    assert _names(teams_store) == ["議会答弁", "日程調整", "ナレッジ検索", "チャット"]


def test_move_swaps_with_the_neighbor_and_stops_at_the_end(teams_store) -> None:
    common = teams_store.COMMON_TEAM_ID
    first = teams_store.create_exapp(common, _fields("日程調整"))
    second = teams_store.create_exapp(common, _fields("議会答弁"))

    teams_store.move_exapp_display_order(common, second["exAppId"], "up")
    assert _names(teams_store) == ["議会答弁", "日程調整"]

    teams_store.move_exapp_display_order(common, second["exAppId"], "up")
    assert _names(teams_store) == ["議会答弁", "日程調整"]

    teams_store.move_exapp_display_order(common, first["exAppId"], "down")
    assert _names(teams_store) == ["議会答弁", "日程調整"]


def test_restart_keeps_an_admin_order(teams_store) -> None:
    common = teams_store.COMMON_TEAM_ID
    teams_store.create_exapp(common, _fields("日程調整"))
    council = teams_store.create_exapp(common, _fields("議会答弁"))
    teams_store.move_exapp_display_order(common, council["exAppId"], "up")

    teams_store.init_db(seed_exapps=[])

    assert _names(teams_store) == ["議会答弁", "日程調整"]


def test_new_seed_is_appended(teams_store) -> None:
    teams_store.create_exapp(teams_store.COMMON_TEAM_ID, _fields("既存"))
    teams_store.init_db(seed_exapps=[_fields("日程調整", "chosei")])
    assert _names(teams_store) == ["既存", "日程調整"]


def test_fresh_seeds_keep_custom_apps_ahead_of_builtins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "fresh.db"))
    from app import teams_store as store

    importlib.reload(store)
    store.init_db(
        seed_exapps=[
            _fields("チャット", "chat", '{"builtin": true, "route": "/chat"}'),
            _fields("日程調整", "chosei"),
            _fields("ナレッジ検索", "rag"),
        ]
    )
    assert [app["exAppName"] for app in store.list_team_exapps(store.COMMON_TEAM_ID)] == [
        "日程調整",
        "ナレッジ検索",
        "チャット",
    ]


def test_old_database_receives_display_order(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "old.db"))
    from app import teams_store as store

    importlib.reload(store)
    store.init_db(seed_exapps=[])
    store.create_exapp(store.COMMON_TEAM_ID, _fields("既存"))
    with store._lock, store._connect() as conn:
        conn.execute("ALTER TABLE exapps DROP COLUMN displayOrder")
    store.init_db(seed_exapps=[])
    apps = store.list_team_exapps(store.COMMON_TEAM_ID)
    assert apps[0]["exAppName"] == "既存"
    assert apps[0]["displayOrder"] == 0


def test_backfill_follows_row_order_not_created_date(teams_store) -> None:
    common = teams_store.COMMON_TEAM_ID
    teams_store.create_exapp(common, _fields("先に作った"))
    teams_store.create_exapp(common, _fields("後から作った"))
    with teams_store._lock, teams_store._connect() as conn:
        conn.execute(
            "UPDATE exapps SET createdDate = '9' WHERE exAppName = '先に作った'"
        )
        conn.execute(
            "UPDATE exapps SET createdDate = '1' WHERE exAppName = '後から作った'"
        )
        conn.execute("UPDATE exapps SET displayOrder = NULL")
        teams_store._fill_missing_display_orders(conn)
    assert _names(teams_store) == ["先に作った", "後から作った"]


def test_sort_exapps_for_display_uses_the_number() -> None:
    from app.teams_store import sort_exapps_for_display

    ordered = sort_exapps_for_display(
        [
            {"exAppId": "b", "displayOrder": 2, "createdDate": "2"},
            {"exAppId": "a", "displayOrder": 0, "createdDate": "9"},
            {"exAppId": "c", "displayOrder": None, "createdDate": "1"},
        ]
    )
    assert [app["exAppId"] for app in ordered] == ["a", "b", "c"]
