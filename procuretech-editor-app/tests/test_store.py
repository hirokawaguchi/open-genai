"""store（projects/files）の CRUD・ユーザー分離・リネーム衝突のテスト。"""

import pytest

from app import objstore, store


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db", None)
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "pte.db"))
    store.init_db()
    yield
    monkeypatch.setattr(store, "_db", None)


def test_create_and_list_project():
    p = store.create_project("user-a", "案件1")
    assert p["file_count"] == 0
    listed = store.list_projects("user-a")
    assert [x["id"] for x in listed] == [p["id"]]
    # 別ユーザーからは見えない
    assert store.list_projects("user-b") == []


def test_get_project_scoped_by_user():
    p = store.create_project("user-a", "案件1")
    assert store.get_project(p["id"], "user-a") is not None
    assert store.get_project(p["id"], "user-b") is None


def test_upsert_and_list_files_and_count():
    p = store.create_project("user-a", "案件1")
    f = store.upsert_file(p["id"], "user-a", "01.md", kind="markdown", size=10)
    assert f["rel_path"] == "01.md"
    # file_count が増える
    assert store.get_project(p["id"], "user-a")["file_count"] == 1
    # 同じ rel_path の upsert は s3_key を維持しサイズ更新
    f2 = store.upsert_file(p["id"], "user-a", "01.md", kind="markdown", size=20)
    assert f2["s3_key"] == f["s3_key"]
    assert f2["size"] == 20
    assert len(store.list_files(p["id"], "user-a")) == 1


def test_rename_file_keeps_key_and_detects_collision():
    p = store.create_project("user-a", "案件1")
    a = store.upsert_file(p["id"], "user-a", "a.md", kind="markdown", size=1)
    store.upsert_file(p["id"], "user-a", "b.md", kind="markdown", size=1)
    # 衝突（b.md へリネーム不可）
    assert store.rename_file(p["id"], "user-a", "a.md", "b.md") is None
    # 正常リネームは s3_key を維持
    renamed = store.rename_file(p["id"], "user-a", "a.md", "c.md")
    assert renamed is not None
    assert renamed["s3_key"] == a["s3_key"]
    assert store.get_file(p["id"], "user-a", "a.md") is None
    assert store.get_file(p["id"], "user-a", "c.md") is not None


def test_delete_file_returns_key():
    p = store.create_project("user-a", "案件1")
    f = store.upsert_file(p["id"], "user-a", "a.md", kind="markdown", size=1)
    assert store.delete_file(p["id"], "user-a", "a.md") == f["s3_key"]
    assert store.delete_file(p["id"], "user-a", "a.md") is None


def test_delete_project_returns_all_keys():
    p = store.create_project("user-a", "案件1")
    k1 = store.upsert_file(p["id"], "user-a", "a.md", kind="markdown", size=1)["s3_key"]
    k2 = store.upsert_file(p["id"], "user-a", "b.md", kind="markdown", size=1)["s3_key"]
    keys = store.delete_project(p["id"], "user-a")
    assert set(keys) == {k1, k2}
    assert store.get_project(p["id"], "user-a") is None


def test_build_s3_key_shape():
    key = store.build_s3_key("user-a", "proj123", "sub/notes.md")
    assert key.startswith(f"{objstore.EDITOR_S3_PREFIX}/")
    # 相対パスの区切りは埋め込まれず、末尾はサニタイズ済みファイル名
    assert key.endswith("-notes.md")
    assert "proj123" in key
    assert "/sub/" not in key
