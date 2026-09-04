"""API レベルのテスト（S3 はメモリ辞書でスタブ化、署名検証はスキップ）。"""

import base64
import io
import zipfile

import openpyxl
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


def _xlsx_with_marker(marker: str) -> str:
    """B1 マーカー入りの xlsx を base64 で返す。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws["B1"] = marker
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def test_config_reports_flags(client):
    res = client.get("/config", headers=USER_A)
    assert res.status_code == 200
    body = res.json()
    assert body["enabled"] is True
    assert "markers" in body
    assert "generate_configured" in body
    assert isinstance(body.get("generate_themes"), list)
    assert body["generate_themes"] and body["generate_themes"][0]["id"] == "procurement_spec"


def test_generate_requires_configured(client, monkeypatch):
    from app import generate

    # テーマの API 未解決（EDITOR_GENERATE_URL 空）→ 503
    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "")
    p = _create_project(client)
    res = client.post(
        f"/projects/{p['id']}/generate",
        json={
            "theme": "procurement_spec",
            "inputs": {
                "systemplan": _xlsx_with_marker("systemplan"),
                "global": _xlsx_with_marker("global"),
            },
        },
        headers=USER_A,
    )
    assert res.status_code == 503


def test_generate_rejects_wrong_marker(client, monkeypatch):
    from app import generate

    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "http://generate.test")
    p = _create_project(client)
    # systemplan の位置に global を渡す → 400
    res = client.post(
        f"/projects/{p['id']}/generate",
        json={
            "theme": "procurement_spec",
            "inputs": {
                "systemplan": _xlsx_with_marker("global"),
                "global": _xlsx_with_marker("global"),
            },
        },
        headers=USER_A,
    )
    assert res.status_code == 400


def test_generate_rejects_unknown_theme(client, monkeypatch):
    from app import generate

    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "http://generate.test")
    p = _create_project(client)
    res = client.post(
        f"/projects/{p['id']}/generate",
        json={"theme": "does-not-exist", "inputs": {}},
        headers=USER_A,
    )
    assert res.status_code == 400


def test_generate_flow_imports_zip(client, monkeypatch):
    from app import generate

    async def fake_start(files, *, base_url, api_key="", username, doc_type=None, options=None):
        assert set(files.keys()) == {"systemplan", "global"}
        assert base_url == "http://generate.test"
        return {"request_id": "gen-1"}

    async def fake_status(request_id, *, base_url, api_key=""):
        assert request_id == "gen-1"
        return {"status": "success", "progress": 100}

    async def fake_result(request_id, *, base_url, api_key=""):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("section1_概要.md", "# 概要\n本文")
            zf.writestr("README.md", "# README")
            zf.writestr(".keep", "")  # 取り込み対象外
        return buf.getvalue()

    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "http://generate.test")
    monkeypatch.setattr(generate, "start_generation", fake_start)
    monkeypatch.setattr(generate, "get_status", fake_status)
    monkeypatch.setattr(generate, "fetch_result", fake_result)

    p = _create_project(client)
    start = client.post(
        f"/projects/{p['id']}/generate",
        json={
            "theme": "procurement_spec",
            "inputs": {
                "systemplan": _xlsx_with_marker("systemplan"),
                "global": _xlsx_with_marker("global"),
            },
        },
        headers=USER_A,
    )
    assert start.status_code == 200, start.text
    rid = start.json()["request_id"]
    assert rid == "gen-1"

    # ステータス確認 → 成功で zip を取り込む
    st = client.get(f"/projects/{p['id']}/generations/{rid}", headers=USER_A)
    assert st.status_code == 200, st.text
    body = st.json()
    assert body["status"] == "success"
    assert body["imported"] is True
    assert set(body["files"]) == {"section1_概要.md", "README.md"}

    # 取り込んだ Markdown を読める
    got = client.get(
        f"/projects/{p['id']}/files/content",
        params={"path": "section1_概要.md"},
        headers=USER_A,
    ).json()
    assert got["content"] == "# 概要\n本文"

    # 2 回目の確認はキャッシュ済み（再取得しなくても success を返す）
    def _boom(_):  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("should not refetch after import")

    monkeypatch.setattr(generate, "get_status", _boom)
    again = client.get(f"/projects/{p['id']}/generations/{rid}", headers=USER_A)
    assert again.status_code == 200
    assert again.json()["imported"] is True


def test_generation_status_not_found(client):
    p = _create_project(client)
    res = client.get(f"/projects/{p['id']}/generations/nope", headers=USER_A)
    assert res.status_code == 404


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


# --- composition（合成定義 + Word 合成） --------------------------------------


def _run_generation_with_sections(client, monkeypatch, project_id):
    """sections.json 付きの生成結果を取り込ませ、section_key を付与する。"""
    from app import generate

    async def fake_start(files, *, base_url, api_key="", username, doc_type=None, options=None):
        return {"request_id": "gen-sec"}

    async def fake_status(request_id, *, base_url, api_key=""):
        return {"status": "success", "progress": 100}

    async def fake_result(request_id, *, base_url, api_key=""):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("section1.md", "# 背景\n本文1")
            zf.writestr("section2.md", "# 目的\n本文2")
            zf.writestr("rfi1.md", "# RFI\n本文rfi")
            zf.writestr(
                "sections.json",
                (
                    '{"theme":"procurement_spec","sections":['
                    '{"file":"section1.md","section_key":"background","order":1},'
                    '{"file":"section2.md","section_key":"businessPurpose","order":2},'
                    '{"file":"rfi1.md","section_key":"rfi","order":3}]}'
                ),
            )
        return buf.getvalue()

    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "http://generate.test")
    monkeypatch.setattr(generate, "start_generation", fake_start)
    monkeypatch.setattr(generate, "get_status", fake_status)
    monkeypatch.setattr(generate, "fetch_result", fake_result)
    start = client.post(
        f"/projects/{project_id}/generate",
        json={
            "theme": "procurement_spec",
            "inputs": {
                "systemplan": _xlsx_with_marker("systemplan"),
                "global": _xlsx_with_marker("global"),
            },
        },
        headers=USER_A,
    )
    assert start.status_code == 200, start.text
    rid = start.json()["request_id"]
    st = client.get(f"/projects/{project_id}/generations/{rid}", headers=USER_A)
    assert st.status_code == 200, st.text
    assert st.json()["imported"] is True


def test_import_assigns_section_keys(client, monkeypatch):
    p = _create_project(client)
    _run_generation_with_sections(client, monkeypatch, p["id"])
    files = client.get(f"/projects/{p['id']}/files", headers=USER_A).json()["files"]
    by_path = {f["rel_path"]: f for f in files}
    assert by_path["section1.md"]["section_key"] == "background"
    assert by_path["section2.md"]["section_key"] == "businessPurpose"
    assert by_path["rfi1.md"]["section_key"] == "rfi"


def test_composition_default_from_theme(client, monkeypatch):
    p = _create_project(client)
    _run_generation_with_sections(client, monkeypatch, p["id"])
    res = client.get(f"/projects/{p['id']}/composition", headers=USER_A)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["saved"] is False
    ids = [o["id"] for o in body["composition"]["outputs"]]
    assert "specification" in ids and "rfi" in ids
    spec = next(o for o in body["composition"]["outputs"] if o["id"] == "specification")
    keys = [it["section_key"] for it in spec["items"]]
    assert keys[:2] == ["background", "businessPurpose"]
    # section カタログ・テーマが返る
    assert body["theme"]["id"] == "procurement_spec"
    assert any(s["key"] == "background" for s in body["theme"]["sections"])


def test_composition_save_and_get(client, monkeypatch):
    p = _create_project(client)
    _run_generation_with_sections(client, monkeypatch, p["id"])
    composition = {
        "theme": "procurement_spec",
        "outputs": [
            {
                "id": "custom",
                "name": "まとめ",
                "enabled": True,
                "items": [{"section_key": "businessPurpose"}, {"section_key": "background"}],
            }
        ],
    }
    put = client.put(
        f"/projects/{p['id']}/composition",
        json={"composition": composition},
        headers=USER_A,
    )
    assert put.status_code == 200, put.text
    got = client.get(f"/projects/{p['id']}/composition", headers=USER_A).json()
    assert got["saved"] is True
    assert got["composition"]["outputs"][0]["name"] == "まとめ"
    keys = [it["section_key"] for it in got["composition"]["outputs"][0]["items"]]
    assert keys == ["businessPurpose", "background"]


def test_compose_assembles_and_returns_url(client, monkeypatch):
    from app import generate

    p = _create_project(client)
    _run_generation_with_sections(client, monkeypatch, p["id"])

    captured = {}

    async def fake_compose(outputs, *, base_url, api_key="", reference=None, assets=None):
        captured["outputs"] = outputs
        captured["reference"] = reference
        captured["assets"] = assets
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for o in outputs:
                zf.writestr(f"{o['name']}.docx", b"DOCX")
        return buf.getvalue()

    monkeypatch.setattr(generate, "compose", fake_compose)

    # Excel 出力（見積/一次審査）は書き出し時生成。ここではスキップさせて Word のみ検証。
    async def fake_build_excel(builder, *, base_url, api_key="", params=None, sections=None):
        raise generate.ExcelSkip("テスト: スキップ")

    monkeypatch.setattr(generate, "build_excel", fake_build_excel)

    # 既定（テーマ）定義で合成
    res = client.post(f"/projects/{p['id']}/compose", json={}, headers=USER_A)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "success"
    assert body["download_url"].startswith("https://dl/")

    # specification 出力は section 順に本文を集約している
    spec = next(o for o in captured["outputs"] if o["name"] == "調達仕様書")
    contents = [s["content"] for s in spec["sections"]]
    # background(section1) → businessPurpose(section2) の順
    assert contents[0].startswith("# 背景")
    assert contents[1].startswith("# 目的")
    # 生成されていない章（outline 等）は本文なしのため含まれない
    assert all("本文" in c for c in contents)
    assert captured["reference"] == "specification"
    # Excel 出力（見積/一次審査）はファイル未生成のため spec-app へは送られない
    assert all("xlsx" not in (s.get("filename", "") or "") for s in spec["sections"])


def test_compose_overrides_and_embeds_image(client, monkeypatch):
    """overrides で本文を差し替え、参照画像を assets として compose へ渡す。"""
    from app import generate

    p = _create_project(client)
    _run_generation_with_sections(client, monkeypatch, p["id"])

    files = client.get(f"/projects/{p['id']}/files", headers=USER_A).json()["files"]
    bg_id = next(f["id"] for f in files if f["rel_path"] == "section1.md")

    # 参照画像をアップロード（images/pic.png）。
    client.post(
        f"/projects/{p['id']}/files/upload",
        json={"filename": "pic.png", "content_b64": base64.b64encode(b"PNGDATA").decode(),
              "dir": "images"},
        headers=USER_A,
    )

    captured = {}

    async def fake_compose(outputs, *, base_url, api_key="", reference=None, assets=None):
        captured["outputs"] = outputs
        captured["assets"] = assets
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for o in outputs:
                zf.writestr(f"{o['name']}.docx", b"DOCX")
        return buf.getvalue()

    monkeypatch.setattr(generate, "compose", fake_compose)

    async def fake_build_excel(builder, *, base_url, api_key="", params=None, sections=None):
        raise generate.ExcelSkip("テスト: スキップ")

    monkeypatch.setattr(generate, "build_excel", fake_build_excel)

    override = "# 背景\n\n![diagram](images/pic.png)\n"
    res = client.post(
        f"/projects/{p['id']}/compose",
        json={"overrides": {bg_id: override}},
        headers=USER_A,
    )
    assert res.status_code == 200, res.text

    spec = next(o for o in captured["outputs"] if o["name"] == "調達仕様書")
    # override が S3 の内容より優先される
    assert spec["sections"][0]["content"] == override
    # 参照画像が assets として渡る
    assert captured["assets"] is not None
    assert captured["assets"]["images/pic.png"] == b"PNGDATA"


def test_download_input_template(client, monkeypatch, _mem_objstore):
    """テーマ入力の様式を生成サービスから取得し、署名付き URL を返す。"""
    from app import generate

    async def fake_fetch(input_key, *, base_url, api_key=""):
        assert input_key == "systemplan"
        return (b"XLSXFORM", "systemplan.xlsx", "application/vnd.ms-excel")

    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "http://gen.test")
    monkeypatch.setattr(generate, "fetch_template", fake_fetch)

    res = client.get(
        "/themes/procurement_spec/inputs/systemplan/template", headers=USER_A
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["download_filename"] == "systemplan.xlsx"
    key = body["download_url"].split("https://dl/", 1)[1]
    assert _mem_objstore[key] == b"XLSXFORM"


def test_download_input_template_missing(client, monkeypatch):
    """生成サービスが様式未対応(404)ならエラーを返す。"""
    from app import generate

    async def fake_fetch(input_key, *, base_url, api_key=""):
        raise generate.GenerateError("この入力の様式は配信されていません。")

    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "http://gen.test")
    monkeypatch.setattr(generate, "fetch_template", fake_fetch)

    res = client.get("/themes/procurement_spec/inputs/global/template", headers=USER_A)
    assert res.status_code == 404


def test_compose_builds_excel_at_export(client, monkeypatch, _mem_objstore):
    """Excel（見積総括表）は書き出し時に、保存パラメータ＋現時点の章から生成される。"""
    from app import generate

    async def fake_start(files, *, base_url, api_key="", username, doc_type=None, options=None):
        return {"request_id": "gen-xlsx"}

    async def fake_status(request_id, *, base_url, api_key=""):
        return {"status": "success", "progress": 100}

    async def fake_result(request_id, *, base_url, api_key=""):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("section1.md", "# 背景\n本文1")
            zf.writestr("section2.md", "# 目的\n本文2")
            # 生成時に保存されるパラメータ（書き出し時の Excel 生成で使う）
            zf.writestr(
                "template_data.json",
                '{"nextyear":"2027","phaselist":"1, 2","projectName":"P"}',
            )
            zf.writestr(
                "sections.json",
                (
                    '{"theme":"procurement_spec","sections":['
                    '{"file":"section1.md","section_key":"background","order":1},'
                    '{"file":"section2.md","section_key":"businessPurpose","order":2}]}'
                ),
            )
        return buf.getvalue()

    monkeypatch.setattr(generate, "EDITOR_GENERATE_URL", "http://generate.test")
    monkeypatch.setattr(generate, "start_generation", fake_start)
    monkeypatch.setattr(generate, "get_status", fake_status)
    monkeypatch.setattr(generate, "fetch_result", fake_result)

    # compose は Excel のみなので generate.compose は呼ばれてはならない
    async def _boom(*a, **k):  # pragma: no cover
        raise AssertionError("generate.compose should not be called for excel-only")

    monkeypatch.setattr(generate, "compose", _boom)

    captured = {}

    async def fake_build_excel(builder, *, base_url, api_key="", params=None, sections=None):
        captured["builder"] = builder
        captured["params"] = params
        captured["sections"] = sections
        return b"XLSXDATA-QUOTATION"

    monkeypatch.setattr(generate, "build_excel", fake_build_excel)

    p = _create_project(client)
    start = client.post(
        f"/projects/{p['id']}/generate",
        json={
            "theme": "procurement_spec",
            "inputs": {
                "systemplan": _xlsx_with_marker("systemplan"),
                "global": _xlsx_with_marker("global"),
            },
        },
        headers=USER_A,
    )
    rid = start.json()["request_id"]
    client.get(f"/projects/{p['id']}/generations/{rid}", headers=USER_A)

    # 見積総括表（excel 出力・builder=quotation）だけを対象に compose
    composition = {
        "theme": "procurement_spec",
        "outputs": [
            {
                "id": "quotation",
                "name": "見積費用総括表",
                "kind": "excel",
                "builder": "quotation",
                "enabled": True,
                "items": [],
            }
        ],
    }
    res = client.post(
        f"/projects/{p['id']}/compose", json={"composition": composition}, headers=USER_A
    )
    assert res.status_code == 200, res.text
    url = res.json()["download_url"]
    key = url.split("https://dl/", 1)[1]
    zdata = _mem_objstore[key]
    with zipfile.ZipFile(io.BytesIO(zdata)) as zf:
        names = zf.namelist()
        assert "見積費用総括表.xlsx" in names
        assert zf.read("見積費用総括表.xlsx") == b"XLSXDATA-QUOTATION"

    # 保存パラメータ（nextyear/phaselist）と現時点の章本文が生成サービスへ渡る
    assert captured["builder"] == "quotation"
    assert captured["params"]["nextyear"] == "2027"
    assert captured["params"]["phaselist"] == "1, 2"
    assert captured["sections"]["background"].startswith("# 背景")


def test_compose_skips_excel_when_no_source(client, monkeypatch, _mem_objstore):
    """一次審査表の対象章が無い場合はスキップし、skipped に理由を返す。"""
    from app import generate

    p = _create_project(client)
    _run_generation_with_sections(client, monkeypatch, p["id"])

    async def fake_build_excel(builder, *, base_url, api_key="", params=None, sections=None):
        raise generate.ExcelSkip("一次審査表の対象章がありません。")

    monkeypatch.setattr(generate, "build_excel", fake_build_excel)

    async def fake_compose(outputs, *, base_url, api_key="", reference=None, assets=None):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for o in outputs:
                zf.writestr(f"{o['name']}.docx", b"DOCX")
        return buf.getvalue()

    monkeypatch.setattr(generate, "compose", fake_compose)

    composition = {
        "theme": "procurement_spec",
        "outputs": [
            {
                "id": "specification",
                "name": "調達仕様書",
                "kind": "markdown",
                "enabled": True,
                "items": [{"section_key": "background"}],
            },
            {
                "id": "primaryexam",
                "name": "一次審査表",
                "kind": "excel",
                "builder": "primaryexam",
                "enabled": True,
                "items": [],
            },
        ],
    }
    res = client.post(
        f"/projects/{p['id']}/compose", json={"composition": composition}, headers=USER_A
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert any(s["name"] == "一次審査表" for s in body.get("skipped", []))
