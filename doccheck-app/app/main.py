"""書類領域分割チェック マイクロサービス。

- 庁内: backend が JWT 検証後、HMAC 署名付きでプロキシ
- 外部: 別ホストの公開プロキシが /public/* のみ upstream

Compose では profiles: ["doccheck"] でオプション起動する。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import intauth, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
PUBLIC_ENDPOINT = (os.environ.get("DOCCHECK_PUBLIC_ENDPOINT") or "").rstrip("/")
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

app = FastAPI(title="Open GENAI Doccheck App", version="0.1.0")


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
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
    )


def _group_set(x_user_groups: str | None) -> set[str]:
    return {g.strip() for g in (x_user_groups or "").split(",") if g.strip()}


def _can_arbitrate(x_user_groups: str | None) -> bool:
    """裁定はシステム管理者またはチーム管理者のみ。"""
    groups = _group_set(x_user_groups)
    return "SystemAdminGroup" in groups or "TeamAdminGroup" in groups


def _forbid_arbitrate() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "error": "裁定はチーム管理者またはシステム管理者のみ実行できます",
            "can_arbitrate": False,
        },
    )


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
    st = store.stats()
    return JSONResponse(
        {
            "enabled": True,
            "public_endpoint": PUBLIC_ENDPOINT or st.get("public_endpoint"),
            "can_arbitrate": _can_arbitrate(x_user_groups),
            **st,
        }
    )


@app.post("/demo/seed")
async def demo_seed(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """同梱デモ帳票を投入（既定で配信まで）。PoC 検証用。"""
    err, uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    dispatch = body.get("dispatch", True)
    if not isinstance(dispatch, bool):
        dispatch = True
    assignees = body.get("assignees")
    try:
        assignees_n = int(assignees) if assignees is not None else None
    except (TypeError, ValueError):
        assignees_n = None
    try:
        doc = store.seed_demo_document(
            created_by=uid, dispatch=dispatch, assignees=assignees_n
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": f"デモ投入に失敗: {e}"})
    return JSONResponse(doc)


@app.get("/stats")
def get_stats(
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
    return JSONResponse(store.stats())


# ----- templates -----


@app.get("/templates")
def list_templates(
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
    return JSONResponse({"templates": store.list_templates()})


@app.post("/templates")
async def create_template(
    request: Request,
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
    body = await request.json()
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": "name は必須です"})
    try:
        tmpl = store.create_template(
            name=name,
            description=body.get("description"),
            created_by=uid,
            regions=body.get("regions"),
            ocr_mode=body.get("ocr_mode"),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return JSONResponse(tmpl)


@app.put("/templates/{template_id}")
async def update_template(
    template_id: str,
    request: Request,
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
    body = await request.json()
    tmpl = store.update_template_meta(
        template_id, ocr_mode=body.get("ocr_mode")
    )
    if not tmpl:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse(tmpl)


@app.get("/templates/{template_id}")
def get_template(
    template_id: str,
    include_sample: bool = False,
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
    tmpl = store.get_template(template_id, include_sample=include_sample)
    if not tmpl:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse(tmpl)


@app.post("/templates/{template_id}/sample")
async def upload_sample(
    template_id: str,
    request: Request,
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
    body = await request.json()
    data = body.get("data") or body.get("image")
    if not data or not isinstance(data, str):
        return JSONResponse(
            status_code=400, content={"error": "data（base64 画像）が必要です"}
        )
    try:
        return JSONResponse(store.set_sample_image(template_id, data))
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.put("/templates/{template_id}/regions")
async def put_regions(
    template_id: str,
    request: Request,
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
    body = await request.json()
    regions = body.get("regions")
    if not isinstance(regions, list):
        return JSONResponse(status_code=400, content={"error": "regions 配列が必要です"})
    try:
        tmpl = store.replace_regions(template_id, regions)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    if not tmpl:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse(tmpl)


@app.delete("/templates/{template_id}")
def delete_template(
    template_id: str,
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
    try:
        return JSONResponse(store.delete_template(template_id))
    except ValueError as e:
        msg = str(e)
        code = 404 if "見つかりません" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})


# ----- documents -----


@app.get("/documents")
def list_documents(
    request: Request,
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
    batch_id = request.query_params.get("batch_id")
    return JSONResponse({"documents": store.list_documents(batch_id=batch_id)})


@app.post("/documents")
async def create_document(
    request: Request,
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
    body = await request.json()
    template_id = (body.get("template_id") or "").strip()
    title = (body.get("title") or "").strip() or "無題の書類"
    pages = body.get("pages") or body.get("images") or []
    if not template_id:
        return JSONResponse(status_code=400, content={"error": "template_id は必須です"})
    if not isinstance(pages, list) or not pages:
        return JSONResponse(
            status_code=400,
            content={"error": "pages（base64 画像の配列）が必要です"},
        )
    try:
        doc = store.create_document_from_images(
            template_id=template_id,
            title=title,
            created_by=uid,
            pages_b64=pages,
            dpi=None,
        )
        # 読み取りテスト: 投入後にソロ割当で自動配信（DOCCHECK_SINGLE_ASSIGNEES）
        auto_dispatch = body.get("auto_dispatch")
        if auto_dispatch is None:
            auto_dispatch = True
        if auto_dispatch:
            assignees = body.get("assignees")
            if assignees is None:
                assignees = store.SINGLE_ASSIGNEES
            doc = store.dispatch_document(doc["id"], assignees=int(assignees))
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": f"処理に失敗しました: {e}"})
    return JSONResponse(doc)


@app.get("/documents/{doc_id}")
def get_document(
    doc_id: str,
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
    doc = store.get_document(doc_id)
    if not doc:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse(doc)


@app.post("/documents/{doc_id}/dispatch")
async def dispatch_document(
    doc_id: str,
    request: Request,
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
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    try:
        doc = store.dispatch_document(doc_id, assignees=body.get("assignees"))
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return JSONResponse(doc)


@app.delete("/documents/{doc_id}")
def delete_document(
    doc_id: str,
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
    try:
        return JSONResponse(store.delete_document(doc_id))
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


# ----- batches -----


@app.get("/batches")
def list_batches(
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
    return JSONResponse({"batches": store.list_batches()})


@app.post("/batches")
async def create_batch(
    request: Request,
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
    body = await request.json()
    template_id = (body.get("template_id") or "").strip()
    images = body.get("images") or []
    if not template_id:
        return JSONResponse(status_code=400, content={"error": "template_id は必須です"})
    if not isinstance(images, list) or not images:
        return JSONResponse(
            status_code=400,
            content={"error": "images（[{data, name}, ...]）が必要です"},
        )
    # data-url 文字列だけの配列も許容
    norm_images: list[dict[str, Any]] = []
    for i, img in enumerate(images):
        if isinstance(img, str):
            norm_images.append({"data": img, "name": f"scan_{i + 1:04d}.png"})
        elif isinstance(img, dict) and img.get("data"):
            norm_images.append(
                {
                    "data": img["data"],
                    "name": img.get("name") or f"scan_{i + 1:04d}.png",
                }
            )
        else:
            return JSONResponse(
                status_code=400, content={"error": f"images[{i}] の形式が不正です"}
            )
    try:
        # バッチは本番想定の割当（未指定時 DOCCHECK_ASSIGNEES=3）。dpi は正規化時に決定。
        batch = store.create_batch(
            name=(body.get("name") or "").strip(),
            template_id=template_id,
            created_by=uid,
            images=norm_images,
            pages_per_document=int(body.get("pages_per_document") or 1),
            auto_dispatch=bool(body.get("auto_dispatch", True)),
            assignees=body.get("assignees"),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": f"バッチ作成に失敗: {e}"})
    return JSONResponse(batch)


@app.get("/batches/{batch_id}")
def get_batch(
    batch_id: str,
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
    batch = store.get_batch(batch_id)
    if not batch:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse(batch)


@app.post("/batches/{batch_id}/dispatch")
async def dispatch_batch(
    batch_id: str,
    request: Request,
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
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    try:
        return JSONResponse(
            store.dispatch_batch(batch_id, assignees=body.get("assignees"))
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.delete("/batches/{batch_id}")
def delete_batch(
    batch_id: str,
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
    try:
        return JSONResponse(store.delete_batch(batch_id))
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@app.get("/batches/{batch_id}/export")
def export_batch(
    batch_id: str,
    request: Request,
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
    fmt = request.query_params.get("format") or "csv"
    status_filter = request.query_params.get("status") or "completed"
    try:
        return JSONResponse(
            store.export_batch(
                batch_id, format=fmt, status_filter=status_filter
            )
        )
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


@app.get("/documents/{doc_id}/export")
def export_document(
    doc_id: str,
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
    try:
        return JSONResponse(store.export_document(doc_id))
    except ValueError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})


# ----- queue / check / arbitration / scores -----


@app.get("/queue/next")
def queue_next(
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
    task = store.claim_internal_task(uid)
    if not task:
        return JSONResponse({"task": None, "message": "未処理のタスクはありません"})
    return JSONResponse({"task": task})


@app.post("/tasks/{token}/answer")
async def answer_internal(
    token: str,
    request: Request,
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
    body = await request.json()
    try:
        result = store.submit_answer(
            token,
            answer_text=body.get("answer_text") or "",
            tier="internal",
            checker_user_id=uid,
            checker_label=body.get("checker_label"),
            is_unreadable=bool(body.get("is_unreadable")),
            is_blank=bool(body.get("is_blank")),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return JSONResponse(result)


@app.get("/regions/{region_id}/image")
def region_image(
    region_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Response:
    err, _uid = _auth(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    data = store.crop_bytes_for_region(region_id)
    if not data:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return Response(content=data, media_type="image/png")


@app.get("/arbitration")
def list_arbitration(
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
    if not _can_arbitrate(x_user_groups):
        return _forbid_arbitrate()
    return JSONResponse({"items": store.list_arbitration()})


@app.post("/arbitration/{region_id}")
async def post_arbitration(
    region_id: str,
    request: Request,
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
    if not _can_arbitrate(x_user_groups):
        return _forbid_arbitrate()
    body = await request.json()
    is_blank = bool(body.get("is_blank"))
    text = (body.get("adopted_text") or "").strip()
    if not text and not is_blank:
        return JSONResponse(status_code=400, content={"error": "adopted_text は必須です"})
    try:
        return JSONResponse(
            store.arbitrate(
                region_id,
                adopted_text="" if is_blank else text,
                arbiter_user_id=uid,
            )
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})


@app.get("/scores/me")
def score_me(
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
    return JSONResponse(store.get_score(uid))


@app.get("/scores/leaderboard")
def score_leaderboard(
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
    return JSONResponse({"leaderboard": store.leaderboard()})


# ----- public -----


@app.get("/public", response_model=None)
@app.get("/public/", response_model=None)
def public_index() -> HTMLResponse:
    return HTMLResponse(
        """<!DOCTYPE html><html lang="ja"><head><meta charset="utf-8"/>
