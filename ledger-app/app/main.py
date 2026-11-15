"""汎用台帳。庁内の backend が HMAC 付きでプロキシする。"""

from __future__ import annotations

import base64
import binascii
import os
from typing import Any

from fastapi import FastAPI, File, Header, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from . import assist, ingest, io, intauth, material, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
SERVICE_KEY = os.environ.get("LEDGER_SERVICE_KEY", "")

app = FastAPI(title="Open GENAI Ledger", version="0.1.0")


@app.on_event("startup")
def on_startup() -> None:
    store.connect()
    store.maybe_import()


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    if SERVICE_KEY:
        return None
    return None


def _actor(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
    x_service_key: str | None = None,
) -> tuple[JSONResponse | None, store.Actor]:
    err = _check_key(x_api_key)
    if err:
        return err, store.Actor("")
    if SERVICE_KEY and x_service_key != SERVICE_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), store.Actor("")
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"}), store.Actor("")
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), store.Actor("")
    groups = [item.strip() for item in (x_user_groups or "").split(",") if item.strip()]
    teams = [item.strip() for item in (x_user_tags or "").split(",") if item.strip()]
    return None, store.Actor(
        user_id=x_user_id,
        groups=groups,
        team_ids=teams,
        tenant_id=(x_scope or "").strip(),
        is_admin="SystemAdminGroup" in groups,
    )


def _fail(message: str | None, status: int = 400) -> JSONResponse:
    code = 404 if message and "見つかりません" in message else status
    if message and "権限" in message:
        code = 403
    return JSONResponse(status_code=code, content={"error": message or "失敗しました"})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/config")
