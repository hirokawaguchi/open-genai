"""下書き再開・複数提出・権限・マイナンバー監査。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import spec, store


def _setup_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store.reset_connection()
    store.DB_PATH = path
    store.init_db()
    return path


def _teardown(path: str) -> None:
    store.reset_connection()
    try:
        os.remove(path)
    except OSError:
        pass


def _definition() -> dict:
    raw = spec.empty_definition("届出")
    raw["components"] = [
        {"id": "name", "type": "text", "label": "氏名", "required": True},
        {"id": "note", "type": "text", "label": "備考", "required": False},
    ]
    return raw


def _publish(creator: str = "u1") -> dict:
    form, err = store.create_form(
        title="届出",
        description=None,
        creator_user_id=creator,
        creator_name="作成者",
        visibility="internal",
        definition=_definition(),
    )
    assert err is None and form
    proc, err = store.create_procedure(
        name="届出の手続き",
        description=None,
        guide_form_id=form["id"],
        creator_user_id=creator,
    )
    assert err is None and proc
    published, err = store.set_procedure_status(
        proc["id"], actor_user_id=creator, status="published"
    )
    assert err is None and published
    detail = store.get_form(form["id"], actor_user_id=creator)
    recs = [r for r in (detail or {}).get("receptions") or [] if r.get("status") == "published"]
    assert recs
    full = store.get_form(recs[0]["id"], actor_user_id=creator)
    assert full
    return full


def test_draft_resume_and_finalize() -> None:
    path = _setup_db()
    try:
        form = _publish()
        draft, err = store.submit_answers(
            form_id=form["id"],
            answers={"note": "途中"},
            submitter_user_id="u2",
            submitter_name="職員",
            is_draft=True,
        )
        assert err is None and draft
        assert draft["is_draft"] is True
        loaded, err = store.get_draft(form_id=form["id"], submitter_user_id="u2")
        assert err is None and loaded
        assert loaded["answers"]["note"] == "途中"
        final, err = store.submit_answers(
            form_id=form["id"],
            answers={"name": "佐藤", "note": "完了"},
            submitter_user_id="u2",
            submitter_name="職員",
        )
        assert err is None and final
        assert final["is_draft"] is False
        assert final["receipt_code"] == draft["receipt_code"]
        items, err = store.list_submissions(form["id"], actor_user_id="u1")
        assert err is None and items and len(items) == 1
    finally:
        _teardown(path)


def test_allow_multiple_false() -> None:
    path = _setup_db()
    try:
        form = _publish()
        updated, err = store.update_form(form["id"], actor_user_id="u1", allow_multiple=False)
        assert err is None and updated
        first, err = store.submit_answers(
            form_id=form["id"],
            answers={"name": "一次"},
            submitter_user_id="u2",
            submitter_name="A",
        )
        assert err is None and first
        second, err = store.submit_answers(
            form_id=form["id"],
            answers={"name": "二次"},
            submitter_user_id="u2",
            submitter_name="A",
        )
        assert second is None and err and "すでに" in err
    finally:
        _teardown(path)


def test_editor_and_viewer_acl() -> None:
    path = _setup_db()
    try:
        created, err = store.create_form(
            title="届出",
            description=None,
            creator_user_id="u1",
            creator_name="作成者",
            visibility="internal",
            definition=_definition(),
        )
        assert err is None and created
        _, err = store.update_form(
            created["id"],
            actor_user_id="u1",
            editor_user_ids=["ed1"],
            viewer_user_ids=["vw1"],
        )
        assert err is None
        proc, err = store.create_procedure(
            name="届出の手続き",
            description=None,
            guide_form_id=created["id"],
            creator_user_id="u1",
        )
        assert err is None and proc
        _, err = store.set_procedure_status(proc["id"], actor_user_id="u1", status="published")
        assert err is None
        detail = store.get_form(created["id"], actor_user_id="u1")
        recs = [r for r in (detail or {}).get("receptions") or [] if r.get("status") == "published"]
        assert recs
        form = store.get_form(recs[0]["id"], actor_user_id="u1")
        assert form
        detail = store.get_form(form["id"], actor_user_id="ed1")
        assert detail and detail["can_edit"] is True
        listed = store.list_forms_for_user("ed1")
        assert any(item["id"] == created["id"] for item in listed)
        _, err = store.update_form(form["id"], actor_user_id="ed1", title="届出改")
        assert err is None
        _, err = store.update_form(form["id"], actor_user_id="ed1", editor_user_ids=["x"])
        assert err and "作成者" in err
        view = store.get_form(form["id"], actor_user_id="vw1")
        assert view and view["can_view_submissions"] is True and view["can_edit"] is False
        items, err = store.list_submissions(form["id"], actor_user_id="vw1")
        assert err is None and items == []
        _, err = store.update_form(form["id"], actor_user_id="vw1", title="不可")
        assert err and "権限" in err
        stranger = store.get_form(form["id"], actor_user_id="zz")
        assert stranger and stranger["can_read"] is True
        assert stranger["can_view_submissions"] is False
    finally:
        _teardown(path)


def test_mynumber_reveal_audit() -> None:
    path = _setup_db()
    try:
        raw = spec.empty_definition("番号")
        raw["components"] = [
            {"id": "mn", "type": "mynumber", "label": "個人番号", "required": True}
        ]
        form, err = store.create_form(
            title="番号",
            description=None,
            creator_user_id="u1",
            creator_name="作成者",
            visibility="internal",
            definition=raw,
        )
        assert err is None and form
        proc, err = store.create_procedure(
            name="番号の手続き",
            description=None,
            guide_form_id=form["id"],
            creator_user_id="u1",
        )
        assert err is None and proc
        published_proc, err = store.set_procedure_status(
            proc["id"], actor_user_id="u1", status="published"
        )
        assert err is None and published_proc
        detail = store.get_form(form["id"], actor_user_id="u1")
        recs = [r for r in (detail or {}).get("receptions") or [] if r.get("status") == "published"]
        assert recs
        form = store.get_form(recs[0]["id"], actor_user_id="u1")
        assert form
        first11 = "12345678901"
        total = 0
        for i in range(1, 12):
            p = int(first11[11 - i])
            q = i + 1 if i <= 6 else i - 5
            total += p * q
        c = total % 11
        mn = first11 + str(0 if c <= 1 else 11 - c)
        assert spec.mynumber_check_digit_ok(mn)
        submitted, err = store.submit_answers(
            form_id=form["id"],
            answers={"mn": mn},
            submitter_user_id="u2",
            submitter_name="本人",
        )
        assert err is None and submitted
        items, err = store.list_submissions(form["id"], actor_user_id="u1")
        assert err is None and items
        assert items[0]["answers"]["mn"].startswith("*")
        shown, err = store.reveal_submission(form["id"], items[0]["id"], actor_user_id="u1")
        assert err is None and shown
        assert shown["answers"]["mn"] == mn
        events, err = store.list_audit(form["id"], actor_user_id="u1")
        assert err is None and events
        assert events[0]["action"] == "reveal"
        csv_body, err = store.export_csv(form["id"], actor_user_id="u1", reveal=True)
        assert err is None and csv_body and mn in csv_body
        events, err = store.list_audit(form["id"], actor_user_id="u1")
        assert err is None and any(ev["action"] == "export_unmasked" for ev in events)
    finally:
        _teardown(path)


def test_identity_modes() -> None:
    path = _setup_db()
    try:
        form = _publish()
        _, err = store.update_form(form["id"], actor_user_id="u1", identity_mode="anonymous")
        assert err is None
        result, err = store.submit_answers(
            form_id=form["id"],
            answers={"name": "佐藤"},
            submitter_user_id="u2",
            submitter_name="佐藤",
        )
        assert err is None and result
        items, err = store.list_submissions(form["id"], actor_user_id="u1")
        assert err is None and items
        assert items[0]["submitter_user_id"] is None
        assert items[0]["submitter_name"] is None
        assert items[0]["respondent_label"] == items[0]["receipt_code"]

        form2 = _publish("u1")
        raw = spec.empty_definition("氏名あり")
        raw["components"] = [
            {
                "id": "who",
                "type": "user_info_composite",
                "label": "氏名",
                "required": True,
            }
        ]
        _, err = store.update_form(
            form2["id"],
            actor_user_id="u1",
            definition=raw,
            identity_mode="required",
        )
        assert err is None
        store.set_status(form2["id"], actor_user_id="u1", status="published")
        named, err = store.submit_answers(
            form_id=form2["id"],
            answers={"who": {"last_name": "山田", "first_name": "太郎"}},
            submitter_user_id="u3",
            submitter_name=None,
        )
        assert err is None and named
        items, err = store.list_submissions(form2["id"], actor_user_id="u1")
        assert err is None and items
        assert items[0]["respondent_label"] == "山田 太郎"
    finally:
        _teardown(path)


def test_withdraw_and_restore() -> None:
    path = _setup_db()
    try:
        form = _publish()
        result, err = store.submit_answers(
            form_id=form["id"],
            answers={"name": "一次"},
            submitter_user_id="u2",
            submitter_name="A",
        )
        assert err is None and result
        items, err = store.list_submissions(form["id"], actor_user_id="u1")
        assert err is None and items
        sid = items[0]["id"]
        out, err = store.set_withdrawn(
            form_id=form["id"], submission_id=sid, actor_user_id="u1", withdrawn=True
        )
        assert err is None and out and out["withdrawn"] is True
        after = store.get_form(form["id"], actor_user_id="u1")
        assert after and after["submission_count"] == 0 and after["withdrawn_count"] == 1
        items, err = store.list_submissions(form["id"], actor_user_id="u1")
        assert err is None and items and items[0]["withdrawn"] is True
        csv_body, err = store.export_csv(form["id"], actor_user_id="u1")
        assert err is None and csv_body and "取下げ" in csv_body
        back, err = store.set_withdrawn(
            form_id=form["id"], submission_id=sid, actor_user_id="u1", withdrawn=False
        )
        assert err is None and back and back["withdrawn"] is False
        after = store.get_form(form["id"], actor_user_id="u1")
        assert after and after["submission_count"] == 1
    finally:
        _teardown(path)


if __name__ == "__main__":
    test_draft_resume_and_finalize()
    test_allow_multiple_false()
    test_editor_and_viewer_acl()
    test_mynumber_reveal_audit()
    test_identity_modes()
    test_withdraw_and_restore()
    print("ok")
