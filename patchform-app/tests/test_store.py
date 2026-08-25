"""工程1-2: フォーム CRUD・公開・回答・CSV。"""

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


def _reception(form_id: str, actor: str = "u1") -> dict:
    proc, err = store.create_procedure(
        name="検証手続き",
        description=None,
        guide_form_id=form_id,
        creator_user_id=actor,
    )
    assert err is None and proc
    published, err = store.set_procedure_status(
        proc["id"], actor_user_id=actor, status="published"
    )
    assert err is None and published
    detail = store.get_form(form_id, actor_user_id=actor)
    recs = [r for r in (detail or {}).get("receptions") or [] if r.get("status") == "published"]
    assert recs
    full = store.get_form(recs[0]["id"], actor_user_id=actor)
    assert full
    return full


def _definition() -> dict:
    raw = spec.empty_definition("子ども医療費助成")
    raw["components"] = [
        {
            "id": "name",
            "type": "text",
            "label": "氏名",
            "required": True,
        },
        {
            "id": "mail",
            "type": "email",
            "label": "メール",
            "required": False,
        },
    ]
    return raw


def test_create_list_update() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="申請A",
            description="説明",
            creator_user_id="u1",
            creator_name="山田",
            visibility="internal",
            definition=_definition(),
        )
        assert err is None and form
        assert form["status"] == "draft"
        assert form["title"] == "申請A"
        listed = store.list_forms_for_user("u1")
        assert len(listed) == 1
        assert listed[0]["id"] == form["id"]
        assert "definition" not in listed[0]

        updated, err = store.update_form(
            form["id"],
            actor_user_id="u1",
            title="申請A改",
        )
        assert err is None and updated
        assert updated["title"] == "申請A改"

        _u, err = store.update_form(form["id"], actor_user_id="other", title="x")
        assert err and "権限" in err
    finally:
        _teardown(path)


def test_form_tags_normalize_and_persist() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="転入案内",
            description=None,
            creator_user_id="u1",
            creator_name="山田",
            tags=["ナビゲーション", "転入", " 転入 ", "", "ナビゲーション"],
        )
        assert err is None and form
        assert form["tags"] == ["ナビゲーション", "転入"]
        listed = store.list_forms_for_user("u1")
        assert listed[0]["tags"] == ["ナビゲーション", "転入"]

        updated, err = store.update_form(
            form["id"],
            actor_user_id="u1",
            tags=["転入", "添付"],
        )
        assert err is None and updated
        assert updated["tags"] == ["転入", "添付"]

        too_long, err = store.create_form(
            title="長い",
            description=None,
            creator_user_id="u1",
            creator_name=None,
            tags=["あ" * 31],
        )
        assert too_long is None and err and "30"
    finally:
        _teardown(path)


def test_publish_requires_components() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="空",
            description=None,
            creator_user_id="u1",
            creator_name=None,
        )
        assert err is None and form
        _d, err = store.set_status(form["id"], actor_user_id="u1", status="published")
        assert err and "手続き" in err
        proc, perr = store.create_procedure(
            name="空",
            description=None,
            guide_form_id=form["id"],
            creator_user_id="u1",
        )
        assert perr is None and proc
        _p, err = store.set_procedure_status(proc["id"], actor_user_id="u1", status="published")
        assert err and "部品" in err
    finally:
        _teardown(path)


def test_publish_submit_csv_guest() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="申請",
            description=None,
            creator_user_id="u1",
            creator_name="作成者",
            visibility="both",
            definition=_definition(),
            pin="1234",
        )
        assert err is None and form
        rejected, err = store.set_status(form["id"], actor_user_id="u1", status="published")
        assert rejected is None and err and "手続き" in err
        published = _reception(form["id"])
        assert published["status"] == "published"
        assert published["kind"] == "reception"
        assert published["source_form_id"] == form["id"]
        assert published["published_version_id"]
        assert published["draft_differs"] is False
        assert published["submission_count"] == 0
        definition = store.get_form(form["id"], actor_user_id="u1")
        assert definition and definition["locked"] is True
        assert definition["status"] == "draft"
        assert definition["kind"] == "definition"
        listed = store.list_forms_for_user("u1")
        assert [item["id"] for item in listed] == [form["id"]]

        public, err = store.public_form(published["guest_token"])
        assert err is None and public
        assert public["requires_pin"] is True

        public, err = store.public_form(published["guest_token"], pin="0000")
        assert err and "暗証" in err

        public, err = store.public_form(published["guest_token"], pin="1234")
        assert err is None and public
        assert public["requires_pin"] is False
        assert public["definition"]["components"][0]["id"] == "name"

        _r, err = store.submit_answers(
            guest_token=published["guest_token"],
            answers={"name": ""},
            submitter_user_id=None,
            submitter_name="市民",
            pin="1234",
        )
        assert err and "必須" in err

        result, err = store.submit_answers(
            guest_token=published["guest_token"],
            answers={"name": "佐藤", "mail": "sato@example.jp"},
            submitter_user_id=None,
            submitter_name="佐藤",
            pin="1234",
        )
        assert err is None and result
        assert result["receipt_code"]

        after = store.get_form(published["id"])
        assert after and after["submission_count"] == 1
        assert after["draft_differs"] is False
        source = store.get_form(form["id"])
        assert source and source["submission_count"] == 0
        items, err = store.list_submissions(published["id"], actor_user_id="u1")
        assert err is None and items
        assert len(items) == 1
        assert items[0]["answers"]["name"] == "佐藤"
        assert items[0]["form_version"] == 1
        assert items[0]["definition"]["components"][0]["id"] == "name"

        csv_text, err = store.export_csv(published["id"], actor_user_id="u1")
        assert err is None and csv_text
        assert "氏名" in csv_text
        assert "佐藤" in csv_text
        assert "form_version" in csv_text
    finally:
        _teardown(path)