def config(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(
        {
            "enabled": True,
            "tenant_id": actor.tenant_id,
            "team_ids": actor.team_ids,
            "is_admin": actor.is_admin,
            "has_tenant": actor.has_tenant(),
        }
    )


@app.get("/ledgers")
def list_ledgers(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse({"ledgers": store.list_ledgers(actor)})


@app.post("/ledgers")
async def create_ledger(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    saved, msg = store.create_ledger(actor, body if isinstance(body, dict) else {})
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(status_code=201, content=saved)


@app.post("/ledgers/{ledger_id}/delete")
def delete_ledger(
    ledger_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    saved, msg = store.delete_ledger(actor, ledger_id)
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.get("/ledgers/{ledger_id}")
def get_ledger(
    ledger_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    saved, msg = store.get_ledger(actor, ledger_id)
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.patch("/ledgers/{ledger_id}")
async def patch_ledger(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    saved, msg = store.update_ledger(actor, ledger_id, body if isinstance(body, dict) else {})
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.get("/ledgers/{ledger_id}/rows")
def list_rows(
    ledger_id: str,
    status: str = "",
    assignee: str = "",
    q: str = "",
    date_from: str = "",
    date_to: str = "",
    offset: int = 0,
    limit: int = 50,
    include_deleted: int = 0,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    saved, msg = store.list_rows(
        actor,
        ledger_id,
        status=status,
        assignee=assignee,
        q=q,
        date_from=date_from,
        date_to=date_to,
        offset=offset,
        limit=limit,
        include_deleted=bool(include_deleted),
    )
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.post("/ledgers/{ledger_id}/rows")
async def create_row(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    saved, msg = store.upsert_row(actor, ledger_id, body if isinstance(body, dict) else {})
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(status_code=201, content=saved)


@app.get("/rows/{row_id}")
def get_row(
    row_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    saved, msg = store.get_row(actor, row_id)
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.post("/rows/{row_id}")
async def update_row(
    row_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    current, msg = store.get_row(actor, row_id)
    if msg or current is None:
        return _fail(msg)
    body = await request.json()
    if not isinstance(body, dict):
        return _fail("行を読めません")
    body["business_key"] = current["business_key"]
    saved, msg = store.upsert_row(actor, current["ledger_id"], body)
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.post("/rows/{row_id}/delete")
def delete_row(
    row_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    saved, msg = store.set_deleted(actor, row_id, True)
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.post("/rows/{row_id}/restore")
def restore_row(
    row_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    saved, msg = store.set_deleted(actor, row_id, False)
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.post("/rows/{row_id}/files")
async def upload_file(
    row_id: str,
    upload: UploadFile = File(...),
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    data = await upload.read()
    saved, msg = store.add_file(
        actor,
        row_id,
        filename=upload.filename or "file",
        mime=upload.content_type or "",
        data=data,
    )
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.get("/rows/{row_id}/files/{file_id}")
def download_file(
    row_id: str,
    file_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Response:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    path, name, msg = store.file_path(actor, row_id, file_id)
    if msg or path is None:
        return _fail(msg)
    return FileResponse(path, filename=name or file_id)


@app.get("/rows/{row_id}/files/{file_id}/preview")
def preview_file(
    row_id: str,
    file_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    path, name, msg = store.file_path(actor, row_id, file_id)
    if msg or path is None:
        return _fail(msg)
    try:
        preview = material.office_preview(name or "", path.read_bytes())
    except ValueError as exc:
        return _fail(str(exc))
    if preview is None:
        return _fail("この形式は画面では表示できません")
    return JSONResponse(preview)


@app.get("/ledgers/{ledger_id}/export")
def export_ledger(
    ledger_id: str,
    format: str = "json",
    status: str = "",
    q: str = "",
    include_deleted: str = "0",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Response:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    ledger, msg = store.get_ledger(actor, ledger_id)
    if msg or ledger is None:
        return _fail(msg)
    rows: list[dict[str, Any]] = []
    offset = 0
    while offset < 5000:
        page, msg = store.list_rows(
            actor,
            ledger_id,
            status=status,
            q=q,
            include_deleted=include_deleted == "1",
            offset=offset,
            limit=200,
        )
        if msg or page is None:
            return _fail(msg)
        batch = page["rows"]
        rows.extend(batch)
        if len(batch) < 200:
            break
        offset += 200
    document = io.export_document(ledger, rows, role=ledger.get("role"))
    store._audit(store.connect(), ledger_id, actor, "書き出した", format)
    store.connect().commit()
    if format == "csv":
        return Response(io.export_csv(document), media_type="text/csv; charset=utf-8")
    if format == "jsonl":
        return Response(io.export_jsonl(document), media_type="application/x-ndjson; charset=utf-8")
    return JSONResponse(document)


@app.post("/ledgers/{ledger_id}/import")
async def import_ledger(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    ledger, msg = store.get_ledger(actor, ledger_id)
    if msg or ledger is None:
        return _fail(msg)
    body = await request.json()
    kind = str(body.get("format") or "json")
    text = str(body.get("text") or "")
    if kind == "csv":
        rows, perr = io.parse_csv_import(text, ledger)
    elif kind == "jsonl":
        rows, perr = io.parse_jsonl_import(text, ledger)
    else:
        rows, perr = io.parse_json_import(text, ledger)
    if perr or rows is None:
        return _fail(perr)
    count, uerr = io.apply_import(actor, ledger_id, rows)
    if uerr:
        return _fail(uerr)
    store._audit(store.connect(), ledger_id, actor, "読み込んだ", f"{kind}:{count}")
    store.connect().commit()
    return JSONResponse({"imported": count})


@app.post("/ledgers/{ledger_id}/promote")
async def promote(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    saved, msg = store.promote_extra(
        actor,
        ledger_id,
        label=str(body.get("label") or ""),
        field_id=str(body.get("field_id") or ""),
        field_type=str(body.get("type") or "text"),
    )
    if msg or saved is None:
        return _fail(msg)
    return JSONResponse(saved)


@app.post("/ledgers/{ledger_id}/assist/definition")
async def assist_definition(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    ledger, msg = store.get_ledger(actor, ledger_id)
    if msg or ledger is None:
        return _fail(msg)
    body = await request.json()
    samples, serr = store.sample_extras(actor, ledger_id)
    if serr or samples is None:
        return _fail(serr)
    extra_samples = body.get("samples") if isinstance(body, dict) else None
    if isinstance(extra_samples, list):
        samples = [*samples, *[item for item in extra_samples if isinstance(item, dict)]]
    note = str((body or {}).get("note") or "") if isinstance(body, dict) else ""
    existing = [str(item.get("label") or "") for item in ledger.get("fields") or []]
    fields = assist.propose_fields(samples, existing_labels=existing, note=note)
    return JSONResponse(
        {
            "fields": fields,
            "statuses": ledger.get("statuses") or [],
            "note": "保存するまで台帳は変わりません。",
        }
    )


@app.post("/ledgers/{ledger_id}/assist/material/read")
async def assist_material_read(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    ledger, msg = store.get_ledger(actor, ledger_id)
    if msg or ledger is None:
        return _fail(msg)
    if ledger.get("role") != "admin":
        return _fail("この台帳を操作する権限がありません")
    body = await request.json()
    if not isinstance(body, dict):
        return _fail("資料を読めませんでした")
    name = str(body.get("name") or "")
    data = str(body.get("data") or "")
    try:
        raw = base64.b64decode(data, validate=False)
        ext = material.extension(name)
    except binascii.Error:
        return _fail("ファイルを読めませんでした")
    except ValueError as exc:
        return _fail(str(exc))
    if len(raw) > material.MAX_BYTES:
        return _fail("ファイルが大きすぎます。8MB までの資料を選んでください。")
    if ext in material.IMAGE_EXTS:
        mime = str(body.get("media_type") or "")
        if not mime.startswith("image/"):
            mime = "image/png" if ext == "png" else "image/jpeg"
        text = await assist.transcribe_image(f"data:{mime};base64,{data}")
        if not text:
            return _fail("この画像から文字を取れませんでした")
    else:
        try:
            text = material.text_from_bytes(name, raw)
        except ValueError as exc:
            return _fail(str(exc))
    text = assist.sanitize_material(text)
    if len(text) < 2:
        return _fail("この資料から文字を取れませんでした")
    return JSONResponse({"text": text})


@app.post("/ledgers/{ledger_id}/assist/material")
async def assist_material(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    ledger, msg = store.get_ledger(actor, ledger_id)
    if msg or ledger is None:
        return _fail(msg)
    if ledger.get("role") != "admin":
        return _fail("この台帳を操作する権限がありません")
    body = await request.json()
    text = assist.sanitize_material(str(body.get("text") or "") if isinstance(body, dict) else "")
    if len(text) < 2:
        return _fail("資料の文章を貼るか、テキストファイルを選んでください")
    existing = [str(item.get("label") or "") for item in ledger.get("fields") or []]
    prompt = (
        "次の資料から、台帳で管理する項目を提案してください。"
        "表は完成した定義ではなく、見出しと見本です。管理すべき項目だけを選んでください。"
        'JSON は {"fields":[{"label":"項目名","type":"text","options":[]}]} だけです。'
        "label は必ず日本語にしてください。資料が英語でも、項目名は日本語に訳してください。"
        "固有名詞は、日本語の項目名の中に残して構いません。"
        "type は text, number, date, select, longtext, file のいずれか。"
        "select のときだけ options に候補を入れてください。候補も日本語にしてください。"
        "マイナンバーや個人番号は項目にしないでください。"
        f"すでに項目にある名前は出さない: {existing}。\n資料:\n{text}"
    )
    data = await assist.complete_json(prompt, timeout=45)
    if not data:
        return _fail("モデルから案を受け取れませんでした")
    fields = assist.fields_from_model(data, existing)
    if not fields:
        return _fail("資料から項目の案を見つけられませんでした")
    return JSONResponse({"fields": fields, "note": "保存するまで台帳は変わりません。"})


@app.post("/ledgers/{ledger_id}/ingest")
async def ingest_files(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    ledger, msg = store.get_ledger(actor, ledger_id)
    if msg or ledger is None:
        return _fail(msg)
    if ledger.get("role") not in ("admin", "editor"):
        return _fail("この台帳を操作する権限がありません")
    fields = [item for item in ledger.get("fields") or [] if isinstance(item, dict)]
    if not fields:
        return _fail("設定項目がまだありません")
    body = await request.json()
    incoming = body.get("files") if isinstance(body, dict) else None
    if not isinstance(incoming, list) or not incoming:
        return _fail("資料を1つ以上選んでください")
    if len(incoming) > ingest.MAX_FILES:
        return _fail("一度に読み込める資料は3つまでです")
    prepared: list[dict[str, Any]] = []
    documents: list[dict[str, Any]] = []
    table_rows: list[dict[str, Any]] = []
    for index, item in enumerate(incoming):
        if not isinstance(item, dict):
            return _fail("資料を読めませんでした")
        name = str(item.get("name") or "")
        try:
            raw = base64.b64decode(str(item.get("data") or ""), validate=False)
            ext = material.extension(name)
        except binascii.Error:
            return _fail("ファイルを読めませんでした")
        except ValueError as exc:
            return _fail(str(exc))
        if len(raw) > material.MAX_BYTES:
            return _fail("ファイルが大きすぎます。8MB までの資料を選んでください。")
        if ext in material.IMAGE_EXTS:
            mime = str(item.get("media_type") or "")
            if not mime.startswith("image/"):
                mime = "image/png" if ext == "png" else "image/jpeg"
            text = await assist.transcribe_image(f"data:{mime};base64,{item.get('data')}", timeout=20)
            if not text:
                return _fail(f"{name} から文字を取れませんでした")
        else:
            mime = str(item.get("media_type") or "application/octet-stream")
            try:
                text = material.text_from_bytes(name, raw)
            except ValueError as exc:
                return _fail(str(exc))
        text = assist.sanitize_material(text)
        prepared.append({"name": name, "mime": mime, "raw": raw})
        parsed = ingest.rows_from_table(text, fields, index)
        if parsed:
            table_rows.extend(parsed)
        elif text:
            documents.append({"name": name, "text": text, "index": index})
    model_rows = await ingest.rows_from_model(fields, documents) if documents else []
    rows = (table_rows + model_rows)[: ingest.MAX_ROWS]
    shown = ingest.public_rows(rows, prepared, fields)
    if not shown:
        return _fail("資料から入れられる値は見つかりませんでした")
    batch_id = ingest.stage_batch(ledger_id, actor.user_id, prepared, rows)
    return JSONResponse({"batch_id": batch_id, "rows": shown, "note": "登録するまで台帳は変わりません。"})


@app.post("/ledgers/{ledger_id}/ingest/{batch_id}")
async def ingest_commit(
    ledger_id: str,
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
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    raw_indexes = body.get("indexes") if isinstance(body, dict) else None
    if not isinstance(raw_indexes, list) or not raw_indexes:
        return _fail("登録する行を選んでください")
    indexes: list[int] = []
    for item in raw_indexes:
        try:
            indexes.append(int(item))
        except (TypeError, ValueError):
            return _fail("登録する行を選んでください")
    count, msg = ingest.commit_batch(actor, ledger_id, batch_id, indexes)
    if msg:
        return JSONResponse(status_code=400, content={"error": msg, "created": count})
    return JSONResponse({"created": count})


@app.post("/ledgers/{ledger_id}/assist/query")
async def assist_query(
    ledger_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    ledger, msg = store.get_ledger(actor, ledger_id)
    if msg or ledger is None:
        return _fail(msg)
    body = await request.json()
    text = str(body.get("text") or "")
    parsed = assist.parse_query(text, [str(item) for item in ledger.get("statuses") or []])
    hinted = await assist.complete_json(
        "次の文を台帳の検索条件 JSON にしてください。"
        'keys は status, assignee, q, date_from, date_to。不明な値は空文字。'
        f"状態の候補: {ledger.get('statuses')}。文: {text}"
    )
    if hinted:
        for key in ("status", "assignee", "q", "date_from", "date_to"):
            if str(hinted.get(key) or "").strip():
                parsed[key] = str(hinted[key]).strip()
    page, qerr = store.list_rows(
        actor,
        ledger_id,
        status=parsed["status"],
        assignee=parsed["assignee"],
        q=parsed["q"],
        date_from=parsed["date_from"],
        date_to=parsed["date_to"],
    )
    if qerr or page is None:
        return _fail(qerr)
    return JSONResponse({"filter": parsed, "rows": page["rows"]})


@app.post("/rows/{row_id}/assist/summary")
async def assist_summary(
    row_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, actor = _actor(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    row, msg = store.get_row(actor, row_id)
    if msg or row is None:
        return _fail(msg)
    ledger, lerr = store.get_ledger(actor, row["ledger_id"])
    if lerr or ledger is None:
        return _fail(lerr)
    text = assist.summarize(row, ledger)
    richer = await assist.complete_json(
        "次の台帳行を、担当への申し送り文 1 段落の JSON {\"summary\": \"...\"} にしてください。\n" + text
    )
    if richer and str(richer.get("summary") or "").strip():
        text = str(richer["summary"]).strip()
    return JSONResponse({"summary": text})
