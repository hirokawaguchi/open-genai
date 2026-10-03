"""二週間の仕事。画面と受付鍵は、定型を一つ指定する同じ登録操作を使う。"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from app import intauth, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

app = FastAPI(title="nishukan-app", docs_url=None, redoc_url=None)


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()


def _error(exc: store.NishukanError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": exc.message})


def _verify_user(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
    x_nishukan_access: str | None,
) -> JSONResponse | store.Access:
    if (x_api_key or "") != API_KEY:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    encoded = x_nishukan_access or ""
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if not x_scope or digest != x_scope:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    try:
        payload = json.loads(base64.b64decode(encoded))
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    try:
        return store.parse_access(payload)
    except store.NishukanError as e:
        return _error(e)


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
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    return JSONResponse(content={"enabled": True})


@app.get("/home")
def home(
    teamId: str | None = None,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.home(access, teamId))
    except store.NishukanError as e:
        return _error(e)


@app.put("/teams/{team_id}/chief")
def put_chief(
    team_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.set_chief(access, team_id, str(body.get("userId") or "")))
    except store.NishukanError as e:
        return _error(e)


@app.put("/teams/{team_id}/headcount")
def put_headcount(
    team_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.set_headcount(access, team_id, body.get("headcount")))
    except store.NishukanError as e:
        return _error(e)


@app.put("/teams/{team_id}/vacation")
def put_vacation(
    team_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(
            content=store.set_vacation(
                access,
                team_id,
                str(body.get("timeboxStart") or ""),
                body.get("size"),
            )
        )
    except store.NishukanError as e:
        return _error(e)


@app.post("/projects")
def post_project(
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.create_project(access, body))
    except store.NishukanError as e:
        return _error(e)


@app.patch("/projects/{project_id}")
def patch_project(
    project_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.update_project(access, project_id, body))
    except store.NishukanError as e:
        return _error(e)


@app.delete("/projects/{project_id}")
def delete_project(
    project_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.delete_project(access, project_id))
    except store.NishukanError as e:
        return _error(e)


@app.post("/projects/{project_id}/members")
def post_member(
    project_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(
            content=store.add_member(
                access, project_id, str(body.get("userId") or ""), str(body.get("role") or "")
            )
        )
    except store.NishukanError as e:
        return _error(e)


@app.post("/templates")
def post_template(
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.create_template(access, body))
    except store.NishukanError as e:
        return _error(e)


@app.patch("/templates/{template_id}")
def patch_template(
    template_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.update_template(access, template_id, body))
    except store.NishukanError as e:
        return _error(e)


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
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.delete_template(access, template_id))
    except store.NishukanError as e:
        return _error(e)


@app.post("/templates/{template_id}/receipt-key")
def post_receipt_key(
    template_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.issue_receipt_key(access, template_id))
    except store.NishukanError as e:
        return _error(e)


@app.delete("/templates/{template_id}/receipt-key")
def delete_receipt_key(
    template_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.revoke_receipt_key(access, template_id))
    except store.NishukanError as e:
        return _error(e)


@app.post("/templates/{template_id}/arrivals")
async def post_arrival(
    template_id: str,
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    body = await _json_body(request)
    try:
        return JSONResponse(
            content=store.arrive(
                template_id,
                access=access,
                event_id=body.get("eventId"),
                title=body.get("title"),
            )
        )
    except store.NishukanError as e:
        return _error(e)


@app.post("/arrivals/{template_id}")
async def post_arrival_with_key(
    template_id: str,
    request: Request,
    x_receipt_key: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
) -> JSONResponse:
    if (x_api_key or "") != API_KEY:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    body = await _json_body(request)
    try:
        return JSONResponse(
            content=store.arrive(
                template_id,
                receipt_key=x_receipt_key,
                event_id=body.get("eventId"),
                title=body.get("title"),
            )
        )
    except store.NishukanError as e:
        return _error(e)


@app.delete("/issues/{issue_id}")
def delete_issue(
    issue_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.undo_issue(access, issue_id))
    except store.NishukanError as e:
        return _error(e)


@app.post("/issues")
def post_issue(
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.create_issue(access, body))
    except store.NishukanError as e:
        return _error(e)


@app.get("/issues/{issue_id}")
def get_issue(
    issue_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.get_issue(access, issue_id))
    except store.NishukanError as e:
        return _error(e)


@app.patch("/issues/{issue_id}")
def patch_issue(
    issue_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.update_issue(access, issue_id, body))
    except store.NishukanError as e:
        return _error(e)


@app.post("/issues/{issue_id}/checks/{check_id}")
def post_check(
    issue_id: str,
    check_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.set_check(access, issue_id, check_id, bool(body.get("done"))))
    except store.NishukanError as e:
        return _error(e)


@app.post("/issues/{issue_id}/comments")
def post_comment(
    issue_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.add_comment(access, issue_id, str(body.get("body") or "")))
    except store.NishukanError as e:
        return _error(e)


@app.post("/teams/{team_id}/holidays")
def post_holidays(
    team_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_nishukan_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _verify_user(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_nishukan_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(
            content=store.apply_holidays(
                access,
                team_id,
                str(body.get("timeboxStart") or ""),
                str(body.get("projectId") or ""),
                body.get("size"),
            )
        )
    except store.NishukanError as e:
        return _error(e)


async def _json_body(request: Request) -> dict:
    raw = await request.body()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
