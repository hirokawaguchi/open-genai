"""研修 LMS。画面は源内の /lms。起動は Compose profile lms。"""

from __future__ import annotations

import base64
import hashlib
import json
import os

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

from app import intauth, store

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

app = FastAPI(title="lms-app", docs_url=None, redoc_url=None)


@app.on_event("startup")
def on_startup() -> None:
    store.init_db()


def _error(exc: store.LmsError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"error": exc.message})


def _verify(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
    x_lms_access: str | None,
) -> JSONResponse | store.Access:
    if (x_api_key or "") != API_KEY:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    encoded = x_lms_access or ""
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    if not x_scope or digest != x_scope:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    try:
        payload = json.loads(base64.b64decode(encoded))
    except (json.JSONDecodeError, ValueError):
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    try:
        return store.parse_access(payload)
    except store.LmsError as e:
        return _error(e)


def _access(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse | store.Access:
    return _verify(
        x_api_key,
        x_user_id,
        x_user_groups,
        x_scope,
        x_user_ts,
        x_user_sig,
        x_user_tags,
        x_lms_access,
    )


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
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    return JSONResponse(content={"enabled": True})


@app.get("/home")
def get_home(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.home(access))
    except store.LmsError as e:
        return _error(e)


@app.get("/materials")
def get_materials(
    view: str = "active",
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    if view not in ("active", "trash"):
        return JSONResponse(status_code=400, content={"error": "一覧の指定が不正です"})
    try:
        return JSONResponse(content=store.list_materials(access, trashed=view == "trash"))
    except store.LmsError as e:
        return _error(e)


@app.post("/materials/sessions")
def post_session(
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.start_upload(access, body))
    except store.LmsError as e:
        return _error(e)


@app.get("/materials/sessions/{session_id}")
def get_session(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.upload_progress(access, session_id))
    except store.LmsError as e:
        return _error(e)


@app.put("/materials/sessions/{session_id}")
async def put_session_part(
    session_id: str,
    request: Request,
    x_part_index: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        index = int(x_part_index or "0")
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "分割番号が不正です"})
    try:
        body = await request.body()
        return JSONResponse(content=store.append_part(access, session_id, index, body))
    except store.LmsError as e:
        return _error(e)


@app.post("/materials/sessions/{session_id}/complete")
def post_session_complete(
    session_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.complete_upload(access, session_id))
    except store.LmsError as e:
        return _error(e)


@app.patch("/materials/{material_id}")
def patch_material(
    material_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.rename_material(access, material_id, str(body.get("title") or "")))
    except store.LmsError as e:
        return _error(e)


@app.post("/materials/{material_id}/hide")
def post_hide_material(
    material_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.hide_material(access, material_id))
    except store.LmsError as e:
        return _error(e)


@app.post("/materials/{material_id}/restore")
def post_restore_material(
    material_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.restore_material(access, material_id))
    except store.LmsError as e:
        return _error(e)


@app.delete("/materials/{material_id}")
def delete_material(
    material_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.delete_material(access, material_id))
    except store.LmsError as e:
        return _error(e)


def _access_from(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
    x_lms_access: str | None,
):
    return _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )


