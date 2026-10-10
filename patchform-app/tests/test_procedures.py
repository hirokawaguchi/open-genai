"""手続きマスタと申請束。"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("INTERNAL_SIGNING_SECRET", "")
os.environ.setdefault("RAG_API_KEY", "test-key")
os.environ["PATCHFORM_SEED"] = ""

from fastapi.testclient import TestClient

from app import assist, ledger, review_engine, spec, store
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
    ledger_fd, ledger_path = tempfile.mkstemp(suffix="-ledger.db")
    os.close(ledger_fd)
    os.environ["PATCHFORM_LEDGER_DB_PATH"] = ledger_path
    os.environ["PATCHFORM_LEDGER_FILES_DIR"] = tempfile.mkdtemp(prefix="pf-ledger-")
    ledger.reset_connection()
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
    ledger.reset_connection()
    ledger_path = os.environ.pop("PATCHFORM_LEDGER_DB_PATH", "")
    if ledger_path:
        try:
            os.remove(ledger_path)
        except OSError:
            pass
    ledger_files = os.environ.pop("PATCHFORM_LEDGER_FILES_DIR", "")
    if ledger_files:
        shutil.rmtree(ledger_files, ignore_errors=True)


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


def test_application_workbench_items() -> None:
    import base64

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
                            "notes": "転入届を出してください",
                            "prepare": ["住民票の写し"],
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
        items = opened["items"]
        kinds = [it["kind"] for it in items]
        assert kinds[0] == "data"
        assert "yoshiki" in kinds
        assert "attach" in kinds
        data_item = items[0]
        assert data_item["status"] == "submitted"
        yoshiki = next(it for it in items if it["kind"] == "yoshiki")
        attach = next(it for it in items if it["kind"] == "attach")
        assert yoshiki["form_id"] == style_a["id"]
        assert yoshiki["status"] == "none"
        assert attach["title"] == "住民票の写し"

        # 添付枠を、記入済みファイルで満たす
        blob = base64.b64encode(b"hello").decode()
        res = client.post(
            f"/public/api/applications/{opened['token']}/items/{attach['id']}/file",
            json={"filename": "juminhyo.pdf", "data": blob},
        )
        assert res.status_code == 200, res.text
        after = res.json()
        attach_after = next(it for it in after["items"] if it["id"] == attach["id"])
        assert attach_after["fulfillment"] == "file"
        assert attach_after["status"] == "submitted"
        assert attach_after["file_name"] == "juminhyo.pdf"

        # 同じ様式をもう1件（複製）
        res = client.post(
            f"/public/api/applications/{opened['token']}/items",
            json={"duplicate_of": yoshiki["id"]},
        )
        assert res.status_code == 201, res.text
        dup = res.json()
        copies = [it for it in dup["items"] if it.get("form_id") == style_a["id"]]
        assert len(copies) == 2

        # カタログから見えるか
        res = client.get(f"/public/api/applications/{opened['token']}/catalog")
        assert res.status_code == 200, res.text
        catalog = res.json()
        assert any(s["form_id"] == style_a["id"] for s in catalog["slots"])

        # 1件目の様式をオンライン記入で満たす（アイテム指定）
        res = client.post(
            f"/public/api/forms/{style_a['guest_token']}/submissions",
            json={
                "answers": {"name": "山田"},
                "submitter_name": "山田",
                "application_token": opened["token"],
                "application_item_id": yoshiki["id"],
            },
        )
        assert res.status_code == 201, res.text
        res = client.get(f"/public/api/applications/{opened['token']}")
        final = res.json()
        first_copy = next(it for it in final["items"] if it["id"] == yoshiki["id"])
        assert first_copy["status"] == "submitted"
    finally:
        _teardown(path)


def test_procedure_export_aligned() -> None:
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
                            "prepare": ["住民票の写し"],
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
        yoshiki = next(it for it in opened["items"] if it["kind"] == "yoshiki")
        res = client.post(
            f"/public/api/forms/{style_a['guest_token']}/submissions",
            json={
                "answers": {"name": "花子"},
                "submitter_name": "花子",
                "application_token": opened["token"],
                "application_item_id": yoshiki["id"],
            },
        )
        assert res.status_code == 201, res.text

        res = client.get(
            f"/procedures/{proc['id']}/export",
            headers=_headers(),
            params={"format": "aligned"},
        )
        assert res.status_code == 200, res.text
        text = res.content.decode("utf-8-sig")
        # 記入必須（案内）の氏名は揃える対象。様式ファイルの欄は混ざらない
        assert "転入案内::氏名" in text
        assert "山田" in text
        assert "転入届::氏名" not in text
        assert "花子" not in text
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


def test_form_tags_endpoint_ignores_locked() -> None:
    client, path = _setup()
    try:
        form = _create_form(client, "タグ対象")
        # 作成完了(ロック)にしてもタグは変更できる
        res = client.post(
            f"/forms/{form['id']}/status",
            headers=_headers(),
            json={"status": "draft", "locked": True},
        )
        assert res.status_code == 200, res.text
        res = client.post(
            f"/forms/{form['id']}/tags",
            headers=_headers(),
            json={"tags": ["転入", "急ぎ"]},
        )
        assert res.status_code == 200, res.text
        assert set(res.json().get("tags") or []) == {"転入", "急ぎ"}
        # タグを外す
        res = client.post(
            f"/forms/{form['id']}/tags",
            headers=_headers(),
            json={"tags": ["転入"]},
        )
        assert res.status_code == 200, res.text
        assert res.json().get("tags") == ["転入"]
    finally:
        _teardown(path)


def test_form_archive_and_restore() -> None:
    client, path = _setup()
    try:
        form = _create_form(client, "退避対象")
        res = client.post(
            f"/forms/{form['id']}/status",
            headers=_headers(),
            json={"status": "archived"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "archived"
        # 一覧に残る（庁内は状態で振り分ける）
        res = client.get("/forms", headers=_headers())
        assert res.status_code == 200, res.text
        found = next(f for f in res.json()["forms"] if f["id"] == form["id"])
        assert found["status"] == "archived"
        # 復元すると作成中に戻る
        res = client.post(
            f"/forms/{form['id']}/status",
            headers=_headers(),
            json={"status": "draft"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "draft"
    finally:
        _teardown(path)


def test_procedure_archive_and_restore() -> None:
    client, path = _setup()
    try:
        guide_def = _create_form(client, "案内フォーム", ["A", "B"])
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "退避手続き", "guide_form_id": guide_def["id"]},
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        # 下書きはゴミ箱へ移せる
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "archived"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "archived"
        res = client.get("/procedures", headers=_headers())
        found = next(p for p in res.json()["procedures"] if p["id"] == proc["id"])
        assert found["status"] == "archived"
        # 復元
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "draft"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "draft"
        # 公開中はゴミ箱へ移せない
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "archived"},
        )
        assert res.status_code == 400, res.text
    finally:
        _teardown(path)


def test_procedure_review_roundtrip_and_freeze(monkeypatch) -> None:
    client, path = _setup()
    try:
        guide = _create_form(client, "一時預かり案内", ["子ども", "保護者の病気"])
        form = _create_form(client, "利用申込書")
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={
                "name": "一時預かり",
                "guide_form_id": guide["id"],
                "mapping": {
                    "rules": [
                        {
                            "component_id": "event",
                            "option": "子ども",
                            "form_ids": [form["id"]],
                            "prepare": ["勤務証明書"],
                            "reviews": [
                                {
                                    "slot_id": "attach:勤務証明書",
                                    "formal": ["file_present"],
                                    "content": [{"id": "work", "text": "勤務先名が読める"}],
                                }
                            ],
                            "cross": [{"id": "same", "text": "氏名が一致する"}],
                        }
                    ]
                },
            },
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        rule = proc["mapping"]["rules"][0]
        assert rule["reviews"][0]["content"][0]["text"] == "勤務先名が読める"
        assert proc["formal_checks"][0]["id"] == "file_present"

        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        reception = _reception_of(client, guide["id"])
        res = client.post(
            f"/forms/{reception['id']}/submissions",
            headers=_headers(),
            json={"answers": {"name": "山田", "event": "子ども"}, "submitter_name": "山田"},
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        res = client.post(
            f"/applications/{opened['id']}/status",
            headers=_headers(),
            json={"status": "提出済"},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["reception_status"] == "確認中"
        assert body["reception_stage"] == "desk"
        frozen = body["review"]
        assert frozen["cross"][0]["text"] == "氏名が一致する"
        assert frozen["cross"][0]["finding"]["result"] == "unknown"
        cert = next(s for s in frozen["slots"] if s["slot_id"] == "attach:勤務証明書")
        assert cert["formal"][0]["result"] == "fail"
        assert cert["content"][0]["text"] == "勤務先名が読める"

        res = client.put(
            f"/procedures/{proc['id']}",
            headers=_headers(),
            json={
                "mapping": {
                    "rules": [
                        {
                            "component_id": "event",
                            "option": "子ども",
                            "form_ids": [form["id"]],
                            "prepare": ["勤務証明書"],
                            "reviews": [
                                {
                                    "slot_id": "attach:勤務証明書",
                                    "formal": ["file_present"],
                                    "content": [{"id": "hat", "text": "帽子がない"}],
                                }
                            ],
                            "cross": [],
                        }
                    ]
                }
            },
        )
        assert res.status_code == 200, res.text
        res = client.get(f"/applications/{opened['id']}", headers=_headers())
        assert res.status_code == 200, res.text
        again = res.json()["review"]
        kept = next(s for s in again["slots"] if s["slot_id"] == "attach:勤務証明書")
        assert kept["content"][0]["text"] == "勤務先名が読める"
        assert again["cross"][0]["text"] == "氏名が一致する"

        res = client.post(
            f"/applications/{opened['id']}/review-finding",
            headers=_headers(),
            json={"id": "work", "result": "pass"},
        )
        assert res.status_code == 200, res.text
        marked = next(
            s for s in res.json()["review"]["slots"] if s["slot_id"] == "attach:勤務証明書"
        )
        assert marked["content"][0]["text"] == "勤務先名が読める"
        assert marked["content"][0]["finding"]["source"] == "staff"
        assert marked["content"][0]["finding"]["result"] == "pass"

        async def _fake_chat(messages, **kwargs):
            return (
                '{"findings":['
                '{"id":"work","result":"fail","detail":"上書きしない"},'
                '{"id":"same","result":"unknown","detail":"氏名の欄がありません"}'
                "]}"
            )

        monkeypatch.setattr("app.llm.chat", _fake_chat)
        res = client.post(
            f"/applications/{opened['id']}/review-findings",
            headers=_headers(),
        )
        assert res.status_code == 200, res.text
        reviewed = res.json()["review"]
        kept = next(s for s in reviewed["slots"] if s["slot_id"] == "attach:勤務証明書")
        assert kept["content"][0]["finding"]["source"] == "staff"
        assert kept["content"][0]["finding"]["result"] == "pass"
        assert reviewed["cross"][0]["finding"]["source"] == "model"
        assert reviewed["cross"][0]["finding"]["detail"] == "氏名の欄がありません"
        assert reviewed["cross"][0]["text"] == "氏名が一致する"

        monkeypatch.setenv("PATCHFORM_REVIEW_ENGINE", "dify")
        res = client.post(
            f"/applications/{opened['id']}/review-findings",
            headers=_headers(),
        )
        assert res.status_code == 200, res.text
        still = res.json()["review"]
        assert still["cross"][0]["finding"]["source"] == "model"
        assert still["cross"][0]["finding"]["detail"] == "氏名の欄がありません"

        secret = "dify-procedure-key"
        res = client.put(
            f"/procedures/{proc['id']}",
            headers=_headers(),
            json={
                "review_call": {
                    "engine": "dify",
                    "base_url": "https://dify.example.lg.jp/v1",
                    "api_key": secret,
                    "stub": True,
                }
            },
        )
        assert res.status_code == 200, res.text
        assert secret not in res.text
        assert res.json()["review_call"]["engine"] == "dify"
        assert res.json()["review_call"]["stub"] is True
        assert res.json()["review_call"]["key_set"] is True
        res = client.post(
            f"/applications/{opened['id']}/review-findings",
            headers=_headers(),
        )
        assert res.status_code == 200, res.text
        stubbed = res.json()["review"]
        kept = next(s for s in stubbed["slots"] if s["slot_id"] == "attach:勤務証明書")
        assert kept["content"][0]["finding"]["source"] == "staff"
        assert kept["content"][0]["finding"]["result"] == "pass"
        assert stubbed["cross"][0]["finding"]["source"] == "dify"
        assert stubbed["cross"][0]["finding"]["detail"] == "Dify のスタブです。人が確認します。"
    finally:
        _teardown(path)


def test_yoshiki_submit_stays_on_its_application() -> None:
    """様式が別手続きの案内でも、記入先の申請から画面が移らない。"""
    client, path = _setup()
    try:
        guide = _create_form(client, "確認用の案内", ["子ども", "保護者の病気"])
        survey = _create_form(client, "研修受講後アンケート")
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "アンケート単独", "guide_form_id": survey["id"]},
        )
        assert res.status_code == 201, res.text
        alone = res.json()
        res = client.post(
            f"/procedures/{alone['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text

        res = client.post(
            "/procedures",
            headers=_headers(),
            json={
                "name": "ウィザード確認",
                "guide_form_id": guide["id"],
                "mapping": {
                    "rules": [
                        {
                            "component_id": "event",
                            "option": "子ども",
                            "form_ids": [survey["id"]],
                        }
                    ]
                },
            },
        )
        assert res.status_code == 201, res.text
        bundle = res.json()
        res = client.post(
            f"/procedures/{bundle['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        guide_rec = _reception_of(client, guide["id"])
        survey_rec = _reception_of(client, survey["id"])

        res = client.post(
            "/applications",
            headers=_headers(),
            json={"procedure_id": bundle["id"]},
        )
        assert res.status_code == 201, res.text
        proj = res.json()
        nav_id = proj["items"][0]["id"]
        res = client.post(
            f"/forms/{guide_rec['id']}/submissions",
            headers=_headers(),
            json={
                "answers": {"name": "山田", "event": "子ども"},
                "application_token": proj["token"],
                "application_item_id": nav_id,
            },
        )
        assert res.status_code == 201, res.text
        after_guide = res.json()["application"]
        assert after_guide["id"] == proj["id"]
        yitem = next(i for i in after_guide["items"] if i.get("form_id") == survey_rec["id"])

        res = client.post(
            f"/forms/{survey_rec['id']}/submissions",
            headers=_headers(),
            json={
                "answers": {"name": "山田"},
                "application_token": proj["token"],
                "application_item_id": yitem["id"],
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["application"]["id"] == proj["id"]
        filled = next(
            i for i in body["application"]["items"] if i["id"] == yitem["id"]
        )
        assert filled["status"] == "submitted"

        res = client.get(f"/procedures/{alone['id']}/applications", headers=_headers())
        assert res.status_code == 200, res.text
        assert res.json()["applications"] == []
    finally:
        _teardown(path)


def test_ledger_answer_blocks_use_field_labels() -> None:
    blocks = store._ledger_answer_blocks(
        [
            {
                "title": "アンケート",
                "definition": {
                    "components": [
                        {"id": "name", "type": "user_info_composite", "label": "氏名"},
                        {"id": "satisfaction", "type": "rating", "label": "満足度"},
                        {
                            "id": "event",
                            "type": "select",
                            "label": "区分",
                            "properties": {"options": ["子ども"]},
                        },
                        {"id": "note", "type": "textarea", "label": "ご意見"},
                    ]
                },
                "answers": {
                    "name": {"last_name": "山田", "first_name": "花子"},
                    "satisfaction": 1.0,
                    "event": "子ども",
                    "note": "",
                },
            }
        ]
    )
    lines = {line["label"]: line["value"] for line in blocks[0]["lines"]}
    assert lines == {"氏名": "山田 花子", "満足度": "1 / 5", "区分": "子ども"}


def test_route_confirm_opens_one_ledger_row() -> None:
    client, path = _setup()
    try:
        guide = _create_form(client, "経路案内", ["子ども"])
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "経路手続き", "guide_form_id": guide["id"]},
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        reception = _reception_of(client, guide["id"])
        res = client.post(
            f"/forms/{reception['id']}/submissions",
            headers=_headers(),
            json={"answers": {"name": "山田", "event": "子ども"}, "submitter_name": "山田"},
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        res = client.post(
            f"/applications/{opened['id']}/status",
            headers=_headers(),
            json={"status": "提出済"},
        )
        assert res.status_code == 200, res.text
        app_id = opened["id"]
        res = client.post(
            f"/applications/{app_id}/reception",
            headers=_headers(),
            json={"reception_status": "受理"},
        )
        assert res.status_code == 400, res.text

        seen: list[tuple[str, str]] = []
        for _ in range(4):
            res = client.post(
                f"/applications/{app_id}/route",
                headers=_headers(),
                json={"action": "advance"},
            )
            assert res.status_code == 200, res.text
            seen.append((res.json()["reception_status"], res.json()["reception_stage"]))
        assert seen == [
            ("確認中", "desk"),
            ("確認中", "section"),
            ("確認中", "confirm"),
            ("受理", "confirm"),
        ]
        ledger_id = res.json()["ledger_id"]
        assert ledger_id
        res = client.get(f"/ledger/{ledger_id}", headers=_headers())
        assert res.status_code == 200, res.text
        labeled = [
            f"{line['label']}={line['value']}"
            for block in res.json()["snapshot"]["answers"]
            for line in block["lines"]
        ]
        assert "氏名=山田" in labeled
        assert "事由=子ども" in labeled

        ldb = sqlite3.connect(os.environ["PATCHFORM_LEDGER_DB_PATH"])
        ldb.execute(
            "UPDATE ledger_rows SET snapshot_json = ? WHERE id = ?",
            (
                json.dumps(
                    {
                        "answers": [
                            {"title": "案内", "lines": ["name.last_name: 山田", "event: 子ども"]}
                        ]
                    },
                    ensure_ascii=False,
                ),
                ledger_id,
            ),
        )
        ldb.commit()
        ldb.close()
        res = client.get(f"/ledger/{ledger_id}", headers=_headers())
        assert res.status_code == 200, res.text
        shown = json.dumps(res.json()["snapshot"]["answers"], ensure_ascii=False)
        assert "last_name" not in shown
        assert "氏名" in shown

        res = client.post(
            f"/applications/{app_id}/route",
            headers=_headers(),
            json={"action": "advance"},
        )
        assert res.status_code == 400, res.text

        res = client.get("/ledger", headers=_headers())
        assert res.status_code == 200, res.text
        assert len(res.json()["rows"]) == 1
        assert res.json()["rows"][0]["status"] == "受理"
        assert res.json()["rows"][0]["assignee"] == "担当課"

        res = client.post(
            f"/ledger/{ledger_id}",
            headers=_headers(),
            json={"assignee": "山田", "status": "処理中", "comment": "確認した"},
        )
        assert res.status_code == 200, res.text
        assert res.json()["status"] == "処理中"
        assert res.json()["assignee"] == "山田"
        assert any(ev["action"] == "状態を変えた" for ev in res.json()["events"])

        res = client.put(
            f"/procedures/{proc['id']}",
            headers=_headers(),
            json={"handling": {"exit": "external", "statuses": ["受理"]}},
        )
        assert res.status_code == 200, res.text
        assert res.json()["handling"]["exit"] == "external"
    finally:
        _teardown(path)


def _valid_mynumber() -> str:
    first11 = "12345678901"
    total = 0
    for i in range(1, 12):
        digit = int(first11[11 - i])
        weight = i + 1 if i <= 6 else i - 5
        total += digit * weight
    check = total % 11
    return first11 + str(0 if check <= 1 else 11 - check)


class _DeliveryCapture:
    def __init__(self) -> None:
        self.hits: list[dict] = []
        self.status = 500


class _DeliveryHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        capture: _DeliveryCapture = self.server.capture  # type: ignore[attr-defined]
        capture.hits.append(
            {
                "idem": self.headers.get("Idempotency-Key"),
                "auth": self.headers.get("Authorization"),
                "body": json.loads(raw.decode("utf-8")),
            }
        )
        code = capture.status
        payload = (
            b'{"receipt_no":"R-9"}' if code < 300 else b'{"error":"no"}'
        )
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:
        return


def test_dify_outputs_parse_as_findings() -> None:
    rows = review_engine.rows_from_dify(
        {"outputs": '{"findings":[{"id":"a","result":"pass","detail":"読める"}]}'}
    )
    assert rows == [{"id": "a", "result": "pass", "detail": "読める"}]
    rows = review_engine.rows_from_dify(
        {"outputs": {"findings": [{"id": "b", "result": "unknown", "detail": ""}]}}
    )
    assert rows[0]["id"] == "b"


def test_external_delivery_retries_same_revision() -> None:
    capture = _DeliveryCapture()
    httpd = HTTPServer(("127.0.0.1", 0), _DeliveryHandler)
    httpd.capture = capture  # type: ignore[attr-defined]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    secret = "delivery-secret-value"
    client, path = _setup()
    try:
        mn = _valid_mynumber()
        assert spec.mynumber_check_digit_ok(mn)
        definition = _form("投入案内", ["子ども"])
        definition["components"].append(
            {"id": "mn", "type": "mynumber", "label": "個人番号", "required": True}
        )
        res = client.post(
            "/forms",
            headers=_headers(),
            json={"title": "投入案内", "visibility": "internal", "definition": definition},
        )
        assert res.status_code == 201, res.text
        guide = res.json()
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={"name": "投入手続き", "guide_form_id": guide["id"]},
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        res = client.put(
            f"/procedures/{proc['id']}",
            headers=_headers(),
            json={
                "handling": {"exit": "external"},
                "delivery": {
                    "url": f"http://127.0.0.1:{port}/intake",
                    "key": secret,
                    "send_mynumber": False,
                },
            },
        )
        assert res.status_code == 200, res.text
        assert secret not in res.text
        assert res.json()["delivery"]["key_set"] is True
        assert res.json()["delivery"]["send_mynumber"] is False
        res = client.put(
            f"/procedures/{proc['id']}",
            headers=_headers(),
            json={"delivery": {"url": "javascript:alert(1)"}},
        )
        assert res.status_code == 400, res.text
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        reception = _reception_of(client, guide["id"])
        res = client.post(
            f"/forms/{reception['id']}/submissions",
            headers=_headers(),
            json={
                "answers": {"name": "山田", "event": "子ども", "mn": mn},
                "submitter_name": "山田",
            },
        )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        res = client.post(
            f"/applications/{opened['id']}/status",
            headers=_headers(),
            json={"status": "提出済"},
        )
        assert res.status_code == 200, res.text
        app_id = opened["id"]
        for _ in range(4):
            res = client.post(
                f"/applications/{app_id}/route",
                headers=_headers(),
                json={"action": "advance"},
            )
            assert res.status_code == 200, res.text
        body = res.json()
        assert body["reception_status"] == "受理"
        assert body["ledger_id"] in (None, "")
        assert body["delivery"]["state"] == "failed"
        assert body["delivery"]["attempts"] == 1
        assert mn not in res.text
        assert len(capture.hits) == 1
        assert "山田" in json.dumps(capture.hits[0]["body"], ensure_ascii=False)
        assert mn not in json.dumps(capture.hits[0]["body"], ensure_ascii=False)
        assert capture.hits[0]["auth"] == f"Bearer {secret}"
        assert capture.hits[0]["idem"] == f"{app_id}:1"
        res = client.get("/ledger", headers=_headers())
        assert res.json()["rows"] == []

        capture.status = 200
        res = client.put(
            f"/procedures/{proc['id']}",
            headers=_headers(),
            json={"delivery": {"send_mynumber": True}},
        )
        assert res.status_code == 200, res.text
        assert secret not in res.text
        assert res.json()["delivery"]["key_set"] is True
        assert res.json()["delivery"]["url"] == f"http://127.0.0.1:{port}/intake"
        res = client.post(f"/applications/{app_id}/delivery", headers=_headers())
        assert res.status_code == 200, res.text
        sent = res.json()
        assert sent["delivery"]["state"] == "sent"
        assert sent["delivery"]["receipt_no"] == "R-9"
        assert sent["delivery"]["attempts"] == 2
        assert sent["delivery"]["revision"] == 1
        assert mn not in res.text
        assert len(capture.hits) == 2
        assert capture.hits[1]["idem"] == f"{app_id}:1"
        assert capture.hits[1]["auth"] == f"Bearer {secret}"
        assert mn in json.dumps(capture.hits[1]["body"], ensure_ascii=False)
        actions = [ev["action"] for ev in sent["events"]]
        assert "既存システムへ送れなかった" in actions
        assert "既存システムへ送った" in actions
    finally:
        httpd.shutdown()
        _teardown(path)


if __name__ == "__main__":
    test_form_tags_endpoint_ignores_locked()
    test_form_archive_and_restore()
    test_procedure_archive_and_restore()
    test_procedure_bundle_from_guide()
    test_publish_requires_guide_published()
    test_create_procedure_from_draft_stays_unpublished()
    test_assist_procedure_template()
    test_assist_procedure_apply_selected_parts()
    test_application_workbench_items()
    test_procedure_export_aligned()
    test_catalog_published_only()
    test_procedure_share_links()
    test_application_and_procedure_export()
    test_service_key_and_since()
    test_procedure_review_roundtrip_and_freeze()
    print("ok")