<title>書類読取とチェック</title>
<link rel="stylesheet" href="/public/assets/style.css"/>
</head><body><div class="wrap">
<div class="brand">Open GENAI · 書類読取とチェック</div>
<p>チェック用のリンク（トークン付き URL）からアクセスしてください。</p>
<p>同一端末では、すでに回答した項目は再配布されません。</p>
<p><a class="btn" href="#" id="claim">次のチェックを始める</a></p>
</div>
<script>
const KEY = 'doccheck_guest_checker_v1';
function checkerKey() {
  let k = localStorage.getItem(KEY);
  if (!k) {
    k = (crypto.randomUUID && crypto.randomUUID()) || ('g-' + Date.now());
    localStorage.setItem(KEY, k);
  }
  return k;
}
document.getElementById('claim').addEventListener('click', async (e) => {
  e.preventDefault();
  const r = await fetch('/public/api/claim', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({checker_key: checkerKey()})
  });
  const j = await r.json();
  if (j.token) location.href = '/public/c/' + j.token;
  else alert(j.error || 'ただいまチェック可能な項目がありません');
});
</script></body></html>"""
    )


@app.get("/public/c/{token}", response_model=None)
def public_check_page(token: str) -> FileResponse | HTMLResponse:
    path = PUBLIC_DIR / "check.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return HTMLResponse("<p>check.html がありません</p>", status_code=500)


@app.get("/public/api/task/{token}")
def public_get_task(token: str) -> JSONResponse:
    task = store.get_task_payload(token, include_internal=False)
    if not task:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return JSONResponse(task)


@app.get("/public/api/image/{token}")
def public_image(token: str) -> Response:
    data = store.crop_bytes_for_token(token)
    if not data:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return Response(
        content=data,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@app.post("/public/api/task/{token}/answer")
async def public_answer(token: str, request: Request) -> JSONResponse:
    body = await request.json()
    try:
        result = store.submit_answer(
            token,
            answer_text=body.get("answer_text") or "",
            tier="external",
            checker_user_id=None,
            checker_label=body.get("checker_label"),
            checker_key=body.get("checker_key"),
            is_unreadable=bool(body.get("is_unreadable")),
            is_blank=bool(body.get("is_blank")),
        )
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    return JSONResponse(result)


@app.post("/public/api/claim")
async def public_claim(request: Request) -> JSONResponse:
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    task = store.claim_public_task(checker_key=body.get("checker_key"))
    if not task:
        return JSONResponse(
            status_code=404,
            content={
                "error": (
                    "ただいまチェック可能な項目がありません"
                    "（未回答の項目がないか、同一端末で回答済みの可能性があります）"
                )
            },
        )
    return JSONResponse({"token": task["token"], "task": task})


if PUBLIC_DIR.is_dir():
    app.mount(
        "/public/assets", StaticFiles(directory=str(PUBLIC_DIR)), name="public-assets"
    )
