"""procuretech-editor マイクロサービス（Open GENAI exApp / 専用ページ向け）。

案件フォルダ（プロジェクト）内の生成文書（Markdown 等）を編集・保存し、Word 変換 API
へ統合するためのバックエンド。ファイル本体は S3 互換ストレージ（SeaweedFS 等）に保存し、
メタデータは SQLite（`store.py`）で管理する。

- 庁内: backend が JWT 検証後、HMAC 署名付きで各エンドポイントへプロキシする。
- Compose では profiles: ["procuretech-editor"] でオプション起動する。
"""

from __future__ import annotations

import io
import os
import zipfile
from typing import Any

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from . import convert, excel, intauth, nextcloud, objstore, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
MAX_UPLOAD_BYTES = int(os.environ.get("EDITOR_MAX_UPLOAD_BYTES", "20971520"))  # 20MB

app = FastAPI(title="Open GENAI ProcureTech Editor App", version="0.1.0")


# --- 認証 ---------------------------------------------------------------------


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _verify_internal(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> tuple[JSONResponse | None, str]:
    err = _check_key(x_api_key)
    if err:
        return err, ""
    if not intauth.verify(
        x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    ):
        return (
            JSONResponse(status_code=401, content={"error": "invalid internal signature"}),
            "",
        )
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), ""
    return None, x_user_id


def _auth(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> tuple[JSONResponse | None, str]:
    return _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )


# --- ファイル種別・パス補助 ---------------------------------------------------

TEXT_KINDS = {"markdown", "text"}
_EXT_KIND = {
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
    ".csv": "text",
    ".xlsx": "excel",
    ".xls": "excel",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".svg": "image",
    ".docx": "word",
    ".doc": "word",
    ".pdf": "pdf",
    ".zip": "zip",
}


def _kind_of(rel_path: str) -> str:
    name = rel_path.rsplit("/", 1)[-1]
    if name == ".keep":
        return "keep"
    dot = name.rfind(".")
    if dot == -1:
        return "text"
    return _EXT_KIND.get(name[dot:].lower(), "binary")


def _pub_file(f: dict[str, Any]) -> dict[str, Any]:
    """フロントへ返すファイル情報（内部の S3 キーは含めない）。"""
    return {k: v for k, v in f.items() if k != "s3_key"}


def _clean_rel_path(path: str | None) -> str | None:
    """相対パスを検証・正規化する（不正なら None）。"""
    if path is None:
        return None
    p = str(path).strip().replace("\\", "/").strip("/")
    while "//" in p:
        p = p.replace("//", "/")
    if not p:
        return None
    parts = p.split("/")
    if any(seg in ("", ".", "..") for seg in parts):
        return None
    return p


