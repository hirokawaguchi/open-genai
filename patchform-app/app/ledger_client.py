"""手続きの確定から ledger-app へ行を書く。未設定のときは呼ばない。"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from . import files

LEDGER_APP_URL = os.environ.get("LEDGER_APP_URL", "").rstrip("/")
API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
TIMEOUT = float(os.environ.get("LEDGER_CLIENT_TIMEOUT", "15"))


class LedgerError(Exception):
    pass


def enabled() -> bool:
    return bool(LEDGER_APP_URL)


def _base() -> str:
    raw = LEDGER_APP_URL
    if raw.endswith("/invoke"):
        raw = raw[: -len("/invoke")]
    return raw.rstrip("/")


def _headers(forwarded: dict[str, str]) -> dict[str, str]:
    headers = {
        "x-api-key": API_KEY,
        "x-user-id": forwarded.get("x-user-id", ""),
        "x-user-groups": forwarded.get("x-user-groups", ""),
        "x-user-tags": forwarded.get("x-user-tags", ""),
        "x-scope": forwarded.get("x-scope", ""),
        "x-user-ts": forwarded.get("x-user-ts", ""),
        "x-user-sig": forwarded.get("x-user-sig", ""),
    }
    return headers


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except json.JSONDecodeError:
        body = {}
    if isinstance(body, dict) and body.get("error"):
        return str(body["error"])
    return "台帳に書けませんでした"


def values_from_snapshot(
    snapshot: dict[str, Any], field_map: list[dict[str, str]]
) -> tuple[dict[str, str], list[dict[str, str]]]:
    mapping = {
        str(item.get("label") or ""): str(item.get("field_id") or "")
        for item in field_map
        if item.get("label") and item.get("field_id")
    }
    fields: dict[str, str] = {}
    extras: list[dict[str, str]] = []
    for block in snapshot.get("answers") or []:
        if not isinstance(block, dict):
            continue
        for line in block.get("lines") or []:
            if not isinstance(line, dict):
                continue
            label = str(line.get("label") or "").strip()
            value = str(line.get("value") or "")
            if not label:
                continue
            target = mapping.get(label)
            if target:
                fields[target] = value
            else:
                extras.append({"label": label, "value": value})
    return fields, extras


def publish(
    *,
    forwarded: dict[str, str],
    procedure_id: str,
    procedure_name: str,
    ledger_id: str,
    statuses: list[str],
    grants: list[dict[str, str]],
    field_map: list[dict[str, str]],
    application_id: str,
    assignee: str,
    status: str,
    snapshot: dict[str, Any],
    copies: list[dict[str, str]],
) -> tuple[str, str]:
    """(台帳 ID, 行 ID)。失敗したら LedgerError。受理状態は呼び出し側で変えない。"""
    headers = _headers(forwarded)
    fields, extras = values_from_snapshot(snapshot, field_map)
    try:
        with httpx.Client(timeout=TIMEOUT) as client:
            if not ledger_id:
                if not grants:
                    teams = [
                        item.strip()
                        for item in forwarded.get("x-user-tags", "").split(",")
                        if item.strip()
                    ]
                    if teams:
                        grants = [{"team_id": teams[0], "role": "admin"}]
                created = client.post(
                    f"{_base()}/ledgers",
                    headers={**headers, "Content-Type": "application/json"},
                    json={
                        "name": procedure_name or "手続き",
                        "statuses": statuses or ["受理"],
                        "source_key": f"procedure:{procedure_id}",
                        "grants": grants,
                    },
                )
                if created.status_code >= 400:
                    raise LedgerError(_error_text(created))
                ledger_id = str(created.json().get("id") or "")
            if not ledger_id:
                raise LedgerError("台帳を用意できませんでした")
            saved = client.post(
                f"{_base()}/ledgers/{ledger_id}/rows",
                headers={**headers, "Content-Type": "application/json"},
                json={
                    "business_key": application_id,
                    "assignee": assignee,
                    "status": status,
                    "fields": fields,
                    "extras": extras,
                },
            )
            if saved.status_code >= 400:
                raise LedgerError(_error_text(saved))
            row_id = str(saved.json().get("id") or "")
            for item in copies:
                form_id = str(item.get("form_id") or "")
                file_id = str(item.get("file_id") or "")
                if not form_id or not file_id:
                    continue
                try:
                    path = files.stored_path(form_id, file_id)
                except ValueError:
                    continue
                if path is None or not path.is_file():
                    continue
                with path.open("rb") as handle:
                    uploaded = client.post(
                        f"{_base()}/rows/{row_id}/files",
                        headers=headers,
                        files={"upload": (str(item.get("filename") or file_id), handle, item.get("mime") or "application/octet-stream")},
                    )
                if uploaded.status_code >= 400:
                    raise LedgerError(_error_text(uploaded))
    except httpx.HTTPError as exc:
        raise LedgerError("台帳サービスに接続できませんでした") from exc
    return ledger_id, row_id
