"""申請者・職員・庁内バッチの一連の流れ。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("INTERNAL_SIGNING_SECRET", "")
os.environ.setdefault("RAG_API_KEY", "test-key")
os.environ["PATCHFORM_SEED"] = ""

from fastapi.testclient import TestClient

from app import store
from app.main import app


def _staff(user_id: str = "u1") -> dict[str, str]:
    return {
        "x-api-key": "test-key",
        "x-user-id": user_id,
        "x-user-groups": "UserGroup",
        "x-scope": "00000000-0000-0000-0000-000000000000",
    }


def _setup() -> tuple[TestClient, str, str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    files_dir = tempfile.mkdtemp(prefix="pf-files-")
    mail_dir = tempfile.mkdtemp(prefix="pf-mail-")
    os.environ["PATCHFORM_FILES_DIR"] = files_dir
    os.environ["PATCHFORM_MAIL_DUMP_DIR"] = mail_dir
    os.environ["PATCHFORM_STAFF_BASE_URL"] = "http://localhost"
    os.environ.pop("PATCHFORM_SMTP_HOST", None)
    os.environ.pop("PATCHFORM_SMTP_FROM", None)
    os.environ["PATCHFORM_SERVICE_KEY"] = "svc-scenario"
    store.reset_connection()
    store.DB_PATH = path
    store.init_db()
    return TestClient(app), path, mail_dir


def _teardown(path: str, mail_dir: str) -> None:
    store.reset_connection()
    try:
        os.remove(path)
    except OSError:
        pass
    for key in (
        "PATCHFORM_FILES_DIR",
        "PATCHFORM_MAIL_DUMP_DIR",
        "PATCHFORM_STAFF_BASE_URL",
        "PATCHFORM_SERVICE_KEY",
    ):
        value = os.environ.pop(key, "")
        if key.endswith("_DIR") and value:
            shutil.rmtree(value, ignore_errors=True)
    shutil.rmtree(mail_dir, ignore_errors=True)


def _create_form(client: TestClient, title: str, components: list[dict]) -> dict:
    res = client.post(
        "/forms",
        headers=_staff(),
        json={
            "title": title,
            "visibility": "both",
            "definition": {
                "$version": "opengenai-patchform/1",
                "metadata": {"title": title, "description": ""},
                "components": components,
            },
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


def _publish(client: TestClient, name: str, guide_id: str, **extra: object) -> dict:
    body = {"name": name, "guide_form_id": guide_id, **extra}
    res = client.post("/procedures", headers=_staff(), json=body)
    assert res.status_code == 201, res.text
    proc = res.json()
    res = client.post(
        f"/procedures/{proc['id']}/status",
        headers=_staff(),
        json={"status": "published"},
    )
    assert res.status_code == 200, res.text
    return res.json()


def _reception(client: TestClient, form_id: str) -> dict:
    res = client.get(f"/forms/{form_id}", headers=_staff())
    assert res.status_code == 200, res.text
    recs = [r for r in res.json().get("receptions") or [] if r.get("status") == "published"]
    assert recs, "公開した窓口がありません"
    res = client.get(f"/forms/{recs[0]['id']}", headers=_staff())
    assert res.status_code == 200, res.text
    return res.json()


def _service() -> dict[str, str]:
    return {"x-api-key": "test-key", "x-service-key": "svc-scenario"}


def test_scenario_single_form_inquiry_and_staff_mail_dump() -> None:
    """1枚だけの手続き。申請者が出して、職員通知がテキストに残る。"""
    client, path, mail_dir = _setup()
    try:
        form = _create_form(
            client,
            "ご意見・お問い合わせ",
            [
                {"id": "name", "type": "text", "label": "お名前", "required": True},
                {"id": "email", "type": "email", "label": "メールアドレス", "required": True},
                {"id": "body", "type": "textarea", "label": "ご意見", "required": True},
            ],
        )
        proc = _publish(
            client,
            "ご意見・お問い合わせ",
            form["id"],
            notify_emails=["staff@example.lg.jp"],
        )
        guide = _reception(client, form["id"])

        res = client.post(
            f"/public/api/forms/{guide['guest_token']}/submissions",
            json={
                "answers": {
                    "name": "山田太郎",
                    "email": "taro@example.jp",
                    "body": "窓口の待ち時間が長い",
                },
                "submitter_name": "山田太郎",
            },
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        assert opened["procedure_id"] == proc["id"]
        assert opened["token"]
        assert len(opened["forms"]) == 1
        assert opened["forms"][0]["status"] == "submitted"
        assert opened["forms"][0]["answers"]["name"] == "山田太郎"

        dumps = list(Path(mail_dir).glob("*.txt"))
        assert len(dumps) == 1, dumps
        text = dumps[0].read_text(encoding="utf-8")
        assert "ご意見・お問い合わせ" in text
        assert opened["token"] in text
        assert "staff@example.lg.jp" in text
        assert f"/patchform/applications/{opened['id']}" in text
        assert "山田太郎" not in text
        assert "待ち時間" not in text
        assert "taro@example.jp" not in text

        res = client.get(f"/procedures/{proc['id']}/applications", headers=_staff())
        assert res.status_code == 200, res.text
        assert res.json()["applications"][0]["id"] == opened["id"]

        res = client.get(f"/applications/{opened['id']}/export", headers=_staff())
        assert res.status_code == 200, res.text
        csv_text = res.content.decode("utf-8-sig")
        assert "山田太郎" in csv_text
        assert "待ち時間" in csv_text
    finally:
        _teardown(path, mail_dir)


def test_scenario_option_value_opens_bundle_and_imi_carries() -> None:
    """表示文と値が違う案内を出すと、値で様式が足され、同じ語彙の氏名が束に残る。"""
    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "転入案内",
            [
                {
                    "id": "name",
                    "type": "text",
                    "label": "氏名",
                    "required": True,
                    "imi_type": "ic:氏名",
                },
                {
                    "id": "event",
                    "type": "radio",
                    "label": "事由",
                    "required": True,
                    "properties": {
                        "options": [
                            {"label": "転入（市外から）", "value": "tennyu"},
                            {"label": "転居（市内）", "value": "tenkyo"},
                        ]
                    },
                },
            ],
        )
        style = _create_form(
            client,
            "転入届",
            [
                {
                    "id": "name",
                    "type": "text",
                    "label": "申請者氏名",
                    "required": True,
                    "imi_type": "ic:氏名",
                }
            ],
        )
        attach = _create_form(
            client,
            "添付台紙",
            [
                {
                    "id": "items",
                    "type": "checkbox",
                    "label": "持参するもの",
                    "properties": {"options": ["住民票", "本人確認書類"]},
                }
            ],
        )
        proc = _publish(
            client,
            "転入の手続き",
            guide["id"],
            notify_emails=["juki@example.lg.jp"],
            mapping={
                "rules": [
                    {
                        "component_id": "event",
                        "option": "tennyu",
                        "form_ids": [style["id"], attach["id"]],
                        "notes": ["転入の案内"],
                        "prepare": ["住民票"],
                    },
                    {
                        "component_id": "event",
                        "option": "tenkyo",
                        "form_ids": [attach["id"]],
                        "notes": ["転居の案内"],
                        "prepare": [],
                    },
                ]
            },
        )
        guide_rec = _reception(client, guide["id"])
        style_rec = _reception(client, style["id"])
        attach_rec = _reception(client, attach["id"])

        res = client.post(
            f"/public/api/forms/{guide_rec['guest_token']}/submissions",
            json={
                "answers": {"name": "佐藤花子", "event": "tennyu"},
                "submitter_name": "佐藤花子",
            },
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        assert opened["procedure_id"] == proc["id"]
        assert opened["notice"]["prepare"] == ["住民票"]
        form_ids = {item["id"] for item in opened["forms"]}
        assert form_ids == {guide_rec["id"], style_rec["id"], attach_rec["id"]}
        submitted = next(item for item in opened["forms"] if item["id"] == guide_rec["id"])
        assert submitted["answers"]["event"] == "tennyu"
        assert submitted["answers"]["name"] == "佐藤花子"
        pending = [item for item in opened["forms"] if item["id"] != guide_rec["id"]]
        assert all(item["status"] == "none" for item in pending)

        res = client.post(
            f"/public/api/forms/{style_rec['guest_token']}/submissions",
            json={
                "answers": {"name": "佐藤花子"},
                "submitter_name": "佐藤花子",
                "application_token": opened["token"],
            },
        )
        assert res.status_code == 201, res.text

        res = client.get(f"/public/api/applications/{opened['token']}")
        assert res.status_code == 200, res.text
        bundle = res.json()
        names = [
            form["answers"]["name"]
            for form in bundle["forms"]
            if form.get("status") == "submitted" and form.get("answers")
        ]
        assert names == ["佐藤花子", "佐藤花子"]
        assert bundle["updated_at"] >= bundle["created_at"]

        dumps = list(Path(mail_dir).glob("*.txt"))
        assert len(dumps) == 1
        mail = dumps[0].read_text(encoding="utf-8")
        assert opened["token"] in mail
        assert "佐藤花子" not in mail
        assert "juki@example.lg.jp" in mail
    finally:
        _teardown(path, mail_dir)


def test_scenario_service_reads_only_the_diff() -> None:
    """庁内バッチは鍵があれば読む。新しい申請だけ since で取れる。書くことはできない。"""
    client, path, mail_dir = _setup()
    try:
        form = _create_form(
            client,
            "ご意見",
            [{"id": "name", "type": "text", "label": "お名前", "required": True}],
        )
        proc = _publish(client, "ご意見", form["id"], notify_emails=["staff@example.lg.jp"])
        guide = _reception(client, form["id"])

        first = client.post(
            f"/public/api/forms/{guide['guest_token']}/submissions",
            json={"answers": {"name": "一郎"}, "submitter_name": "一郎"},
        )
        assert first.status_code == 201, first.text
        app1 = first.json()["application"]

        res = client.get("/procedures", headers=_service())
        assert res.status_code == 200, res.text
        assert any(item["id"] == proc["id"] for item in res.json()["procedures"])

        res = client.post(
            "/forms",
            headers=_service(),
            json={
                "title": "書けない",
                "visibility": "both",
                "definition": {
                    "$version": "opengenai-patchform/1",
                    "metadata": {"title": "書けない", "description": ""},
                    "components": [{"id": "n", "type": "text", "label": "名"}],
                },
            },
        )
        assert res.status_code == 401

        second = client.post(
            f"/public/api/forms/{guide['guest_token']}/submissions",
            json={"answers": {"name": "二郎"}, "submitter_name": "二郎"},
        )
        assert second.status_code == 201, second.text
        app2 = second.json()["application"]

        res = client.get(
            f"/procedures/{proc['id']}/applications",
            headers=_service(),
            params={"since": app2["created_at"]},
        )
        assert res.status_code == 200, res.text
        ids = [item["id"] for item in res.json()["applications"]]
        assert app2["id"] in ids
        assert app1["id"] not in ids or app2["created_at"] == app1["created_at"]

        res = client.get(
            f"/procedures/{proc['id']}/export",
            headers=_service(),
            params={"format": "jsonl", "since": "2099-01-01T00:00:00+00:00"},
        )
        assert res.status_code == 200, res.text
        assert res.content.decode("utf-8").strip() == ""

        res = client.get(
            f"/applications/{app1['id']}",
            headers={"x-api-key": "test-key", "x-service-key": "wrong"},
        )
        assert res.status_code == 401
    finally:
        _teardown(path, mail_dir)


def test_scenario_wrong_option_does_not_add_forms() -> None:
    """案内で別の値を選ぶと、転入届は束に入らない。"""
    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "転入案内",
            [
                {"id": "name", "type": "text", "label": "氏名", "required": True},
                {
                    "id": "event",
                    "type": "radio",
                    "label": "事由",
                    "required": True,
                    "properties": {
                        "options": [
                            {"label": "転入（市外から）", "value": "tennyu"},
                            {"label": "転居（市内）", "value": "tenkyo"},
                        ]
                    },
                },
            ],
        )
        style = _create_form(
            client,
            "転入届",
            [{"id": "name", "type": "text", "label": "氏名", "required": True}],
        )
        _publish(
            client,
            "転入の手続き",
            guide["id"],
            mapping={
                "rules": [
                    {
                        "component_id": "event",
                        "option": "tennyu",
                        "form_ids": [style["id"]],
                    }
                ]
            },
        )
        guide_rec = _reception(client, guide["id"])
        res = client.post(
            f"/public/api/forms/{guide_rec['guest_token']}/submissions",
            json={"answers": {"name": "鈴木", "event": "tenkyo"}, "submitter_name": "鈴木"},
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        assert [item["title"] for item in opened["forms"]] == ["転入案内"]
        assert list(Path(mail_dir).glob("*.txt")) == []
    finally:
        _teardown(path, mail_dir)


if __name__ == "__main__":
    test_scenario_single_form_inquiry_and_staff_mail_dump()
    test_scenario_option_value_opens_bundle_and_imi_carries()
    test_scenario_service_reads_only_the_diff()
    test_scenario_wrong_option_does_not_add_forms()
    print("ok")
