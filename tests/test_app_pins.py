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


def _make_team_with_app(store, team_name="テストチーム", admin="admin@example.com"):
    team = store.create_team(team_name, admin)
    app = store.create_exapp(
        team["teamId"],
        {
            "exAppName": "テストアプリ",
            "endpoint": "http://example.com/invoke",
            "placeholder": "{}",
            "description": "説明",
            "howToUse": "使い方",
            "apiKey": "key",
            "status": "published",
        },
    )
    return team, app


def test_pin_and_list(teams_store) -> None:
    team, app = _make_team_with_app(teams_store)
    pins, error = teams_store.add_user_app_pin(
        "admin@example.com", team["teamId"], app["exAppId"], False
    )
    assert error is None
    assert pins is not None
    assert len(pins) == 1
    assert pins[0]["teamId"] == team["teamId"]
    assert pins[0]["itemId"] == app["exAppId"]


def test_pin_common_genu_app(teams_store) -> None:
    pins, error = teams_store.add_user_app_pin(
        "user@example.com", teams_store.COMMON_TEAM_ID, "chat", False
    )
    assert error is None
    assert pins is not None
    assert pins[0]["itemId"] == "chat"


def test_pin_is_idempotent(teams_store) -> None:
    team, app = _make_team_with_app(teams_store)
    teams_store.add_user_app_pin("admin@example.com", team["teamId"], app["exAppId"], False)
    pins, error = teams_store.add_user_app_pin(
        "admin@example.com", team["teamId"], app["exAppId"], False
    )
    assert error is None
    assert len(pins) == 1


def test_pin_limit(teams_store) -> None:
    team = teams_store.create_team("上限テスト", "admin@example.com")
    team_id = team["teamId"]
    created_ids = []
    for i in range(teams_store.MAX_APP_PINS + 1):
        app = teams_store.create_exapp(
            team_id,
            {
                "exAppName": f"アプリ{i}",
                "endpoint": f"http://example.com/{i}/invoke",
                "placeholder": "{}",
                "description": "d",
                "howToUse": "h",
                "apiKey": "k",
                "status": "published",
            },
        )
        created_ids.append(app["exAppId"])

    last_error = None
    for ex_id in created_ids:
        _, last_error = teams_store.add_user_app_pin(
            "admin@example.com", team_id, ex_id, False
        )
    assert last_error is not None
    assert str(teams_store.MAX_APP_PINS) in last_error
    assert len(teams_store.list_user_app_pins("admin@example.com")) == teams_store.MAX_APP_PINS


def test_pin_rejects_unknown_app(teams_store) -> None:
    team = teams_store.create_team("拒否テスト", "admin@example.com")
    pins, error = teams_store.add_user_app_pin(
        "admin@example.com", team["teamId"], "not-a-real-app", False
    )
    assert pins is None
    assert error is not None


def test_pin_rejects_invisible_app(teams_store) -> None:
    team, app = _make_team_with_app(teams_store)
    # other@example.com は team に所属しないため、その exApp は不可視
    pins, error = teams_store.add_user_app_pin(
        "other@example.com", team["teamId"], app["exAppId"], False
    )
    assert pins is None
    assert error is not None


def test_remove_pin(teams_store) -> None:
    team, app = _make_team_with_app(teams_store)
    teams_store.add_user_app_pin("admin@example.com", team["teamId"], app["exAppId"], False)
    pins = teams_store.remove_user_app_pin("admin@example.com", team["teamId"], app["exAppId"])
    assert pins == []


def test_pins_are_per_user(teams_store) -> None:
    team, app = _make_team_with_app(teams_store)
    teams_store.add_user_app_pin("admin@example.com", team["teamId"], app["exAppId"], False)
    # 別ユーザーにはピンが共有されない
    assert teams_store.list_user_app_pins("someone-else@example.com") == []


def test_delete_exapp_removes_pins(teams_store) -> None:
    team, app = _make_team_with_app(teams_store)
    teams_store.add_user_app_pin("admin@example.com", team["teamId"], app["exAppId"], False)
    teams_store.delete_exapp(team["teamId"], app["exAppId"])
    assert teams_store.list_user_app_pins("admin@example.com") == []
