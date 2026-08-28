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


def test_scenario_workbench_bundle_grows() -> None:
    """申請束は閉じない。申請者が複製・添付し、他システムへは記入必須だけ揃える。"""
    import base64

    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "許可申請案内",
            [
                {"id": "name", "type": "text", "label": "氏名", "required": True, "imi_type": "ic:氏名"},
                {
                    "id": "kind",
                    "type": "radio",
                    "label": "申請",
                    "required": True,
                    "properties": {"options": ["新規", "更新"]},
                },
            ],
        )
        keireki = _create_form(
            client,
            "役員経歴書",
            [{"id": "name", "type": "text", "label": "役員氏名", "required": True}],
        )
        proc = _publish(
            client,
            "許可の手続き",
            guide["id"],
            mapping={
                "rules": [
                    {
                        "component_id": "kind",
                        "option": "新規",
                        "form_ids": [keireki["id"]],
                        "prepare": ["住民票の写し"],
                    }
                ]
            },
        )
        guide_rec = _reception(client, guide["id"])
        keireki_rec = _reception(client, keireki["id"])

        res = client.post(
            f"/public/api/forms/{guide_rec['guest_token']}/submissions",
            json={"answers": {"name": "田中一郎", "kind": "新規"}, "submitter_name": "田中一郎"},
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        keireki_item = next(it for it in opened["items"] if it["kind"] == "yoshiki")
        juminhyo_item = next(it for it in opened["items"] if it["kind"] == "attach")

        # 役員が2人。経歴書を人数分に複製する
        res = client.post(
            f"/public/api/applications/{opened['token']}/items",
            json={"duplicate_of": keireki_item["id"]},
        )
        assert res.status_code == 201, res.text
        grown = res.json()
        keireki_items = [it for it in grown["items"] if it.get("form_id") == keireki_rec["id"]]
        assert len(keireki_items) == 2

        # 住民票はファイル添付で満たす
        blob = base64.b64encode(b"pdf-bytes").decode()
        res = client.post(
            f"/public/api/applications/{opened['token']}/items/{juminhyo_item['id']}/file",
            json={"filename": "juminhyo.pdf", "data": blob},
        )
        assert res.status_code == 200, res.text

        # 経歴書は2件ともオンライン記入
        for idx, item in enumerate(keireki_items):
            res = client.post(
                f"/public/api/forms/{keireki_rec['guest_token']}/submissions",
                json={
                    "answers": {"name": f"役員{idx}"},
                    "submitter_name": "田中一郎",
                    "application_token": opened["token"],
                    "application_item_id": item["id"],
                },
            )
            assert res.status_code == 201, res.text

        res = client.get(f"/public/api/applications/{opened['token']}")
        final = res.json()
        by_id = {it["id"]: it for it in final["items"]}
        assert by_id[juminhyo_item["id"]]["status"] == "submitted"
        assert all(by_id[it["id"]]["status"] == "submitted" for it in keireki_items)

        # 記入必須だけ揃える書き出しは、記入必須（案内）の氏名だけ。様式ファイルは混ざらない
        res = client.get(
            f"/procedures/{proc['id']}/export",
            headers=_staff(),
            params={"format": "aligned"},
        )
        assert res.status_code == 200, res.text
        aligned = res.content.decode("utf-8-sig")
        assert "許可申請案内::ic:氏名" in aligned
        assert "田中一郎" in aligned
        assert "役員経歴書" not in aligned
    finally:
        _teardown(path, mail_dir)


def test_scenario_mypage_project_first() -> None:
    """マイ手続き: 空プロジェクトを先に作り、案内回答で書類が埋まり、状態が育つ。"""
    import base64

    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "許可申請の案内",
            [
                {"id": "name", "type": "text", "label": "氏名", "required": True},
                {
                    "id": "kind",
                    "type": "radio",
                    "label": "申請の種類",
                    "required": True,
                    "properties": {"options": ["新規", "更新"]},
                },
            ],
        )
        # file 部品だけのプレースホルダ様式（添付専用）
        yoshiki = _create_form(
            client, "様式第3号", [{"id": "a", "type": "file", "label": "様式ファイル"}]
        )
        proc = _publish(
            client,
            "建設業許可の手続き",
            guide["id"],
            mapping={
                "rules": [
                    {
                        "component_id": "kind",
                        "option": "新規",
                        "form_ids": [yoshiki["id"]],
                        "prepare": ["住民票の写し"],
                    }
                ]
            },
        )
        guide_rec = _reception(client, guide["id"])
        yoshiki_rec = _reception(client, yoshiki["id"])

        # 1) 空プロジェクト作成（未着手）
        res = client.post(
            "/applications", headers=_staff(), json={"procedure_id": proc["id"]}
        )
        assert res.status_code == 201, res.text
        proj = res.json()
        token = proj["token"]
        assert proj["title"] == "建設業許可の手続き"
        assert proj["status"]["effective"] == "未着手"
        assert [i["kind"] for i in proj["items"]] == ["data"]
        nav_id = proj["items"][0]["id"]

        # 2) マイ手続き一覧に出る（本人のみ）
        res = client.get("/applications/mine", headers=_staff())
        assert res.status_code == 200, res.text
        assert len(res.json()["applications"]) == 1
        assert client.get("/applications/mine", headers=_staff("other")).json()[
            "applications"
        ] == []

        # 3) 案内回答で書類が生成（作業中）
        res = client.post(
            f"/forms/{guide_rec['id']}/submissions",
            headers=_staff(),
            json={
                "answers": {"name": "田中一郎", "kind": "新規"},
                "application_token": token,
                "application_item_id": nav_id,
            },
        )
        assert res.status_code == 201, res.text
        after = res.json()["application"]
        assert after["status"]["effective"] == "作業中"
        assert "様式第3号" in [i["title"] for i in after["items"]]
        assert after["notice"]["prepare"] == ["住民票の写し"]

        # 4) 書類をすべて満たすと提出済
        yitem = next(i for i in after["items"] if i.get("form_id") == yoshiki_rec["id"])
        attach = next(i for i in after["items"] if i["kind"] == "attach")
        blob = base64.b64encode(b"pdf").decode()
        for it in (yitem, attach):
            res = client.post(
                f"/applications/{proj['id']}/items/{it['id']}/file",
                headers=_staff(),
                json={"filename": "f.pdf", "data": blob},
            )
            assert res.status_code == 200, res.text
        assert res.json()["status"]["effective"] == "提出済"

        # 5) 手動上書き（取下げ）と改名
        res = client.post(
            f"/applications/{proj['id']}/status",
            headers=_staff(),
            json={"status": "取下げ"},
        )
        assert res.status_code == 200, res.text
        st = res.json()["status"]
        assert st["auto"] == "提出済" and st["effective"] == "取下げ"
        res = client.patch(
            f"/applications/{proj['id']}",
            headers=_staff(),
            json={"title": "田中建設 新規許可"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["title"] == "田中建設 新規許可"
    finally:
        _teardown(path, mail_dir)


def test_scenario_guide_submission_registers_owner() -> None:
    """一本化: 庁内ユーザーが案内に回答した束は、その人のマイ手続きに載る。"""
    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "案内",
            [
                {
                    "id": "kind",
                    "type": "radio",
                    "label": "種類",
                    "required": True,
                    "properties": {"options": ["新規", "更新"]},
                }
            ],
        )
        proc = _publish(client, "許可の手続き", guide["id"], mapping={"rules": []})
        guide_rec = _reception(client, guide["id"])

        # プロジェクトを先に作らず、案内へ直接回答（庁内=owner付き）
        res = client.post(
            f"/forms/{guide_rec['id']}/submissions",
            headers=_staff(),
            json={"answers": {"kind": "新規"}},
        )
        assert res.status_code == 201, res.text
        app = res.json()["application"]
        assert app["owner_kind"] == "internal"
        assert app["status"]["effective"] in ("作業中", "提出済")

        # マイ手続きに出る（本人のみ）
        mine = client.get("/applications/mine", headers=_staff()).json()["applications"]
        assert any(a["id"] == app["id"] for a in mine)
        assert client.get("/applications/mine", headers=_staff("other")).json()[
            "applications"
        ] == []
        _ = proc
    finally:
        _teardown(path, mail_dir)


def test_scenario_wizard_resolve_meta_and_imi() -> None:
    """作成ウィザード: dry-run 解決・案件メタ更新・本人横断 IMI 候補。"""
    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "案内",
            [
                {"id": "name", "type": "text", "label": "氏名", "required": True, "imi_type": "ic:氏名"},
                {
                    "id": "kind",
                    "type": "radio",
                    "label": "種類",
                    "required": True,
                    "properties": {"options": ["新規", "更新"]},
                },
            ],
        )
        yoshiki = _create_form(
            client,
            "様式第4号",
            [{"id": "cnt", "type": "text", "label": "使用人数", "required": True}],
        )
        proc = _publish(
            client,
            "建設業許可の手続き",
            guide["id"],
            mapping={
                "rules": [
                    {"component_id": "kind", "option": "新規", "form_ids": [yoshiki["id"]]}
                ]
            },
        )
        guide_rec = _reception(client, guide["id"])
        _reception(client, yoshiki["id"])

        # 1) dry-run 解決: 新規なら様式第4号が必要書類に出る（DB書き込みなし）
        res = client.post(
            f"/procedures/{proc['id']}/resolve",
            headers=_staff(),
            json={"answers": {"name": "田中一郎", "kind": "新規"}},
        )
        assert res.status_code == 200, res.text
        preview = res.json()
        titles = [i["title"] for i in preview["items"]]
        assert "様式第4号" in titles
        y = next(i for i in preview["items"] if i["title"] == "様式第4号")
        assert y["kind"] == "yoshiki" and y["can_fill_online"] is True
        # 解決はプレビューのみ（マイ手続きは増えない）
        assert client.get("/applications/mine", headers=_staff()).json()["applications"] == []

        # 2) プロジェクトA 作成 + 案内回答（名前を記録）
        proj_a = client.post(
            "/applications", headers=_staff(), json={"procedure_id": proc["id"]}
        ).json()
        nav_a = proj_a["items"][0]["id"]
        res = client.post(
            f"/forms/{guide_rec['id']}/submissions",
            headers=_staff(),
            json={
                "answers": {"name": "田中一郎", "kind": "新規"},
                "application_token": proj_a["token"],
                "application_item_id": nav_a,
            },
        )
        assert res.status_code == 201, res.text

        # 3) 案件メタ（担当・期限・次回更新日）を更新
        res = client.patch(
            f"/applications/{proj_a['id']}",
            headers=_staff(),
            json={"assignee": "窓口A", "deadline": "2026-09-30", "next_action_date": "2026-09-01"},
        )
        assert res.status_code == 200, res.text
        meta = res.json()
        assert meta["assignee"] == "窓口A"
        assert meta["deadline"] == "2026-09-30"
        assert meta["next_action_date"] == "2026-09-01"
        mine = client.get("/applications/mine", headers=_staff()).json()["applications"]
        row = next(a for a in mine if a["id"] == proj_a["id"])
        assert row["assignee"] == "窓口A" and row["deadline"] == "2026-09-30"

        # 不正な日付は 400
        assert (
            client.patch(
                f"/applications/{proj_a['id']}",
                headers=_staff(),
                json={"deadline": "2026/09/30"},
            ).status_code
            == 400
        )

        # 4) プロジェクトB から本人横断 IMI 候補（A の氏名が候補源に載る）
        proj_b = client.post(
            "/applications", headers=_staff(), json={"procedure_id": proc["id"]}
        ).json()
        res = client.get(
            f"/applications/{proj_b['id']}/imi-sources", headers=_staff()
        )
        assert res.status_code == 200, res.text
        sources = res.json()["sources"]
        names = [
            src["answers"].get("name")
            for src in sources
            if isinstance(src.get("answers"), dict)
        ]
        assert "田中一郎" in names
        # 他人からは A の候補は見えない
        assert (
            client.get(
                f"/applications/{proj_b['id']}/imi-sources", headers=_staff("other")
            ).status_code
            == 403
        )
    finally:
        _teardown(path, mail_dir)