@app.get("/materials/{material_id}/transcript")
def get_material_transcript(
    material_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access_from(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.get_transcript(access, material_id))
    except store.LmsError as e:
        return _error(e)


@app.post("/materials/{material_id}/transcript")
def post_material_transcript(
    material_id: str,
    body: dict | None = None,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access_from(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        redo = bool((body or {}).get("redo"))
        return JSONResponse(content=store.start_transcript(access, material_id, redo=redo))
    except store.LmsError as e:
        return _error(e)


@app.put("/materials/{material_id}/transcript")
def put_material_transcript(
    material_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    access = _access_from(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.save_transcript(access, material_id, body))
    except store.LmsError as e:
        return _error(e)


@app.post("/materials/{material_id}/transcript/confirm")
def post_material_transcript_confirm(
    material_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access_from(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.confirm_transcript(access, material_id))
    except store.LmsError as e:
        return _error(e)


@app.post("/courses")
def post_course(
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.create_course(access, str(body.get("title") or "")))
    except store.LmsError as e:
        return _error(e)


@app.get("/courses/{course_id}")
def get_course(
    course_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.get_course(access, course_id))
    except store.LmsError as e:
        return _error(e)


@app.delete("/courses/{course_id}")
def delete_course(
    course_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.delete_course(access, course_id))
    except store.LmsError as e:
        return _error(e)


@app.put("/courses/{course_id}/draft")
def put_draft(
    course_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.save_draft(access, course_id, body))
    except store.LmsError as e:
        return _error(e)


@app.post("/courses/{course_id}/publish")
def post_publish(
    course_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.publish_course(access, course_id))
    except store.LmsError as e:
        return _error(e)


@app.post("/courses/{course_id}/roles")
def post_role(
    course_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(
            content=store.set_role(access, course_id, str(body.get("userId") or ""), str(body.get("role") or ""))
        )
    except store.LmsError as e:
        return _error(e)


@app.delete("/courses/{course_id}/roles")
def delete_role(
    course_id: str,
    userId: str,
    role: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.remove_role(access, course_id, userId, role))
    except store.LmsError as e:
        return _error(e)


@app.post("/courses/{course_id}/assignments")
def post_assignment(
    course_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.set_assignment(access, course_id, body))
    except store.LmsError as e:
        return _error(e)


@app.delete("/courses/{course_id}/assignments/{assignment_id}")
def delete_assignment(
    course_id: str,
    assignment_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.remove_assignment(access, course_id, assignment_id))
    except store.LmsError as e:
        return _error(e)


@app.get("/courses/{course_id}/preview")
def get_preview(
    course_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.preview_course(access, course_id))
    except store.LmsError as e:
        return _error(e)


@app.get("/courses/{course_id}/progress.csv")
def get_progress_csv(
    course_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> Response:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        text = store.progress_csv(access, course_id)
    except store.LmsError as e:
        return _error(e)
    return Response(
        content="\ufeff" + text,
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": "attachment; filename=lms-progress.csv"},
    )


@app.get("/courses/{course_id}/progress")
def get_progress(
    course_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.progress(access, course_id))
    except store.LmsError as e:
        return _error(e)


@app.post("/learn/{course_id}/start")
def post_start(
    course_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.start_enrollment(access, course_id))
    except store.LmsError as e:
        return _error(e)


@app.get("/learn/{enrollment_id}")
def get_learn(
    enrollment_id: str,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.get_enrollment(access, enrollment_id))
    except store.LmsError as e:
        return _error(e)


@app.post("/learn/{enrollment_id}/lessons/{lesson_id}/progress")
def post_progress(
    enrollment_id: str,
    lesson_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(content=store.record_progress(access, enrollment_id, lesson_id, body))
    except store.LmsError as e:
        return _error(e)


@app.post("/learn/{enrollment_id}/lessons/{lesson_id}/quiz")
def post_quiz(
    enrollment_id: str,
    lesson_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(
            content=store.submit_quiz(access, enrollment_id, lesson_id, list(body.get("answers") or []))
        )
    except store.LmsError as e:
        return _error(e)


@app.post("/learn/{enrollment_id}/lessons/{lesson_id}/grade")
def post_grade(
    enrollment_id: str,
    lesson_id: str,
    body: dict,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
    x_lms_access: str | None = Header(default=None),
) -> JSONResponse:
    access = _access(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags, x_lms_access
    )
    if isinstance(access, JSONResponse):
        return access
    try:
        return JSONResponse(
            content=store.grade_practical(
                access,
                enrollment_id,
                lesson_id,
                str(body.get("lesson_status") or ""),
                body.get("score_raw"),
            )
        )
    except store.LmsError as e:
        return _error(e)
