"""ノートの項目を、Markdown エディタの編集画面へ渡す。

シートは職員に渡さない。エディタの「ヒアリングシートから生成」を、
ログイン中の利用者の範囲で起動するだけである。合成（compose）は呼ばない。
"""

from __future__ import annotations

import base64
import re
from typing import Any
from urllib.parse import quote

import httpx

_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class HandoffError(Exception):
    def __init__(self, status: int, message: str, project_id: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.project_id = project_id


def _error_text(res: httpx.Response, fallback: str) -> str:
    try:
        body: Any = res.json()
    except Exception:  # noqa: BLE001
        return fallback
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return fallback


async def _ensure_project(
    client: httpx.AsyncClient,
    *,
    editor_base: str,
    editor_headers: dict[str, str],
    mode: str,
    name: str,
    project_id: str,
) -> tuple[str, str]:
    if mode not in ("new", "existing"):
        raise HandoffError(400, "渡し先を選んでください。")
    base = editor_base.rstrip("/")
    if mode == "new":
        title = name.strip()
        if not title:
            raise HandoffError(400, "プロジェクト名を入力してください。")
        created = await client.post(
            f"{base}/projects", headers=editor_headers, json={"name": title}
        )
        if created.status_code != 200:
            raise HandoffError(
                created.status_code,
                _error_text(created, "プロジェクトを作成できませんでした。"),
            )
        pid = str((created.json().get("project") or {}).get("id") or "")
        if not pid:
            raise HandoffError(502, "プロジェクトを作成できませんでした。")
        return base, pid
    pid = project_id.strip()
    if not pid:
        raise HandoffError(400, "プロジェクトを選んでください。")
    found = await client.get(
        f"{base}/projects/{quote(pid, safe='')}", headers=editor_headers
    )
    if found.status_code != 200:
        raise HandoffError(
            found.status_code,
            _error_text(found, "プロジェクトが見つかりません。"),
        )
    return base, pid


def manuscript_filename(title: str, form: str, taken: set[str]) -> str:
    """文書とスライドを別の名前にし、すでにあるファイルは残す。"""
    kind = "スライド" if form == "slides" else "文書"
    stem = _UNSAFE_NAME.sub(" ", title or "").strip()
    stem = re.sub(r"\s+", " ", stem).strip(" .")[:40] or "原稿"
    base = f"{stem}-{kind}"
    name = f"{base}.md"
    n = 2
    while name in taken and n < 100:
        name = f"{base}-{n}.md"
        n += 1
    return name


def _taken_paths(payload: Any) -> set[str]:
    files = payload.get("files") if isinstance(payload, dict) else None
    if not isinstance(files, list):
        return set()
    taken: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("rel_path") or item.get("path") or "").strip()
        if path:
            taken.add(path)
    return taken


async def place_manuscript(
    client: httpx.AsyncClient,
    *,
    editor_base: str,
    editor_headers: dict[str, str],
    mode: str,
    name: str,
    project_id: str,
    manuscript: str,
    form: str = "",
    title: str = "",
) -> dict[str, Any]:
    """書き終えた原稿をプロジェクトへ置き、エディタでは生成しない。"""
    base, pid = await _ensure_project(
        client,
        editor_base=editor_base,
        editor_headers=editor_headers,
        mode=mode,
        name=name,
        project_id=project_id,
    )
    listed = await client.get(
        f"{base}/projects/{quote(pid, safe='')}/files",
        headers=editor_headers,
    )
    taken = _taken_paths(listed.json()) if listed.status_code == 200 else set()
    path = manuscript_filename(title or name, form, taken)
    saved = await client.post(
        f"{base}/projects/{quote(pid, safe='')}/files/save",
        headers=editor_headers,
        json={"path": path, "content": manuscript},
    )
    if saved.status_code != 200:
        raise HandoffError(
            saved.status_code,
            _error_text(saved, "原稿を置けませんでした。"),
            project_id=pid,
        )
    return {"project_id": pid, "ready": True, "file": path}


async def open_in_editor(
    client: httpx.AsyncClient,
    *,
    download_url: str,
    editor_base: str,
    notebook_headers: dict[str, str],
    editor_headers: dict[str, str],
    mode: str,
    name: str,
    project_id: str,
) -> dict[str, str]:
    """記入済みシートを作り、新規または既存プロジェクトで生成を始める。"""
    sheet = await client.get(download_url, headers=notebook_headers)
    if sheet.status_code != 200 or not sheet.content.startswith(b"PK"):
        raise HandoffError(
            sheet.status_code if sheet.status_code != 200 else 502,
            _error_text(sheet, "シートを用意できませんでした。"),
        )
    encoded = base64.b64encode(sheet.content).decode("ascii")
    base, pid = await _ensure_project(
        client,
        editor_base=editor_base,
        editor_headers=editor_headers,
        mode=mode,
        name=name,
        project_id=project_id,
    )
    started = await client.post(
        f"{base}/projects/{quote(pid, safe='')}/generate",
        headers=editor_headers,
        json={"theme": "hearing", "inputs": {"hearing": encoded}},
    )
    if started.status_code != 200:
        raise HandoffError(
            started.status_code,
            _error_text(started, "文書の生成を開始できませんでした。"),
            project_id=pid,
        )
    request_id = str(started.json().get("request_id") or "")
    if not request_id:
        raise HandoffError(502, "文書の生成を開始できませんでした。", project_id=pid)
    return {"project_id": pid, "request_id": request_id}
