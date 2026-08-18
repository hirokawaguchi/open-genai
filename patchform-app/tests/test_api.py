"""工程1-2: FastAPI（庁内 HMAC + ゲスト公開面）。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("INTERNAL_SIGNING_SECRET", "")
os.environ.setdefault("RAG_API_KEY", "test-key")

from fastapi.testclient import TestClient

from app import store
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


def _definition() -> dict:
    return {
        "$version": "opengenai-patchform/1",
        "metadata": {"title": "届出", "description": ""},
        "components": [
            {"id": "name", "type": "text", "label": "氏名", "required": True},
            {
                "id": "kind",
                "type": "select",
                "label": "区分",
                "required": True,
                "properties": {"options": ["新規", "変更"]},
            },
        ],
    }


def test_health() -> None:
    client, path = _setup()
    try:
        res = client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "ok"
    finally:
        _teardown(path)


def test_config_requires_auth() -> None:
    client, path = _setup()
    try:
        res = client.get("/config")
        assert res.status_code == 401
        res = client.get("/config", headers=_headers())
        assert res.status_code == 200
        body = res.json()
        assert body["enabled"] is True
        types = {c["type"] for c in body["catalog"]}
        assert "text" in types
        assert "image_recognition" in types
        assert "location" in types
    finally:
        _teardown(path)


def test_crud_publish_submit_export() -> None:
    client, path = _setup()
    try:
        res = client.post(
            "/forms",
            headers=_headers(),
            json={
                "title": "届出",
                "visibility": "both",
                "definition": _definition(),
                "pin": "4321",
            },
        )
        assert res.status_code == 201, res.text
        form = res.json()
        fid = form["id"]
        token = form["guest_token"]

        res = client.get("/forms", headers=_headers())
        assert res.status_code == 200
        assert len(res.json()["forms"]) == 1

        res = client.post(
            f"/forms/{fid}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "published"

        res = client.get(f"/public/api/forms/{token}")
        assert res.status_code == 200
        assert res.json()["requires_pin"] is True

        res = client.post(f"/public/api/forms/{token}", json={"pin": "4321"})
        assert res.status_code == 200
        assert res.json()["requires_pin"] is False

        res = client.post(
            f"/public/api/forms/{token}/submissions",
            json={"answers": {"name": "田中", "kind": "新規"}, "pin": "4321", "submitter_name": "田中"},
        )
        assert res.status_code == 201, res.text
        assert res.json()["receipt_code"]

        res = client.get(f"/forms/{fid}/submissions", headers=_headers())
        assert res.status_code == 200
        assert res.json()["submissions"][0]["answers"]["name"] == "田中"

        res = client.get(f"/forms/{fid}/export", headers=_headers())
        assert res.status_code == 200
        text = res.content.decode("utf-8-sig")
        assert "氏名" in text
        assert "田中" in text

        res = client.get(f"/forms/{fid}/export?format=jsonl", headers=_headers())
        assert res.status_code == 200
        line = res.content.decode("utf-8").strip().split("\n")[0]
        payload = __import__("json").loads(line)
        assert payload["answers"]["name"] == "田中"

        res = client.get(f"/forms/{fid}/carrier", headers=_headers())
        assert res.status_code == 200
        assert "/public/f/" in res.json()["public_url"]
    finally:
        _teardown(path)


def test_extract_document_text() -> None:
    client, path = _setup()
    try:
        import base64

        payload = base64.b64encode("内容テキスト".encode("utf-8")).decode("ascii")
        res = client.post(
            "/extract",
            headers=_headers(),
            json={
                "kind": "document",
                "filename": "a.txt",
                "data": f"data:text/plain;base64,{payload}",
            },
        )
        assert res.status_code == 200, res.text
        assert res.json()["extracted"] == "内容テキスト"
        res = client.post(
            "/public/api/extract",
            json={
                "kind": "document",
                "filename": "a.txt",
                "data": f"data:text/plain;base64,{payload}",
            },
        )
        assert res.status_code == 200
        assert res.json()["source"] == "text"
    finally:
        _teardown(path)


def test_assist_generate_template() -> None:
    client, path = _setup()
    try:
        from unittest.mock import AsyncMock, patch

        with patch("app.assist.llm.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
            res = client.post(
                "/assist/generate",
                headers=_headers(),
                json={"text": "子ども医療費の申請", "visibility": "internal"},
            )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["source"] == "template"
        assert body["definition"]["components"]
    finally:
        _teardown(path)


def test_other_user_cannot_edit() -> None:
    client, path = _setup()
    try:
        res = client.post("/forms", headers=_headers("u1"), json={"title": "秘密"})
        fid = res.json()["id"]
        res = client.get(f"/forms/{fid}", headers=_headers("u2"))
        assert res.status_code == 403
        res = client.delete(f"/forms/{fid}", headers=_headers("u2"))
        assert res.status_code == 403
    finally:
        _teardown(path)


if __name__ == "__main__":
    test_health()
    test_config_requires_auth()
    test_crud_publish_submit_export()
    test_extract_document_text()
    test_assist_generate_template()
    test_other_user_cannot_edit()
    print("ok")
