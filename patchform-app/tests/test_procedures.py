"""手続きマスタと申請束。"""

from __future__ import annotations

import json
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

from app import assist, store
from app.main import app


def _headers(user_id: str = "u1") -> dict[str, str]:
    return {
        "x-api-key": "test-key",
        "x-user-id": user_id,
        "x-user-groups": "UserGroup",
        "x-scope": "00000000-0000-0000-0000-000000000000",
    }


def _setup() -> tuple[TestClient, str]:
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    files_dir = tempfile.mkdtemp(prefix="pf-files-")
    os.environ["PATCHFORM_FILES_DIR"] = files_dir
    store.reset_connection()
    store.DB_PATH = path
    store.init_db()
    return TestClient(app), path


def _teardown(path: str) -> None:
    store.reset_connection()
    try:
        os.remove(path)
    except OSError:
        pass
    files_dir = os.environ.pop("PATCHFORM_FILES_DIR", "")
    if files_dir:
        shutil.rmtree(files_dir, ignore_errors=True)


def _form(title: str, options: list[str] | None = None) -> dict:
    comps = [{"id": "name", "type": "text", "label": "氏名", "required": True}]
    if options is not None:
        comps.append(
            {
                "id": "event",
                "type": "radio",
                "label": "事由",
                "required": True,
                "properties": {"options": options},
            }
        )
    return {
        "$version": "opengenai-patchform/1",
        "metadata": {"title": title, "description": ""},
        "components": comps,
    }


def _create_form(client: TestClient, title: str, options: list[str] | None = None) -> dict:
    res = client.post(
        "/forms",
        headers=_headers(),
        json={"title": title, "visibility": "both", "definition": _form(title, options)},
    )
    assert res.status_code == 201, res.text
    return res.json()


def _reception_of(client: TestClient, form_id: str) -> dict:
    res = client.get(f"/forms/{form_id}", headers=_headers())
    assert res.status_code == 200, res.text
    recs = [r for r in res.json().get("receptions") or [] if r.get("status") == "published"]
    assert recs
    res = client.get(f"/forms/{recs[0]['id']}", headers=_headers())
    assert res.status_code == 200, res.text
    return res.json()


def _create_published(client: TestClient, title: str, options: list[str] | None = None) -> dict:
    form = _create_form(client, title, options)
    res = client.post(
        "/procedures",
        headers=_headers(),
        json={"name": f"{title}の手続き", "guide_form_id": form["id"]},
    )
    assert res.status_code == 201, res.text
    res = client.post(
        f"/procedures/{res.json()['id']}/status",
        headers=_headers(),
        json={"status": "published"},
    )
    assert res.status_code == 200, res.text
    return _reception_of(client, form["id"])


