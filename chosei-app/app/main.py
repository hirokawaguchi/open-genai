"""日程調整マイクロサービス（Open GENAI exApp / 専用ページ向け）。

- 庁内: backend が JWT 検証後、HMAC 署名付きで /events 等へプロキシ
- 外部: 別ホストの公開プロキシが /public/* のみ upstream（ゲスト回答）

Compose では profiles: ["chosei"] でオプション起動する。
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import assist, intauth, llm, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
PUBLIC_ENDPOINT = (os.environ.get("CHOSEI_PUBLIC_ENDPOINT") or "").rstrip("/")
RETENTION_DAYS = int(os.environ.get("CHOSEI_RETENTION_DAYS", "90"))
CLEANUP_HOUR = int(os.environ.get("CHOSEI_CLEANUP_HOUR", "2"))

PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"
APP_TITLE = (os.environ.get("APP_TITLE") or "Open GENAI").strip() or "Open GENAI"

app = FastAPI(title="Open GENAI Chosei App", version="0.1.0")


def _public_html(name: str) -> FileResponse | HTMLResponse:
    path = PUBLIC_DIR / name
    if not path.is_file():
        return HTMLResponse("<p>ゲスト UI が未配置です</p>", status_code=500)
    text = path.read_text(encoding="utf-8")
    if APP_TITLE != "Open GENAI":
        text = text.replace("Open GENAI", APP_TITLE)
    return HTMLResponse(text)


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


def _normalize_dates(raw: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(raw, list) or len(raw) == 0:
        return None, "日程候補は必須です"
    out: list[dict[str, Any]] = []
    for d in raw:
        if isinstance(d, str):
            out.append({"start_time": d, "end_time": None, "is_all_day": False})
        elif isinstance(d, dict) and d.get("start_time"):
            out.append(
                {
                    "start_time": d["start_time"],
                    "end_time": d.get("end_time"),
                    "is_all_day": bool(d.get("is_all_day")),
                }
            )
        else:
            return None, "日程候補の形式が不正です"
    return out, None


def _cleanup_loop() -> None:
    """毎日 CLEANUP_HOUR 時頃に古いイベントを削除する簡易スケジューラ。"""
    while True:
        try:
            store.delete_old_events(RETENTION_DAYS)
        except Exception as e:  # noqa: BLE001
            print(f"[chosei] cleanup error: {e}")
        # 次回 CLEANUP_HOUR まで待つ（簡易: 1時間ポーリング）
        time.sleep(3600)


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()
    try:
        n = store.delete_old_events(RETENTION_DAYS)
        if n:
            print(f"[chosei] startup cleanup: deleted {n} old events")
    except Exception as e:  # noqa: BLE001
        print(f"[chosei] startup cleanup error: {e}")
    t = threading.Thread(target=_cleanup_loop, name="chosei-cleanup", daemon=True)
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
            "llm": {
                "model": llm.CHOSEI_MODEL,
                "base_url": llm.OPENAI_BASE_URL,
            },
        }
    )


@app.get("/events")
def list_events(
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
    return JSONResponse(content={"events": store.list_events_for_user(uid)})


@app.post("/events")
async def create_event(
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
    dates, derr = _normalize_dates(body.get("dates"))
    if derr or dates is None:
        return JSONResponse(status_code=400, content={"error": derr})
    event_password = body.get("event_password")
    if event_password:
        perr = store.validate_pin(event_password)
        if perr:
            return JSONResponse(status_code=400, content={"error": perr})
    detail = store.create_event(
        title=title,
        description=(body.get("description") or None),
        creator_name=(body.get("creator_name") or None),
        creator_user_id=uid,
        event_password=event_password,
        dates=dates,
    )
    print(f"[chosei] event created id={detail['event']['id']} by={uid}")
    return JSONResponse(status_code=201, content=detail)


@app.get("/events/{event_id}")
def get_event(
    event_id: str,
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
    detail = store.event_detail(event_id=event_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "イベントが見つかりません"})
    return JSONResponse(content=detail)


@app.put("/events/{event_id}")
async def update_event(
    event_id: str,
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
    dates = None
    if body.get("dates") is not None:
        dates, derr = _normalize_dates(body.get("dates"))
        if derr or dates is None:
            return JSONResponse(status_code=400, content={"error": derr})
    detail, msg = store.update_event(
        event_id,
        title=title,
        description=(body.get("description") or None),
        creator_name=(body.get("creator_name") or None),
        dates=dates,
        event_password=body.get("event_password"),
        actor_user_id=uid,
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content=detail)


@app.delete("/events/{event_id}")
async def delete_event(
    event_id: str,
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
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    msg = store.delete_event(
        event_id, event_password=body.get("event_password"), actor_user_id=uid
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403
        return JSONResponse(status_code=code, content={"error": msg})
    print(f"[chosei] event deleted id={event_id} by={uid}")
    return JSONResponse(content={"message": "イベントが削除されました"})


@app.post("/events/{event_id}/responses")
async def submit_response_auth(
    event_id: str,
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
    name = (body.get("participant_name") or "").strip()
    responses = body.get("responses")
    if not name or not isinstance(responses, list):
        return JSONResponse(status_code=400, content={"error": "参加者名と回答は必須です"})
    result, msg = store.submit_response(
        event_id=event_id,
        participant_name=name,
        responses=responses,
        password=body.get("password"),
        participant_user_id=uid,
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "正しくありません" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(status_code=201, content=result)


@app.delete("/events/{event_id}/participants/{participant_name}")
async def delete_participant_auth(
    event_id: str,
    participant_name: str,
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
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    msg = store.delete_participant(
        event_id=event_id,
        participant_name=participant_name,
        password=body.get("password"),
        actor_user_id=uid,
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "正しくありません" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content={"message": "参加者と回答を削除しました"})


@app.get("/events/{event_id}/carrier")
def event_carrier(
    event_id: str,
    format: str = "txt",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    """外部共有 URL を記載したリンクファイル本文を返す（LGWAN carrier 向け）。"""
    err, _uid = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    detail = store.event_detail(event_id=event_id)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "イベントが見つかりません"})
    ev = detail["event"]
    url = ev["public_url"]
    title = ev["title"]
    fmt = (format or "txt").lower()
    if fmt == "html":
        body = (
            "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>"
            f"<title>{title} - 日程調整リンク</title></head><body>"
            f"<h1>{title}</h1><p>外部から回答するURL:</p>"
            f"<p><a href='{url}'>{url}</a></p>"
            "<p>LGWAN 端末から開けない場合は、このファイルを持ち出して"
            "インターネット接続端末で開いてください。</p></body></html>"
        )
        filename = f"{title}_chosei_link.html"
    else:
        body = (
            f"日程調整: {title}\n\n"
            f"外部から回答するURL:\n{url}\n\n"
            "LGWAN 端末から開けない場合は、このファイルを持ち出して"
            "インターネット接続端末で開いてください。\n"
        )
        filename = f"{title}_chosei_link.txt"
    return JSONResponse(
        content={"filename": filename, "content": body, "public_url": url, "format": fmt}
    )


# ---------------------------------------------------------------------------
# LLM アシスト（庁内のみ・HMAC 必須。ゲスト公開面には出さない）
# ---------------------------------------------------------------------------
@app.post("/assist/parse-dates")
async def assist_parse_dates(
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
    try:
        result = await assist.parse_dates_from_text(text)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"error": f"日程の解釈に失敗しました: {e}"},
        )
    return JSONResponse(content=result)


@app.post("/events/{event_id}/assist/recommend")
async def assist_recommend(
    event_id: str,
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
    try:
        result = await assist.recommend_slot(event_id)
    except LookupError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"error": f"最適日の提案に失敗しました: {e}"},
        )
    return JSONResponse(content=result)


@app.post("/events/{event_id}/assist/invite")
async def assist_invite(
    event_id: str,
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
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    tone = (body.get("tone") or "丁寧").strip() or "丁寧"
    try:
        result = await assist.draft_invite(event_id, tone=tone)
    except LookupError as e:
        return JSONResponse(status_code=404, content={"error": str(e)})
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502,
            content={"error": f"案内文の作成に失敗しました: {e}"},
        )
    return JSONResponse(content=result)


@app.post("/admin/cleanup")
def admin_cleanup(
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
    deleted = store.delete_old_events(RETENTION_DAYS)
    return JSONResponse(
        content={
            "success": True,
            "deleted_count": deleted,
            "message": f"{deleted}件の古いイベントを削除しました",
        }
    )


# ---------------------------------------------------------------------------
# 公開面（ゲスト）。公開プロキシはここだけ upstream すること。
# ---------------------------------------------------------------------------
@app.get("/public/api/events/{guest_token}")
def public_get_event(guest_token: str) -> JSONResponse:
    detail = store.event_detail(guest_token=guest_token)
    if not detail:
        return JSONResponse(status_code=404, content={"error": "イベントが見つかりません"})
    # 内部識別子はゲストに出さない
    ev = dict(detail["event"])
    ev.pop("creator_user_id", None)
    ev.pop("id", None)
    return JSONResponse(
        content={
            "event": ev,
            "dates": detail["dates"],
            "responses": [
                {
                    "participant_name": r["participant_name"],
                    "event_date_id": r["event_date_id"],
                    "status": r["status"],
                    "date_time": r["date_time"],
                }
                for r in detail["responses"]
            ],
            "statistics": detail["statistics"],
        }
    )


@app.post("/public/api/events/{guest_token}/responses")
async def public_submit_response(guest_token: str, request: Request) -> JSONResponse:
    body = await request.json()
    name = (body.get("participant_name") or "").strip()
    responses = body.get("responses")
    if not name or not isinstance(responses, list):
        return JSONResponse(status_code=400, content={"error": "参加者名と回答は必須です"})
    result, msg = store.submit_response(
        guest_token=guest_token,
        participant_name=name,
        responses=responses,
        password=body.get("password"),
        participant_user_id=None,
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "正しくありません" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(status_code=201, content=result)


@app.delete("/public/api/events/{guest_token}/participants/{participant_name}")
async def public_delete_participant(
    guest_token: str, participant_name: str, request: Request
) -> JSONResponse:
    body = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    msg = store.delete_participant(
        guest_token=guest_token,
        participant_name=participant_name,
        password=body.get("password"),
        actor_user_id=None,
    )
    if msg:
        code = 404 if "見つかりません" in msg else 403 if "正しくありません" in msg else 400
        return JSONResponse(status_code=code, content={"error": msg})
    return JSONResponse(content={"message": "参加者と回答を削除しました"})


@app.get("/public/e/{guest_token}", response_model=None)
def public_event_page(guest_token: str) -> FileResponse | HTMLResponse:
    return _public_html("event.html")


@app.get("/public/", response_class=HTMLResponse)
@app.get("/public", response_class=HTMLResponse)
def public_index() -> HTMLResponse:
    return HTMLResponse(
        "<!DOCTYPE html><html lang='ja'><head><meta charset='utf-8'>"
        "<title>日程調整</title></head><body>"
        "<p>イベントの共有リンクからアクセスしてください。</p></body></html>"
    )


if PUBLIC_DIR.is_dir():
    app.mount("/public/assets", StaticFiles(directory=str(PUBLIC_DIR)), name="public-assets")
