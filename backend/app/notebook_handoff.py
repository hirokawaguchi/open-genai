"""ノートの項目を、Markdown エディタの編集画面へ渡す。

シートは職員に渡さない。エディタの「ヒアリングシートから生成」を、
ログイン中の利用者の範囲で起動するだけである。合成（compose）は呼ばない。
"""

from __future__ import annotations

import base64
from typing import Any
from urllib.parse import quote

import httpx


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
    if mode not in ("new", "existing"):
        raise HandoffError(400, "渡し先を選んでください。")
    sheet = await client.get(download_url, headers=notebook_headers)
    if sheet.status_code != 200 or not sheet.content.startswith(b"PK"):
        raise HandoffError(
            sheet.status_code if sheet.status_code != 200 else 502,
            _error_text(sheet, "シートを用意できませんでした。"),
        )
    encoded = base64.b64encode(sheet.content).decode("ascii")
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
    else:
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
