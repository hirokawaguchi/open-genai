"""procuretech-editor マイクロサービス（Open GENAI exApp / 専用ページ向け）。

案件フォルダ（プロジェクト）内の生成文書（Markdown 等）を編集・保存し、Word 変換 API
へ統合するためのバックエンド。ファイル本体は S3 互換ストレージ（SeaweedFS 等）に保存し、
メタデータは SQLite（`store.py`）で管理する。

- 庁内: backend が JWT 検証後、HMAC 署名付きで各エンドポイントへプロキシする。
- Compose では profiles: ["procuretech-editor"] でオプション起動する。
"""

from __future__ import annotations

import io
import json
import os
import re
import uuid
import zipfile
from typing import Any

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from . import excel, generate, intauth, objstore, store

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
            "generate_configured": generate.is_configured(),
            "generate_themes": generate.public_themes(),
            "max_upload_bytes": MAX_UPLOAD_BYTES,
            "markers": excel.MARKERS,
        }
    )


@app.get("/themes/{theme_id}/inputs/{input_key}/template")
async def download_input_template(
    theme_id: str,
    input_key: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """テーマの入力に対応する様式（ヒアリングシート）を生成サービスから取得し、
    署名付き URL で返す（生成サービスが `GET /template/{key}` を実装している場合）。"""
    err, _uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    theme = generate.get_theme(theme_id)
    if theme is None:
        return JSONResponse(status_code=404, content={"error": "テーマが見つかりません。"})
    base_url = generate.theme_base_url(theme)
    if not base_url:
        return JSONResponse(
            status_code=503, content={"error": "このテーマの生成 API が未設定です。"}
        )
    if not objstore.is_configured():
        return JSONResponse(status_code=503, content={"error": "ストレージが未設定です。"})
    try:
        data, filename, ctype = await generate.fetch_template(
            input_key, base_url=base_url, api_key=generate.theme_api_key(theme)
        )
    except generate.GenerateError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    safe_theme = "".join(c for c in theme_id if c.isalnum() or c in "-_") or "theme"
    safe_key = "".join(c for c in input_key if c.isalnum() or c in "-_") or "input"
    obj_key = "/".join([objstore.EDITOR_S3_PREFIX, "_templates", f"{safe_theme}-{safe_key}.xlsx"])
    if not objstore.put_bytes(obj_key, data, content_type=ctype):
        return JSONResponse(status_code=502, content={"error": "様式の保存に失敗しました。"})
    url = objstore.presign_get(obj_key, filename=filename, expiry=3600)
    return JSONResponse(content={"download_url": url, "download_filename": filename})


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


# --- generation（Excel → 章別 Markdown 生成） ---------------------------------

# 生成結果 zip から取り込まない内部ファイル（テンプレのメタ情報等）。
# template_data.json は書き出し時の Excel 生成（見積総括表の nextyear/phaselist）に使うため、
# ファイルとして取り込まず gen_params として保存する。
_SKIP_IMPORT_NAMES = {
    ".keep",
    "hidden_template_data.json",
    ".gitkeep",
    "sections.json",
    "template_data.json",
}


def _parse_gen_params(zf: zipfile.ZipFile, prefix: str) -> dict[str, Any] | None:
    """生成結果 zip の `template_data.json` を読み、書き出し用パラメータを返す。"""
    for name in zf.namelist():
        inner = name[len(prefix):] if prefix and name.startswith(prefix) else name
        if inner.rsplit("/", 1)[-1] != "template_data.json":
            continue
        try:
            data = json.loads(zf.read(name).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
        return data if isinstance(data, dict) else None
    return None


def _strip_common_prefix(names: list[str]) -> str:
    """zip 内エントリが単一トップレベルフォルダ配下なら、その接頭辞を返す。"""
    tops = {n.split("/", 1)[0] for n in names if "/" in n}
    files_at_root = any("/" not in n for n in names)
    if not files_at_root and len(tops) == 1:
        return next(iter(tops)) + "/"
    return ""


def _parse_sections_manifest(zf: zipfile.ZipFile, prefix: str) -> dict[str, str]:
    """生成結果 zip の `sections.json` を読み、ファイル名 → section key の対応を返す。

    合成定義がファイル名の変更に強くなるよう、取り込み時に各ファイルへ安定 ID
    （section key）を付与するために用いる。
    """
    mapping: dict[str, str] = {}
    for name in zf.namelist():
        inner = name[len(prefix):] if prefix and name.startswith(prefix) else name
        if inner.rsplit("/", 1)[-1] != "sections.json":
            continue
        try:
            manifest = json.loads(zf.read(name).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return mapping
        for sec in manifest.get("sections", []) if isinstance(manifest, dict) else []:
            if not isinstance(sec, dict):
                continue
            fname = str(sec.get("file") or "").strip()
            key = str(sec.get("section_key") or "").strip()
            if fname and key:
                mapping[fname] = key
                mapping[fname.rsplit("/", 1)[-1]] = key
        break
    return mapping


def _import_zip_to_project(zip_bytes: bytes, project_id: str, uid: str) -> list[str]:
    """生成結果 zip を展開し、案件フォルダへ取り込む（取り込んだ相対パス一覧を返す）。"""
    imported: list[str] = []
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
        prefix = _strip_common_prefix(names)
        section_map = _parse_sections_manifest(zf, prefix)
        gen_params = _parse_gen_params(zf, prefix)
        if gen_params:
            store.save_gen_params(project_id, uid, gen_params)
        for name in names:
            inner = name[len(prefix):] if prefix and name.startswith(prefix) else name
            base = inner.rsplit("/", 1)[-1]
            if not base or base in _SKIP_IMPORT_NAMES or base.startswith("."):
                continue
            rel = _clean_rel_path(inner)
            if rel is None:
                continue
            data = zf.read(name)
            if len(data) > MAX_UPLOAD_BYTES:
                continue
            kind = _kind_of(rel)
            existing = store.get_file(project_id, uid, rel)
            s3_key = (
                existing["s3_key"] if existing else store.build_s3_key(uid, project_id, rel)
            )
            content_type = (
                "text/markdown; charset=utf-8" if kind in TEXT_KINDS else None
            )
            if not objstore.put_bytes(s3_key, data, content_type=content_type):
                continue
            section_key = section_map.get(rel) or section_map.get(base) or ""
            store.upsert_file(
                project_id,
                uid,
                rel,
                kind=kind,
                size=len(data),
                s3_key=s3_key,
                section_key=section_key,
            )
            imported.append(rel)
    return imported


def _decode_theme_inputs(
    theme: dict[str, Any], payload: dict[str, Any]
) -> tuple[dict[str, bytes] | None, JSONResponse | None]:
    """テーマ定義に従って入力ファイル群を復号・様式検証する。

    入力は `inputs` マップ（key → base64）で受け取る。後方互換として、旧形式の
    トップレベル `<key>_b64`（例: `systemplan_b64`）も参照する。
    """
    raw_inputs = payload.get("inputs") if isinstance(payload.get("inputs"), dict) else {}
    files: dict[str, bytes] = {}
    for spec in theme.get("inputs", []):
        key = spec.get("key")
        if not key:
            continue
        b64 = raw_inputs.get(key) or payload.get(f"{key}_b64") or ""
        try:
            data = excel.decode_upload(str(b64), max_bytes=MAX_UPLOAD_BYTES)
        except excel.ExcelError as e:
            label = spec.get("label", key)
            return None, JSONResponse(
                status_code=400, content={"error": f"「{label}」: {e}"}
            )
        marker = spec.get("marker")
        if marker:
            try:
                excel.validate_type(data, str(marker))
            except excel.ExcelError as e:
                return None, JSONResponse(status_code=400, content={"error": str(e)})
        files[key] = data
    if not files:
        return None, JSONResponse(
            status_code=400, content={"error": "入力ファイルが指定されていません。"}
        )
    return files, None


@app.post("/projects/{project_id}/generate")
async def generate_from_excel(
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
    """テーマ（例: 調達仕様書）ごとのヒアリングシートから章別 Markdown 生成を開始する。"""
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    theme = generate.get_theme(str(payload.get("theme") or "").strip() or None)
    if theme is None:
        return JSONResponse(status_code=400, content={"error": "不明なテーマです。"})
    base_url = generate.theme_base_url(theme)
    if not base_url:
        return JSONResponse(
            status_code=503,
            content={"error": "このテーマの文書生成 API が未設定です（管理者に確認してください）。"},
        )
    files, ferr = _decode_theme_inputs(theme, payload)
    if ferr:
        return ferr
    doc_type = str(payload.get("doc_type") or "").strip() or theme.get("doc_type")
    options = payload.get("options") if isinstance(payload.get("options"), dict) else None
    try:
        result = await generate.start_generation(
            files,  # type: ignore[arg-type]
            base_url=base_url,
            api_key=generate.theme_api_key(theme),
            username=uid,
            doc_type=doc_type,
            options=options,
        )
    except generate.GenerateError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    request_id = str(result.get("request_id") or "").strip()
    if not request_id:
        return JSONResponse(
            status_code=502, content={"error": "生成 API から request_id が返りませんでした。"}
        )
    store.create_generation(
        request_id,
        project_id,
        uid,
        theme=str(theme.get("id") or ""),
        doc_type=str(doc_type or generate.DEFAULT_DOC_TYPE),
    )
    return JSONResponse(content={"request_id": request_id, "status": "processing"})


@app.get("/projects/{project_id}/generations/{request_id}")
async def generation_status(
    project_id: str,
    request_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """生成ステータスを確認し、成功していれば結果 zip を案件フォルダへ取り込む。"""
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    gen = store.get_generation(request_id, project_id, uid)
    if gen is None:
        return JSONResponse(status_code=404, content={"error": "生成ジョブが見つかりません。"})
    # 既に取り込み済みなら、その結果をそのまま返す（多重取り込みを防ぐ）。
    if gen["imported"]:
        return JSONResponse(
            content={
                "status": "success",
                "imported": True,
                "files": gen["imported_paths"],
            }
        )
    # ジョブ開始時のテーマから API 接続先を解決する。
    theme = generate.get_theme(gen.get("theme"))
    base_url = generate.theme_base_url(theme) if theme else generate.EDITOR_GENERATE_URL
    api_key = generate.theme_api_key(theme) if theme else generate.EDITOR_GENERATE_API_KEY
    try:
        status = await generate.get_status(request_id, base_url=base_url, api_key=api_key)
    except generate.GenerateError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    state = str(status.get("status") or "").lower()
    if state == "error":
        store.update_generation(
            request_id, uid, status="error", error=str(status.get("error") or "")
        )
        return JSONResponse(
            content={"status": "error", "error": status.get("error") or "生成に失敗しました。"}
        )
    if state != "success":
        return JSONResponse(
            content={"status": "processing", "progress": status.get("progress")}
        )
    # 成功 → 結果 zip を取り込む。
    if not objstore.is_configured():
        return JSONResponse(status_code=503, content={"error": "ストレージが未設定です。"})
    try:
        zip_bytes = await generate.fetch_result(request_id, base_url=base_url, api_key=api_key)
        imported = _import_zip_to_project(zip_bytes, project_id, uid)
    except generate.GenerateError as e:
        return JSONResponse(status_code=502, content={"error": str(e)})
    except zipfile.BadZipFile:
        return JSONResponse(status_code=502, content={"error": "生成結果の展開に失敗しました。"})
    store.update_generation(
        request_id, uid, status="success", imported=True, imported_paths=imported
    )
    return JSONResponse(content={"status": "success", "imported": True, "files": imported})


# --- composition（出力ファイルの合成定義 + Word 合成実行） --------------------


def _resolve_theme_for_project(
    project_id: str, uid: str, *, hint: str | None = None, saved: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """プロジェクトの合成に用いるテーマを解決する。

    優先順: 明示指定(hint) → 保存済み定義のテーマ → 直近生成ジョブのテーマ → 先頭テーマ。
    """
    theme_id = (
        (hint or "").strip()
        or (str(saved.get("theme")) if isinstance(saved, dict) and saved.get("theme") else "")
        or (store.latest_generation_theme(project_id, uid) or "")
    )
    return generate.get_theme(theme_id or None)


def _default_composition(theme: dict[str, Any]) -> dict[str, Any]:
    """テーマ既定から合成定義（出力ファイル毎の順序付き section）を作る。"""
    outputs = []
    for o in generate.theme_outputs(theme):
        entry: dict[str, Any] = {
            "id": o["id"],
            "name": o["name"],
            "kind": o.get("kind", "markdown"),
            "enabled": True,
            "items": [{"section_key": k} for k in o.get("sections", [])],
        }
        if o.get("builder"):
            entry["builder"] = o["builder"]
        outputs.append(entry)
    return {"theme": theme.get("id"), "outputs": outputs}


def _normalize_composition(data: Any, theme: dict[str, Any]) -> dict[str, Any]:
    """保存/入力された合成定義を安全な形へ整える。"""
    if not isinstance(data, dict):
        return _default_composition(theme)
    raw_outputs = data.get("outputs")
    if not isinstance(raw_outputs, list):
        return _default_composition(theme)
    outputs: list[dict[str, Any]] = []
    for i, o in enumerate(raw_outputs, start=1):
        if not isinstance(o, dict):
            continue
        items: list[dict[str, Any]] = []
        for it in o.get("items", []) or []:
            if not isinstance(it, dict):
                continue
            sk = str(it.get("section_key") or "").strip()
            fid = str(it.get("file_id") or "").strip()
            if not sk and not fid:
                continue
            entry: dict[str, Any] = {}
            if sk:
                entry["section_key"] = sk
            if fid:
                entry["file_id"] = fid
            items.append(entry)
        entry = {
            "id": str(o.get("id") or f"output{i}"),
            "name": str(o.get("name") or f"output{i}"),
            "kind": "excel" if str(o.get("kind") or "") == "excel" else "markdown",
            "enabled": o.get("enabled", True) is not False,
            "items": items,
        }
        if o.get("builder"):
            entry["builder"] = str(o.get("builder"))
        outputs.append(entry)
    return {"theme": str(data.get("theme") or theme.get("id") or ""), "outputs": outputs}


@app.get("/projects/{project_id}/composition")
async def get_composition(
    project_id: str,
    theme: str | None = None,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """プロジェクトの合成定義（保存済み or テーマ既定）と、参照可能なファイル一覧を返す。"""
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    saved = store.get_composition(project_id, uid)
    theme_def = _resolve_theme_for_project(project_id, uid, hint=theme, saved=saved)
    if theme_def is None:
        return JSONResponse(status_code=400, content={"error": "テーマが未設定です。"})
    if saved:
        composition = _normalize_composition(saved, theme_def)
        is_saved = True
    else:
        composition = _default_composition(theme_def)
        is_saved = False
    files = [
        {
            "id": f["id"],
            "rel_path": f["rel_path"],
            "kind": f["kind"],
            "section_key": f.get("section_key", ""),
        }
        for f in store.list_files(project_id, uid)
        if f["kind"] != "keep"
    ]
    theme_public = {
        "id": theme_def.get("id"),
        "label": theme_def.get("label", theme_def.get("id")),
        "doc_type": theme_def.get("doc_type", generate.DEFAULT_DOC_TYPE),
        "sections": generate.theme_sections(theme_def),
        "outputs": generate.theme_outputs(theme_def),
        "configured": bool(generate.theme_base_url(theme_def)),
    }
    return JSONResponse(
        content={
            "theme": theme_public,
            "saved": is_saved,
            "composition": composition,
            "files": files,
        }
    )


@app.put("/projects/{project_id}/composition")
async def put_composition(
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
    """プロジェクトの合成定義を保存（上書き）する。"""
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if store.get_project(project_id, uid) is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    theme_def = _resolve_theme_for_project(
        project_id, uid, hint=str(payload.get("theme") or "")
    )
    if theme_def is None:
        return JSONResponse(status_code=400, content={"error": "テーマが未設定です。"})
    composition = _normalize_composition(payload.get("composition") or payload, theme_def)
    store.save_composition(project_id, uid, composition)
    return JSONResponse(content={"saved": True, "composition": composition})


# Markdown 本文中の画像参照 `![alt](path)` を抽出する（http/https/data: は除外）。
_IMAGE_REF_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def _extract_image_refs(content: str) -> list[str]:
    refs: list[str] = []
    for m in _IMAGE_REF_RE.finditer(content or ""):
        p = (m.group(1) or "").strip()
        if not p or "://" in p or p.startswith("data:") or p.startswith("#"):
            continue
        refs.append(p.lstrip("/"))
    return refs


def _collect_output_sections(
    output: dict[str, Any], files_by_key: dict[str, dict[str, Any]],
    files_by_id: dict[str, dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """合成定義の 1 出力について、順序通りに {filename, content} を集約する。

    overrides（{file_id: content}）が与えられた場合は S3 の内容より優先する
    （クライアントが Mermaid ブロックを画像参照へ差し替えた本文など）。
    """
    overrides = overrides or {}
    sections: list[dict[str, str]] = []
    for it in output.get("items", []) or []:
        if not isinstance(it, dict):
            continue
        f: dict[str, Any] | None = None
        sk = str(it.get("section_key") or "").strip()
        fid = str(it.get("file_id") or "").strip()
        if sk:
            f = files_by_key.get(sk)
        if f is None and fid:
            f = files_by_id.get(fid)
        if f is None:
            continue
        ov = overrides.get(f["id"])
        if isinstance(ov, str):
            content = ov
        else:
            data = objstore.get_bytes(f["s3_key"])
            if data is None:
                continue
            try:
                content = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
        sections.append({"filename": f["rel_path"].rsplit("/", 1)[-1], "content": content})
    return sections


@app.post("/projects/{project_id}/compose")
async def compose_project(
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
    """合成定義に従い各出力の本文を順に集約し、生成サービスの /compose で Word 化する。"""
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    project = store.get_project(project_id, uid)
    if project is None:
        return JSONResponse(status_code=404, content={"error": "プロジェクトが見つかりません。"})
    if not objstore.is_configured():
        return JSONResponse(status_code=503, content={"error": "ストレージが未設定です。"})
    saved = store.get_composition(project_id, uid)
    # body の composition を優先（未指定なら保存済み → テーマ既定）。
    body_comp = payload.get("composition")
    theme_def = _resolve_theme_for_project(
        project_id, uid, hint=str(payload.get("theme") or ""), saved=body_comp or saved
    )
    if theme_def is None:
        return JSONResponse(status_code=400, content={"error": "テーマが未設定です。"})
    # base_url は Markdown→Word 合成のときのみ必須（Excel のみの出力なら不要）。
    base_url = generate.theme_base_url(theme_def)
    if body_comp is not None:
        composition = _normalize_composition(body_comp, theme_def)
    elif saved:
        composition = _normalize_composition(saved, theme_def)
    else:
        composition = _default_composition(theme_def)

    files = store.list_files(project_id, uid)
    files_by_key: dict[str, dict[str, Any]] = {}
    for f in files:
        sk = f.get("section_key")
        if sk and sk not in files_by_key:
            files_by_key[sk] = f
    files_by_id = {f["id"]: f for f in files}
    files_by_rel = {f["rel_path"]: f for f in files}
    # 本文が指定するファイル内容の差し替え（クライアントが Mermaid→画像化した結果など）。
    overrides = payload.get("overrides")
    overrides = overrides if isinstance(overrides, dict) else {}

    # 書き出し時の Excel 生成に使う「現時点の（編集済み）章本文」を集める（section key→本文）。
    section_contents: dict[str, str] = {}
    for sk, f in files_by_key.items():
        if f.get("kind") != "markdown":
            continue
        data = objstore.get_bytes(f["s3_key"])
        if data is None:
            continue
        try:
            section_contents[sk] = data.decode("utf-8")
        except UnicodeDecodeError:
            continue

    # テーマ既定から出力 id → builder を引けるようにする（builder はテーマ属性）。
    theme_builder_by_id = {
        o["id"]: o.get("builder") for o in generate.theme_outputs(theme_def) if o.get("builder")
    }

    # 出力を Markdown（Word 合成）と Excel（書き出し時に生成）に振り分ける。
    md_outputs: list[dict[str, Any]] = []
    excel_outputs: list[tuple[str, str]] = []  # (name, builder)
    excel_files: list[tuple[str, bytes]] = []
    included_names: list[str] = []
    skipped: list[dict[str, str]] = []
    used_names: set[str] = set()

    def _unique_arcname(base: str, ext: str) -> str:
        # zip 内のファイル名は日本語を保持（パス区切り・禁止文字のみ除去）。
        safe = "".join(c for c in (base or "") if c not in '\\/:*?"<>|' and ord(c) >= 32).strip()
        safe = safe or "output"
        name = f"{safe}.{ext}"
        i = 2
        while name in used_names:
            name = f"{safe}({i}).{ext}"
            i += 1
        used_names.add(name)
        return name

    for o in composition.get("outputs", []):
        if o.get("enabled") is False:
            continue
        name = str(o.get("name") or o.get("id") or "output")
        if str(o.get("kind") or "") == "excel":
            builder = str(o.get("builder") or theme_builder_by_id.get(o.get("id")) or "").strip()
            if not builder:
                skipped.append({"name": name, "reason": "生成方法（builder）が未設定です。"})
                continue
            excel_outputs.append((name, builder))
        else:
            sections = _collect_output_sections(o, files_by_key, files_by_id, overrides)
            if not sections:
                continue
            md_outputs.append({"name": name, "sections": sections})
            included_names.append(name)

    # Markdown 本文が参照する画像を集約し、生成サービスへ同送する（Word へ埋め込むため）。
    assets: dict[str, bytes] = {}
    for o in md_outputs:
        for sec in o["sections"]:
            for rel in _extract_image_refs(sec.get("content", "")):
                if rel in assets:
                    continue
                f = files_by_rel.get(rel)
                if f is None:
                    continue
                data = objstore.get_bytes(f["s3_key"])
                if data is not None:
                    assets[rel] = data

    if not md_outputs and not excel_outputs:
        return JSONResponse(
            status_code=400,
            content={"error": "出力できる内容がありません（章の設定や生成状況を確認してください）。"},
        )

    # Markdown・Excel いずれの出力も生成サービス（spec-app）を使うため base_url が必須。
    if (md_outputs or excel_outputs) and not base_url:
        return JSONResponse(
            status_code=503,
            content={"error": "このテーマの生成 API が未設定です（管理者に確認してください）。"},
        )
    api_key = generate.theme_api_key(theme_def)

    # Markdown 出力は生成サービスへ送って Word(.docx) 化する。
    docx_zip: bytes | None = None
    if md_outputs:
        try:
            docx_zip = await generate.compose(
                md_outputs,
                base_url=base_url,
                api_key=api_key,
                reference=str(theme_def.get("doc_type") or ""),
                assets=assets or None,
            )
        except generate.GenerateError as e:
            return JSONResponse(status_code=502, content={"error": str(e)})

    # Excel 出力は、その時点の章本文＋保存パラメータから書き出し時に生成する。
    if excel_outputs:
        params = store.get_gen_params(project_id, uid)
        params = dict(params) if isinstance(params, dict) else {}
        params.setdefault("username", uid)
        for name, builder in excel_outputs:
            try:
                data = await generate.build_excel(
                    builder,
                    base_url=base_url,
                    api_key=api_key,
                    params=params,
                    sections=section_contents,
                )
            except generate.ExcelSkip as e:
                skipped.append({"name": name, "reason": str(e)})
                continue
            except generate.GenerateError as e:
                return JSONResponse(status_code=502, content={"error": f"{name}: {e}"})
            excel_files.append((_unique_arcname(name, "xlsx"), data))
            included_names.append(name)

    if not md_outputs and not excel_files:
        # 例: 一次審査表のみ指定したが対象章が無かった等。
        detail = "; ".join(f"{s['name']}: {s['reason']}" for s in skipped) or "対象がありません。"
        return JSONResponse(
            status_code=400,
            content={"error": f"出力できる内容がありません（{detail}）。"},
        )

    # docx（合成結果）と Excel（生成物）を 1 つの zip にまとめる。
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if docx_zip:
            try:
                with zipfile.ZipFile(io.BytesIO(docx_zip)) as dz:
                    for n in dz.namelist():
                        if n.endswith("/"):
                            continue
                        arc = n.rsplit("/", 1)[-1]
                        if arc in used_names:
                            continue
                        used_names.add(arc)
                        zf.writestr(arc, dz.read(n))
            except zipfile.BadZipFile:
                return JSONResponse(
                    status_code=502, content={"error": "Word 合成結果の展開に失敗しました。"}
                )
        for arc, data in excel_files:
            zf.writestr(arc, data)

    project_name = objstore.sanitize_filename(project["name"]) or "project"
    key = "/".join([objstore.EDITOR_S3_PREFIX, "_exports", f"compose-{uuid.uuid4().hex}.zip"])
    if not objstore.put_bytes(key, buf.getvalue(), content_type="application/zip"):
        return JSONResponse(status_code=502, content={"error": "合成結果の保存に失敗しました。"})
    download_filename = f"{project_name}-output.zip"
    url = objstore.presign_get(key, filename=download_filename, expiry=3600)
    return JSONResponse(
        content={
            "status": "success",
            "download_url": url,
            "download_filename": download_filename,
            "outputs": included_names,
            "skipped": skipped,
        }
    )
