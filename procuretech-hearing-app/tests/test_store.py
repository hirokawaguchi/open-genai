from app import store


def test_session_item_and_file_roundtrip(tmp_path, monkeypatch):
    db = tmp_path / "hearing.db"
    monkeypatch.setenv("HEARING_DB_PATH", str(db))
    store._db = None
    store.init_db()

    created = store.create_session(user_id="u1", title="案件A")
    sid = created["id"]
    assert created["title"] == "案件A"

    detail = store.add_item(sid, "u1", label="課題は何か")
    assert detail is not None
    item_id = detail["items"][0]["id"]
    detail = store.update_item(sid, "u1", item_id, value="予算不足")
    assert detail["items"][0]["value"] == "予算不足"

    detail = store.add_file(sid, "u1", filename="note.txt", raw=b"hello", error="")
    assert detail["files"][0]["filename"] == "note.txt"
    blobs = store.list_file_blobs(sid, "u1")
    assert blobs and blobs[0][1] == b"hello"

    assert store.get_session(sid, "other") is None