# --- ライフサイクル -----------------------------------------------------------


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def get_config(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(
        content={
            "enabled": True,
            "storage_configured": objstore.is_configured(),
            "convert_configured": convert.is_configured(),
            "nextcloud_configured": nextcloud.is_configured(),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "markers": excel.MARKERS,
        }
    )


# --- projects -----------------------------------------------------------------


@app.get("/projects")
async def list_projects(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(content={"projects": store.list_projects(uid)})


@app.post("/projects")
async def create_project(
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    name = str(payload.get("name") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "プロジェクト名を入力してください。"})
    if len(name) > 200:
        return JSONResponse(status_code=400, content={"error": "プロジェクト名が長すぎます。"})
    project = store.create_project(uid, name)
    return JSONResponse(content={"project": project})


@app.get("/projects/{project_id}")
async def get_project(
    project_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    project = store.get_project(project_id, uid)
    if project is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    return JSONResponse(
        content={
            "project": project,
            "files": [_pub_file(f) for f in store.list_files(project_id, uid)],
        }
    )


@app.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    keys = store.delete_project(project_id, uid)
    objstore.delete_keys(keys)
    return JSONResponse(content={"deleted": True})


# --- files --------------------------------------------------------------------


@app.get("/projects/{project_id}/files")
async def list_files(
    project_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    return JSONResponse(
        content={"files": [_pub_file(f) for f in store.list_files(project_id, uid)]}
    )


@app.get("/projects/{project_id}/files/content")
async def get_file_content(
    project_id: str,
    path: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    rel = _clean_rel_path(path)
    if rel is None:
        return JSONResponse(status_code=400, content={"error": "不正なパスです。"})
    f = store.get_file(project_id, uid, rel)
    if f is None:
        return JSONResponse(status_code=404, content={"error": "ファイルが見つかりません。"})
    result: dict[str, Any] = {
        "path": f["rel_path"],
        "kind": f["kind"],
        "size": f["size"],
        "updated_at": f["updated_at"],
    }
    if f["kind"] in TEXT_KINDS:
        data = objstore.get_bytes(f["s3_key"]) or b""
        result["content"] = data.decode("utf-8", errors="replace")
    else:
        result["download_url"] = objstore.presign_get(
            f["s3_key"], filename=rel.rsplit("/", 1)[-1]
        )
    return JSONResponse(content=result)


@app.post("/projects/{project_id}/files/save")
async def save_file(
    project_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    rel = _clean_rel_path(payload.get("path"))
    if rel is None:
        return JSONResponse(status_code=400, content={"error": "不正なパスです。"})
    kind = _kind_of(rel)
    if kind not in TEXT_KINDS:
        return JSONResponse(
            status_code=400, content={"error": "テキスト（.md/.txt 等）以外はアップロードから追加してください。"}
        )
    content = str(payload.get("content") or "")
    data = content.encode("utf-8")
    if len(data) > MAX_UPLOAD_BYTES:
        return JSONResponse(status_code=413, content={"error": "内容が大きすぎます。"})
    existing = store.get_file(project_id, uid, rel)
    s3_key = existing["s3_key"] if existing else store.build_s3_key(uid, project_id, rel)
    if not objstore.put_bytes(s3_key, data, content_type="text/markdown; charset=utf-8"):
        return JSONResponse(status_code=502, content={"error": "ストレージへの保存に失敗しました。"})
    f = store.upsert_file(project_id, uid, rel, kind=kind, size=len(data), s3_key=s3_key)
    return JSONResponse(content={"file": _pub_file(f)})


@app.post("/projects/{project_id}/files/upload")
async def upload_file(
    project_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    filename = str(payload.get("filename") or "").strip()
    if not filename:
        return JSONResponse(status_code=400, content={"error": "ファイル名が必要です。"})
    # 保存先の相対パス（省略時はファイル名、dir 指定時はその配下）。
    # 表示名は日本語等を保持するため sanitize せず、パス区切りのみ落とす
    # （S3 キーの安全化は store.build_s3_key 側で行う）。
    directory = _clean_rel_path(payload.get("dir")) if payload.get("dir") else None
    base = filename.replace("\\", "/").split("/")[-1]
    rel = _clean_rel_path(f"{directory}/{base}" if directory else base)
    if rel is None:
        return JSONResponse(status_code=400, content={"error": "不正なパスです。"})
    try:
        data = excel.decode_upload(str(payload.get("content_b64") or ""), max_bytes=MAX_UPLOAD_BYTES)
    except excel.ExcelError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    validate = payload.get("validate_type")
    if validate:
        try:
            excel.validate_type(data, str(validate))
        except excel.ExcelError as e:
            return JSONResponse(status_code=400, content={"error": str(e)})
    kind = _kind_of(rel)
    existing = store.get_file(project_id, uid, rel)
    s3_key = existing["s3_key"] if existing else store.build_s3_key(uid, project_id, rel)
    if not objstore.put_bytes(s3_key, data):
        return JSONResponse(status_code=502, content={"error": "ストレージへの保存に失敗しました。"})
    f = store.upsert_file(project_id, uid, rel, kind=kind, size=len(data), s3_key=s3_key)
    return JSONResponse(content={"file": _pub_file(f)})


@app.post("/projects/{project_id}/dir")
async def create_dir(
    project_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """空フォルダを作成する（`.keep` センチネルで保持）。"""
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    directory = _clean_rel_path(payload.get("path"))
    if directory is None:
        return JSONResponse(status_code=400, content={"error": "不正なパスです。"})
    rel = f"{directory}/.keep"
    if store.get_file(project_id, uid, rel) is not None:
        return JSONResponse(content={"created": True})
    s3_key = store.build_s3_key(uid, project_id, rel)
    objstore.put_bytes(s3_key, b"")
    store.upsert_file(project_id, uid, rel, kind="keep", size=0, s3_key=s3_key)
    return JSONResponse(content={"created": True})


@app.post("/projects/{project_id}/files/rename")
async def rename_file(
    project_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    old_rel = _clean_rel_path(payload.get("old_path"))
    new_rel = _clean_rel_path(payload.get("new_path"))
    if old_rel is None or new_rel is None:
        return JSONResponse(status_code=400, content={"error": "不正なパスです。"})
    f = store.rename_file(project_id, uid, old_rel, new_rel, new_kind=_kind_of(new_rel))
    if f is None:
        return JSONResponse(
            status_code=409, content={"error": "リネームできません（存在しないか、移動先が既にあります）。"}
        )
    return JSONResponse(content={"file": _pub_file(f)})


@app.post("/projects/{project_id}/files/duplicate")
async def duplicate_file(
    project_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    src_rel = _clean_rel_path(payload.get("path"))
    if src_rel is None:
        return JSONResponse(status_code=400, content={"error": "不正なパスです。"})
    src = store.get_file(project_id, uid, src_rel)
    if src is None:
        return JSONResponse(status_code=404, content={"error": "ファイルが見つかりません。"})
    dst_rel = _clean_rel_path(payload.get("new_path")) or _auto_copy_name(
        project_id, uid, src_rel
    )
    if store.get_file(project_id, uid, dst_rel) is not None:
        return JSONResponse(status_code=409, content={"error": "移動先が既に存在します。"})
    dst_key = store.build_s3_key(uid, project_id, dst_rel)
    if not objstore.copy_key(src["s3_key"], dst_key):
        return JSONResponse(status_code=502, content={"error": "複製に失敗しました。"})
    f = store.upsert_file(
        project_id, uid, dst_rel, kind=_kind_of(dst_rel), size=src["size"], s3_key=dst_key
    )
    return JSONResponse(content={"file": _pub_file(f)})


def _auto_copy_name(project_id: str, uid: str, src_rel: str) -> str:
    """`name.md` → `name (コピー).md` のような重複しない複製名を作る。"""
    if "/" in src_rel:
        parent, base = src_rel.rsplit("/", 1)
        parent += "/"
    else:
        parent, base = "", src_rel
    dot = base.rfind(".")
    stem, ext = (base[:dot], base[dot:]) if dot > 0 else (base, "")
    i = 1
    while True:
        suffix = " (コピー)" if i == 1 else f" (コピー{i})"
        cand = f"{parent}{stem}{suffix}{ext}"
        if store.get_file(project_id, uid, cand) is None:
            return cand
        i += 1


@app.post("/projects/{project_id}/files/delete")
async def delete_file(
    project_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    rel = _clean_rel_path(payload.get("path"))
    if rel is None:
        return JSONResponse(status_code=400, content={"error": "不正なパスです。"})
    key = store.delete_file(project_id, uid, rel)
    if key is None:
        return JSONResponse(status_code=404, content={"error": "ファイルが見つかりません。"})
    objstore.delete_key(key)
    return JSONResponse(content={"deleted": True})


# --- export / conversion ------------------------------------------------------


@app.post("/projects/{project_id}/export")
async def export_project(
    project_id: str,
    payload: dict[str, Any],
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    project = store.get_project(project_id, uid)
    if project is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    if not convert.is_configured():
        return JSONResponse(status_code=503, content={"error": "Word 変換 API が未設定です。"})
    files = store.list_files(project_id, uid)
    md_files = [f for f in files if f["kind"] != "keep"]
    if not md_files:
        return JSONResponse(status_code=400, content={"error": "書き出せるファイルがありません。"})
    project_name = objstore.sanitize_filename(project["name"]) or "project"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in md_files:
            data = objstore.get_bytes(f["s3_key"])
            if data is None:
                continue
            zf.writestr(f"{project_name}/{f['rel_path']}", data)
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    try:
        result = await convert.start_conversion(
            buf.getvalue(),
            project_name=project_name,
            username=uid,
            options=options,
        )
    except convert.ConvertError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    return JSONResponse(content=result)


@app.get("/conversions/{request_id}")
async def conversion_status(
    request_id: str,
    project_id: str | None = None,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    try:
        status = await convert.get_status(request_id)
    except convert.ConvertError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    # 成功かつ Nextcloud 出力があり、Nextcloud/ストレージが利用可能なら結果を取り込み、
    # ダウンロード用の署名付き URL を付与する。
    if (
        status.get("status") == "success"
        and status.get("nextcloud_path")
        and nextcloud.is_configured()
        and objstore.is_configured()
    ):
        try:
            tree = nextcloud.download_tree(str(status["nextcloud_path"]))
            if tree:
                zbuf = io.BytesIO()
                with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_DEFLATED) as zf:
                    for rel, data in tree.items():
                        zf.writestr(rel, data)
                base = os.path.basename(str(status["nextcloud_path"]).rstrip("/")) or "word"
                key = "/".join(
                    [objstore.EDITOR_S3_PREFIX, "_exports", f"{request_id}.zip"]
                )
                if objstore.put_bytes(
                    key, zbuf.getvalue(), content_type="application/zip"
                ):
                    status["download_url"] = objstore.presign_get(
                        key, filename=f"{base}.zip", expiry=3600
                    )
                    status["download_filename"] = f"{base}.zip"
        except Exception as e:  # noqa: BLE001
            status["download_error"] = f"変換結果の取り込みに失敗しました: {e}"
    return JSONResponse(content=status)
