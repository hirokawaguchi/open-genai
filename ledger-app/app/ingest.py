"""既存の台帳へ、資料から値の案を作る。保存は人が選んでから。"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from typing import Any

from . import assist, material, store

MAX_FILES = 3
MAX_ROWS = 30
_SPACE = re.compile(r"\s+")


def rows_from_table(text: str, fields: list[dict[str, Any]], file_index: int) -> list[dict[str, Any]]:
    by_label = {_norm(str(item.get("label") or "")): item for item in fields if item.get("type") != "file"}
    found: list[dict[str, Any]] = []
    for block in _blocks(text):
        grid = _grid(block)
        if len(grid) < 2:
            continue
        header = [_norm(cell) for cell in grid[0]]
        columns = [(index, by_label[name]) for index, name in enumerate(header) if name in by_label]
        if not columns:
            continue
        for cells in grid[1:]:
            values: dict[str, str] = {}
            origins: dict[str, dict[str, Any]] = {}
            for index, spec in columns:
                value = cells[index].strip() if index < len(cells) else ""
                if not value or store._check_value(spec, value):
                    continue
                fid = str(spec["id"])
                values[fid] = value
                origins[fid] = {"origin": "imported", "file_index": file_index}
            if values:
                found.append({"fields": values, "origins": origins, "file_indexes": [file_index]})
            if len(found) >= MAX_ROWS:
                return found
    return found


async def rows_from_model(
    fields: list[dict[str, Any]], documents: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    usable = [item for item in fields if item.get("type") != "file" and not _secret_label(str(item.get("label") or ""))]
    if not usable or not documents:
        return []
    catalog = [
        {
            "label": item.get("label"),
            "type": item.get("type"),
            "options": item.get("options") or [],
        }
        for item in usable
    ]
    body = "\n\n".join(f"# {item['name']}\n{item['text']}" for item in documents)
    prompt = (
        "次の資料から、指定された台帳の項目へ入れる値の案を出してください。"
        "資料にその値そのものが書いてある項目は origin を imported にしてください。"
        "書いていないが、資料から推測できる項目は origin を inferred にしてください。"
        "根拠の無い値は出さないでください。空の項目は出さないでください。"
        "資料に複数の対象があるときは、rows をその件数にしてください。"
        "状態は変えません。"
        'JSON は {"rows":[{"values":[{"label":"項目名","value":"値","origin":"imported","file":"ファイル名"}]}]} だけです。'
        f"項目: {json.dumps(catalog, ensure_ascii=False)}\n資料:\n{body}"
    )
    data = await assist.complete_json(prompt, timeout=25)
    if not data or not isinstance(data.get("rows"), list):
        return []
    by_label = {_norm(str(item.get("label") or "")): item for item in usable}
    names = {str(item["name"]): int(item["index"]) for item in documents}
    rows: list[dict[str, Any]] = []
    for raw in data["rows"]:
        if not isinstance(raw, dict):
            continue
        values: dict[str, str] = {}
        origins: dict[str, dict[str, Any]] = {}
        indexes: list[int] = []
        for item in raw.get("values") or []:
            if not isinstance(item, dict):
                continue
            spec = by_label.get(_norm(str(item.get("label") or "")))
            if spec is None:
                continue
            value = str(item.get("value") or "").strip()
            if not value or store._check_value(spec, value):
                continue
            origin = str(item.get("origin") or "")
            if origin not in ("imported", "inferred"):
                origin = "inferred"
            fid = str(spec["id"])
            values[fid] = value
            file_index = names.get(str(item.get("file") or ""))
            if file_index is None and len(documents) == 1:
                file_index = int(documents[0]["index"])
            entry: dict[str, Any] = {"origin": origin}
            if file_index is not None:
                entry["file_index"] = file_index
                if file_index not in indexes:
                    indexes.append(file_index)
            origins[fid] = entry
        if values:
            if not indexes:
                indexes = [int(item["index"]) for item in documents]
            rows.append({"fields": values, "origins": origins, "file_indexes": indexes})
        if len(rows) >= MAX_ROWS:
            break
    return rows


def public_rows(rows: list[dict[str, Any]], files: list[dict[str, Any]], fields: list[dict[str, Any]]) -> list[dict[str, Any]]:
    labels = {str(item.get("id")): str(item.get("label") or item.get("id")) for item in fields}
    shown = []
    for index, row in enumerate(rows):
        values = []
        for fid, value in (row.get("fields") or {}).items():
            origin = (row.get("origins") or {}).get(fid) or {}
            slot = origin.get("file_index")
            name = ""
            if isinstance(slot, int) and 0 <= slot < len(files):
                name = str(files[slot].get("name") or "")
            values.append(
                {
                    "id": fid,
                    "label": labels.get(str(fid), str(fid)),
                    "value": value,
                    "origin": origin.get("origin") or "inferred",
                    "file_name": name,
                }
            )
        if values:
            shown.append({"index": index, "values": values})
    return shown


def stage_batch(
    ledger_id: str,
    user_id: str,
    files: list[dict[str, Any]],
    rows: list[dict[str, Any]],
) -> str:
    batch_id = str(uuid.uuid4())
    root = store.files_root() / "_staging" / batch_id
    root.mkdir(parents=True, exist_ok=True)
    stored = []
    for index, item in enumerate(files):
        (root / str(index)).write_bytes(item["raw"])
        stored.append({"name": item["name"], "mime": item["mime"]})
    manifest = {
        "ledger_id": ledger_id,
        "user_id": user_id,
        "files": stored,
        "rows": rows,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return batch_id


def load_batch(batch_id: str) -> dict[str, Any] | None:
    path = store.files_root() / "_staging" / batch_id / "manifest.json"
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def commit_batch(actor: store.Actor, ledger_id: str, batch_id: str, indexes: list[int]) -> tuple[int, str | None]:
    manifest = load_batch(batch_id)
    if manifest is None or manifest.get("ledger_id") != ledger_id or manifest.get("user_id") != actor.user_id:
        return 0, "読み込んだ資料が見つかりません。もう一度選んでください"
    rows = manifest.get("rows") or []
    if not isinstance(rows, list):
        return 0, "読み込んだ資料が見つかりません。もう一度選んでください"
    ledger, err = store.get_ledger(actor, ledger_id)
    if err or ledger is None:
        return 0, err
    status = (ledger.get("statuses") or [""])[0]
    root = store.files_root() / "_staging" / batch_id
    count = 0
    for index in indexes:
        if index < 0 or index >= len(rows) or not isinstance(rows[index], dict):
            return count, "選んだ行が見つかりません"
        proposal = rows[index]
        saved, msg = store.upsert_row(
            actor,
            ledger_id,
            {"status": status, "fields": proposal.get("fields") or {}, "origins": proposal.get("origins") or {}},
        )
        if msg or saved is None:
            return count, msg
        file_ids: dict[int, str] = {}
        for file_index in proposal.get("file_indexes") or []:
            try:
                slot = int(file_index)
            except (TypeError, ValueError):
                continue
            info = (manifest.get("files") or [None])[slot] if slot < len(manifest.get("files") or []) else None
            blob = root / str(slot)
            if not isinstance(info, dict) or not blob.is_file() or slot in file_ids:
                continue
            attached, ferr = store.add_file(
                actor,
                saved["id"],
                filename=str(info.get("name") or "資料"),
                mime=str(info.get("mime") or "application/octet-stream"),
                data=blob.read_bytes(),
            )
            if ferr or attached is None:
                return count, ferr
            files = attached.get("files") or []
            if files:
                file_ids[slot] = str(files[-1].get("file_id") or "")
        origins = {}
        for fid, item in (proposal.get("origins") or {}).items():
            if not isinstance(item, dict):
                continue
            entry = {"origin": item.get("origin") or "inferred"}
            slot = item.get("file_index")
            if slot in file_ids and file_ids[slot]:
                entry["file_id"] = file_ids[slot]
            origins[str(fid)] = entry
        if origins:
            updated, uerr = store.upsert_row(
                actor,
                ledger_id,
                {"business_key": saved["business_key"], "origins": origins, "fields": proposal.get("fields") or {}},
            )
            if uerr or updated is None:
                return count, uerr
        count += 1
    _remove_batch(batch_id)
    return count, None


def _remove_batch(batch_id: str) -> None:
    root = store.files_root() / "_staging" / batch_id
    if not root.is_dir():
        return
    for child in root.iterdir():
        if child.is_file():
            child.unlink()
    root.rmdir()


def _blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("# "):
            if buf:
                blocks.append(buf)
                buf = []
            continue
        if line.strip() and line.strip() != "…":
            buf.append(line)
    if buf:
        blocks.append(buf)
    return blocks


def _grid(lines: list[str]) -> list[list[str]]:
    sample = "\n".join(lines)
    if "\t" in sample:
        return [line.split("\t") for line in lines]
    if "," in lines[0]:
        return [row for row in csv.reader(io.StringIO("\n".join(lines)))]
    return []


def _norm(value: str) -> str:
    return _SPACE.sub("", value).strip().lower()


def _secret_label(label: str) -> bool:
    return "マイナンバー" in label or "個人番号" in label
