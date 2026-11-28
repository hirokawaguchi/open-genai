"""日程調整の候補を整え、確認後に案件を1件作る。招待は送らない。"""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:\d{2})?$"
)


def chosei_base() -> str:
    raw = os.environ.get("CHOSEI_URL", "http://chosei-app:8010").strip().rstrip("/")
    if raw.endswith("/invoke"):
        raw = raw[: -len("/invoke")]
    return raw


def normalize_dates(raw: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    if not isinstance(raw, list) or not raw:
        return None, "候補日がありません。日付が決まっていなければ、一度だけ聞いて止めてください。"
    if len(raw) > 12:
        return None, "候補日は12件までです。"
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, str):
            start, end, all_day, err = _one_date(item, None, False)
        elif isinstance(item, dict):
            start, end, all_day, err = _one_date(
                item.get("start_time"),
                item.get("end_time"),
                bool(item.get("is_all_day")),
            )
        else:
            return None, "候補日は YYYY-MM-DD または YYYY-MM-DDTHH:MM で渡してください。"
        if err or not start:
            return None, err or "候補日の形式が不正です。"
        out.append({"start_time": start, "end_time": end, "is_all_day": all_day})
    return out, None


def _one_date(
    start_raw: Any, end_raw: Any, all_day: bool
) -> tuple[str, str | None, bool, str | None]:
    start = str(start_raw or "").strip()
    if _DATE.fullmatch(start):
        return start, None, True, None
    if not _DATETIME.fullmatch(start):
        return "", None, False, "候補日は YYYY-MM-DD または YYYY-MM-DDTHH:MM で渡してください。"
    end = str(end_raw or "").strip()
    if all_day:
        return start, None, True, None
    if not end:
        return start, None, False, None
    if not _DATETIME.fullmatch(end):
        return "", None, False, "終了日時は YYYY-MM-DDTHH:MM で渡してください。"
    return start, end, False, None


def proposal(title: str, description: str, dates: Any) -> tuple[dict[str, Any] | None, str | None]:
    name = title.strip()
    if not name:
        return None, "タイトルがありません。一度だけ聞いて止めてください。"
    if len(name) > 80:
        return None, "タイトルは80文字までです。"
    body = description.strip()
    if len(body) > 1000:
        return None, "説明は1000文字までです。"
    normalized, err = normalize_dates(dates)
    if err or normalized is None:
        return None, err or "候補日がありません。"
    return {
        "status": "proposed",
        "title": name,
        "description": body,
        "dates": normalized,
        "event_id": "",
    }, None


async def create_event(
    headers: dict[str, str], proposal_body: dict[str, Any]
) -> tuple[str, str]:
    """案件 ID と、失敗したときの案内。成功するまで ID は空。"""
    base = chosei_base()
    if not base:
        return "", "日程調整が止まっています。案件は作っていません。"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                f"{base}/events",
                headers=headers,
                json={
                    "title": proposal_body.get("title") or "",
                    "description": proposal_body.get("description") or "",
                    "dates": proposal_body.get("dates") or [],
                },
            )
    except Exception as exc:  # noqa: BLE001
        print(f"[notebook-schedule] 日程調整へ接続できません: {exc}")
        return "", "日程調整が止まっています。案件は作っていません。"
    if res.status_code >= 400:
        print(f"[notebook-schedule] 作成に失敗 status={res.status_code}")
        return "", "案件を作れませんでした。招待は送っていません。"
    try:
        payload = res.json()
    except ValueError:
        return "", "案件を作れませんでした。招待は送っていません。"
    event = payload.get("event") if isinstance(payload, dict) else None
    event_id = str((event or {}).get("id") or "").strip()
    if not event_id:
        return "", "案件を作れませんでした。招待は送っていません。"
    return event_id, ""
