import base64
import hashlib
import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app import store
from app.main import app


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("NISHUKAN_DB_PATH", str(tmp_path / "nishukan.db"))
    monkeypatch.setenv("INTERNAL_SIGNING_SECRET", "")
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "nishukan.db"))
    store.init_db()
    return store


def access(user="chief@example.jp", *, admin=True, member=True, inherited=False, team="team-1"):
    return store.Access(
        user,
        "tenant-1",
        {
            team: {
                "teamId": team,
                "teamName": "市民課",
                "admin": admin,
                "member": member,
                "inherited": inherited,
            }
        },
    )


def test_editor_cannot_place_in_box_or_complete(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    project = db.create_project(admin, {"teamId": "team-1", "key": "DX", "name": "更改", "mode": "plan"})
    db.add_member(admin, project["id"], "editor@example.jp", "editor")
    editor = access("editor@example.jp", admin=False)
    with pytest.raises(store.NishukanError) as raised:
        db.create_issue(
            editor,
            {
                "projectId": project["id"],
                "title": "仕様",
                "timeboxStart": "2026-10-05",
                "completionText": "仕様が記録にある",
                "completionMode": "chief",
                "priority": "high",
            },
        )
    assert raised.value.status == 403
    issue = db.create_issue(editor, {"projectId": project["id"], "title": "仕様"})
    placed = db.create_issue(
        admin,
        {
            "projectId": project["id"],
            "title": "議会",
            "timeboxStart": "2026-10-05",
            "completionText": "答弁案が記録にある",
            "completionMode": "chief",
            "priority": "high",
            "size": 5,
        },
    )
    assert placed["timeboxStart"] == "2026-10-05"
    with pytest.raises(store.NishukanError):
        db.update_issue(editor, placed["id"], {"status": "done"})
    with pytest.raises(store.NishukanError):
        db.update_issue(editor, issue["id"], {"complete": True})
    done = db.update_issue(admin, placed["id"], {"complete": True})
    assert done["status"] == "done"


def test_objective_completes_when_checks_are_recorded(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    project = db.create_project(admin, {"teamId": "team-1", "key": "DX", "name": "更改", "mode": "plan"})
    db.add_member(admin, project["id"], "editor@example.jp", "editor")
    issue = db.create_issue(
        admin,
        {
            "projectId": project["id"],
            "title": "受付",
            "completionText": "収受印がある",
            "completionMode": "objective",
            "checks": ["収受印がある"],
            "timeboxStart": "2026-10-05",
            "priority": "normal",
            "size": 1,
        },
    )
    editor = access("editor@example.jp", admin=False)
    updated = db.set_check(editor, issue["id"], issue["checks"][0]["id"], True)
    assert updated["status"] == "done"
    assert updated["checks"][0]["doneBy"] == "editor@example.jp"


def test_arrival_is_idempotent_and_receipt_key_is_the_same_operation(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    project = db.create_project(
        admin, {"teamId": "team-1", "key": "MAD", "name": "窓口", "mode": "routine"}
    )
    template = db.create_template(
        admin,
        {
            "projectId": project["id"],
            "name": "相談",
            "size": 1,
            "priority": "normal",
            "completionText": "回答の記録がある",
            "completionMode": "objective",
            "checks": ["回答の記録がある"],
        },
    )
    staff = access("staff@example.jp", admin=False)
    first = db.arrive(template["id"], access=staff, event_id="evt-1")
    second = db.arrive(template["id"], access=staff, event_id="evt-1")
    assert first["id"] == second["id"]
    assert first["title"] == "相談"
    assert first["size"] == 1
    named = db.arrive(template["id"], access=staff, title="山田花子さんの相談対応")
    assert named["id"] != first["id"]
    assert named["title"] == "山田花子さんの相談対応"
    assert named["templateId"] == template["id"]
    issued = db.issue_receipt_key(admin, template["id"])
    external = db.arrive(template["id"], receipt_key=issued["receiptKey"], event_id="evt-2")
    assert external["templateId"] == template["id"]
    db.revoke_receipt_key(admin, template["id"])
    with pytest.raises(store.NishukanError) as raised:
        db.arrive(template["id"], receipt_key=issued["receiptKey"], event_id="evt-3")
    assert raised.value.status == 401


def test_home_reserves_previous_routine_size_on_the_next_box(db, monkeypatch):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    monkeypatch.setattr(store, "today", lambda: date(2026, 10, 6))
    routine = db.create_project(
        admin, {"teamId": "team-1", "key": "MAD", "name": "窓口", "mode": "routine"}
    )
    template = db.create_template(
        admin,
        {
            "projectId": routine["id"],
            "name": "相談",
            "size": 2,
            "priority": "normal",
            "completionText": "記録がある",
            "completionMode": "chief",
        },
    )
    current = store.box_bounds(date(2026, 10, 6), 0)[0]
    previous_start = (current - timedelta(days=14)).isoformat()
    db.arrive(template["id"], access=admin, event_id="now")
    with store._lock, store._connect() as conn:
        conn.execute(
            "UPDATE issues SET timebox_start = ? WHERE template_id = ?",
            (previous_start, template["id"]),
        )
    page = db.home(admin, "team-1")
    assert page["boxes"]["next"]["routineReserve"] == 2
    assert page["boxes"]["next"]["forecastSize"] == 2
    assert page["routine"][0]["count"] == 1
    assert page["routine"][0]["openCount"] == 1


def test_inherited_viewer_cannot_press_a_template(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    project = db.create_project(
        admin, {"teamId": "team-1", "key": "MAD", "name": "窓口", "mode": "routine"}
    )
    template = db.create_template(
        admin,
        {
            "projectId": project["id"],
            "name": "相談",
            "size": 1,
            "priority": "low",
            "completionText": "記録がある",
            "completionMode": "chief",
        },
    )
    parent = store.Access(
        "parent@example.jp",
        "tenant-1",
        {"team-1": {"teamId": "team-1", "teamName": "市民課", "admin": False, "member": True, "inherited": True}},
    )
    with pytest.raises(store.NishukanError) as raised:
        db.arrive(template["id"], access=parent)
    assert raised.value.status == 403


def test_http_arrival_uses_the_same_api_as_the_button(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    project = db.create_project(
        admin, {"teamId": "team-1", "key": "MAD", "name": "窓口", "mode": "routine"}
    )
    template = db.create_template(
        admin,
        {
            "projectId": project["id"],
            "name": "申請",
            "size": 3,
            "priority": "normal",
            "completionText": "収受印がある",
            "completionMode": "objective",
            "checks": ["収受印がある"],
        },
    )
    issued = db.issue_receipt_key(admin, template["id"])
    client = TestClient(app)
    res = client.post(
        f"/arrivals/{template['id']}",
        headers={"x-api-key": "local-rag-key", "x-receipt-key": issued["receiptKey"]},
        json={"eventId": "paper-1"},
    )
    assert res.status_code == 200
    again = client.post(
        f"/arrivals/{template['id']}",
        headers={"x-api-key": "local-rag-key", "x-receipt-key": issued["receiptKey"]},
        json={"eventId": "paper-1"},
    )
    assert again.json()["id"] == res.json()["id"]

    payload = {
        "userId": "staff@example.jp",
        "tenantId": "tenant-1",
        "teams": [
            {
                "teamId": "team-1",
                "teamName": "市民課",
                "admin": False,
                "member": True,
                "inherited": False,
            }
        ],
    }
    raw = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    pressed = client.post(
        f"/templates/{template['id']}/arrivals",
        headers={
            "x-api-key": "local-rag-key",
            "x-user-id": "staff@example.jp",
            "x-nishukan-access": raw,
            "x-scope": hashlib.sha256(raw.encode()).hexdigest(),
        },
        json={},
    )
    assert pressed.status_code == 200
    assert pressed.json()["id"] != res.json()["id"]


def test_quarter_size_completion_while_unfiled_and_project_move(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    project = db.create_project(admin, {"teamId": "team-1", "key": "DX", "name": "更改", "mode": "plan"})
    issue = db.create_issue(admin, {"teamId": "team-1", "title": "下書き"})
    assert issue["projectKey"] == ""
    assert issue["timeboxStart"] is None
    renamed = db.update_issue(admin, issue["id"], {"title": "体制案"})
    assert renamed["title"] == "体制案"
    with pytest.raises(store.NishukanError) as empty_title:
        db.update_issue(admin, issue["id"], {"title": "  "})
    assert empty_title.value.status == 400
    saved = db.update_issue(
        admin,
        issue["id"],
        {"completionText": "記録がある", "completionMode": "chief"},
    )
    assert saved["completionText"] == "記録がある"
    assert saved["timeboxStart"] is None
    placed = db.update_issue(
        admin,
        issue["id"],
        {"status": "todo", "timeboxStart": "2026-10-05", "size": 0.25},
    )
    assert placed["size"] == 0.25
    assert placed["timeboxStart"] == "2026-10-05"
    with pytest.raises(store.NishukanError) as raised:
        db.update_issue(admin, issue["id"], {"completionText": "後から変える"})
    assert raised.value.status == 400
    with pytest.raises(store.NishukanError):
        db.update_issue(admin, issue["id"], {"size": 0.1})
    moved = db.update_issue(admin, issue["id"], {"projectId": project["id"]})
    assert moved["projectKey"] == "DX"
    assert moved["number"] == 1
    page = db.home(admin, "team-1")
    assert all(p["key"] != "UNFILED" for p in page["projects"])


def test_japanese_holidays_fill_the_visible_boxes(db, monkeypatch):
    admin = access()
    monkeypatch.setattr(store, "today", lambda: date(2026, 10, 3))
    current = store.box_bounds(date(2026, 10, 3), 0)[0]
    page = db.home(admin, "team-1")
    holidays = [
        issue
        for issue in page["leaveIssues"]
        if issue.get("holidayDate") and issue["timeboxStart"] == current.isoformat()
    ]
    assert {issue["title"] for issue in holidays} == {"敬老の日", "国民の休日", "秋分の日"}
    assert all(issue["size"] is None for issue in holidays)
    nxt = current + timedelta(days=14)
    sports = [
        issue
        for issue in page["boxes"]["next"]["issues"]
        if issue.get("holidayDate") and issue["timeboxStart"] == nxt.isoformat()
    ]
    assert {issue["title"] for issue in sports} == {"スポーツの日"}
    before = len([issue for issue in page["leaveIssues"] if issue.get("holidayDate")])
    page = db.home(admin, "team-1")
    assert len([issue for issue in page["leaveIssues"] if issue.get("holidayDate")]) == before
    db.set_headcount(admin, "team-1", 5)
    page = db.home(admin, "team-1")
    holidays = [issue for issue in page["leaveIssues"] if issue.get("holidayDate")]
    assert holidays
    assert all(issue["size"] == 5 for issue in holidays)
    db.set_headcount(admin, "team-1", 4)
    page = db.home(admin, "team-1")
    holidays = [issue for issue in page["leaveIssues"] if issue.get("holidayDate")]
    assert all(issue["size"] == 4 for issue in holidays)


def test_vacation_is_one_total_for_the_period(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    first = db.set_vacation(admin, "team-1", "2026-09-21", 6)
    assert first["title"] == "休暇"
    assert first["leaveName"] == ""
    assert first["size"] == 6
    second = db.set_vacation(admin, "team-1", "2026-09-21", 4)
    assert second["id"] == first["id"]
    assert second["size"] == 4
    page = db.home(admin, "team-1")
    vacations = [
        issue
        for issue in page["leaveIssues"]
        if issue["title"] == "休暇" and issue["timeboxStart"] == "2026-09-21"
    ]
    assert len(vacations) == 1
    assert vacations[0]["size"] == 4
    cleared = db.set_vacation(admin, "team-1", "2026-09-21", 0)
    assert cleared["size"] == 0
    page = db.home(admin, "team-1")
    assert not [
        issue for issue in page["leaveIssues"] if issue["title"] == "休暇"
    ]


def test_project_and_template_can_be_renamed_and_removed(db):
    admin = access()
    db.set_chief(admin, "team-1", "chief@example.jp")
    project = db.create_project(admin, {"teamId": "team-1", "key": "DX", "name": "更改", "mode": "plan"})
    renamed = db.update_project(admin, project["id"], {"name": "庁内DX", "key": "DX2"})
    assert renamed["name"] == "庁内DX"
    assert renamed["key"] == "DX2"
    db.create_issue(admin, {"projectId": project["id"], "title": "下書き"})
    with pytest.raises(store.NishukanError) as blocked:
        db.update_project(admin, project["id"], {"mode": "routine"})
    assert blocked.value.status == 400
    with pytest.raises(store.NishukanError) as kept:
        db.delete_project(admin, project["id"])
    assert kept.value.status == 400
    empty = db.create_project(admin, {"teamId": "team-1", "key": "WIN", "name": "窓口", "mode": "routine"})
    assert db.delete_project(admin, empty["id"])["deleted"] is True
    routine = db.create_project(admin, {"teamId": "team-1", "key": "MAD", "name": "相談窓口", "mode": "routine"})
    template = db.create_template(
        admin,
        {
            "projectId": routine["id"],
            "name": "相談",
            "size": 1,
            "priority": "normal",
            "completionText": "記録がある",
            "completionMode": "chief",
        },
    )
    arrived = db.arrive(template["id"], access=admin, title="山田さんの相談")
    updated = db.update_template(admin, template["id"], {"name": "窓口相談", "size": 2})
    assert updated["name"] == "窓口相談"
    assert updated["size"] == 2
    page = db.home(admin, "team-1")
    kept_issue = next(issue for issue in page["routine"][0]["issues"] if issue["id"] == arrived["id"])
    assert kept_issue["title"] == "山田さんの相談"
    assert kept_issue["size"] == 1
    assert db.delete_template(admin, template["id"])["deleted"] is True
    page = db.home(admin, "team-1")
    assert page["templates"] == []
    group = page["routine"][0]
    assert group["name"] == "窓口相談"
    assert group["issues"][0]["templateName"] == "窓口相談"
