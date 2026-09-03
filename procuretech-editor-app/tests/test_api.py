"""API レベルのテスト（S3 はメモリ辞書でスタブ化、署名検証はスキップ）。"""

import base64

import pytest
from fastapi.testclient import TestClient

from app import main, objstore, store

USER_A = {"x-api-key": "local-rag-key", "x-user-id": "user-a"}
USER_B = {"x-api-key": "local-rag-key", "x-user-id": "user-b"}


@pytest.fixture(autouse=True)
def _fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_db", None)
    monkeypatch.setattr(store, "DB_PATH", str(tmp_path / "pte.db"))
    store.init_db()
    yield
    monkeypatch.setattr(store, "_db", None)


@pytest.fixture(autouse=True)
def _mem_objstore(monkeypatch):
    """objstore を辞書ベースのメモリ実装に差し替える（store/main が共有参照）。"""
    blobs: dict[str, bytes] = {}

    monkeypatch.setattr(objstore, "is_configured", lambda: True)
    monkeypatch.setattr(
        objstore,
        "put_bytes",
        lambda key, data, content_type=None: (blobs.__setitem__(key, data), True)[1],
    )
    monkeypatch.setattr(objstore, "get_bytes", lambda key: blobs.get(key))
    monkeypatch.setattr(
        objstore, "delete_key", lambda key: (blobs.pop(key, None), True)[1]
    )
    monkeypatch.setattr(
        objstore,
        "delete_keys",
        lambda keys: sum(1 for k in keys if blobs.pop(k, None) is not None),
    )
    monkeypatch.setattr(
        objstore,
        "copy_key",
        lambda src, dst: (blobs.__setitem__(dst, blobs.get(src, b"")), True)[1],
    )
    monkeypatch.setattr(
        objstore, "presign_get", lambda key, filename=None, expiry=None: f"https://dl/{key}"
    )
    return blobs


@pytest.fixture
def client():
    return TestClient(main.app)


def _create_project(client, name="案件1", headers=USER_A):
    res = client.post("/projects", json={"name": name}, headers=headers)
    assert res.status_code == 200, res.text
    return res.json()["project"]


def test_config_reports_flags(client):
    res = client.get("/config", headers=USER_A)
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert "markers" in body


def test_requires_auth(client):
    assert client.get("/projects").status_code == 401
    assert client.get("/projects", headers={"x-api-key": "wrong"}).status_code == 401


def test_project_crud_and_isolation(client):
    p = _create_project(client)
    # 一覧に出る
    assert [x["id"] for x in client.get("/projects", headers=USER_A).json()["projects"]] == [
        p["id"]
    ]
    # 他ユーザーには見えない
    assert client.get("/projects", headers=USER_B).json()["projects"] == []
    assert client.get(f"/projects/{p['id']}", headers=USER_B).status_code == 404
    # 削除
    assert client.delete(f"/projects/{p['id']}", headers=USER_A).status_code == 200
    assert client.get(f"/projects/{p['id']}", headers=USER_A).status_code == 404


def test_save_and_read_markdown(client):
    p = _create_project(client)
    res = client.post(
        f"/projects/{p['id']}/files/save",
        json={"path": "01_仕様.md", "content": "# タイトル\n本文"},
        headers=USER_A,
    )
    assert res.status_code == 200, res.text
    f = res.json()["file"]
    assert f["kind"] == "markdown"
    assert "s3_key" not in f  # 内部キーは返さない
    # 内容取得
    got = client.get(
        f"/projects/{p['id']}/files/content",
        params={"path": "01_仕様.md"},
        headers=USER_A,
    )
    assert got.status_code == 200
    assert got.json()["content"] == "# タイトル\n本文"


def test_save_rejects_binary_extension(client):
    p = _create_project(client)
    res = client.post(
        f"/projects/{p['id']}/files/save",
        json={"path": "a.xlsx", "content": "x"},
        headers=USER_A,
    )
    assert res.status_code == 400


def test_upload_binary_and_download_url(client):
    p = _create_project(client)
    content_b64 = base64.b64encode(b"PNGDATA").decode()
    res = client.post(
        f"/projects/{p['id']}/files/upload",
        json={"filename": "図.png", "content_b64": content_b64},
        headers=USER_A,
    )
    assert res.status_code == 200, res.text
    assert res.json()["file"]["kind"] == "image"
    got = client.get(
        f"/projects/{p['id']}/files/content",
        params={"path": "図.png"},
        headers=USER_A,
    ).json()
    assert got["download_url"].startswith("https://dl/")
    assert "content" not in got


def test_rename_duplicate_delete(client):
    p = _create_project(client)
    client.post(
        f"/projects/{p['id']}/files/save",
        json={"path": "a.md", "content": "A"},
        headers=USER_A,
    )
    # rename
    r = client.post(
        f"/projects/{p['id']}/files/rename",
        json={"old_path": "a.md", "new_path": "b.md"},
        headers=USER_A,
    )
    assert r.status_code == 200
    assert r.json()["file"]["rel_path"] == "b.md"
    # duplicate（自動命名）
    d = client.post(
        f"/projects/{p['id']}/files/duplicate",
        json={"path": "b.md"},
        headers=USER_A,
    )
    assert d.status_code == 200
    dup_path = d.json()["file"]["rel_path"]
    assert dup_path != "b.md"
    # 複製内容は元と同一
    dup = client.get(
        f"/projects/{p['id']}/files/content", params={"path": dup_path}, headers=USER_A
    ).json()
    assert dup["content"] == "A"
    # delete
    assert (
        client.post(
            f"/projects/{p['id']}/files/delete", json={"path": "b.md"}, headers=USER_A
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/projects/{p['id']}/files/content", params={"path": "b.md"}, headers=USER_A
        ).status_code
        == 404
    )


def test_dir_creates_keep_sentinel_hidden_from_kind(client):
    p = _create_project(client)
    res = client.post(f"/projects/{p['id']}/dir", json={"path": "図"}, headers=USER_A)
    assert res.status_code == 200
    files = client.get(f"/projects/{p['id']}/files", headers=USER_A).json()["files"]
    assert any(f["rel_path"] == "図/.keep" for f in files)


def test_path_traversal_rejected(client):
    p = _create_project(client)
    res = client.post(
        f"/projects/{p['id']}/files/save",
        json={"path": "../evil.md", "content": "x"},
        headers=USER_A,
    )
    assert res.status_code == 400


def test_export_requires_convert_configured(client, monkeypatch):
    from app import convert

    monkeypatch.setattr(convert, "is_configured", lambda: False)
    p = _create_project(client)
    client.post(
        f"/projects/{p['id']}/files/save",
        json={"path": "a.md", "content": "A"},
        headers=USER_A,
    )
    res = client.post(f"/projects/{p['id']}/export", json={"options": {}}, headers=USER_A)
    assert res.status_code == 503