def test_procedure_bundle_from_guide() -> None:
    client, path = _setup()
    try:
        guide_def = _create_form(client, "転入案内", ["転入", "転居"])
        style_a_def = _create_form(client, "転入届")
        attach_def = _create_form(client, "添付台紙")

        res = client.post(
            "/procedures",
            headers=_headers(),
            json={
                "name": "転入の手続き",
                "description": "サンプル",
                "guide_form_id": guide_def["id"],
                "mapping": {
                    "rules": [
                        {
                            "component_id": "event",
                            "option": "転入",
                            "form_ids": [style_a_def["id"], attach_def["id"]],
                            "notes": "転入届を出してください",
                            "prepare": ["本人確認書類"],
                        },
                        {
                            "component_id": "event",
                            "option": "転居",
                            "form_ids": [attach_def["id"]],
                            "notes": "転居のみ",
                            "prepare": [],
                        },
                    ]
                },
            },
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        assert proc["status"] == "draft"
        assert proc["choice_fields"][0]["options"] == ["転入", "転居"]

        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "published"
        guide = _reception_of(client, guide_def["id"])
        style_a = _reception_of(client, style_a_def["id"])
        attach = _reception_of(client, attach_def["id"])

        res = client.post(
            f"/public/api/forms/{guide['guest_token']}/submissions",
            json={"answers": {"name": "山田", "event": "転入"}, "submitter_name": "山田"},
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        assert opened["token"]
        assert {f["id"] for f in opened["forms"]} == {guide["id"], style_a["id"], attach["id"]}
        assert "転入届を出してください" in opened["notice"]["notes"]
        assert opened["notice"]["prepare"] == ["本人確認書類"]

        res = client.get(f"/public/api/applications/{opened['token']}")
        assert res.status_code == 200
        body = res.json()
        assert body["procedure_name"] == "転入の手続き"
        statuses = {item["id"]: item["status"] for item in body["forms"]}
        assert statuses[guide["id"]] == "submitted"
        assert statuses[style_a["id"]] == "none"
        assert statuses[attach["id"]] == "none"

        res = client.post(
            f"/public/api/forms/{style_a['guest_token']}/submissions",
            json={
                "answers": {"name": "山田"},
                "submitter_name": "山田",
                "application_token": opened["token"],
            },
        )
        assert res.status_code == 201, res.text

        res = client.get(f"/public/api/applications/{opened['token']}")
        statuses = {item["id"]: item["status"] for item in res.json()["forms"]}
        assert statuses[guide["id"]] == "submitted"
        assert statuses[style_a["id"]] == "submitted"
        assert statuses[attach["id"]] == "none"

        res = client.get(f"/procedures/{proc['id']}/applications", headers=_headers())
        assert res.status_code == 200
        apps = res.json()["applications"]
        assert len(apps) == 1
        answered = {item["id"]: item for item in apps[0]["forms"]}
        assert answered[guide["id"]]["answers"]["name"] == "山田"
        assert answered[guide["id"]]["answers"]["event"] == "転入"
        assert answered[style_a["id"]]["answers"]["name"] == "山田"
        assert answered[guide["id"]]["receipt_code"]
        assert answered[guide["id"]]["definition"]

        standalone = _create_published(client, "単体アンケート")
        res = client.post(
            f"/public/api/forms/{standalone['guest_token']}/submissions",
            json={"answers": {"name": "佐藤"}, "submitter_name": "佐藤"},
        )
        assert res.status_code == 201, res.text
        one = res.json()["application"]
        assert {f["id"] for f in one["forms"]} == {standalone["id"]}
        assert one["forms"][0]["status"] == "submitted"

        res = client.get("/inbox", headers=_headers())
        assert res.status_code == 200
        inbox = res.json()
        assert inbox["bundle_count"] == 2
        assert inbox["form_count"] == 0
        kinds = {item["kind"] for item in inbox["items"]}
        assert kinds == {"bundle"}
        bundle = next(item for item in inbox["items"] if item["id"] == opened["id"])
        assert bundle["kind"] == "bundle"
        assert any(o["kind"] == "procedure" and o["id"] == proc["id"] for o in inbox["openings"])
        assert all(o["kind"] == "procedure" for o in inbox["openings"])
        assert any(p["id"] == proc["id"] and p["bundle_count"] >= 1 for p in inbox["procedures"])

        res = client.get("/inbox", headers=_headers(), params={"procedure_id": proc["id"]})
        assert res.status_code == 200
        filtered = res.json()
        assert filtered["bundle_count"] == 1
        assert filtered["form_count"] == 0
        assert all(item["kind"] == "bundle" for item in filtered["items"])

        res = client.post(f"/procedures/{proc['id']}/status", headers=_headers(), json={"status": "draft"})
        assert res.status_code == 200
        res = client.get("/inbox", headers=_headers())
        closed = next(p for p in res.json()["procedures"] if p["id"] == proc["id"])
        assert closed["status"] == "draft"
        assert closed["bundle_count"] >= 1
        res = client.delete(f"/procedures/{proc['id']}", headers=_headers())
        assert res.status_code == 400
        assert "申請" in res.json()["error"]

        res = client.delete(f"/forms/{style_a['id']}", headers=_headers())
        assert res.status_code == 400
        assert "様式" in res.json()["error"]
    finally:
        _teardown(path)


def test_publish_requires_guide_published() -> None:
    client, path = _setup()
    try:
        res = client.post(
            "/forms",
            headers=_headers(),
            json={
                "title": "下書き案内",
                "visibility": "internal",
                "definition": _form("下書き案内", ["A"]),
            },
        )
        assert res.status_code == 201
        guide = res.json()
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "未公開案内", "guide_form_id": guide["id"]},
        )
        assert res.status_code == 201
        proc = res.json()
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "published"
        detail = store.get_form(guide["id"], actor_user_id="u1")
        assert detail and detail["locked"] is True
        assert detail["receptions"]
        assert detail["receptions"][0]["status"] == "published"

        empty = client.post(
            "/forms",
            headers=_headers(),
            json={"title": "空案内", "visibility": "internal"},
        )
        assert empty.status_code == 201
        empty_id = empty.json()["id"]
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "空案内の手続き", "guide_form_id": empty_id},
        )
        assert res.status_code == 201
        res = client.post(
            f"/procedures/{res.json()['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 400
        assert "部品" in res.json()["error"]
    finally:
        _teardown(path)


def test_create_procedure_from_draft_stays_unpublished() -> None:
    client, path = _setup()
    try:
        raw = assist.fallback_procedure_draft("転入届の手引き")
        draft, err = assist.normalize_procedure_draft(raw)
        assert err is None and draft
        result, msg = store.create_procedure_from_draft(
            draft,
            creator_user_id="u1",
            creator_name="職員",
            visibility="internal",
        )
        assert msg is None and result
        detail = result["procedure"]
        assert detail and detail["status"] == "draft"
        assert "【確認】" in (detail.get("description") or "")
        created = detail["created_forms"]
        assert {item["role"] for item in created} == {"guide", "form"}
        form_ids = {item["id"] for item in created if item["role"] == "form"}
        mapped = {fid for rule in detail["mapping"]["rules"] for fid in rule["form_ids"]}
        assert form_ids == mapped
        for item in created:
            form = store.get_form(item["id"], actor_user_id="u1")
            assert form and form["status"] == "draft"
            assert form["visibility"] == "internal"
    finally:
        _teardown(path)


def test_assist_procedure_template() -> None:
    from unittest.mock import AsyncMock, patch

    client, path = _setup()
    try:
        with patch("app.assist.llm.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
            res = client.post(
                "/assist/procedure",
                headers=_headers(),
                json={"text": "転入届の手引き。転入と転居。", "visibility": "internal"},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["source"] == "template"
        assert body["preview"]["name"] == "転入・転居の手続き"
        assert body["preview"]["navigation"]["found"] is True
        assert {f["key"] for f in body["preview"]["forms"]} == {"move_in", "attach"}
        listed = client.get("/procedures", headers=_headers())
        assert listed.status_code == 200
        assert listed.json()["procedures"] == []

        applied = client.post(
            "/assist/procedure/apply",
            headers=_headers(),
            json={
                "draft": body["draft"],
                "visibility": "internal",
                "apply": {"forms": True, "navigation": True, "notice": True},
            },
        )
        assert applied.status_code == 201, applied.text
        created = applied.json()
        assert created["procedure"]["status"] == "draft"
        assert created["procedure"]["name"] == "転入・転居の手続き"
        res = client.get(f"/procedures/{created['procedure']['id']}", headers=_headers())
        assert res.status_code == 200
        assert res.json()["status"] == "draft"

        res = client.post("/assist/procedure", headers=_headers(), json={"text": "  "})
        assert res.status_code == 400
    finally:
        _teardown(path)


def test_assist_procedure_apply_selected_parts() -> None:
    from unittest.mock import AsyncMock, patch

    client, path = _setup()
    try:
        with patch("app.assist.llm.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
            preview = client.post(
                "/assist/procedure",
                headers=_headers(),
                json={"text": "転入届の手引き。転入と転居。", "visibility": "internal"},
            )
        draft = preview.json()["draft"]

        forms_only = client.post(
            "/assist/procedure/apply",
            headers=_headers(),
            json={
                "draft": draft,
                "visibility": "internal",
                "apply": {"forms": True, "navigation": False, "notice": False},
                "form_keys": ["move_in"],
            },
        )
        assert forms_only.status_code == 201, forms_only.text
        body = forms_only.json()
        assert body["procedure"] is None
        assert [item["role"] for item in body["created_forms"]] == ["form"]
        assert body["created_forms"][0]["title"] == "転入届"
        listed = client.get("/procedures", headers=_headers())
        assert listed.json()["procedures"] == []

        nav_missing = client.post(
            "/assist/procedure/apply",
            headers=_headers(),
            json={
                "draft": {**draft, "guide": {"metadata": {"title": "案内"}, "components": []}},
                "visibility": "internal",
                "apply": {"forms": False, "navigation": True, "notice": False},
            },
        )
        assert nav_missing.status_code == 400
        assert "選択肢" in nav_missing.json()["error"]

        toc = assist.fallback_procedure_draft("## 指定申請の手引き － 目次 －")
        toc_draft, err = assist.normalize_procedure_draft(toc)
        assert err is None and toc_draft
        empty = client.post(
            "/assist/procedure/apply",
            headers=_headers(),
            json={
                "draft": toc_draft,
                "visibility": "internal",
                "apply": {"forms": True, "navigation": False, "notice": False},
            },
        )
        assert empty.status_code == 400
        assert "様式" in empty.json()["error"]
    finally:
        _teardown(path)


def test_catalog_published_only() -> None:
    client, path = _setup()
    try:
        guide = _create_form(client, "転入案内", ["転入", "転居"])
        style_a = _create_form(client, "転入届")
        attach = _create_form(client, "添付台紙")
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={
                "name": "転入の手続き",
                "guide_form_id": guide["id"],
                "mapping": {
                    "rules": [
                        {
                            "component_id": "event",
                            "option": "転入",
                            "form_ids": [style_a["id"], attach["id"]],
                            "notes": "転入届を出してください",
                            "prepare": ["本人確認書類"],
                        }
                    ]
                },
            },
        )
        assert res.status_code == 201
        proc = res.json()
        draft_guide = _create_form(client, "下書き案内", ["A"])
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "未公開手続き", "guide_form_id": draft_guide["id"]},
        )
        assert res.status_code == 201
        draft_id = res.json()["id"]

        res = client.get("/catalog/procedures")
        assert res.status_code == 401

        key = {"x-api-key": "test-key"}
        res = client.get("/catalog/procedures", headers=key)
        assert res.status_code == 200
        assert res.json()["count"] == 0

        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200

        res = client.get("/catalog/procedures", headers=key)
        ids = {item["id"] for item in res.json()["procedures"]}
        assert proc["id"] in ids
        assert draft_id not in ids
        assert "creator_user_id" not in res.json()["procedures"][0]

        res = client.get("/catalog/procedure", headers=key, params={"ref": "転入の手続き"})
        assert res.status_code == 200
        body = res.json()["procedure"]
        assert body["id"] == proc["id"]
        assert "creator_user_id" not in body
        assert body["guide"]["choice_fields"][0]["options"] == ["転入", "転居"]
        assert {f["title"] for f in body["forms"]} == {"転入届", "添付台紙"}

        res = client.get("/catalog/procedure", headers=key, params={"ref": draft_id})
        assert res.status_code == 404

        res = client.post(
            "/catalog/resolve",
            headers=key,
            json={"procedure": proc["id"], "answers": {"事由": "転入"}},
        )
        assert res.status_code == 200, res.text
        resolved = res.json()
        assert "token" not in resolved
        assert "application" not in resolved
        assert {f["id"] for f in resolved["forms"]} == {style_a["id"], attach["id"]}
        assert "転入届を出してください" in resolved["notes"]
        assert resolved["prepare"] == ["本人確認書類"]
    finally:
        _teardown(path)


def test_procedure_share_links() -> None:
    client, path = _setup()
    try:
        form = _create_form(client, "庁内申請")
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "庁内手続き", "guide_form_id": form["id"]},
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        res = client.get(
            f"/procedures/{proc['id']}/share",
            headers=_headers(),
            params={"origin": "http://office.example"},
        )
        assert res.status_code == 400

        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        published = res.json()
        assert published["guide_reception_id"]
        assert published["guide_visibility"] == "both"

        res = client.get(
            f"/procedures/{proc['id']}/share",
            headers=_headers(),
            params={"origin": "not-a-url"},
        )
        assert res.status_code == 400

        res = client.get(
            f"/procedures/{proc['id']}/share",
            headers=_headers(),
            params={"origin": "http://office.example"},
        )
        assert res.status_code == 200, res.text
        share = res.json()
        assert share["internal_url"] == f"http://office.example/patchform/apply/{proc['id']}"
        assert share["external_url"]
        assert "<svg" in share["internal_qr_svg"].lower()
        assert "<svg" in (share["external_qr_svg"] or "").lower()

        res = client.post(
            "/forms",
            headers=_headers(),
            json={
                "title": "庁内限定",
                "visibility": "internal",
                "definition": _form("庁内限定"),
            },
        )
        assert res.status_code == 201, res.text
        inside = res.json()
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "庁内限定手続き", "guide_form_id": inside["id"]},
        )
        assert res.status_code == 201, res.text
        limited = res.json()
        res = client.post(
            f"/procedures/{limited['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        res = client.get(
            f"/procedures/{limited['id']}/share",
            headers=_headers(),
            params={"origin": "https://lgwan.example"},
        )
        assert res.status_code == 200, res.text
        inner = res.json()
        assert inner["internal_url"] == f"https://lgwan.example/patchform/apply/{limited['id']}"
        assert inner["external_url"] is None
        assert inner["external_qr_svg"] is None
    finally:
        _teardown(path)


