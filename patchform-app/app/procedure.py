"""手続きマスタの対応表。答えから様式の和集合をサーバー側で決める。"""

from __future__ import annotations

from typing import Any

from . import spec

CHOICE_TYPES = ("select", "radio", "checkbox")


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


def normalize_mapping(raw: Any) -> tuple[dict[str, Any], str | None]:
    if raw is None or raw == "":
        return {"rules": []}, None
    data = raw
    if isinstance(raw, str):
        import json

        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return {"rules": []}, "対応表の JSON が不正です"
    if not isinstance(data, dict):
        return {"rules": []}, "対応表はオブジェクトです"
    rules_in = data.get("rules")
    if rules_in is None:
        rules_in = []
    if not isinstance(rules_in, list):
        return {"rules": []}, "rules は配列です"
    rules: list[dict[str, Any]] = []
    for i, item in enumerate(rules_in):
        if not isinstance(item, dict):
            return {"rules": []}, f"rules[{i}] はオブジェクトです"
        component_id = str(item.get("component_id") or "").strip()
        option = str(item.get("option") or "").strip()
        if not component_id or not option:
            return {"rules": []}, f"rules[{i}] に component_id と option が必要です"
        form_ids = _as_str_list(item.get("form_ids"))
        notes = str(item.get("notes") or "").strip()
        prepare = _as_str_list(item.get("prepare"))
        refs = _as_str_list(item.get("refs"))
        rules.append(
            {
                "component_id": component_id,
                "option": option,
                "form_ids": form_ids,
                "notes": notes,
                "prepare": prepare,
                "refs": refs,
            }
        )
    return {"rules": rules}, None


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