def test_answers_use_submitted_version() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="版確認",
            description=None,
            creator_user_id="u1",
            creator_name=None,
            visibility="internal",
            definition=_definition(),
        )
        assert err is None and form
        reception = _reception(form["id"])
        store.submit_answers(
            form_id=reception["id"],
            answers={"name": "旧回答", "mail": "old@example.jp"},
            submitter_user_id="u1",
            submitter_name="旧",
        )
        changed = _definition()
        changed["components"] = [
            {"id": "new_field", "type": "text", "label": "新しい項目", "required": True}
        ]
        store.update_form(
            reception["id"],
            actor_user_id="u1",
            definition=changed,
        )
        pending = store.get_form(reception["id"])
        assert pending and pending["draft_differs"] is True
        assert pending["submission_count"] == 1
        published, err = store.set_status(reception["id"], actor_user_id="u1", status="published")
        assert err is None and published and published["published_version"] == 2
        assert published["draft_differs"] is False
        result, err = store.submit_answers(
            form_id=reception["id"],
            answers={"new_field": "新回答"},
            submitter_user_id="u1",
            submitter_name="新",
        )
        assert err is None and result
        items, err = store.list_submissions(reception["id"], actor_user_id="u1")
        assert err is None and items
        assert len(items) == 2
        newest = next(i for i in items if i["form_version"] == 2)
        oldest = next(i for i in items if i["form_version"] == 1)
        assert newest["answers"]["new_field"] == "新回答"
        assert [c["id"] for c in newest["definition"]["components"]] == ["new_field"]
        assert oldest["answers"]["name"] == "旧回答"
        assert [c["label"] for c in oldest["definition"]["components"] if c["id"] == "name"] == ["氏名"]
        csv_text, err = store.export_csv(reception["id"], actor_user_id="u1")
        assert err is None and csv_text
        assert "氏名" in csv_text
        assert "新しい項目" in csv_text
        assert "旧回答" in csv_text
        assert "新回答" in csv_text
        detail = store.get_form(reception["id"])
        assert detail and detail["published_version"] == 2
    finally:
        _teardown(path)


def test_internal_not_on_public() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="庁内のみ",
            description=None,
            creator_user_id="u1",
            creator_name=None,
            visibility="internal",
            definition=_definition(),
        )
        assert err is None and form
        published = _reception(form["id"])
        _p, err = store.public_form(published["guest_token"])
        assert err and "外部公開" in err
    finally:
        _teardown(path)


def test_mynumber_masked() -> None:
    path = _setup_db()
    try:
        first11 = "12345678901"
        total = 0
        for i in range(1, 12):
            p = int(first11[11 - i])
            q = i + 1 if i <= 6 else i - 5
            total += p * q
        c = total % 11
        mn = first11 + str(0 if c <= 1 else 11 - c)
        raw = spec.empty_definition("庁内")
        raw["components"] = [{"id": "mn", "type": "mynumber", "label": "個人番号", "required": True}]
        form, err = store.create_form(
            title="庁内",
            description=None,
            creator_user_id="u1",
            creator_name=None,
            visibility="internal",
            definition=raw,
        )
        assert err is None and form
        published = _reception(form["id"])
        result, err = store.submit_answers(
            form_id=published["id"],
            answers={"mn": mn},
            submitter_user_id="u1",
            submitter_name="職員",
        )
        assert err is None and result
        items, err = store.list_submissions(published["id"], actor_user_id="u1")
        assert err is None and items
        shown = items[0]["answers"]["mn"]
        assert shown != mn
        assert shown.endswith(mn[-4:])
        assert "*" in shown
    finally:
        _teardown(path)


def test_retention_cleanup() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="古い",
            description=None,
            creator_user_id="u1",
            creator_name=None,
            retention_days=0,
        )
        assert err is None and form
        db = store.connect()
        db.execute(
            "UPDATE forms SET created_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", form["id"]),
        )
        db.commit()
        n = store.delete_old_forms()
        assert n == 1
        assert store.get_form(form["id"]) is None
    finally:
        _teardown(path)


