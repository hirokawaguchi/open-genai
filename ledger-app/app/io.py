"""行の JSON / JSONL / CSV。定義の変更はしない。"""

from __future__ import annotations

import csv
import io
import json
from typing import Any

from .store import Actor


def _visible_fields(ledger: dict[str, Any], actor_role: str | None) -> list[dict[str, Any]]:
    fields = ledger.get("fields") or []
    if actor_role in ("admin", "editor"):
        return list(fields)
    return [item for item in fields if not item.get("masked")]


def export_document(ledger: dict[str, Any], rows: list[dict[str, Any]], *, role: str | None) -> dict[str, Any]:
    fields = _visible_fields(ledger, role)
    allowed = {item["id"] for item in fields}
    slim = []
    for row in rows:
        values = {key: value for key, value in (row.get("fields") or {}).items() if key in allowed}
        slim.append(
            {
                "business_key": row.get("business_key") or "",
                "assignee": row.get("assignee") or "",
                "status": row.get("status") or "",
                "comment": row.get("comment") or "",
                "fields": values,
                "extras": row.get("extras") or [],
                "files": [
                    {"file_id": item.get("file_id"), "name": item.get("name")}
                    for item in row.get("files") or []
                ],
            }
        )
    return {
        "ledger": {
            "name": ledger.get("name") or "",
            "fields": [
                {"id": item["id"], "label": item.get("label"), "type": item.get("type")}
                for item in fields
            ],
        },
        "rows": slim,
    }


def export_jsonl(document: dict[str, Any]) -> str:
    return "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in document["rows"])


def export_csv(document: dict[str, Any]) -> str:
    fields = document["ledger"]["fields"]
    header = ["business_key", "status", "assignee", "comment", *[item["label"] for item in fields]]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(header)
    ids = [item["id"] for item in fields]
    for row in document["rows"]:
        values = row.get("fields") or {}
        writer.writerow(
            [
                row.get("business_key") or "",
                row.get("status") or "",
                row.get("assignee") or "",
                row.get("comment") or "",
                *[values.get(fid, "") for fid in ids],
            ]
        )
    return "\ufeff" + buf.getvalue()


def parse_json_import(text: str, ledger: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None, "JSON を読めません"
    if isinstance(data, list):
        rows = data
        declared = []
    elif isinstance(data, dict):
        rows = data.get("rows")
        declared = (data.get("ledger") or {}).get("fields") or []
    else:
        return None, "JSON を読めません"
    if not isinstance(rows, list):
        return None, "行の配列がありません"
    labels = {str(item.get("id")): str(item.get("label") or item.get("id")) for item in declared if isinstance(item, dict)}
    known = {str(item.get("id")) for item in ledger.get("fields") or []}
    parsed: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            return None, "行を読めません"
        fields = {}
        extras = []
        for item in row.get("extras") or []:
            if isinstance(item, dict) and str(item.get("label") or "").strip():
                extras.append({"label": str(item.get("label")), "value": str(item.get("value") or "")})
        for fid, value in (row.get("fields") or {}).items():
            if str(fid) in known:
                fields[str(fid)] = value
            else:
                extras.append({"label": labels.get(str(fid), str(fid)), "value": str(value or "")})
        parsed.append(
            {
                "business_key": str(row.get("business_key") or ""),
                "status": row.get("status"),
                "assignee": row.get("assignee"),
                "comment": row.get("comment"),
                "fields": fields,
                "extras": extras,
            }
        )
    return parsed, None


def parse_jsonl_import(text: str, ledger: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            return None, "JSONL を読めません"
        rows.append(item)
    return parse_json_import(json.dumps(rows), ledger)


def parse_csv_import(text: str, ledger: dict[str, Any]) -> tuple[list[dict[str, Any]] | None, str | None]:
    sample = text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(sample))
    if reader.fieldnames is None:
        return None, "CSV の見出しがありません"
    system = {"business_key", "status", "assignee", "comment"}
    by_label = {str(item.get("label")): str(item.get("id")) for item in ledger.get("fields") or []}
    unknown = [name for name in reader.fieldnames if name and name not in system and name not in by_label]
    if unknown:
        return None, "CSV に定義の無い列があります: " + "、".join(unknown[:5])
    parsed = []
    for row in reader:
        fields = {}
        for label, fid in by_label.items():
            if label in row and row[label] is not None:
                fields[fid] = row[label]
        parsed.append(
            {
                "business_key": str(row.get("business_key") or ""),
                "status": row.get("status") or None,
                "assignee": row.get("assignee"),
                "comment": row.get("comment"),
                "fields": fields,
            }
        )
    return parsed, None


def apply_import(actor: Actor, ledger_id: str, rows: list[dict[str, Any]]) -> tuple[int, str | None]:
    from . import store

    count = 0
    for row in rows:
        body = {key: value for key, value in row.items() if value is not None}
        if not body.get("business_key"):
            return count, "業務キーが空の行があります"
        saved, err = store.upsert_row(actor, ledger_id, body)
        if err or saved is None:
            return count, err
        count += 1
    return count, None
