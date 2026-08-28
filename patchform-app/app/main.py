"""オンラインフォーム マイクロサービス（Open GENAI / patchform）。

- 庁内: backend が JWT 検証後、HMAC 署名付きで /forms 等へプロキシ
- 外部: 別ホストの公開プロキシが /public/* のみ upstream（ゲスト回答）

Compose では profiles: ["patchform"] でオプション起動する。
画面上の日本語名は「フォーム」（フロント定数。後で変更可）。
"""

from __future__ import annotations

import hmac
import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import assist, extract, files, intauth, llm, lookup, notify, seed, spec, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
PUBLIC_ENDPOINT = (os.environ.get("PATCHFORM_PUBLIC_ENDPOINT") or "").rstrip("/")
RETENTION_DAYS = int(os.environ.get("PATCHFORM_RETENTION_DAYS", "365"))
CLEANUP_HOUR = int(os.environ.get("PATCHFORM_CLEANUP_HOUR", "2"))
SERVICE_USER_ID = "service"

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

app = FastAPI(title="Open GENAI Patchform App", version="0.1.0")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _groups(x_user_groups: str | None) -> list[str]:
    return [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]


def _service_key() -> str:
    return (os.environ.get("PATCHFORM_SERVICE_KEY") or "").strip()


def _service_ok(x_service_key: str | None) -> bool:
    expected = _service_key()
    offered = (x_service_key or "").strip()
    if not expected or not offered:
        return False
    return hmac.compare_digest(expected, offered)


def _verify_internal(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
    x_service_key: str | None = None,
    *,
    allow_service: bool = False,
) -> tuple[JSONResponse | None, str]:
    err = _check_key(x_api_key)
    if err:
        return err, ""
    if allow_service and _service_ok(x_service_key):
        return None, SERVICE_USER_ID
    if not intauth.verify(
        x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    ):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"}), ""
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), ""
    return None, x_user_id


def _groups_for(uid: str, x_user_groups: str | None) -> list[str]:
    if uid == SERVICE_USER_ID:
        return ["SystemAdminGroup"]
    return _groups(x_user_groups)


def _query_error(msg: str | None) -> JSONResponse:
    text = msg or "不正な要求です"
    if text.startswith("since"):
        return JSONResponse(status_code=400, content={"error": text})
    code = 404 if "見つかりません" in text else 403
    return JSONResponse(status_code=code, content={"error": text})


def _cleanup_loop() -> None:
    while True:
        try:
            store.delete_old_forms(RETENTION_DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"[patchform] cleanup error: {e}")
        time.sleep(3600)


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()
    try:
        n = store.delete_old_forms(RETENTION_DAYS)
        if n:
            print(f"[patchform] startup cleanup: deleted {n} old forms")
    except Exception as e:  # noqa: BLE001
        print(f"[patchform] startup cleanup error: {e}")
    if seed.seed_enabled():
        try:
            seed.ensure_sample_data()
        except Exception as e:  # noqa: BLE001
            print(f"[patchform] sample seed error: {e}")
    t = threading.Thread(target=_cleanup_loop, name="patchform-cleanup", daemon=True)
    t.start()


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
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(
        content={
            "public_endpoint": PUBLIC_ENDPOINT,
            "retention_days": RETENTION_DAYS,
            "enabled": True,
            "spec_version": spec.SPEC_VERSION,
            "catalog": spec.catalog_public(),
            "llm": {
                "model": llm.PATCHFORM_MODEL,
                "base_url": llm.OPENAI_BASE_URL,
            },
            "mail": notify.mail_status(),
        }
    )