def test_scenario_item_source_and_reorder() -> None:
    """記入と添付は併存でき、採用ソースを切り替えられる。並び替えも保存される。"""
    import base64

    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "案内",
            [
                {
                    "id": "kind",
                    "type": "radio",
                    "label": "種類",
                    "required": True,
                    "properties": {"options": ["新規", "更新"]},
                }
            ],
        )
        # 実入力欄を持つ様式（オンライン記入できる）
        yoshiki = _create_form(
            client,
            "様式第3号 工事施工金額",
            [{"id": "amount", "type": "text", "label": "金額", "required": True}],
        )
        proc = _publish(
            client,
            "許可の手続き",
            guide["id"],
            mapping={
                "rules": [
                    {
                        "component_id": "kind",
                        "option": "新規",
                        "form_ids": [yoshiki["id"]],
                        "prepare": ["住民票の写し"],
                    }
                ]
            },
        )
        guide_rec = _reception(client, guide["id"])
        yoshiki_rec = _reception(client, yoshiki["id"])

        proj = client.post(
            "/applications", headers=_staff(), json={"procedure_id": proc["id"]}
        ).json()
        nav_id = proj["items"][0]["id"]
        after = client.post(
            f"/forms/{guide_rec['id']}/submissions",
            headers=_staff(),
            json={
                "answers": {"kind": "新規"},
                "application_token": proj["token"],
                "application_item_id": nav_id,
            },
        ).json()["application"]
        yitem = next(i for i in after["items"] if i.get("form_id") == yoshiki_rec["id"])
        attach = next(i for i in after["items"] if i["kind"] == "attach")
        assert yitem["can_fill_online"] is True

        # 1) オンライン記入で満たす
        client.post(
            f"/forms/{yoshiki_rec['id']}/submissions",
            headers=_staff(),
            json={
                "answers": {"amount": "1000"},
                "application_token": proj["token"],
                "application_item_id": yitem["id"],
            },
        )
        state = client.get(f"/applications/{proj['id']}", headers=_staff()).json()
        y = next(i for i in state["items"] if i["id"] == yitem["id"])
        assert y["form_submitted"] is True
        assert y["status"] == "submitted"

        # 2) 同じ枠にファイルも添付（併存）→ 既定は添付を採用
        blob = base64.b64encode(b"pdf").decode()
        client.post(
            f"/applications/{proj['id']}/items/{yitem['id']}/file",
            headers=_staff(),
            json={"filename": "y.pdf", "data": blob},
        )
        state = client.get(f"/applications/{proj['id']}", headers=_staff()).json()
        y = next(i for i in state["items"] if i["id"] == yitem["id"])
        assert y["form_submitted"] is True and y["file_attached"] is True
        assert y["fulfillment"] == "file"

        # 3) 採用ソースを記入へ切り替え（添付は残る）
        res = client.post(
            f"/applications/{proj['id']}/items/{yitem['id']}/source",
            headers=_staff(),
            json={"source": "form"},
        )
        assert res.status_code == 200, res.text
        y = next(i for i in res.json()["items"] if i["id"] == yitem["id"])
        assert y["fulfillment"] == "form" and y["file_attached"] is True
        assert y["status"] == "submitted"

        # 4) 並び替え（添付を先頭へ）
        order = [attach["id"], yitem["id"]]
        res = client.post(
            f"/applications/{proj['id']}/items/order",
            headers=_staff(),
            json={"order": order},
        )
        assert res.status_code == 200, res.text
        docs = [i["id"] for i in res.json()["items"] if i["kind"] != "data"]
        # 指定した並びが先頭に反映される（常設「その他」枠などは末尾に残る）
        assert docs[: len(order)] == order
    finally:
        _teardown(path, mail_dir)


