from __future__ import annotations

from app import notices


def test_notice_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(notices, "DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setattr(notices, "_ready", False)
    notices.set_extra_items(lambda user_id: [])
    created = notices.create_notice(
        scope="all", body="全体です", author_id="admin@example.jp", tenant_id=""
    )
    tenant = notices.create_notice(
        scope="tenant",
        body="棟です",
        author_id="admin@example.jp",
        tenant_id="tenant-1",
    )
    visible = notices.list_visible("tenant-1", "user@example.jp")
    ids = {item["noticeId"] for item in visible}
    assert created["noticeId"] in ids
    assert tenant["noticeId"] in ids
    other = notices.list_visible("tenant-2", "user@example.jp")
    other_ids = {item["noticeId"] for item in other}
    assert created["noticeId"] in other_ids
    assert tenant["noticeId"] not in other_ids
    assert notices.delete_notice(created["noticeId"])
    assert notices.get_notice(created["noticeId"]) is None


def test_extra_items_come_first(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(notices, "DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setattr(notices, "_ready", False)
    notices.set_extra_items(
        lambda user_id: [
            {
                "noticeId": "billing-lock",
                "scope": "billing",
                "body": user_id,
                "readOnly": True,
            }
        ]
    )
    notices.create_notice(scope="all", body="管理者", author_id="a", tenant_id="")
    items = notices.list_visible("", "locked@example.jp")
    assert items[0]["noticeId"] == "billing-lock"
    assert items[0]["body"] == "locked@example.jp"
    notices.set_extra_items(lambda user_id: [])