def test_application_and_procedure_export() -> None:
    client, path = _setup()
    try:
        guide_def = _create_form(client, "転入案内", ["転入", "転居"])
        style_a_def = _create_form(client, "転入届")
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={
                "name": "転入の手続き",
                "guide_form_id": guide_def["id"],
                "mapping": {
                    "rules": [
                        {
                            "component_id": "event",
                            "option": "転入",
                            "form_ids": [style_a_def["id"]],
                            "notes": [],
                            "prepare": [],
                        }
                    ]
                },
            },
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        guide = _reception_of(client, guide_def["id"])
        style_a = _reception_of(client, style_a_def["id"])

        res = client.post(
            f"/public/api/forms/{guide['guest_token']}/submissions",
            json={"answers": {"name": "山田", "event": "転入"}, "submitter_name": "山田"},
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        res = client.post(
            f"/public/api/forms/{style_a['guest_token']}/submissions",
            json={
                "answers": {"name": "山田"},
                "submitter_name": "山田",
                "application_token": opened["token"],
            },
        )
        assert res.status_code == 201, res.text

        res = client.get(f"/applications/{opened['id']}/export", headers=_headers())
        assert res.status_code == 200, res.text
        text = res.content.decode("utf-8-sig")
        assert "氏名" in text
        assert "山田" in text
        assert "転入" in text

        res = client.get(
            f"/applications/{opened['id']}/export",
            headers=_headers(),
            params={"format": "jsonl"},
        )
        assert res.status_code == 200, res.text
        one = json.loads(res.content.decode("utf-8").strip().split("\n")[0])
        answered = {item["id"]: item for item in one["forms"]}
        assert answered[guide["id"]]["answers"]["name"] == "山田"
        assert answered[style_a["id"]]["answers"]["name"] == "山田"

        res = client.get(f"/procedures/{proc['id']}/export", headers=_headers())
        assert res.status_code == 200, res.text
        csv_text = res.content.decode("utf-8-sig")
        assert opened["token"] in csv_text
        assert "山田" in csv_text
        assert "転入案内/氏名" in csv_text or "氏名" in csv_text

        res = client.get(
            f"/procedures/{proc['id']}/export",
            headers=_headers(),
            params={"format": "jsonl"},
        )
        assert res.status_code == 200, res.text
        line = res.content.decode("utf-8").strip().split("\n")[0]
        payload = json.loads(line)
        assert payload["token"] == opened["token"]
        assert payload["id"] == opened["id"]

        missing = client.get("/procedures/does-not-exist/export", headers=_headers())
        assert missing.status_code == 404
    finally:
        _teardown(path)


def test_service_key_and_since() -> None:
    client, path = _setup()
    previous = os.environ.get("PATCHFORM_SERVICE_KEY")
    os.environ["PATCHFORM_SERVICE_KEY"] = "svc-test"
    try:
        guide_def = _create_form(client, "転入案内", ["転入", "転居"])
        style_a_def = _create_form(client, "転入届")
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={
                "name": "転入の手続き",
                "guide_form_id": guide_def["id"],
                "mapping": {
                    "rules": [
                        {
                            "component_id": "event",
                            "option": "転入",
                            "form_ids": [style_a_def["id"]],
                            "notes": [],
                            "prepare": [],
                        }
                    ]
                },
            },
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        guide = _reception_of(client, guide_def["id"])
        style_a = _reception_of(client, style_a_def["id"])
        res = client.post(
            f"/public/api/forms/{guide['guest_token']}/submissions",
            json={"answers": {"name": "山田", "event": "転入"}, "submitter_name": "山田"},
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]

        service = {"x-api-key": "test-key", "x-service-key": "svc-test"}
        res = client.get("/procedures", headers=service)
        assert res.status_code == 200, res.text
        assert any(item["id"] == proc["id"] for item in res.json()["procedures"])

        res = client.get(f"/procedures/{proc['id']}/applications", headers=service)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["as_of"]
        assert body["applications"][0]["id"] == opened["id"]
        assert body["applications"][0]["updated_at"]

        res = client.get(
            f"/procedures/{proc['id']}/applications",
            headers=service,
            params={"since": "not-a-date"},
        )
        assert res.status_code == 400

        res = client.get(
            f"/procedures/{proc['id']}/applications",
            headers=service,
            params={"since": "2099-01-01T00:00:00+00:00"},
        )
        assert res.status_code == 200
        assert res.json()["applications"] == []

        res = client.get(
            f"/procedures/{proc['id']}/applications",
            headers=service,
            params={"since": opened["created_at"]},
        )
        assert res.status_code == 200
        assert res.json()["applications"][0]["id"] == opened["id"]

        res = client.post(
            "/forms",
            headers=service,
            json={"title": "書けない", "visibility": "both", "definition": _form("書けない")},
        )
        assert res.status_code == 401

        res = client.get("/procedures", headers={"x-api-key": "test-key", "x-service-key": "wrong"})
        assert res.status_code == 401

        res = client.post(
            f"/public/api/forms/{style_a['guest_token']}/submissions",
            json={
                "answers": {"name": "山田"},
                "submitter_name": "山田",
                "application_token": opened["token"],
            },
        )
        assert res.status_code == 201, res.text
        res = client.get(f"/applications/{opened['id']}", headers=service)
        assert res.status_code == 200, res.text
        detail = res.json()
        assert detail["updated_at"] >= detail["created_at"]
        assert any(form.get("submitted_at") for form in detail["forms"] if form["id"] == style_a["id"])

        res = client.get(
            f"/procedures/{proc['id']}/export",
            headers=service,
            params={"format": "jsonl", "since": opened["created_at"]},
        )
        assert res.status_code == 200, res.text
        line = res.content.decode("utf-8").strip().split("\n")[0]
        assert json.loads(line)["id"] == opened["id"]
    finally:
        if previous is None:
            os.environ.pop("PATCHFORM_SERVICE_KEY", None)
        else:
            os.environ["PATCHFORM_SERVICE_KEY"] = previous
        _teardown(path)


if __name__ == "__main__":
    test_procedure_bundle_from_guide()
    test_publish_requires_guide_published()
    test_create_procedure_from_draft_stays_unpublished()
    test_assist_procedure_template()
    test_assist_procedure_apply_selected_parts()
    test_catalog_published_only()
    test_procedure_share_links()
    test_application_and_procedure_export()
    test_service_key_and_since()
    print("ok")