@app.get("/forms")
def list_forms(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(content={"forms": store.list_forms_for_user(uid, actor_groups=_groups(x_user_groups))})


@app.post("/forms")
async def create_form(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    title = (body.get("title") or "").strip()
    if not title:
        return JSONResponse(status_code=400, content={"error": "タイトルは必須です"})
    detail, msg = store.create_form(
        title=title,
        description=(body.get("description") or None),
        creator_user_id=uid,
        creator_name=(body.get("creator_name") or None),
        visibility=(body.get("visibility") or "internal"),
        definition=body.get("definition"),
        pin=body.get("pin"),
        retention_days=body.get("retention_days"),
        tags=body.get("tags"),
    )
    if msg or detail is None:
        return JSONResponse(status_code=400, content={"error": msg})
    print(f"[patchform] form created id={detail['id']} by={uid}")
    return JSONResponse(status_code=201, content=detail)


@app.get("/forms/{form_id}")
def get_form(
    form_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    detail = store.get_form(form_id, actor_user_id=uid, actor_groups=_groups(x_user_groups))
    if not detail:
        return JSONResponse(status_code=404, content={"error": "フォームが見つかりません"})
    if not detail.get("can_read"):
        return JSONResponse(status_code=403, content={"error": "このフォームを閲覧する権限がありません"})
    return JSONResponse(content=detail)


@app.put("/forms/{form_id}")
async def update_form(
    form_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    detail, msg = store.update_form(
        form_id,
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
        title=body.get("title"),
        description=body.get("description"),
        visibility=body.get("visibility"),
        definition=body.get("definition"),
        pin=body.get("pin"),
        retention_days=body.get("retention_days"),
        allow_draft=body.get("allow_draft"),
        allow_multiple=body.get("allow_multiple"),
        editor_user_ids=body.get("editor_user_ids"),
        viewer_user_ids=body.get("viewer_user_ids"),
        identity_mode=body.get("identity_mode"),
        tags=body.get("tags"),
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "権限" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.post("/forms/{form_id}/status")
async def set_status(
    form_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    status = (body.get("status") or "").strip()
    locked = body.get("locked")
    detail, msg = store.set_status(
        form_id,
        actor_user_id=uid,
        status=status,
        actor_groups=_groups(x_user_groups),
        locked=None if locked is None else bool(locked),
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "権限" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.get("/tags")
def list_tags(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    tags = store.list_all_tags(actor_user_id=uid, actor_groups=_groups(x_user_groups))
    return JSONResponse(content={"tags": tags})


@app.post("/tags/rename")
async def rename_tag(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.rename_tag(
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
        old=str(body.get("from") or ""),
        new=str(body.get("to") or ""),
    )
    if msg or result is None:
        return JSONResponse(status_code=400, content={"error": msg or "操作に失敗しました"})
    return JSONResponse(content=result)


@app.post("/tags/delete")
async def delete_tag(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.delete_tag(
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
        tag=str(body.get("tag") or ""),
    )
    if msg or result is None:
        return JSONResponse(status_code=400, content={"error": msg or "操作に失敗しました"})
    return JSONResponse(content=result)


@app.post("/forms/{form_id}/tags")
async def set_form_tags(
    form_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    detail, msg = store.set_tags(
        form_id,
        actor_user_id=uid,
        tags=body.get("tags"),
        actor_groups=_groups(x_user_groups),
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "権限" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.delete("/forms/{form_id}")
def delete_form(
    form_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    msg = store.delete_form(form_id, actor_user_id=uid, actor_groups=_groups(x_user_groups))
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "権限" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    print(f"[patchform] form deleted id={form_id} by={uid}")
    return JSONResponse(content={"message": "フォームを削除しました"})


@app.get("/procedures")
def list_procedures(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        x_service_key,
        allow_service=True,
    )
    if err:
        return err
    return JSONResponse(
        content={
            "procedures": store.list_procedures(
                actor_user_id=uid, actor_groups=_groups_for(uid, x_user_groups)
            )
        }
    )


@app.post("/procedures")
async def create_procedure(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    detail, msg = store.create_procedure(
        name=(body.get("name") or body.get("title") or ""),
        description=(body.get("description") or None),
        guide_form_id=(body.get("guide_form_id") or ""),
        mapping=body.get("mapping"),
        notify_emails=body.get("notify_emails"),
        creator_user_id=uid,
        creator_name=(body.get("creator_name") or None),
    )
    if msg or detail is None:
        return JSONResponse(status_code=400, content={"error": msg})
    return JSONResponse(status_code=201, content=detail)


@app.get("/procedures/{procedure_id}")
def get_procedure(
    procedure_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        x_service_key,
        allow_service=True,
    )
    if err:
        return err
    detail = store.get_procedure(
        procedure_id, actor_user_id=uid, actor_groups=_groups_for(uid, x_user_groups)
    )
    if not detail:
        return JSONResponse(status_code=404, content={"error": "手続きが見つかりません"})
    return JSONResponse(content=detail)


@app.get("/procedures/{procedure_id}/share")
def get_procedure_share(
    procedure_id: str,
    origin: str = "",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    detail, msg = store.procedure_share(
        procedure_id,
        origin=origin,
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
    )
    if msg or detail is None:
        code = 404 if "見つかりません" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.put("/procedures/{procedure_id}")
async def update_procedure(
    procedure_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    detail, msg = store.update_procedure(
        procedure_id,
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
        name=body.get("name"),
        description=body.get("description"),
        guide_form_id=body.get("guide_form_id"),
        mapping=body.get("mapping"),
        notify_emails=body.get("notify_emails"),
    )
    if msg or detail is None:
        code = 404 if "見つかりません" in (msg or "") else 403 if "権限" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.post("/procedures/{procedure_id}/status")
async def set_procedure_status(
    procedure_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    detail, msg = store.set_procedure_status(
        procedure_id,
        actor_user_id=uid,
        status=(body.get("status") or ""),
        actor_groups=_groups(x_user_groups),
    )
    if msg or detail is None:
        code = 404 if "見つかりません" in (msg or "") else 403 if "権限" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.delete("/procedures/{procedure_id}")
def delete_procedure(
    procedure_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    msg = store.delete_procedure(
        procedure_id, actor_user_id=uid, actor_groups=_groups(x_user_groups)
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "権限" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content={"message": "手続きを削除しました"})


@app.get("/inbox")
def get_inbox(
    procedure_id: str | None = None,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(
        content=store.list_inbox(
            actor_user_id=uid,
            actor_groups=_groups(x_user_groups),
            procedure_id=procedure_id,
        )
    )


@app.get("/procedures/{procedure_id}/applications")
def list_procedure_applications(
    procedure_id: str,
    since: str | None = None,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        x_service_key,
        allow_service=True,
    )
    if err:
        return err
    items, msg = store.list_applications(
        procedure_id,
        actor_user_id=uid,
        actor_groups=_groups_for(uid, x_user_groups),
        since=since,
    )
    if msg or items is None:
        return _query_error(msg)
    return JSONResponse(
        content={
            "applications": items,
            "since": (since or "").strip() or None,
            "as_of": store.now_iso(),
        }
    )


def _application_error(msg: str | None) -> JSONResponse:
    text = msg or "操作に失敗しました"
    if "見つかりません" in text:
        code = 404
    elif "権限" in text:
        code = 403
    else:
        code = 400
    return JSONResponse(status_code=code, content={"error": text})


@app.get("/applications/mine")
def list_my_applications(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    items = store.list_my_applications(owner_kind="internal", owner_key=uid)
    return JSONResponse(content={"applications": items})


@app.post("/applications")
async def create_project(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.create_project(
        procedure_id=str(body.get("procedure_id") or ""),
        owner_kind="internal",
        owner_key=uid,
        title=(body.get("title") or None),
    )
    if msg or result is None:
        return _application_error(msg)
    return JSONResponse(status_code=201, content=result)


@app.post("/applications/{application_id}/status")
async def set_application_status(
    application_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.set_application_status(
        application_id=application_id,
        owner_kind="internal",
        owner_key=uid,
        status=str(body.get("status") or ""),
    )
    if msg or result is None:
        return _application_error(msg)
    return JSONResponse(content=result)


@app.patch("/applications/{application_id}")
async def update_application_meta(
    application_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    # 送られてきたキーのみ更新（None は変更しない）
    kwargs: dict[str, str] = {}
    for key in ("title", "assignee", "deadline", "next_action_date"):
        if key in body:
            kwargs[key] = str(body.get(key) or "")
    result, msg = store.update_application_meta(
        application_id=application_id,
        owner_kind="internal",
        owner_key=uid,
        **kwargs,
    )
    if msg or result is None:
        return _application_error(msg)
    return JSONResponse(content=result)


@app.delete("/applications/{application_id}")
def delete_application(
    application_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    msg = store.delete_application(
        application_id=application_id,
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
    )
    if msg:
        return _application_error(msg)
    return JSONResponse(content={"message": "申請を削除しました"})


@app.get("/applications/{application_id}/imi-sources")
def application_imi_sources(
    application_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    result, msg = store.application_imi_sources(
        application_id=application_id, owner_kind="internal", owner_key=uid
    )
    if msg or result is None:
        return _application_error(msg)
    return JSONResponse(content=result)


@app.get("/applications/{application_id}")
def get_application(
    application_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        x_service_key,
        allow_service=True,
    )
    if err:
        return err
    detail = store.get_application(application_id, actor_user_id=uid)
    if not detail:
        detail = store.get_application(token=application_id, actor_user_id=uid)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "申請が見つかりません"})
    return JSONResponse(content=detail)


def _export_attachment(body: str | None, msg: str | None, *, filename: str, media: str, utf8_sig: bool) -> Response:
    if msg or body is None:
        code = 404 if msg and "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    encoded = (body or "").encode("utf-8-sig" if utf8_sig else "utf-8")
    return Response(
        content=encoded,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/procedures/{procedure_id}/export")
def export_procedure_applications(
    procedure_id: str,
    format: str = "csv",
    since: str | None = None,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> Response:
    err, uid = _verify_internal(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        x_service_key,
        allow_service=True,
    )
    if err:
        return err
    fmt = (format or "csv").lower()
    body, msg = store.export_procedure_applications(
        procedure_id,
        actor_user_id=uid,
        actor_groups=_groups_for(uid, x_user_groups),
        fmt=fmt,
        since=since,
    )
    if msg and msg.startswith("since"):
        return JSONResponse(status_code=400, content={"error": msg})
    if fmt == "jsonl":
        return _export_attachment(
            body,
            msg,
            filename=f"procedure_{procedure_id}.jsonl",
            media="application/x-ndjson; charset=utf-8",
            utf8_sig=False,
        )
    return _export_attachment(
        body,
        msg,
        filename=f"procedure_{procedure_id}.csv",
        media="text/csv; charset=utf-8",
        utf8_sig=True,
    )


@app.get("/applications/{application_id}/export")
def export_application(
    application_id: str,
    format: str = "csv",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> Response:
    err, uid = _verify_internal(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        x_service_key,
        allow_service=True,
    )
    if err:
        return err
    fmt = (format or "csv").lower()
    body, msg = store.export_application(application_id, fmt=fmt)
    if fmt in ("json", "jsonl"):
        return _export_attachment(
            body,
            msg,
            filename=f"application_{application_id}.{'json' if fmt == 'json' else 'jsonl'}",
            media="application/x-ndjson; charset=utf-8"
            if fmt == "jsonl"
            else "application/json; charset=utf-8",
            utf8_sig=False,
        )
    return _export_attachment(
        body,
        msg,
        filename=f"application_{application_id}.csv",
        media="text/csv; charset=utf-8",
        utf8_sig=True,
    )


@app.post("/forms/{form_id}/submissions")
async def submit_internal(
    form_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.submit_answers(
        form_id=form_id,
        answers=body.get("answers") or {},
        submitter_user_id=uid,
        submitter_name=(body.get("submitter_name") or None),
        pin=body.get("pin"),
        is_draft=bool(body.get("is_draft")),
        resume_token=(body.get("resume_token") or None),
        application_token=(body.get("application_token") or None),
        application_item_id=(body.get("application_item_id") or None),
    )
    if msg or result is None:
        code = 404 if "見つかりません" in (msg or "") else 403 if "公開" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(status_code=201, content=result)


def _item_error(msg: str | None) -> JSONResponse:
    code = 404 if msg and "見つかりません" in msg else 400
    return JSONResponse(status_code=code, content={"error": msg})


@app.get("/procedures/{procedure_id}/catalog")
def procedure_catalog(
    procedure_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags,
        x_service_key, allow_service=True,
    )
    if err:
        return err
    data, msg = store.procedure_catalog(procedure_id)
    if msg or data is None:
        return _item_error(msg)
    return JSONResponse(content=data)


@app.post("/applications/{application_id}/items")
async def add_application_item_internal(
    application_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.add_application_item(
        application_id=application_id,
        duplicate_of=(body.get("duplicate_of") or None),
        form_id=(body.get("form_id") or None),
        slot_id=(body.get("slot_id") or None),
        title=(body.get("title") or None),
        kind=(body.get("kind") or None),
        added_by="staff",
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(status_code=201, content=result)


@app.post("/applications/{application_id}/items/{item_id}/file")
async def fulfill_item_internal(
    application_id: str,
    item_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.fulfill_item_with_file(
        application_id=application_id,
        item_id=item_id,
        filename=str(body.get("filename") or "file"),
        data=str(body.get("data") or ""),
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.delete("/applications/{application_id}/items/{item_id}/file")
def clear_item_internal(
    application_id: str,
    item_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    result, msg = store.clear_item_fulfillment(
        application_id=application_id, item_id=item_id
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.post("/applications/{application_id}/items/{item_id}/source")
async def set_item_source_internal(
    application_id: str,
    item_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.set_item_source(
        application_id=application_id,
        item_id=item_id,
        source=str(body.get("source") or ""),
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.post("/applications/{application_id}/items/order")
async def reorder_items_internal(
    application_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    order = body.get("order")
    if not isinstance(order, list):
        return _item_error("order には並び順のIDリストが必要です")
    result, msg = store.reorder_application_items(
        application_id=application_id,
        order=[str(x) for x in order],
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.post("/procedures/{procedure_id}/resolve")
async def resolve_procedure_preview(
    procedure_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags,
        x_service_key, allow_service=True,
    )
    if err:
        return err
    body = await request.json()
    answers = body.get("answers")
    if not isinstance(answers, dict):
        answers = {}
    result, msg = store.resolve_procedure_preview(
        procedure_id=procedure_id, answers=answers
    )
    if msg or result is None:
        return _application_error(msg)
    return JSONResponse(content=result)


@app.post("/forms/{form_id}/template")
async def set_form_template(
    form_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    result, msg = store.set_form_template(
        form_id=form_id,
        filename=str(body.get("filename") or "template"),
        data=str(body.get("data") or ""),
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(status_code=201, content=result)


@app.delete("/forms/{form_id}/template")
def delete_form_template(
    form_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    msg = store.delete_form_template(
        form_id=form_id,
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
    )
    if msg:
        return _item_error(msg)
    return JSONResponse(content={"message": "ひな型を削除しました"})


@app.get("/forms/{form_id}/templates/{file_id}/download")
def download_form_template(
    form_id: str,
    file_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> Response:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags,
        x_service_key, allow_service=True,
    )
    if err:
        return err
    meta, msg = store.get_form_template_file(form_id, file_id)
    if msg or meta is None:
        code = 404 if "見つかりません" in (msg or "") else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return FileResponse(
        meta["path"],
        media_type=meta["mime"],
        headers={"Content-Disposition": files.content_disposition(meta["filename"])},
    )


@app.get("/applications/{application_id}/items/{item_id}/template")
def download_item_template_internal(
    application_id: str,
    item_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_service_key: str | None = Header(default=None),
) -> Response:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags,
        x_service_key, allow_service=True,
    )
    if err:
        return err
    meta, msg = store.get_item_template_file(application_id=application_id, item_id=item_id)
    if msg or meta is None:
        return JSONResponse(status_code=404, content={"error": msg})
    return FileResponse(
        meta["path"],
        media_type=meta["mime"],
        headers={"Content-Disposition": files.content_disposition(meta["filename"])},
    )


@app.get("/forms/{form_id}/submissions")
def list_submissions(
    form_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    items, msg = store.list_submissions(
        form_id, actor_user_id=uid, actor_groups=_groups(x_user_groups)
    )
    if msg or items is None:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content={"submissions": items})


@app.get("/forms/{form_id}/draft")
def get_draft(
    form_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    data, msg = store.get_draft(form_id=form_id, submitter_user_id=uid)
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "権限" in msg or "公開" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=data)


@app.get("/forms/{form_id}/submissions/{submission_id}")
def reveal_submission(
    form_id: str,
    submission_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    item, msg = store.reveal_submission(
        form_id, submission_id, actor_user_id=uid, actor_groups=_groups(x_user_groups)
    )
    if msg or item is None:
        code = 404 if "見つかりません" in (msg or "") else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=item)


@app.post("/forms/{form_id}/submissions/{submission_id}/withdraw")
async def withdraw_submission(
    form_id: str,
    submission_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    result, msg = store.set_withdrawn(
        form_id=form_id,
        submission_id=submission_id,
        actor_user_id=uid,
        actor_groups=_groups(x_user_groups),
        withdrawn=body.get("withdrawn", True) is not False,
    )
    if msg or result is None:
        code = 404 if "見つかりません" in (msg or "") else 403 if "権限" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=result)


@app.get("/forms/{form_id}/audit")
def list_audit(
    form_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    items, msg = store.list_audit(
        form_id, actor_user_id=uid, actor_groups=_groups(x_user_groups)
    )
    if msg or items is None:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content={"events": items})


@app.get("/forms/{form_id}/export")
def export_answers(
    form_id: str,
    format: str = "csv",
    reveal: bool = False,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Response:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    fmt = (format or "csv").lower()
    groups = _groups(x_user_groups)
    if fmt == "jsonl":
        body, msg = store.export_jsonl(
            form_id, actor_user_id=uid, actor_groups=groups, reveal=reveal
        )
        media = "application/x-ndjson; charset=utf-8"
        filename = f"patchform_{form_id}.jsonl"
        encoded = (body or "").encode("utf-8")
    else:
        body, msg = store.export_csv(
            form_id, actor_user_id=uid, actor_groups=groups, reveal=reveal
        )
        media = "text/csv; charset=utf-8"
        filename = f"patchform_{form_id}.csv"
        encoded = (body or "").encode("utf-8-sig")
    if msg or body is None:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return Response(
        content=encoded,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _upload_from_body(
    body: dict[str, Any],
    *,
    form_id: str | None = None,
    guest_token: str | None = None,
    actor_user_id: str | None = None,
) -> JSONResponse:
    meta, msg = store.save_upload(
        form_id=form_id,
        guest_token=guest_token,
        filename=str(body.get("filename") or "upload"),
        data=str(body.get("data") or ""),
        kind=str(body.get("kind") or "file"),
        pin=body.get("pin"),
        actor_user_id=actor_user_id,
    )
    if msg or meta is None:
        code = (
            404
            if "見つかりません" in msg
            else 403
            if "公開" in (msg or "") or "暗証" in (msg or "") or "庁内" in (msg or "")
            else 400
        )
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(status_code=201, content=meta)


@app.post("/forms/{form_id}/files")
async def upload_internal(
    form_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not _extract_rate_ok(f"up-int:{uid}", limit=40):
        return JSONResponse(status_code=429, content={"error": "添付の回数制限に達しました"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return _upload_from_body(body if isinstance(body, dict) else {}, form_id=form_id, actor_user_id=uid)


@app.get("/forms/{form_id}/files/{file_id}")
def download_internal(
    form_id: str,
    file_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Response:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    meta, msg = store.get_stored_file(
        form_id, file_id, actor_user_id=uid, actor_groups=_groups(x_user_groups)
    )
    if msg or meta is None:
        code = 404 if "見つかりません" in (msg or "") else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return FileResponse(
        meta["path"],
        media_type=meta["mime"],
        headers={"Content-Disposition": files.content_disposition(meta["filename"])},
    )


@app.get("/forms/{form_id}/carrier")
def form_carrier(
    form_id: str,
    format: str = "txt",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    detail = store.get_form(form_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "フォームが見つかりません"})
    if detail["creator_user_id"] != uid:
        return JSONResponse(status_code=403, content={"error": "このフォームを閲覧する権限がありません"})
    url = detail["public_url"]
    title = detail["title"]
    fmt = (format or "txt").lower()
    if fmt == "html":
        body = (
            "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>"
            f"<title>{title} - フォームリンク</title></head><body>"
            f"<h1>{title}</h1><p>外部から回答するURL:</p>"
            f"<p><a href='{url}'>{url}</a></p>"
            "<p>LGWAN 端末から開けない場合は、このファイルを持ち出して"
            "インターネット接続端末で開いてください。</p></body></html>"
        )
        filename = f"{title}_patchform_link.html"
    else:
        body = (
            f"フォーム: {title}\n\n"
            f"外部から回答するURL:\n{url}\n\n"
            "LGWAN 端末から開けない場合は、このファイルを持ち出して"
            "インターネット接続端末で開いてください。\n"
        )
        filename = f"{title}_patchform_link.txt"
    return JSONResponse(
        content={"filename": filename, "content": body, "public_url": url, "format": fmt}
    )


@app.post("/assist/generate")
async def assist_generate(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    text = (body.get("text") or "").strip()
    visibility = (body.get("visibility") or "internal").strip() or "internal"
    current = body.get("definition") if isinstance(body.get("definition"), dict) else None
    try:
        result = await assist.generate_form(text, visibility=visibility, current=current)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": f"フォーム生成に失敗しました: {e}"})
    return JSONResponse(content=result)


def _apply_flags(body: dict) -> tuple[bool, bool, bool, list[str] | None]:
    apply = body.get("apply") if isinstance(body.get("apply"), dict) else {}
    form_keys = body.get("form_keys")
    keys = [str(k).strip() for k in form_keys if str(k).strip()] if isinstance(form_keys, list) else None
    return (
        bool(apply.get("forms", False)),
        bool(apply.get("navigation", False)),
        bool(apply.get("notice", False)),
        keys,
    )


@app.post("/assist/procedure")
async def assist_procedure(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    text = (body.get("text") or "").strip()
    visibility = (body.get("visibility") or "internal").strip() or "internal"
    try:
        generated = await assist.draft_procedure(text, visibility=visibility)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": f"手続きの候補を出せませんでした: {e}"})
    return JSONResponse(content=assist.pack_procedure_preview(generated))


@app.post("/assist/procedure/apply")
async def assist_procedure_apply(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    visibility = (body.get("visibility") or "internal").strip() or "internal"
    draft, derr = assist.normalize_procedure_draft(body.get("draft") or {}, visibility=visibility)
    if derr or draft is None:
        return JSONResponse(status_code=400, content={"error": derr or "手続き案の形式が不正です"})
    apply_forms, apply_navigation, apply_notice, form_keys = _apply_flags(body)
    result, msg = store.create_procedure_from_draft(
        draft,
        creator_user_id=uid,
        creator_name=(body.get("creator_name") or None),
        visibility=visibility,
        apply_forms=apply_forms,
        apply_navigation=apply_navigation,
        apply_notice=apply_notice,
        form_keys=form_keys,
    )
    if msg or result is None:
        return JSONResponse(status_code=400, content={"error": msg})
    return JSONResponse(status_code=201, content=result)


@app.post("/assist/invite")
async def assist_invite(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    body = await request.json()
    title = (body.get("title") or "").strip() or "フォーム"
    url = (body.get("public_url") or "").strip()
    tone = (body.get("tone") or "丁寧").strip() or "丁寧"
    if not url:
        return JSONResponse(status_code=400, content={"error": "公開 URL は必須です"})
    result = await assist.draft_invite(title, url, tone=tone)
    return JSONResponse(content=result)


_EXTRACT_HITS: dict[str, list[float]] = {}


def _extract_rate_ok(key: str, *, limit: int = 20, window: float = 60.0) -> bool:
    now = time.time()
    hits = [t for t in _EXTRACT_HITS.get(key, []) if now - t < window]
    if len(hits) >= limit:
        _EXTRACT_HITS[key] = hits
        return False
    hits.append(now)
    _EXTRACT_HITS[key] = hits
    return True


async def _run_extract(body: dict[str, Any]) -> JSONResponse:
    kind = str(body.get("kind") or "").strip()
    filename = str(body.get("filename") or "upload")
    data = str(body.get("data") or "")
    if not data:
        return JSONResponse(status_code=400, content={"error": "ファイルデータがありません"})
    try:
        result = await extract.extract_payload(kind=kind, filename=filename, data=data)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": f"読取に失敗しました: {e}"})
    return JSONResponse(content=result)


@app.post("/extract")
async def extract_internal(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not _extract_rate_ok(f"int:{uid}"):
        return JSONResponse(status_code=429, content={"error": "読取の回数制限に達しました"})
    body = await request.json()
    return await _run_extract(body if isinstance(body, dict) else {})


async def _run_lookup(kind: str, q: str) -> JSONResponse:
    if kind == "postal":
        data, msg = await lookup.lookup_postal(q)
    elif kind == "corporate":
        data, msg = await lookup.lookup_corporate(q)
    else:
        return JSONResponse(status_code=400, content={"error": "検索の種類が不正です"})
    if msg:
        return JSONResponse(status_code=400, content={"error": msg})
    return JSONResponse(content=data)


@app.get("/lookup/postal")
async def lookup_postal_internal(
    zip: str = "",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not _extract_rate_ok(f"lk-int:{uid}", limit=40):
        return JSONResponse(status_code=429, content={"error": "検索の回数制限に達しました"})
    return await _run_lookup("postal", zip)


@app.get("/lookup/corporate")
async def lookup_corporate_internal(
    number: str = "",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err, uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    if not _extract_rate_ok(f"lk-int:{uid}", limit=40):
        return JSONResponse(status_code=429, content={"error": "検索の回数制限に達しました"})
    return await _run_lookup("corporate", number)


# ---------------------------------------------------------------------------
# 機械向けカタログ（API キーのみ）。公開済み手続きだけ。提出・下書きは出さない。
# ---------------------------------------------------------------------------
CATALOG_LIST_NOTE = (
    "公開中の手続き一覧です。下書きは含みません。"
    "市民の提出本文や申請束トークンは出ません。"
)
CATALOG_INSPECT_NOTE = (
    "案内の選択肢と、答えごとに足す様式・持ち物です。"
    "提出は受け付けません。束を作るには patchform の案内を提出してください。"
)
CATALOG_RESOLVE_NOTE = (
    "案内の答えから、今回足す様式の和集合です。申請束は作っていません。"
)


@app.get("/catalog/procedures")
def catalog_list_procedures(
    q: str | None = None,
    x_api_key: str | None = Header(default=None),
) -> JSONResponse:
    err = _check_key(x_api_key)
    if err:
        return err
    items = store.list_published_procedures(query=q)
    return JSONResponse(
        content={
            "meaning": "庁が公開している手続きマスタの一覧",
            "note": CATALOG_LIST_NOTE,
            "procedures": items,
            "count": len(items),
        }
    )


@app.get("/catalog/procedure")
def catalog_inspect_procedure(
    ref: str = "",
    x_api_key: str | None = Header(default=None),
) -> JSONResponse:
    err = _check_key(x_api_key)
    if err:
        return err
    detail, msg = store.find_published_procedure(ref)
    if msg or detail is None:
        code = 400 if msg and ("必須" in msg or "複数" in msg) else 404
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(
        content={
            "meaning": "答えが様式を足す対応表",
            "note": CATALOG_INSPECT_NOTE,
            "procedure": detail,
        }
    )


@app.post("/catalog/resolve")
async def catalog_resolve_bundle(
    request: Request,
    x_api_key: str | None = Header(default=None),
) -> JSONResponse:
    err = _check_key(x_api_key)
    if err:
        return err
    body = await request.json()
    ref = str(body.get("procedure") or body.get("procedure_id") or body.get("ref") or "").strip()
    resolved, msg = store.resolve_published_bundle(ref, body.get("answers"))
    if msg or resolved is None:
        code = 400 if msg and ("必須" in msg or "複数" in msg) else 404
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(
        content={
            "meaning": "この答えなら足す様式の和集合",
            "note": CATALOG_RESOLVE_NOTE,
            **resolved,
        }
    )


# ---------------------------------------------------------------------------
# 公開面（ゲスト）。公開プロキシはここだけ upstream すること。
# ---------------------------------------------------------------------------
@app.get("/public/api/forms/{guest_token}")
def public_get_form(guest_token: str, pin: str | None = None) -> JSONResponse:
    detail, msg = store.public_form(guest_token, pin=pin)
    if msg:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.post("/public/api/forms/{guest_token}")
async def public_unlock_form(guest_token: str, request: Request) -> JSONResponse:
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    detail, msg = store.public_form(guest_token, pin=body.get("pin"))
    if msg:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.post("/public/api/extract")
async def public_extract(request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if not _extract_rate_ok(f"pub:{ip}"):
        return JSONResponse(status_code=429, content={"error": "読取の回数制限に達しました"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _run_extract(body if isinstance(body, dict) else {})


@app.get("/public/api/lookup/postal")
async def public_lookup_postal(request: Request, zip: str = "") -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if not _extract_rate_ok(f"lk-pub:{ip}", limit=40):
        return JSONResponse(status_code=429, content={"error": "検索の回数制限に達しました"})
    return await _run_lookup("postal", zip)


@app.get("/public/api/lookup/corporate")
async def public_lookup_corporate(request: Request, number: str = "") -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if not _extract_rate_ok(f"lk-pub:{ip}", limit=40):
        return JSONResponse(status_code=429, content={"error": "検索の回数制限に達しました"})
    return await _run_lookup("corporate", number)


@app.post("/public/api/forms/{guest_token}/files")
async def public_upload(guest_token: str, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if not _extract_rate_ok(f"up-pub:{ip}", limit=40):
        return JSONResponse(status_code=429, content={"error": "添付の回数制限に達しました"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return _upload_from_body(
        body if isinstance(body, dict) else {},
        guest_token=guest_token,
    )


@app.post("/public/api/forms/{guest_token}/withdraw")
async def public_withdraw(guest_token: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    result, msg = store.set_withdrawn(
        guest_token=guest_token,
        receipt_code=(body.get("receipt_code") or None),
        pin=body.get("pin"),
        withdrawn=True,
    )
    if msg or result is None:
        code = (
            404
            if "見つかりません" in (msg or "")
            else 403
            if "公開" in (msg or "") or "暗証" in (msg or "")
            else 400
        )
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=result)


@app.get("/public/api/forms/{guest_token}/draft")
def public_get_draft(
    guest_token: str, resume: str = "", pin: str | None = None
) -> JSONResponse:
    data, msg = store.get_draft(
        guest_token=guest_token, resume_token=(resume or None), pin=pin
    )
    if msg:
        code = (
            404
            if "見つかりません" in msg
            else 403
            if "公開" in msg or "暗証" in msg
            else 400
        )
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=data)


@app.post("/public/api/forms/{guest_token}/submissions")
async def public_submit(guest_token: str, request: Request) -> JSONResponse:
    body = await request.json()
    result, msg = store.submit_answers(
        guest_token=guest_token,
        answers=body.get("answers") or {},
        submitter_user_id=None,
        submitter_name=(body.get("submitter_name") or None),
        pin=body.get("pin"),
        is_draft=bool(body.get("is_draft")),
        resume_token=(body.get("resume_token") or None),
        application_token=(body.get("application_token") or None),
        application_item_id=(body.get("application_item_id") or None),
    )
    if msg or result is None:
        code = 404 if "見つかりません" in (msg or "") else 403 if "公開" in (msg or "") or "暗証" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(status_code=201, content=result)


@app.get("/public/api/applications/{token}")
def public_get_application(token: str) -> JSONResponse:
    data, msg = store.public_application(token)
    if msg or data is None:
        return JSONResponse(status_code=404, content={"error": msg})
    return JSONResponse(content=data)


@app.get("/public/api/applications/{token}/catalog")
def public_application_catalog(token: str) -> JSONResponse:
    data, msg = store.public_application(token)
    if msg or data is None:
        return JSONResponse(status_code=404, content={"error": msg})
    catalog, cmsg = store.procedure_catalog(str(data.get("procedure_id") or ""))
    if cmsg or catalog is None:
        return JSONResponse(status_code=404, content={"error": cmsg})
    return JSONResponse(content=catalog)


@app.post("/public/api/applications/{token}/items")
async def public_add_application_item(token: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    result, msg = store.add_application_item(
        token=token,
        duplicate_of=(body.get("duplicate_of") or None),
        form_id=(body.get("form_id") or None),
        slot_id=(body.get("slot_id") or None),
        title=(body.get("title") or None),
        kind=(body.get("kind") or None),
        added_by="guest",
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(status_code=201, content=result)


@app.post("/public/api/applications/{token}/items/{item_id}/file")
async def public_fulfill_item(token: str, item_id: str, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    if not _extract_rate_ok(f"item-pub:{ip}", limit=40):
        return JSONResponse(status_code=429, content={"error": "添付の回数制限に達しました"})
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    result, msg = store.fulfill_item_with_file(
        token=token,
        item_id=item_id,
        filename=str(body.get("filename") or "file"),
        data=str(body.get("data") or ""),
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.delete("/public/api/applications/{token}/items/{item_id}/file")
def public_clear_item(token: str, item_id: str) -> JSONResponse:
    result, msg = store.clear_item_fulfillment(token=token, item_id=item_id)
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.post("/public/api/applications/{token}/items/{item_id}/source")
async def public_set_item_source(token: str, item_id: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    result, msg = store.set_item_source(
        token=token, item_id=item_id, source=str(body.get("source") or "")
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.post("/public/api/applications/{token}/items/order")
async def public_reorder_items(token: str, request: Request) -> JSONResponse:
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    order = body.get("order")
    if not isinstance(order, list):
        return _item_error("order には並び順のIDリストが必要です")
    result, msg = store.reorder_application_items(
        token=token, order=[str(x) for x in order]
    )
    if msg or result is None:
        return _item_error(msg)
    return JSONResponse(content=result)


@app.get("/public/api/applications/{token}/items/{item_id}/template", response_model=None)
def public_download_item_template(token: str, item_id: str) -> Response:
    meta, msg = store.get_item_template_file(token=token, item_id=item_id)
    if msg or meta is None:
        return JSONResponse(status_code=404, content={"error": msg})
    return FileResponse(
        meta["path"],
        media_type=meta["mime"],
        headers={"Content-Disposition": files.content_disposition(meta["filename"])},
    )


@app.get("/public/f/{guest_token}", response_model=None)
@app.get("/public/p/{token}", response_model=None)
def public_form_page(guest_token: str = "", token: str = "") -> FileResponse | HTMLResponse:
    path = PUBLIC_DIR / "form.html"
    if path.is_file():
        return FileResponse(path, media_type="text/html; charset=utf-8")
    return HTMLResponse("<p>ゲスト UI が未配置です</p>", status_code=500)


@app.get("/public/", response_class=HTMLResponse)
@app.get("/public", response_class=HTMLResponse)
def public_index() -> HTMLResponse:
    return HTMLResponse(
        "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>"
        "<title>フォーム</title></head><body>"
        "<p>フォームの共有リンクからアクセスしてください。</p></body></html>"
    )


if PUBLIC_DIR.is_dir():
    app.mount("/public/assets", StaticFiles(directory=str(PUBLIC_DIR)), name="public-assets")
