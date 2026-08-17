"""チェック回答の正規化と合意判定。"""

from __future__ import annotations

import re
import unicodedata
from typing import Any


CHOICE_MULTI_SEP = "|"

# 「空欄（記入なし）」を確定値として合意判定するための内部センチネル。
# 実際の採用値は空文字で書き戻す。
BLANK_KEY = "\x00blank"


def normalize_text(value: str | None, *, field_type: str = "text") -> str:
    """比較用にテキストを正規化する。

    choice_multi は区切りで分割し、順序差を無視できるようソートして再結合する。
    """
    if field_type == "choice_multi":
        parts = [
            re.sub(r"\s+", "", unicodedata.normalize("NFKC", p.strip()))
            for p in (value or "").split(CHOICE_MULTI_SEP)
        ]
        parts = sorted({p for p in parts if p})
        return CHOICE_MULTI_SEP.join(parts)
    s = unicodedata.normalize("NFKC", (value or "").strip())
    s = re.sub(r"\s+", "", s)
    if field_type in ("date", "number"):
        s = s.replace("/", "-").replace(".", "-")
        s = s.replace("年", "-").replace("月", "-").replace("日", "")
    return s


def checker_identity(answer: dict[str, Any]) -> str:
    """同一人物判定用キー。user_id > checker_key > checker_label > task_id。"""
    for key in ("checker_user_id", "checker_key", "checker_label"):
        v = (answer.get(key) or "").strip()
        if v:
            return f"{key}:{v}"
    tid = answer.get("task_id")
    if tid:
        return f"task:{tid}"
    return f"anon:{id(answer)}"