def test_lock_and_second_reception() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="定義",
            description=None,
            creator_user_id="u1",
            creator_name=None,
            visibility="both",
            definition=_definition(),
        )
        assert err is None and form
        locked, err = store.set_status(
            form["id"], actor_user_id="u1", status="draft", locked=True
        )
        assert err is None and locked and locked["locked"] is True
        _u, err = store.update_form(form["id"], actor_user_id="u1", title="変更")
        assert err and "作成完了" in err
        denied, err = store.set_status(form["id"], actor_user_id="u1", status="published")
        assert denied is None and err and "手続き" in err
        first = _reception(form["id"])
        closed, err = store.set_status(first["id"], actor_user_id="u1", status="closed")
        assert err is None and closed and closed["status"] == "closed"
        procs = store.list_procedures(actor_user_id="u1")
        assert procs
        store.set_procedure_status(procs[0]["id"], actor_user_id="u1", status="draft")
        token = first["guest_token"]
        store.set_procedure_status(procs[0]["id"], actor_user_id="u1", status="published")
        detail = store.get_form(form["id"], actor_user_id="u1")
        assert detail and len(detail["receptions"]) == 1
        reopened = store.get_form(first["id"], actor_user_id="u1")
        assert reopened and reopened["status"] == "published"
        assert reopened["guest_token"] == token
        inbox = store.list_inbox(actor_user_id="u1")
        opening_ids = {item["id"] for item in inbox["openings"] if item["kind"] == "procedure"}
        assert procs[0]["id"] in opening_ids
        assert all(item["kind"] == "procedure" for item in inbox["openings"])
        assert any(p["id"] == procs[0]["id"] for p in inbox["procedures"])
        denied = store.delete_procedure(procs[0]["id"], actor_user_id="u1")
        assert denied and "公開中" in denied
        store.set_procedure_status(procs[0]["id"], actor_user_id="u1", status="draft")
        inbox = store.list_inbox(actor_user_id="u1")
        assert not any(p["id"] == procs[0]["id"] for p in inbox["procedures"])
        assert store.delete_procedure(procs[0]["id"], actor_user_id="u1") is None
    finally:
        _teardown(path)


def test_legacy_published_migrates_to_reception() -> None:
    path = _setup_db()
    try:
        form, err = store.create_form(
            title="旧公開",
            description=None,
            creator_user_id="u1",
            creator_name=None,
            visibility="both",
            definition=_definition(),
        )
        assert err is None and form
        token = form["guest_token"]
        db = store.connect()
        db.execute(
            "UPDATE forms SET status = 'published', source_form_id = NULL, locked = 0 WHERE id = ?",
            (form["id"],),
        )
        db.commit()
        store.reset_connection()
        store.DB_PATH = path
        store.init_db()
        detail = store.get_form(form["id"], actor_user_id="u1")
        assert detail and detail["kind"] == "definition"
        assert detail["locked"] is True
        assert detail["status"] == "draft"
        assert detail["guest_token"] != token
        assert len(detail["receptions"]) == 1
        rec = detail["receptions"][0]
        assert rec["guest_token"] == token
        assert rec["status"] == "published"
        public, perr = store.public_form(token)
        assert perr is None and public
    finally:
        _teardown(path)


def test_sample_single_form_procedure() -> None:
    path = _setup_db()
    try:
        from app import seed

        first = seed.ensure_sample_data()
        second = seed.ensure_sample_data()
        assert first
        assert second is None
        procs = store.list_procedures(actor_user_id="seed")
        assert any(p["name"] == seed.SAMPLE_PROC_NAME for p in procs)
        detail = store.get_procedure(first, actor_user_id="seed")
        assert detail
        assert detail["status"] == "published"
        assert detail["choice_fields"] == []
        assert (detail.get("mapping") or {}).get("rules") == []
        form = store.get_form(detail["guide_form_id"], actor_user_id="seed")
        assert form
        assert "ナビゲーション" not in (form.get("tags") or [])
        assert "サンプル" in (form.get("tags") or [])
        db = store.connect()
        db.execute(
            "UPDATE forms SET tags = ? WHERE id = ?",
            ('["ナビゲーション", "サンプル"]', form["id"]),
        )
        db.commit()
        assert seed.ensure_sample_data() is None
        form = store.get_form(detail["guide_form_id"], actor_user_id="seed")
        assert form
        assert "ナビゲーション" not in (form.get("tags") or [])
        types = [c["type"] for c in form["definition"]["components"]]
        assert "radio" not in types
        assert "select" not in types
        assert "checkbox" not in types
    finally:
        _teardown(path)


if __name__ == "__main__":
    test_create_list_update()
    test_publish_requires_components()
    test_publish_submit_csv_guest()
    test_answers_use_submitted_version()
    test_internal_not_on_public()
    test_mynumber_masked()
    test_retention_cleanup()
    test_lock_and_second_reception()
    test_legacy_published_migrates_to_reception()
    test_sample_single_form_procedure()
    print("ok")