def test_scenario_form_level_template_and_standing_other() -> None:
    """ひな型は様式フォーム自身に登録。手続き公開では選ぶだけ。常設『その他』枠も付く。"""
    import base64

    client, path, mail_dir = _setup()
    try:
        guide = _create_form(
            client,
            "案内",
            [
                {
                    "id": "kind",
                    "type": "radio",
                    "label": "種類",
                    "required": True,
                    "properties": {"options": ["新規", "更新"]},
                }
            ],
        )
        # 記入様式（実入力欄あり）と、添付専用フォーム（ファイルのみ）
        yoshiki = _create_form(
            client,
            "様式第3号 工事施工金額",
            [{"id": "amount", "type": "text", "label": "金額", "required": True}],
        )
        juminhyo = _create_form(
            client, "住民票の写し", [{"id": "f", "type": "file", "label": "ファイル"}]
        )

        # 役割の自己記述: 記入様式=yoshiki / ファイルのみ=attachment
        y_detail = client.get(f"/forms/{yoshiki['id']}", headers=_staff()).json()
        j_detail = client.get(f"/forms/{juminhyo['id']}", headers=_staff()).json()
        assert y_detail["definition"]["metadata"]["doc_role"] == "yoshiki"
        assert j_detail["definition"]["metadata"]["doc_role"] == "attachment"

        # フォーム作成時にひな型を登録
        blob = base64.b64encode(b"template-doc").decode()
        res = client.post(
            f"/forms/{yoshiki['id']}/template",
            headers=_staff(),
            json={"filename": "yoshiki3.docx", "data": blob},
        )
        assert res.status_code == 201, res.text

        proc = _publish(
            client,
            "許可の手続き",
            guide["id"],
            mapping={
                "rules": [
                    {
                        "component_id": "kind",
                        "option": "新規",
                        "form_ids": [yoshiki["id"], juminhyo["id"]],
                    }
                ]
            },
        )
        guide_rec = _reception(client, guide["id"])
        yoshiki_rec = _reception(client, yoshiki["id"])
        _reception(client, juminhyo["id"])

        proj = client.post(
            "/applications", headers=_staff(), json={"procedure_id": proc["id"]}
        ).json()
        nav_id = proj["items"][0]["id"]
        after = client.post(
            f"/forms/{guide_rec['id']}/submissions",
            headers=_staff(),
            json={
                "answers": {"kind": "新規"},
                "application_token": proj["token"],
                "application_item_id": nav_id,
            },
        ).json()["application"]

        yitem = next(i for i in after["items"] if i.get("form_id") == yoshiki_rec["id"])
        # ひな型は様式フォーム由来で引ける
        assert yitem["template"] and yitem["template"]["filename"] == "yoshiki3.docx"
        assert yitem["can_fill_online"] is True
        # 常設の「その他」枠が必ず付く
        assert any(i["slot_id"] == "attach:__other__" for i in after["items"])

        # アイテム単位のひな型DLが出所を問わず通る
        res = client.get(
            f"/applications/{proj['id']}/items/{yitem['id']}/template", headers=_staff()
        )
        assert res.status_code == 200, res.text
        assert res.content == b"template-doc"

        # 必須の書類を満たせば、任意の「その他」枠が空でも提出済になる
        juminhyo_item = next(
            i for i in after["items"] if i.get("form_id") and i.get("form_id") != yoshiki_rec["id"] and i["kind"] == "yoshiki"
        )
        fblob = base64.b64encode(b"pdf").decode()
        client.post(
            f"/forms/{yoshiki_rec['id']}/submissions",
            headers=_staff(),
            json={
                "answers": {"amount": "1"},
                "application_token": proj["token"],
                "application_item_id": yitem["id"],
            },
        )
        res = client.post(
            f"/applications/{proj['id']}/items/{juminhyo_item['id']}/file",
            headers=_staff(),
            json={"filename": "j.pdf", "data": fblob},
        )
        assert res.json()["status"]["effective"] == "提出済", res.text
    finally:
        _teardown(path, mail_dir)


if __name__ == "__main__":
    test_scenario_single_form_inquiry_and_staff_mail_dump()
    test_scenario_option_value_opens_bundle_and_imi_carries()
    test_scenario_service_reads_only_the_diff()
    test_scenario_wrong_option_does_not_add_forms()
    test_scenario_workbench_bundle_grows()
    test_scenario_mypage_project_first()
    test_scenario_wizard_resolve_meta_and_imi()
    test_scenario_guide_submission_registers_owner()
    test_scenario_item_source_and_reorder()
    test_scenario_form_level_template_and_standing_other()
    print("ok")
