"""日程調整向け LLM アシスト（最適日提案・自然文パース・案内文）。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import llm, store

JST = ZoneInfo("Asia/Tokyo")


def _matrix_summary(detail: dict[str, Any]) -> dict[str, Any]:
    dates = detail["dates"]
    responses = detail["responses"]
    stats = detail["statistics"]
    participants: list[str] = []
    seen: set[str] = set()
    for r in responses:
        if r["participant_name"] not in seen:
            seen.add(r["participant_name"])
            participants.append(r["participant_name"])
    by_person: dict[str, dict[int, str]] = {}
    for r in responses:
        by_person.setdefault(r["participant_name"], {})[r["event_date_id"]] = r["status"]
    rows = []
    for d in dates:
        st = stats.get(str(d["id"])) or {}
        cells = {
            name: by_person.get(name, {}).get(d["id"], "—") for name in participants
        }
        rows.append(
            {
                "date_id": d["id"],
                "date_time": d["date_time"],
                "end_time": d.get("end_time"),
                "is_all_day": d.get("is_all_day"),
                "ok": st.get("ok", 0),
                "maybe": st.get("maybe", 0),
                "ng": st.get("ng", 0),
                "answers": cells,
            }
        )
    return {
        "title": detail["event"]["title"],
        "description": detail["event"].get("description"),
        "participants": participants,
        "rows": rows,
    }


def heuristic_recommend(detail: dict[str, Any]) -> dict[str, Any]:
    """LLM なしのフォールバック: ○多く ×少ない順。"""
    rows = []
    for d in detail["dates"]:
        st = detail["statistics"].get(str(d["id"])) or {}
        ok = int(st.get("ok", 0))
        maybe = int(st.get("maybe", 0))
        ng = int(st.get("ng", 0))
        score = ok * 2 + maybe - ng * 3
        rows.append(
            {
                "date_id": d["id"],
                "date_time": d["date_time"],
                "end_time": d.get("end_time"),
                "is_all_day": bool(d.get("is_all_day")),
                "ok": ok,
                "maybe": maybe,
                "ng": ng,
                "score": score,
            }
        )
    rows.sort(key=lambda x: (-x["score"], x["ng"], -x["ok"], x["date_time"]))
    best = rows[0] if rows else None
    return {
        "source": "heuristic",
        "recommended_date_id": best["date_id"] if best else None,
        "recommended_date_time": best["date_time"] if best else None,
        "reasoning": (
            "回答数に基づく簡易スコア（○×2 + △×1 − ××3）で最有力候補を選びました。"
            if best
            else "日程候補がありません。"
        ),
        "ranking": rows,
    }


async def recommend_slot(event_id: str) -> dict[str, Any]:
    detail = store.event_detail(event_id=event_id)
    if not detail:
        raise LookupError("イベントが見つかりません")
    if not detail["dates"]:
        return heuristic_recommend(detail)
    if not detail["responses"]:
        base = heuristic_recommend(detail)
        base["reasoning"] = "まだ回答がないため、最初の日程候補を仮の候補とします。"
        return base

    summary = _matrix_summary(detail)
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは日程調整の補助アシスタントです。"
                "与えられた出欠マトリクスから最適な候補を選び、JSON のみで答えてください。"
                "キー: recommended_date_id (整数), reasoning (日本語の短い理由), "
                "ranking (配列。各要素は date_id, score(0-100), note)。"
                "○を最重視し、×が多い候補は避けてください。説明文やコードフェンス以外は出力しないでください。"
            ),
        },
        {
            "role": "user",
            "content": (
                "次の日程調整の結果から最適日を提案してください。\n"
                f"{summary}"
            ),
        },
    ]
    try:
        text = await llm.chat(messages, temperature=0.1)
        data = llm.extract_json(text)
        if not isinstance(data, dict):
            raise ValueError("オブジェクトではありません")
        rid = data.get("recommended_date_id")
        valid_ids = {d["id"] for d in detail["dates"]}
        if rid is not None:
            try:
                rid = int(rid)
            except (TypeError, ValueError) as e:
                raise ValueError("recommended_date_id が不正です") from e
            if rid not in valid_ids:
                raise ValueError("存在しない date_id です")
        ranking = data.get("ranking") if isinstance(data.get("ranking"), list) else []
        # date_time を補完
        id_to_date = {d["id"]: d for d in detail["dates"]}
        norm_rank = []
        for item in ranking:
            if not isinstance(item, dict):
                continue
            try:
                did = int(item.get("date_id"))
            except (TypeError, ValueError):
                continue
            if did not in id_to_date:
                continue
            d = id_to_date[did]
            norm_rank.append(
                {
                    "date_id": did,
                    "date_time": d["date_time"],
                    "end_time": d.get("end_time"),
                    "is_all_day": bool(d.get("is_all_day")),
                    "score": item.get("score"),
                    "note": item.get("note") or "",
                }
            )
        rec_date = id_to_date.get(rid) if rid is not None else None
        return {
            "source": "llm",
            "recommended_date_id": rid,
            "recommended_date_time": rec_date["date_time"] if rec_date else None,
            "reasoning": str(data.get("reasoning") or "").strip()
            or "モデルが候補を提案しました。",
            "ranking": norm_rank or heuristic_recommend(detail)["ranking"],
            "model": llm.CHOSEI_MODEL,
        }
    except Exception as e:  # noqa: BLE001
        fallback = heuristic_recommend(detail)
        fallback["llm_error"] = str(e)
        fallback["reasoning"] = (
            f"LLM 提案に失敗したため簡易集計に切り替えました（{e}）。"
            + fallback["reasoning"]
        )
        return fallback


async def parse_dates_from_text(text: str, *, now: datetime | None = None) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("テキストを入力してください")
    now = now or datetime.now(JST)
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは日程候補の抽出器です。日本語の要望から候補日時を抽出し、"
                "JSON オブジェクトのみを1つ返してください。説明やコードフェンスは不要です。"
                '形式: {"dates":[{"start_time":"YYYY-MM-DDTHH:MM:SS+09:00",'
                '"end_time":"YYYY-MM-DDTHH:MM:SS+09:00"|null,'
                '"is_all_day":false,"label":"8/14 12:00"}],"notes":""}。'
                "タイムゾーンは必ず +09:00。"
                "候補は最大14件まで。平日連続などは必要な日だけ列挙し、冗長な説明は notes に書かない。"
                "終日なら is_all_day=true、start_time はその日 00:00:00+09:00、end_time は null。"
                "必ず完全な JSON で閉じること。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"現在日時: {now.isoformat()}\n"
                f"要望:\n{text}"
            ),
        },
    ]
    raw = await llm.chat(messages, temperature=0.1, max_tokens=4096)
    data = llm.extract_json(raw)
    if not isinstance(data, dict):
        raise ValueError("モデル応答の形式が不正です")
    dates_in = data.get("dates") if isinstance(data.get("dates"), list) else []
    dates: list[dict[str, Any]] = []
    for item in dates_in:
        if not isinstance(item, dict) or not item.get("start_time"):
            continue
        start = str(item["start_time"]).strip()
        end = item.get("end_time")
        end_s = str(end).strip() if end else None
        dates.append(
            {
                "start_time": start,
                "end_time": end_s,
                "is_all_day": bool(item.get("is_all_day")),
                "label": str(item.get("label") or start),
            }
        )
    return {
        "dates": dates,
        "notes": str(data.get("notes") or "").strip(),
        "model": llm.CHOSEI_MODEL,
        "raw_text": text,
    }


async def draft_invite(event_id: str, *, tone: str = "丁寧") -> dict[str, Any]:
    detail = store.event_detail(event_id=event_id)
    if not detail:
        raise LookupError("イベントが見つかりません")
    ev = detail["event"]
    date_lines = []
    for i, d in enumerate(detail["dates"], 1):
        line = f"{i}. {d['date_time']}"
        if d.get("end_time") and not d.get("is_all_day"):
            line += f" 〜 {d['end_time']}"
        if d.get("is_all_day"):
            line += "（終日）"
        date_lines.append(line)
    public_url = ev.get("public_url") or ""
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは自治体・組織向けの事務連絡文案アシスタントです。"
                "日程調整への回答依頼メール／チャット文を作成し、JSON のみで返してください。"
                'キー: subject (件名), body (本文), tips (任意の短い注意書き)。'
                "本文には候補一覧と回答用 URL を必ず含め、誇張や個人情報の捏造はしないでください。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"トーン: {tone}\n"
                f"タイトル: {ev['title']}\n"
                f"説明: {ev.get('description') or '（なし）'}\n"
                f"作成者: {ev.get('creator_name') or '（未記入）'}\n"
                f"候補:\n" + ("\n".join(date_lines) or "（なし）") + "\n"
                f"回答用URL: {public_url or '（未設定）'}\n"
            ),
        },
    ]
    text = await llm.chat(messages, temperature=0.4)
    data = llm.extract_json(text)
    if not isinstance(data, dict):
        raise ValueError("モデル応答の形式が不正です")
    subject = str(data.get("subject") or f"【日程調整】{ev['title']}").strip()
    body = str(data.get("body") or "").strip()
    if public_url and public_url not in body:
        body = (body + f"\n\n回答はこちらからお願いします:\n{public_url}").strip()
    return {
        "subject": subject,
        "body": body,
        "tips": str(data.get("tips") or "").strip(),
        "public_url": public_url,
        "model": llm.CHOSEI_MODEL,
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
