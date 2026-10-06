from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("TEAMS_DB_PATH", str(tmp_path / "teams-history.db"))
    from app import teams_store as ts

    importlib.reload(ts)
    ts.init_db(seed_exapps=[])
    return ts


def _history(store, *, ex_app_id: str, status: str, outputs: str, created: str) -> None:
    store.create_exapp_history(
        {
            "teamId": store.COMMON_TEAM_ID,
            "exAppId": ex_app_id,
            "userId": "a@example.com",
            "tenantId": store.DEFAULT_TENANT_ID,
            "outputs": outputs,
            "status": status,
            "progress": "処理中",
            "createdDate": created,
        }
    )


def test_update_exapp_history_changes_status_and_outputs(store) -> None:
    _history(
        store,
        ex_app_id="whisper",
        status="IN_PROGRESS",
        outputs="",
        created="1000",
    )
    updated = store.update_exapp_history(
        store.COMMON_TEAM_ID,
        "whisper",
        "1000",
        user_id="a@example.com",
        tenant_id=store.DEFAULT_TENANT_ID,
        outputs="文字起こし結果",
        status="COMPLETED",
        progress="",
    )
    assert updated is not None
    assert updated["status"] == "COMPLETED"
    assert updated["outputs"] == "文字起こし結果"
    assert updated["progress"] == ""


def test_update_exapp_history_does_not_touch_other_user(store) -> None:
    _history(
        store,
        ex_app_id="whisper",
        status="IN_PROGRESS",
        outputs="",
        created="1000",
    )
    missed = store.update_exapp_history(
        store.COMMON_TEAM_ID,
        "whisper",
        "1000",
        user_id="other@example.com",
        tenant_id=store.DEFAULT_TENANT_ID,
        outputs="別ユーザー",
        status="COMPLETED",
        progress="",
    )
    assert missed is None
    kept = store.get_exapp_history(
        store.COMMON_TEAM_ID,
        "whisper",
        "1000",
        "a@example.com",
        store.DEFAULT_TENANT_ID,
    )
    assert kept["status"] == "IN_PROGRESS"
    assert kept["outputs"] == ""


def test_fail_in_progress_only_pending_whisper(store) -> None:
    _history(
        store,
        ex_app_id="whisper",
        status="IN_PROGRESS",
        outputs="",
        created="1000",
    )
    _history(
        store,
        ex_app_id="whisper",
        status="ACCEPTED",
        outputs="",
        created="1001",
    )
    _history(
        store,
        ex_app_id="whisper",
        status="COMPLETED",
        outputs="済",
        created="1002",
    )
    _history(
        store,
        ex_app_id="rag",
        status="IN_PROGRESS",
        outputs="",
        created="1003",
    )

    n = store.fail_in_progress_exapp_histories("whisper", "処理が中断されました。")
    assert n == 2

    rows = {
        h["createdDate"]: h
        for h in store.list_exapp_histories(
            store.COMMON_TEAM_ID, "whisper", "a@example.com", store.DEFAULT_TENANT_ID
        )
    }
    assert rows["1000"]["status"] == "ERROR"
    assert rows["1000"]["outputs"] == "処理が中断されました。"
    assert rows["1001"]["status"] == "ERROR"
    assert rows["1002"]["status"] == "COMPLETED"
    assert rows["1002"]["outputs"] == "済"

    rag = store.list_exapp_histories(
        store.COMMON_TEAM_ID, "rag", "a@example.com", store.DEFAULT_TENANT_ID
    )
    assert rag[0]["status"] == "IN_PROGRESS"
