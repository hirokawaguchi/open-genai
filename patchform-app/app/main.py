"""オンラインフォーム マイクロサービス（Open GENAI / patchform）。

- 庁内: backend が JWT 検証後、HMAC 署名付きで /forms 等へプロキシ
- 外部: 別ホストの公開プロキシが /public/* のみ upstream（ゲスト回答）

Compose では profiles: ["patchform"] でオプション起動する。
画面上の日本語名は「フォーム」（フロント定数。後で変更可）。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import assist, extract, intauth, llm, spec, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
PUBLIC_ENDPOINT = (os.environ.get("PATCHFORM_PUBLIC_ENDPOINT") or "").rstrip("/")
RETENTION_DAYS = int(os.environ.get("PATCHFORM_RETENTION_DAYS", "365"))
CLEANUP_HOUR = int(os.environ.get("PATCHFORM_CLEANUP_HOUR", "2"))

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

app = FastAPI(title="Open GENAI Patchform App", version="0.1.0")


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
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"}), ""
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), ""
    return None, x_user_id


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
    return JSONResponse(content={"forms": store.list_forms_for_user(uid)})


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
    detail = store.get_form(form_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "フォームが見つかりません"})
    if detail["creator_user_id"] != uid:
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
        title=body.get("title"),
        description=body.get("description"),
        visibility=body.get("visibility"),
        definition=body.get("definition"),
        pin=body.get("pin"),
        retention_days=body.get("retention_days"),
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
    detail, msg = store.set_status(form_id, actor_user_id=uid, status=status)
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
    msg = store.delete_form(form_id, actor_user_id=uid)
    if msg:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    print(f"[patchform] form deleted id={form_id} by={uid}")
    return JSONResponse(content={"message": "フォームを削除しました"})


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
    )
    if msg or result is None:
        code = 404 if "見つかりません" in (msg or "") else 403 if "公開" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(status_code=201, content=result)


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
    items, msg = store.list_submissions(form_id, actor_user_id=uid)
    if msg or items is None:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content={"submissions": items})


@app.get("/forms/{form_id}/export")
def export_answers(
    form_id: str,
    format: str = "csv",
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
    if fmt == "jsonl":
        body, msg = store.export_jsonl(form_id, actor_user_id=uid)
        media = "application/x-ndjson; charset=utf-8"
        filename = f"patchform_{form_id}.jsonl"
        encoded = (body or "").encode("utf-8")
    else:
        body, msg = store.export_csv(form_id, actor_user_id=uid)
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


@app.post("/public/api/forms/{guest_token}/submissions")
async def public_submit(guest_token: str, request: Request) -> JSONResponse:
    body = await request.json()
    result, msg = store.submit_answers(
        guest_token=guest_token,
        answers=body.get("answers") or {},
        submitter_user_id=None,
        submitter_name=(body.get("submitter_name") or None),
        pin=body.get("pin"),
    )
    if msg or result is None:
        code = 404 if "見つかりません" in (msg or "") else 403 if "公開" in (msg or "") or "暗証" in (msg or "") else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(status_code=201, content=result)


@app.get("/public/f/{guest_token}", response_model=None)
def public_form_page(guest_token: str) -> FileResponse | HTMLResponse:
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