def unique_answers(answers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同一チェッカーの重複回答を除く（先勝ち）。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for a in answers:
        cid = checker_identity(a)
        if cid in seen:
            continue
        seen.add(cid)
        out.append(a)
    return out


def evaluate_consensus(
    answers: list[dict[str, Any]],
    *,
    field_type: str = "text",
    min_agree: int = 2,
    assignee_count: int | None = None,
) -> dict[str, Any]:
    """回答一覧から合意結果を返す。

    - 同一人物の複数回答は 1 票にまとめる
    - assignee_count=1（ソロ検証）のときは 1 票で採用可
    - 採用: 一致票 >= min_agree かつ (庁内含む OR 全員一致)
    """
    if not answers:
        return {"status": "pending", "adopted_text": None, "reason": "no_answers"}

    uniq = unique_answers(answers)
    effective_min = min_agree
    if assignee_count is not None and assignee_count > 0:
        effective_min = min(min_agree, assignee_count)
    effective_min = max(1, effective_min)

    buckets: dict[str, list[dict[str, Any]]] = {}
    for a in uniq:
        if a.get("is_blank"):
            # 空欄は確定値（空文字）として1つのバケットに束ねる
            buckets.setdefault(BLANK_KEY, []).append(a)
            continue
        key = normalize_text(a.get("answer_text"), field_type=field_type)
        if not key:
            continue
        buckets.setdefault(key, []).append(a)

    if not buckets:
        return {"status": "pending", "adopted_text": None, "reason": "empty_answers"}

    best_key = max(buckets.keys(), key=lambda k: len(buckets[k]))
    best = buckets[best_key]
    all_same = len(buckets) == 1 and len(uniq) >= effective_min
    has_internal = any(a.get("tier") == "internal" for a in best)

    if len(best) >= effective_min and (has_internal or all_same or effective_min == 1):
        preferred = next((a for a in best if a.get("tier") == "internal"), best[0])
        adopted_text = "" if best_key == BLANK_KEY else preferred.get("answer_text")
        return {
            "status": "adopted",
            "adopted_text": adopted_text,
            "normalized": best_key,
            "agree_count": len(best),
            "unique_checkers": len(uniq),
            "reason": (
                "solo"
                if effective_min == 1
                else ("internal_agree" if has_internal else "unanimous")
            ),
        }

    # 想定人数ぶん集まったのに合意しない → 裁定
    quota = assignee_count if assignee_count is not None else max(effective_min, 3)
    if len(uniq) >= quota and len(best) < effective_min:
        return {
            "status": "needs_arbitration",
            "adopted_text": None,
            "agree_count": len(best),
            "unique_checkers": len(uniq),
            "reason": "disagreement",
            "candidates": [
                {
                    "text": "" if k == BLANK_KEY else buckets[k][0].get("answer_text"),
                    "count": len(buckets[k]),
                    "normalized": k,
                    "is_blank": k == BLANK_KEY,
                }
                for k in sorted(buckets.keys(), key=lambda x: -len(buckets[x]))
            ],
        }

    return {
        "status": "pending",
        "adopted_text": None,
        "agree_count": len(best),
        "unique_checkers": len(uniq),
        "reason": "awaiting_more",
    }


def join_adjacent_parts(parts: list[str | None]) -> str:
    """横分割片を左から結合する。境界の重複（隣同士オーバーラップ）を除去する。"""
    result = ""
    for raw in parts:
        nxt = (raw or "").strip()
        if not nxt:
            continue
        if not result:
            result = nxt
            continue
        max_k = min(len(result), len(nxt))
        overlap = 0
        for k in range(max_k, 0, -1):
            if result.endswith(nxt[:k]):
                overlap = k
                break
        result = result + nxt[overlap:]
    return result


def _group_key(region: dict[str, Any]) -> str | None:
    """結合キー。

    - group_id を最優先（単一行の横N分割は同時生成の安定 ID で束ねる。
      出力項目名が偶然一致しても混ざらない）。
    - group_id が無い場合は出力項目名で束ねる（複数行は行ごとに別枠を作り、
      同じ項目名を付けて結合する。行ごとに横分割しても group_id は付かない）。
    """
    gid = (region.get("group_id") or "").strip()
    if gid:
        return f"id:{gid}"
    gname = (region.get("group_name") or "").strip()
    if gname:
        return f"name:{gname}"
    return None


def _field_export_name(region: dict[str, Any]) -> str:
    gname = (region.get("group_name") or "").strip()
    if gname:
        return gname
    return str(region.get("name") or "")


def _worst_status(statuses: list[str]) -> str:
    order = {
        "needs_arbitration": 3,
        "pending": 2,
        "ready": 2,
        "processing": 2,
        "adopted": 1,
    }
    worst = "adopted"
    score = 0
    for s in statuses:
        sc = order.get(s or "", 2)
        if sc > score:
            score = sc
            worst = s or "pending"
    return worst


def merge_export_fields(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """領域一覧を出力フィールドに畳む。

    - group_id / group_name がある片は 1 項目にまとめる
    - 同一行（line_index）内は横結合、行どうしは改行で結合
    - グループ無しは従来どおり name 単位
    """
    groups: dict[str, list[dict[str, Any]]] = {}

    for r in regions:
        if r.get("is_trap"):
            continue
        key = _group_key(r)
        if not key:
            continue
        groups.setdefault(key, []).append(r)

    fields: list[dict[str, Any]] = []

    # 出現順を保つ（テンプレ sort / ドキュメント順）。グループと単体を混在させるため
    # 元リストを再度走査する。
    emitted: set[str] = set()
    for r in regions:
        if r.get("is_trap"):
            continue
        key = _group_key(r)
        if not key:
            fields.append(
                {
                    "name": r.get("name"),
                    "value": r.get("adopted_text"),
                    "status": r.get("status"),
                    "ocr_text": r.get("ocr_text"),
                    "ocr_confidence": r.get("ocr_confidence"),
                    "parts": None,
                }
            )
            continue
        if key in emitted:
            continue
        emitted.add(key)
        members = sorted(
            groups[key],
            key=lambda x: (
                int(x.get("line_index") or 0),
                int(x.get("part_index") or 0),
                str(x.get("name") or ""),
            ),
        )
        by_line: dict[int, list[dict[str, Any]]] = {}
        for m in members:
            by_line.setdefault(int(m.get("line_index") or 0), []).append(m)

        line_texts: list[str] = []
        line_ocr: list[str] = []
        statuses: list[str] = []
        part_summaries: list[dict[str, Any]] = []
        all_adopted = True
        confs: list[float] = []

        for line_i in sorted(by_line.keys()):
            line_members = by_line[line_i]
            adopted_parts = [m.get("adopted_text") for m in line_members]
            ocr_parts = [m.get("ocr_text") for m in line_members]
            for m in line_members:
                statuses.append(str(m.get("status") or "pending"))
                if m.get("status") != "adopted" or not (m.get("adopted_text") or "").strip():
                    all_adopted = False
                try:
                    confs.append(float(m.get("ocr_confidence") or 0))
                except (TypeError, ValueError):
                    pass
                part_summaries.append(
                    {
                        "name": m.get("name"),
                        "line_index": int(m.get("line_index") or 0),
                        "part_index": int(m.get("part_index") or 0),
                        "status": m.get("status"),
                        "adopted_text": m.get("adopted_text"),
                        "ocr_text": m.get("ocr_text"),
                    }
                )
            line_texts.append(join_adjacent_parts(adopted_parts))
            line_ocr.append(join_adjacent_parts(ocr_parts))

        status = "adopted" if all_adopted and members else _worst_status(statuses)
        value = "\n".join(line_texts) if all_adopted else None
        fields.append(
            {
                "name": _field_export_name(members[0]),
                "value": value,
                "status": status,
                "ocr_text": "\n".join(line_ocr) if any(line_ocr) else None,
                "ocr_confidence": (sum(confs) / len(confs)) if confs else None,
                "parts": part_summaries,
                "group_id": members[0].get("group_id"),
                "group_name": members[0].get("group_name"),
            }
        )

    return fields


def export_column_names(regions: list[dict[str, Any]]) -> list[str]:
    """CSV 列名（トラップ除外・グループは 1 列）。"""
    names: list[str] = []
    seen: set[str] = set()
    emitted_groups: set[str] = set()
    for r in regions:
        if r.get("is_trap"):
            continue
        key = _group_key(r)
        if key:
            if key in emitted_groups:
                continue
            emitted_groups.add(key)
            name = _field_export_name(r)
        else:
            name = str(r.get("name") or "")
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names
