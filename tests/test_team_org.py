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
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "teams-org.db"))
    from app import teams_store as ts

    importlib.reload(ts)
    ts.init_db(seed_exapps=[])
    return ts


def test_normalize_org_name_fullwidth(store) -> None:
    assert store.normalize_org_name("ＤＸ推進課") == "DX推進課"
    assert store.normalize_org_name("  デジタル戦略局  ") == "デジタル戦略局"


def test_primary_and_effective_downward(store) -> None:
    bureau = store.create_team("デジタル戦略局", "watanabe.eiji@city.oita.oita.jp")
    ka = store.create_team(
        "ＤＸ推進課",
        "goto.issei@city.oita.oita.jp",
        parent_team_id=bureau["teamId"],
    )
    store.create_team_user(ka["teamId"], "shuto.naoya@city.oita.oita.jp", False)

    assert ka["parentTeamId"] == bureau["teamId"]
    assert ka["teamName"] == "DX推進課"

    watanabe = "watanabe.eiji@city.oita.oita.jp"
    goto = "goto.issei@city.oita.oita.jp"
    shuto = "shuto.naoya@city.oita.oita.jp"

    assert store.get_primary_team_id(watanabe) == bureau["teamId"]
    assert store.get_primary_team_id(goto) == ka["teamId"]
    assert store.get_primary_team_id(shuto) == ka["teamId"]

    assert set(store.list_effective_team_ids_for_user(watanabe)) == {
        bureau["teamId"],
        ka["teamId"],
    }
    assert store.list_effective_team_ids_for_user(goto) == [ka["teamId"]]
    assert store.can_read_team(ka["teamId"], watanabe)
    assert not store.can_read_team(bureau["teamId"], goto)
    assert store.is_team_member(ka["teamId"], goto)
    assert not store.is_team_member(ka["teamId"], watanabe)


def test_extra_tag_does_not_expand(store) -> None:
    bureau = store.create_team("デジタル戦略局", "chief@example.com")
    ka = store.create_team("DX推進課", "staff@example.com", parent_team_id=bureau["teamId"])
    extra = store.create_team("プロジェクトA", "lead@example.com")
    # 課員がプロジェクトを追加タグで持つ（主所属は課のまま）
    store.create_team_user(extra["teamId"], "staff@example.com", False, is_primary=False)
    # 別局を兼務しても配下は展開しない
    other_bureau = store.create_team("別局", "other@example.com")
    other_ka = store.create_team(
        "別課", "other.staff@example.com", parent_team_id=other_bureau["teamId"]
    )
    store.create_team_user(
        other_bureau["teamId"], "staff@example.com", False, is_primary=False
    )

    effective = set(store.list_effective_team_ids_for_user("staff@example.com"))
    assert ka["teamId"] in effective
    assert extra["teamId"] in effective
    assert other_bureau["teamId"] in effective
    assert other_ka["teamId"] not in effective


def test_visible_exapps_include_descendants(store) -> None:
    bureau = store.create_team("デジタル戦略局", "chief@example.com")
    ka = store.create_team("DX推進課", "staff@example.com", parent_team_id=bureau["teamId"])
    store.create_exapp(
        ka["teamId"],
        {
            "exAppName": "課アプリ",
            "endpoint": "http://example.com/invoke",
            "placeholder": "{}",
            "status": "published",
        },
    )
    apps = store.list_visible_exapps("chief@example.com", False)
    assert any(a["exAppId"] and a["teamId"] == ka["teamId"] for a in apps)


def test_share_targets_are_explicit_only(store) -> None:
    bureau = store.create_team("デジタル戦略局", "chief@example.com")
    store.create_team("DX推進課", "staff@example.com", parent_team_id=bureau["teamId"])
    mine = store.list_teams_for_member("chief@example.com")
    assert [t["teamId"] for t in mine] == [bureau["teamId"]]
    assert mine[0]["isPrimary"] is True


def test_parent_cycle_rejected(store) -> None:
    a = store.create_team("A", "a@example.com")
    b = store.create_team("B", "b@example.com", parent_team_id=a["teamId"])
    err = store.validate_parent_team_id(a["teamId"], b["teamId"])
    assert err is not None


def test_switching_primary_unsets_previous(store) -> None:
    t1 = store.create_team("課1", "u@example.com")
    t2 = store.create_team("課2", "admin2@example.com")
    store.create_team_user(t2["teamId"], "u@example.com", False, is_primary=True)
    assert store.get_primary_team_id("u@example.com") == t2["teamId"]
    u1 = store.get_team_user(t1["teamId"], "u@example.com")
    assert u1["isPrimary"] is False
