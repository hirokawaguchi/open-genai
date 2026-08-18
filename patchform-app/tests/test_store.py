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
        published, err = store.set_status(form["id"], actor_user_id="u1", status="published")
        assert err is None and published
        assert published["status"] == "published"
        assert published["published_version_id"]

        public, err = store.public_form(form["guest_token"])
        assert err is None and public
        assert public["requires_pin"] is True

        public, err = store.public_form(form["guest_token"], pin="0000")
        assert err and "暗証" in err

        public, err = store.public_form(form["guest_token"], pin="1234")
        assert err is None and public
        assert public["requires_pin"] is False
        assert public["definition"]["components"][0]["id"] == "name"

        _r, err = store.submit_answers(
            guest_token=form["guest_token"],
            answers={"name": ""},
            submitter_user_id=None,
            submitter_name="市民",
            pin="1234",
        )
        assert err and "必須" in err

        result, err = store.submit_answers(
            guest_token=form["guest_token"],
            answers={"name": "佐藤", "mail": "sato@example.jp"},
            submitter_user_id=None,
            submitter_name="佐藤",
            pin="1234",
        )
        assert err is None and result
        assert result["receipt_code"]

        items, err = store.list_submissions(form["id"], actor_user_id="u1")
        assert err is None and items
        assert len(items) == 1
        assert items[0]["answers"]["name"] == "佐藤"

        csv_text, err = store.export_csv(form["id"], actor_user_id="u1")
        assert err is None and csv_text
        assert "氏名" in csv_text
        assert "佐藤" in csv_text
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
        store.set_status(form["id"], actor_user_id="u1", status="published")
        _p, err = store.public_form(form["guest_token"])
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
        store.set_status(form["id"], actor_user_id="u1", status="published")
        result, err = store.submit_answers(
            form_id=form["id"],
            answers={"mn": mn},
            submitter_user_id="u1",
            submitter_name="職員",
        )
        assert err is None and result
        items, err = store.list_submissions(form["id"], actor_user_id="u1")
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


if __name__ == "__main__":
    test_create_list_update()
    test_publish_requires_components()
    test_publish_submit_csv_guest()
    test_internal_not_on_public()
    test_mynumber_masked()
    test_retention_cleanup()
    print("ok")
