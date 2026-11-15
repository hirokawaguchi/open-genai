"""管理項目の提案、検索文の翻訳、申し送り文。モデルが止まっても定義は手で作れる。"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

FIELD_TYPES = ("text", "number", "date", "select", "longtext", "file")
_SECRET_LINE = re.compile(r"マイナンバー|個人番号")
_LONG_NUMBER = re.compile(r"\d{12}")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_NUM = re.compile(r"^-?\d+(?:[.,]\d+)?$")


def _infer(values: list[str]) -> dict[str, Any]:
    cleaned = [item.strip() for item in values if item and item.strip()]
    if not cleaned:
        return {"type": "text", "options": []}
    if all(_DATE.match(item) for item in cleaned):
        return {"type": "date", "options": []}
    if all(_NUM.match(item.replace(",", "")) for item in cleaned):
        return {"type": "number", "options": []}
    distinct = list(dict.fromkeys(cleaned))
    if 1 < len(distinct) <= 8 and len(cleaned) >= 3 and len(distinct) <= len(cleaned) / 2:
        return {"type": "select", "options": distinct[:12]}
    if sum(len(item) for item in cleaned) / len(cleaned) > 80:
        return {"type": "longtext", "options": []}
    return {"type": "text", "options": []}


def propose_fields(
    samples: list[dict[str, str]],
    *,
    existing_labels: list[str],
    note: str = "",
) -> list[dict[str, Any]]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for item in samples:
        label = str(item.get("label") or "").strip()
        if not label or label in existing_labels:
            continue
        if "マイナンバー" in label or "個人番号" in label:
            continue
        grouped[label].append(str(item.get("value") or ""))
    ranked = Counter({label: len(values) for label, values in grouped.items()})
    proposals = []
    for label, _count in ranked.most_common(20):
        inferred = _infer(grouped[label])
        proposals.append(
            {
                "id": "",
                "label": label,
                "type": inferred["type"],
                "masked": False,
                "options": inferred["options"],
                "seen": ranked[label],
            }
        )
    if note.strip() and not proposals:
        for line in note.splitlines():
            label = line.strip().lstrip("-・").strip()
            if label and label not in existing_labels:
                proposals.append(
                    {"id": "", "label": label[:80], "type": "text", "masked": False, "options": [], "seen": 0}
                )
    return proposals


def _month_range(today: datetime) -> tuple[str, str]:
    first = today.replace(day=1)
    prev_end = first - timedelta(days=1)
    prev_start = prev_end.replace(day=1)
    return prev_start.date().isoformat(), prev_end.date().isoformat()


def parse_query(text: str, statuses: list[str]) -> dict[str, str]:
    raw = text.strip()
    found = {"status": "", "assignee": "", "q": "", "date_from": "", "date_to": ""}
    if "先月" in raw:
        start, end = _month_range(datetime.now(timezone.utc))
        found["date_from"] = start
        found["date_to"] = end
        raw = raw.replace("先月", " ")
    for status in statuses:
        if status and status in raw:
            found["status"] = status
            raw = raw.replace(status, " ")
    parts = []
    for part in re.split(r"[\s、,]+", raw):
        part = part.strip("のをは")
        if part:
            parts.append(part)
    if parts:
        found["q"] = " ".join(parts)[:80]
    return found


def summarize(row: dict[str, Any], ledger: dict[str, Any]) -> str:
    labels = {item["id"]: item.get("label") or item["id"] for item in ledger.get("fields") or []}
    lines = [
        f"状態: {row.get('status') or '—'}",
        f"担当: {row.get('assignee') or '—'}",
    ]
    for fid, value in (row.get("fields") or {}).items():
        if value:
            lines.append(f"{labels.get(fid, fid)}: {value}")
    for extra in row.get("extras") or []:
        if extra.get("value"):
            lines.append(f"{extra.get('label')}: {extra.get('value')}")
    if row.get("comment"):
        lines.append(f"コメント: {row['comment']}")
    revisions = row.get("revisions") or []
    if revisions:
        lines.append(f"直近の変更: {len(revisions)} 件")
    return "\n".join(lines)


def sanitize_material(text: str) -> str:
    kept = []
    for line in text.splitlines():
        if _SECRET_LINE.search(line):
            continue
        kept.append(_LONG_NUMBER.sub("［番号］", line))
    return "\n".join(kept).strip()[:8000]


def fields_from_model(data: dict[str, Any], existing: list[str]) -> list[dict[str, Any]]:
    raw = data.get("fields")
    if not isinstance(raw, list):
        return []
    known = {item.strip() for item in existing if item and item.strip()}
    seen: set[str] = set()
    fields: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        label = str(item.get("label") or "").strip()[:80]
        if not label or label in known or label in seen:
            continue
        if "マイナンバー" in label or "個人番号" in label:
            continue
        kind = str(item.get("type") or "text").strip()
        if kind not in FIELD_TYPES:
            kind = "text"
        options: list[str] = []
        if kind == "select":
            for opt in item.get("options") or []:
                text = str(opt or "").strip()[:40]
                if text and text not in options:
                    options.append(text)
            if not options:
                kind = "text"
        fields.append(
            {
                "id": "",
                "label": label,
                "type": kind,
                "masked": False,
                "options": options[:30],
                "seen": 0,
            }
        )
        seen.add(label)
        if len(fields) >= 20:
            break
    return fields


def _llm_target() -> tuple[str, str, str]:
    base = (os.environ.get("OPENAI_BASE_URL") or "").rstrip("/")
    if not base:
        ollama = os.environ.get("OLLAMA_BASE_URL", "").rstrip("/")
        base = f"{ollama}/v1" if ollama else ""
    model = os.environ.get("LEDGER_MODEL") or os.environ.get("DEFAULT_MODEL") or "qwen2.5:7b"
    key = os.environ.get("OPENAI_API_KEY") or "ollama"
    return base, model, key


async def transcribe_image(data_url: str, timeout: float = 45) -> str | None:
    base, model, key = _llm_target()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "画像の資料に書かれている文字を、読めた順に書き出してください。説明は付けないでください。",
                                },
                                {"type": "image_url", "image_url": {"url": data_url}},
                            ],
                        }
                    ],
                },
            )
        res.raise_for_status()
        content = str(res.json()["choices"][0]["message"]["content"]).strip()
    except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None
    return content or None


async def complete_json(prompt: str, timeout: float = 20.0) -> dict[str, Any] | None:
    base, model, key = _llm_target()
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={
                    "model": model,
                    "temperature": 0,
                    "messages": [
                        {"role": "system", "content": "JSON だけを返してください。"},
                        {"role": "user", "content": prompt},
                    ],
                },
            )
        res.raise_for_status()
        content = str(res.json()["choices"][0]["message"]["content"])
    except (httpx.HTTPError, KeyError, IndexError, TypeError, json.JSONDecodeError):
        return None
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        data = json.loads(content[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None
