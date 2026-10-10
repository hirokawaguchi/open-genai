"""手続きマスタの対応表。答えから様式の和集合をサーバー側で決める。

解釈するキーの意味はここに置く。将来のキーは docs/patchform-kmap.md にあり、
ここに無いキーは読まない。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from . import spec

CHOICE_TYPES = ("select", "radio", "checkbox")

# 受付が機械で見る形式検査。手続きごとにこの語彙から選ぶ。
FORMAL_CHECKS = (
    ("file_present", "ファイルがある"),
    ("pdf_or_image", "PDF または画像"),
    ("issued_within_3_months", "発行日から3か月以内"),
)
FORMAL_CHECK_IDS = {item[0] for item in FORMAL_CHECKS}
FORMAL_LABELS = dict(FORMAL_CHECKS)

# 枠（申請束のアイテムの型）。
# - data   : 記入必須。オンライン記入のみ。他システムへ項目を揃えて渡せる
# - yoshiki: 様式。フォーム記入でも事前の PDF/Word 添付でも満たせる
# - attach : 添付。疎明・証明・写真。ファイルのみ
SLOT_KINDS = ("data", "yoshiki", "attach")
SLOT_REQUIRED = ("required", "recommended", "optional")
SLOT_CARDINALITY = ("one", "many")


def _as_str_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        items = raw.replace("\r\n", "\n").split("\n")
    elif isinstance(raw, list):
        items = raw
    else:
        items = [raw]
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
    return out


def answer_values(answer: Any) -> list[str]:
    if answer is None:
        return []
    if isinstance(answer, list):
        return [str(x).strip() for x in answer if str(x).strip()]
    text = str(answer).strip()
    return [text] if text else []


def _blank_review() -> dict[str, Any]:
    return {"slots": [], "cross": []}


def _blank_mapping() -> dict[str, Any]:
    return {"rules": [], "review": _blank_review()}


def _line_id(raw: str) -> str:
    text = (raw or "").strip()
    if text and len(text) <= 64 and all(ch.isalnum() or ch in "-_" for ch in text):
        return text
    return uuid.uuid4().hex[:8]


def _norm_lines(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            text = item.strip()
            cid = ""
        elif isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            cid = str(item.get("id") or "").strip()
        else:
            continue
        if not text:
            continue
        cid = _line_id(cid)
        while cid in seen:
            cid = uuid.uuid4().hex[:8]
        seen.add(cid)
        out.append({"id": cid, "text": text})
    return out


def _norm_formal(raw: Any) -> list[str]:
    found: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                key = str(item.get("id") or "").strip()
            else:
                key = str(item or "").strip()
            if key in FORMAL_CHECK_IDS:
                found.add(key)
    return [cid for cid, _label in FORMAL_CHECKS if cid in found]


def _norm_slot_reviews(raw: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        slot_id = str(item.get("slot_id") or "").strip()
        if not slot_id or slot_id not in allowed or slot_id in seen:
            continue
        seen.add(slot_id)
        out.append(
            {
                "slot_id": slot_id,
                "formal": _norm_formal(item.get("formal")),
                "content": _norm_lines(item.get("content")),
            }
        )
    return out


def _norm_review_block(raw: Any) -> dict[str, Any]:
    """案内に依存しない審査（申請用紙1枚の手続き）。"""
    if not isinstance(raw, dict):
        return _blank_review()
    slots_in = raw.get("slots") if isinstance(raw.get("slots"), list) else []
    allowed: set[str] = set()
    for item in slots_in:
        if not isinstance(item, dict):
            continue
        slot_id = str(item.get("slot_id") or "").strip()
        if slot_id.startswith("yoshiki:") and len(slot_id) > len("yoshiki:"):
            allowed.add(slot_id)
        elif slot_id.startswith("attach:") and len(slot_id) > len("attach:"):
            allowed.add(slot_id)
    return {
        "slots": _norm_slot_reviews(slots_in, allowed),
        "cross": _norm_lines(raw.get("cross")),
    }


def normalize_mapping(raw: Any) -> tuple[dict[str, Any], str | None]:
    if raw is None or raw == "":
        return _blank_mapping(), None
    data = raw
    if isinstance(raw, str):
        import json

        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return _blank_mapping(), "対応表の JSON が不正です"
    if not isinstance(data, dict):
        return _blank_mapping(), "対応表はオブジェクトです"
    rules_in = data.get("rules")
    if rules_in is None:
        rules_in = []
    if not isinstance(rules_in, list):
        return _blank_mapping(), "rules は配列です"
    rules: list[dict[str, Any]] = []
    for i, item in enumerate(rules_in):
        if not isinstance(item, dict):
            return _blank_mapping(), f"rules[{i}] はオブジェクトです"
        component_id = str(item.get("component_id") or "").strip()
        option = str(item.get("option") or "").strip()
        if not component_id or not option:
            return _blank_mapping(), f"rules[{i}] に component_id と option が必要です"
        form_ids = _as_str_list(item.get("form_ids"))
        notes = str(item.get("notes") or "").strip()
        prepare = _as_str_list(item.get("prepare"))
        refs = _as_str_list(item.get("refs"))
        allowed = {f"yoshiki:{fid}" for fid in form_ids}
        allowed.update(f"attach:{name}" for name in prepare)
        rules.append(
            {
                "component_id": component_id,
                "option": option,
                "form_ids": form_ids,
                "notes": notes,
                "prepare": prepare,
                "refs": refs,
                "reviews": _norm_slot_reviews(item.get("reviews"), allowed),
                "cross": _norm_lines(item.get("cross")),
            }
        )
    return {"rules": rules, "review": _norm_review_block(data.get("review"))}, None


def choice_fields(definition: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    comps = (definition or {}).get("components") or []
    if not isinstance(comps, list):
        return out
    for comp in comps:
        if not isinstance(comp, dict):
            continue
        if comp.get("type") not in CHOICE_TYPES:
            continue
        cid = str(comp.get("id") or "").strip()
        if not cid:
            continue
        props = comp.get("properties") if isinstance(comp.get("properties"), dict) else {}
        items = spec.option_items((props or {}).get("options"))
        out.append(
            {
                "id": cid,
                "type": comp.get("type"),
                "label": str(comp.get("label") or cid),
                "options": [item["value"] for item in items],
                "option_items": items,
            }
        )
    return out


def mapping_warnings(
    mapping: dict[str, Any], definition: dict[str, Any] | None
) -> list[str]:
    fields = {f["id"]: f for f in choice_fields(definition)}
    warnings: list[str] = []
    for rule in mapping.get("rules") or []:
        field = fields.get(rule["component_id"])
        if field is None:
            warnings.append(
                f"部品「{rule['component_id']}」が案内フォームにありません"
            )
            continue
        allowed = {item["value"] for item in (field.get("option_items") or [])}
        allowed.update(field.get("options") or [])
        allowed.update(item["label"] for item in (field.get("option_items") or []))
        if rule["option"] not in allowed:
            warnings.append(
                f"「{field['label']}」に選択肢「{rule['option']}」がありません"
            )
    return warnings


def _norm_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def coerce_answers(raw: Any) -> dict[str, Any]:
    """MCP / LLM から来る答えの揺れを dict にする。"""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        if text.startswith("{") or text.startswith("["):
            import json

            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return coerce_answers(parsed)
        if "=" in text and "\n" not in text and text.count("=") == 1:
            key, value = text.split("=", 1)
            return {key.strip(): value.strip()}
        return {"_free": text}
    if isinstance(raw, list):
        out: dict[str, Any] = {}
        for item in raw:
            if isinstance(item, dict):
                cid = str(item.get("component_id") or item.get("id") or item.get("field") or "").strip()
                option = item.get("option") if "option" in item else item.get("value")
                if cid and option is not None:
                    current = out.get(cid)
                    if current is None:
                        out[cid] = option
                    else:
                        prev = current if isinstance(current, list) else [current]
                        out[cid] = [*prev, option]
            elif item is not None and str(item).strip():
                free = out.setdefault("_free", [])
                if not isinstance(free, list):
                    free = [free]
                    out["_free"] = free
                free.append(str(item).strip())
        return out
    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items() if str(k).strip()}
    return {}


def normalize_answers(
    fields: list[dict[str, Any]], raw: Any
) -> tuple[dict[str, Any], list[str]]:
    """部品 ID / ラベルと選択肢の表記ゆれを揃える。"""
    notes: list[str] = []
    by_id = {str(f.get("id") or ""): f for f in fields if f.get("id")}
    by_label = {_norm_text(f.get("label")).lower(): f for f in fields if _norm_text(f.get("label"))}
    parsed = coerce_answers(raw)
    free_values = answer_values(parsed.pop("_free", None))
    out: dict[str, Any] = {}

    def _match_field(key: str) -> dict[str, Any] | None:
        if key in by_id:
            return by_id[key]
        nk = _norm_text(key).lower()
        if nk in by_id:
            return by_id[nk]
        return by_label.get(nk)

    def _match_options(field: dict[str, Any], values: list[str]) -> list[str]:
        items = field.get("option_items") or [
            {"value": opt, "label": opt} for opt in (field.get("options") or [])
        ]
        canon: dict[str, str] = {}
        for item in items:
            value = str(item.get("value") or "").strip()
            label = str(item.get("label") or value).strip()
            if value:
                canon[_norm_text(value).lower()] = value
            if label:
                canon[_norm_text(label).lower()] = value or label
        matched: list[str] = []
        for value in values:
            found = canon.get(_norm_text(value).lower())
            if found:
                matched.append(found)
            else:
                notes.append(f"「{field.get('label') or field.get('id')}」に選択肢「{value}」はありません")
        return matched

    for key, value in parsed.items():
        field = _match_field(str(key))
        if field is None:
            notes.append(f"部品「{key}」は案内にありません")
            continue
        values = _match_options(field, answer_values(value))
        if not values:
            continue
        if field.get("type") == "checkbox":
            out[field["id"]] = values
        else:
            out[field["id"]] = values if len(values) > 1 else values[0]

    for value in free_values:
        def _field_tokens(field: dict[str, Any]) -> set[str]:
            items = field.get("option_items") or [
                {"value": opt, "label": opt} for opt in (field.get("options") or [])
            ]
            tokens: set[str] = set()
            for item in items:
                tokens.add(_norm_text(item.get("value")).lower())
                tokens.add(_norm_text(item.get("label")).lower())
            return {t for t in tokens if t}

        hits = [field for field in fields if _norm_text(value).lower() in _field_tokens(field)]
        if len(hits) == 1:
            field = hits[0]
            matched = _match_options(field, [value])
            if not matched:
                continue
            canon = matched[0]
            if field.get("type") == "checkbox":
                current = out.get(field["id"]) or []
                if not isinstance(current, list):
                    current = [current]
                if canon not in current:
                    current.append(canon)
                out[field["id"]] = current
            else:
                out[field["id"]] = canon
        elif not hits:
            notes.append(f"選択肢「{value}」に当たる部品がありません")
        else:
            notes.append(f"選択肢「{value}」が複数の部品にあります")

    return out, notes


def resolve_bundle(
    mapping: dict[str, Any], answers: dict[str, Any] | None
) -> dict[str, Any]:
    answers = answers or {}
    form_ids: list[str] = []
    notes: list[str] = []
    prepare: list[str] = []
    refs: list[str] = []
    seen_forms: set[str] = set()
    for rule in mapping.get("rules") or []:
        values = answer_values(answers.get(rule.get("component_id")))
        if rule.get("option") not in values:
            continue
        for fid in rule.get("form_ids") or []:
            if fid in seen_forms:
                continue
            seen_forms.add(fid)
            form_ids.append(fid)
        note = str(rule.get("notes") or "").strip()
        if note:
            notes.append(note)
        for item in rule.get("prepare") or []:
            if item not in prepare:
                prepare.append(item)
        for item in rule.get("refs") or []:
            if item not in refs:
                refs.append(item)
    return {
        "form_ids": form_ids,
        "notes": notes,
        "prepare": prepare,
        "refs": refs,
    }


def resolve_slots(
    mapping: dict[str, Any], answers: dict[str, Any] | None
) -> dict[str, Any]:
    """答えに当たった枠（推奨アイテムの種）を1件ずつ返す。

    様式フォームは記入・添付のどちらでも満たせる `yoshiki` 枠に、`prepare`
    の持ち物は `attach` 枠にする。ここでは束を閉じず、推奨セットを置くだけ。
    """
    answers = answers or {}
    slots: list[dict[str, Any]] = []
    notes: list[str] = []
    prepare: list[str] = []
    refs: list[str] = []
    seen: set[str] = set()

    def _push(slot: dict[str, Any]) -> None:
        key = slot["slot_id"]
        if key in seen:
            return
        seen.add(key)
        slots.append(slot)

    for rule in mapping.get("rules") or []:
        values = answer_values(answers.get(rule.get("component_id")))
        if rule.get("option") not in values:
            continue
        for fid in rule.get("form_ids") or []:
            _push(
                {
                    "slot_id": f"yoshiki:{fid}",
                    "title": "",
                    "kind": "yoshiki",
                    "required": "recommended",
                    "cardinality": "one",
                    "form_id": fid,
                    "template_file_id": "",
                }
            )
        for item in rule.get("prepare") or []:
            text = str(item).strip()
            if not text:
                continue
            if text not in prepare:
                prepare.append(text)
            _push(
                {
                    "slot_id": f"attach:{text}",
                    "title": text,
                    "kind": "attach",
                    "required": "recommended",
                    "cardinality": "one",
                    "form_id": "",
                    "template_file_id": "",
                }
            )
        note = str(rule.get("notes") or "").strip()
        if note:
            notes.append(note)
        for item in rule.get("refs") or []:
            if item not in refs:
                refs.append(item)
    return {
        "slots": slots,
        "notes": notes,
        "prepare": prepare,
        "refs": refs,
    }


def formal_check_catalog() -> list[dict[str, str]]:
    return [{"id": cid, "label": label} for cid, label in FORMAL_CHECKS]


def _items_for_slot(items: list[dict[str, Any]], slot_id: str) -> list[dict[str, Any]]:
    return [it for it in items if str(it.get("slot_id") or "") == slot_id]


def _slot_title(slot_id: str, group: list[dict[str, Any]]) -> str:
    if slot_id.startswith("attach:"):
        return slot_id[len("attach:") :]
    for it in group:
        title = str(it.get("title") or "").strip()
        if title:
            return title
    return slot_id


def _fulfilled(item: dict[str, Any], slot_id: str) -> bool:
    if slot_id.startswith("attach:") or item.get("kind") == "attach":
        return bool(item.get("file_id"))
    if item.get("fulfillment") == "file":
        return bool(item.get("file_id"))
    return item.get("status") == "submitted" or bool(item.get("file_id"))


def _formal_result(check_id: str, slot_id: str, group: list[dict[str, Any]]) -> dict[str, str]:
    label = FORMAL_LABELS[check_id]
    base = {"id": check_id, "label": label}
    if check_id == "issued_within_3_months":
        return {**base, "result": "unknown", "detail": "日付は受付で確認します"}
    if not group:
        return {**base, "result": "fail", "detail": "この枠がありません"}
    if check_id == "file_present":
        ok = all(_fulfilled(it, slot_id) for it in group)
        return {
            **base,
            "result": "pass" if ok else "fail",
            "detail": "" if ok else "ファイルまたは記入がありません",
        }
    mimes = [str(it.get("mime") or "") for it in group if it.get("file_id")]
    if not mimes:
        return {**base, "result": "unknown", "detail": "ファイルがありません"}
    ok = all(m == "application/pdf" or m.startswith("image/") for m in mimes)
    return {
        **base,
        "result": "pass" if ok else "fail",
        "detail": "" if ok else "PDF または画像ではありません",
    }


def review_snapshot(
    mapping: dict[str, Any],
    answers: dict[str, Any] | None,
    items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """提出時点の審査項目。当たった答えの枠だけを残す。"""
    answers = answers or {}
    items = items or []
    slots_out: list[dict[str, Any]] = []
    cross_out: list[dict[str, str]] = []
    seen_slots: set[str] = set()
    seen_cross: set[str] = set()

    def _take_slot(rev: dict[str, Any]) -> None:
        slot_id = str(rev.get("slot_id") or "")
        if not slot_id or slot_id in seen_slots:
            return
        seen_slots.add(slot_id)
        group = _items_for_slot(items, slot_id)
        slots_out.append(
            {
                "slot_id": slot_id,
                "title": _slot_title(slot_id, group),
                "formal": [
                    _formal_result(cid, slot_id, group) for cid in rev.get("formal") or []
                ],
                "content": [_snapshot_line(line) for line in rev.get("content") or []],
            }
        )

    def _take_cross(lines: list[dict[str, str]]) -> None:
        for line in lines:
            cid = line.get("id") or ""
            if not cid or cid in seen_cross:
                continue
            seen_cross.add(cid)
            cross_out.append(_snapshot_line(line))

    block = mapping.get("review") if isinstance(mapping.get("review"), dict) else {}
    for rev in block.get("slots") or []:
        if isinstance(rev, dict):
            _take_slot(rev)
    _take_cross(block.get("cross") or [])

    for rule in mapping.get("rules") or []:
        values = answer_values(answers.get(rule.get("component_id")))
        if rule.get("option") not in values:
            continue
        allowed = {f"yoshiki:{fid}" for fid in rule.get("form_ids") or []}
        allowed.update(f"attach:{name}" for name in rule.get("prepare") or [])
        for rev in rule.get("reviews") or []:
            if isinstance(rev, dict) and rev.get("slot_id") in allowed:
                _take_slot(rev)
        _take_cross(rule.get("cross") or [])
    return {"slots": slots_out, "cross": cross_out}


def _snapshot_line(line: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(line.get("id") or ""),
        "text": str(line.get("text") or ""),
        "finding": {"result": "unknown", "detail": "", "source": ""},
    }


def review_needs_clerk(snap: dict[str, Any]) -> bool:
    """形式が揃っていない、または確認文がある。受付が目を通す。"""
    for slot in snap.get("slots") or []:
        if not isinstance(slot, dict):
            continue
        for formal in slot.get("formal") or []:
            if isinstance(formal, dict) and formal.get("result") != "pass":
                return True
        if slot.get("content"):
            return True
    return bool(snap.get("cross"))


def open_finding_lines(snap: dict[str, Any]) -> list[dict[str, str]]:
    """職員がまだ確定していない確認文。"""
    out: list[dict[str, str]] = []
    for line in _walk_lines(snap):
        current = line.get("finding") if isinstance(line.get("finding"), dict) else {}
        if current.get("source") == "staff":
            continue
        out.append({"id": str(line.get("id") or ""), "text": str(line.get("text") or "")})
    return out


def _walk_lines(snap: dict[str, Any]):
    for slot in snap.get("slots") or []:
        if isinstance(slot, dict):
            for line in slot.get("content") or []:
                if isinstance(line, dict):
                    yield line
    for line in snap.get("cross") or []:
        if isinstance(line, dict):
            yield line


def set_line_finding(
    snap: dict[str, Any], line_id: str, result: str, detail: str, source: str
) -> bool:
    """確認文の所見だけを書く。本文は変えない。"""
    for line in _walk_lines(snap):
        if str(line.get("id") or "") != line_id:
            continue
        line["finding"] = {
            "result": result,
            "detail": detail[:200],
            "source": source,
        }
        return True
    return False


def merge_model_findings(
    snap: dict[str, Any], rows: list[Any], *, source: str = "model"
) -> int:
    """所見を足す。職員が確定した行は残す。"""
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("id") or "")
        result = str(row.get("result") or "")
        if rid and result in ("pass", "fail", "unknown"):
            by_id[rid] = row
    changed = 0
    for line in _walk_lines(snap):
        current = line.get("finding") if isinstance(line.get("finding"), dict) else {}
        if current.get("source") == "staff":
            continue
        row = by_id.get(str(line.get("id") or ""))
        if not row:
            continue
        line["finding"] = {
            "result": row["result"],
            "detail": str(row.get("detail") or "")[:200],
            "source": source if source in ("model", "dify") else "model",
        }
        changed += 1
    return changed


ROUTE_STEPS = (
    {"id": "desk", "label": "受付確認"},
    {"id": "section", "label": "担当課"},
    {"id": "confirm", "label": "確定"},
)
_ROUTE_IDS = tuple(step["id"] for step in ROUTE_STEPS)


def default_handling() -> dict[str, Any]:
    return {
        "route": [
            {"id": "desk", "label": "受付確認", "role": "受付"},
            {"id": "section", "label": "担当課", "role": "担当課"},
            {"id": "confirm", "label": "確定", "role": "受付"},
        ],
        "exit": "ledger",
        "statuses": ["受理", "処理中", "完了"],
    }


def normalize_handling(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    """確定前の3段と、確定後の行き先。段の名前は固定で、役割名だけを書く。"""
    if raw is None or raw == "" or raw == {}:
        return default_handling(), None
    if isinstance(raw, str):
        try:
            raw = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return None, "確定前の経路を読めません"
    if not isinstance(raw, dict):
        return None, "確定前の経路を読めません"
    roles: dict[str, str] = {}
    for step in raw.get("route") or []:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id") or "")
        role = str(step.get("role") or "").strip()
        if sid in _ROUTE_IDS and role:
            roles[sid] = role[:40]
    route = []
    for step in default_handling()["route"]:
        route.append({**step, "role": roles.get(step["id"], step["role"])})
    exit_to = str(raw.get("exit") or "ledger").strip()
    if exit_to not in ("ledger", "external"):
        return None, "確定後の行き先が不正です"
    statuses: list[str] = []
    given = raw.get("statuses")
    source = given if isinstance(given, list) and given else default_handling()["statuses"]
    for item in source:
        text = str(item or "").strip()
        if text and text not in statuses:
            statuses.append(text[:40])
    if not statuses:
        return None, "台帳の状態を1つ以上書いてください"
    return {"route": route, "exit": exit_to, "statuses": statuses[:12]}, None


def route_step(stage: str, status: str, action: str) -> tuple[str, str, str | None]:
    """進む、戻す、差戻し。受理は最後の段からだけ。"""
    action = (action or "").strip()
    if action not in ("advance", "back", "return"):
        return status, stage, "操作が不正です"
    if status == "受理":
        return status, stage, "確定済みです"
    if status == "差戻し":
        if action == "advance":
            return "確認中", "desk", None
        if action == "return":
            return status, stage, "すでに差戻しです"
        return status, stage, "これより前はありません"
    if status == "未確認":
        if action == "advance":
            return "確認中", "desk", None
        if action == "return":
            return "差戻し", "", None
        return status, stage, "これより前はありません"
    if status != "確認中":
        return status, stage, "提出後に進めます"
    current = stage if stage in _ROUTE_IDS else "desk"
    index = _ROUTE_IDS.index(current)
    if action == "return":
        return "差戻し", "", None
    if action == "back":
        if index == 0:
            return status, current, "これより前はありません"
        return "確認中", _ROUTE_IDS[index - 1], None
    if index == len(_ROUTE_IDS) - 1:
        return "受理", "confirm", None
    return "確認中", _ROUTE_IDS[index + 1], None
