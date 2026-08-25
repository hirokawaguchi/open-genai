"""職員通知メール。回答本文は載せない。"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("INTERNAL_SIGNING_SECRET", "")
os.environ.setdefault("RAG_API_KEY", "test-key")
os.environ["PATCHFORM_SEED"] = ""

from fastapi.testclient import TestClient

from app import notify, store
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


def test_parse_notify_emails() -> None:
    emails, err = notify.parse_notify_emails("a@example.lg.jp、b@example.lg.jp\nc@example.lg.jp")
    assert err is None
    assert emails == ["a@example.lg.jp", "b@example.lg.jp", "c@example.lg.jp"]
    emails, err = notify.parse_notify_emails("not-an-email")
    assert emails is None
    assert err and "形式" in err


def test_staff_message_has_no_answers() -> None:
    os.environ["PATCHFORM_SMTP_FROM"] = "noreply@example.lg.jp"
    os.environ["PATCHFORM_STAFF_BASE_URL"] = "https://genai.example.lg.jp"
    msg = notify.build_staff_message(
        procedure_name="転入の手続き",
        token="abc-token",
        application_id="app-1",
        recipients=["staff@example.lg.jp"],
    )
    body = msg.get_content()
    assert "転入の手続き" in body
    assert "abc-token" in body
    assert "https://genai.example.lg.jp/patchform/applications/app-1" in body
    assert "山田" not in body
    assert "answers" not in body
    assert "マイナンバー" not in body


def test_notify_skips_without_smtp() -> None:
    os.environ.pop("PATCHFORM_SMTP_HOST", None)
    os.environ.pop("PATCHFORM_SMTP_FROM", None)
    result = notify.notify_new_application(
        {"id": "a1", "token": "t1", "procedure_name": "x"},
        recipients=["staff@example.lg.jp"],
    )
    assert result["sent"] is False
    assert result["reason"] == "smtp_unconfigured"


def test_notify_on_new_application() -> None:
    client, path = _setup()
    os.environ["PATCHFORM_SMTP_HOST"] = "smtp.test.local"
    os.environ["PATCHFORM_SMTP_FROM"] = "noreply@example.lg.jp"
    os.environ["PATCHFORM_STAFF_BASE_URL"] = "http://localhost"
    sent: list[object] = []
    try:
        res = client.post(
            "/forms",
            headers=_headers(),
            json={
                "title": "転入案内",
                "visibility": "both",
                "definition": {
                    "$version": "opengenai-patchform/1",
                    "metadata": {"title": "転入案内", "description": ""},
                    "components": [
                        {"id": "name", "type": "text", "label": "氏名", "required": True},
                    ],
                },
            },
        )
        assert res.status_code == 201, res.text
        form_id = res.json()["id"]
        res = client.post(
            "/procedures",
            headers=_headers(),
            json={
                "name": "転入の手続き",
                "guide_form_id": form_id,
                "notify_emails": ["staff@example.lg.jp"],
            },
        )
        assert res.status_code == 201, res.text
        proc = res.json()
        assert proc["notify_emails"] == ["staff@example.lg.jp"]
        res = client.post(
            f"/procedures/{proc['id']}/status",
            headers=_headers(),
            json={"status": "published"},
        )
        assert res.status_code == 200, res.text
        recs = [
            r
            for r in client.get(f"/forms/{form_id}", headers=_headers()).json().get("receptions") or []
            if r.get("status") == "published"
        ]
        rec = client.get(f"/forms/{recs[0]['id']}", headers=_headers()).json()

        with patch("app.notify.send_email", side_effect=lambda msg: sent.append(msg)):
            res = client.post(
                f"/public/api/forms/{rec['guest_token']}/submissions",
                json={"answers": {"name": "山田太郎"}, "submitter_name": "山田太郎"},
            )
        assert res.status_code == 201, res.text
        opened = res.json()["application"]
        assert len(sent) == 1
        body = sent[0].get_content()
        assert opened["token"] in body
        assert "山田太郎" not in body
        assert "/patchform/applications/" in body
        assert opened["id"] in body
    finally:
        os.environ.pop("PATCHFORM_SMTP_HOST", None)
        os.environ.pop("PATCHFORM_SMTP_FROM", None)
        os.environ.pop("PATCHFORM_STAFF_BASE_URL", None)
        _teardown(path)


if __name__ == "__main__":
    test_parse_notify_emails()
    test_staff_message_has_no_answers()
    test_notify_skips_without_smtp()
    test_notify_on_new_application()
    print("ok")
