"""フォーム作成・修正の LLM アシスト。失敗時はカタログ制約付きテンプレートにフォールバック。"""

from __future__ import annotations

import json
import time
from typing import Any

from . import llm, spec


def catalog_for_prompt() -> list[dict[str, Any]]:
    return [
        {
            "type": t,
            "label": meta["label"],
            "has_options": meta.get("has_options", False),
            "category": meta["category"],
            "description": meta.get("description") or "",
        }
        for t, meta in spec.CATALOG.items()
        if meta["enabled"]
    ]


def fallback_definition(text: str) -> dict[str, Any]:
    """LLM なしでも動く自治体向け下書き。"""
    q = (text or "").strip()
    title = q[:40] or "申請フォーム"
    if any(k in q for k in ("医療", "子ども", "小児", "助成")):
        title = title if "フォーム" in title else "子ども医療費助成の申請"
        comps = [
            _c("applicant", "user_info_composite", "申請者", True),
            _c("addr", "address_composite", "住所", True),
            _c("child_name", "text", "お子さまの氏名", True),
            _c("birth", "date", "生年月日", True),
            _c("hospital", "text", "受診医療機関"),
            _c("bank", "financial_institution_composite", "振込先"),
            _c("note", "textarea", "備考"),
        ]
    elif any(k in q for k in ("法人", "事業者", "会社")):
        title = title if len(q) > 8 else "事業者届出"
        comps = [
            _c("company", "company_info_composite", "法人情報", True),
            _c("addr", "address_composite", "所在地", True),
            _c("contact", "user_info_composite", "担当者", True),
            _c("mail", "email", "メールアドレス", True),
            _c("tel", "phone", "電話番号", True),
        ]
    elif any(k in q for k in ("口座", "振込", "補助金", "給付")):
        title = title if len(q) > 8 else "補助金申請"
        comps = [
            _c("applicant", "user_info_composite", "申請者", True),
            _c("addr", "address_composite", "住所", True),
            _c("amount", "number", "申請額", True),
            _c("bank", "financial_institution_composite", "振込先", True),
            _c("reason", "textarea", "申請理由", True),
        ]
    elif any(k in q for k in ("アンケート", "調査", "意見")):
        title = title if len(q) > 8 else "アンケート"
        comps = [
            _c("name", "text", "お名前"),
            _c(
                "satisfy",
                "radio",
                "満足度",
                True,
                options=["とても満足", "満足", "普通", "不満"],
            ),
            _c("comment", "textarea", "ご意見"),
        ]
    else:
        comps = [
            _c("applicant", "user_info_composite", "氏名", True),
            _c("addr", "address_composite", "住所", True),
            _c("mail", "email", "メールアドレス"),
            _c("tel", "phone", "電話番号"),
            _c("note", "textarea", "内容"),
        ]
    return {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": title, "description": q},
        "components": comps,
    }


def _c(
    cid: str,
    ctype: str,
    label: str,
    required: bool = False,
    *,
    options: list[str] | None = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if options:
        props["options"] = options
    return spec.fill_default_imi(
        {
            "id": cid,
            "type": ctype,
            "label": label,
            "required": required,
            "placeholder": "",
            "properties": props,
        }
    )


def merge_definition(
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """既存 id をできるだけ維持して差し替える。"""
    if not current:
        return incoming
    used = {c.get("id") for c in current.get("components") or []}
    by_label = {
        str(c.get("label") or ""): c for c in current.get("components") or [] if c.get("label")
    }
    merged: list[dict[str, Any]] = []
    for raw in incoming.get("components") or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "")
        old = by_label.get(label)
        cid = str(raw.get("id") or "")
        if old and old.get("type") == raw.get("type"):
            cid = old["id"]
        elif cid in used and (not old or old.get("id") != cid):
            cid = f"c_{int(time.time() * 1000)}_{len(merged)}"
        used.add(cid)
        item = dict(raw)
        item["id"] = cid
        if old and old.get("type") == raw.get("type"):
            if not str(item.get("imi_type") or "").strip() and old.get("imi_type"):
                item["imi_type"] = old["imi_type"]
            old_subs = old.get("imi_subfields") if isinstance(old.get("imi_subfields"), dict) else {}
            new_subs = item.get("imi_subfields") if isinstance(item.get("imi_subfields"), dict) else {}
            if old_subs or new_subs:
                item["imi_subfields"] = {**old_subs, **new_subs}
        merged.append(item)
    meta = {
        **(current.get("metadata") or {}),
        **(incoming.get("metadata") or {}),
    }
    return {
        "$version": spec.SPEC_VERSION,
        "metadata": {
            "title": str(meta.get("title") or ""),
            "description": str(meta.get("description") or ""),
        },
        "components": merged,
    }


def apply_generated(
    raw: Any,
    *,
    visibility: str,
    current: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "生成結果の形式が不正です"
    incoming = raw.get("definition") if isinstance(raw.get("definition"), dict) else raw
    if current:
        incoming = merge_definition(current, incoming)
    comps = incoming.get("components") if isinstance(incoming, dict) else None
    if isinstance(incoming, dict) and isinstance(comps, list):
        incoming = {
            **incoming,
            "components": [
                spec.fill_default_imi(c) if isinstance(c, dict) else c for c in comps
            ],
        }
    return spec.validate_definition(incoming, visibility=visibility)


def fallback_invite(title: str, public_url: str, tone: str = "丁寧") -> dict[str, str]:
    polite = tone != "カジュアル"
    if polite:
        subject = f"【ご案内】{title}のご回答のお願い"
        body = (
            f"{title}へのご回答をお願いいたします。\n\n"
            f"回答用URL:\n{public_url}\n\n"
            "ご不明点があれば作成者までお問い合わせください。"
        )
    else:
        subject = f"{title}の回答をお願いします"
        body = f"{title}の回答フォームです。\n{public_url}\n"
    return {"subject": subject, "body": body}


async def generate_form(
    text: str,
    *,
    visibility: str = "internal",
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    q = (text or "").strip()
    if not q:
        raise ValueError("指示文は必須です")
    allowed = json.dumps(catalog_for_prompt(), ensure_ascii=False)
    system = (
        "あなたは日本の自治体向けオンラインフォーム設計者です。"
        "必ず JSON オブジェクトだけを返してください。"
        "キーは $version, metadata{title,description}, components です。"
        f"$version は {spec.SPEC_VERSION}。"
        "components の各要素は id, type, label, required, properties を持ちます。"
        "imi_type と imi_subfields は省略してよい（サーバーが型の既定語彙を補う）。"
        f"type は次のカタログに含まれるものだけ使ってください: {allowed}。"
        "select/radio/checkbox には properties.options 配列が必要です。"
        "説明文やコードフェンス以外は出力しないでください。"
    )
    user = f"次の要件でフォームを作成してください。\n{q}"
    if current:
        user += "\n\n既存定義を尊重し、可能な限り id を維持して修正してください。\n"
        user += json.dumps(current, ensure_ascii=False)
    try:
        raw = await llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        parsed = llm.extract_json(raw)
        definition, err = apply_generated(parsed, visibility=visibility, current=current)
        if err or definition is None:
            raise ValueError(err or "検証に失敗しました")
        return {
            "source": "llm",
            "definition": definition,
            "notes": "AI が生成した定義です。保存前に内容を確認してください。",
            "model": llm.PATCHFORM_MODEL,
        }
    except Exception as e:  # noqa: BLE001
        base = fallback_definition(q)
        if current:
            base = merge_definition(current, base)
        base = {
            **base,
            "components": [
                spec.fill_default_imi(c) if isinstance(c, dict) else c
                for c in (base.get("components") or [])
            ],
        }
        definition, err = spec.validate_definition(base, visibility=visibility)
        if err or definition is None:
            raise ValueError(err or "テンプレートの検証に失敗しました") from e
        return {
            "source": "template",
            "definition": definition,
            "notes": f"LLM を使えなかったためテンプレートを使いました（{e}）。",
            "model": llm.PATCHFORM_MODEL,
        }


async def draft_invite(title: str, public_url: str, tone: str = "丁寧") -> dict[str, Any]:
    fallback = fallback_invite(title, public_url, tone)
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは自治体の案内文作成者です。JSON のみ返してください。"
                "キー: subject, body。本文は日本語。"
            ),
        },
        {
            "role": "user",
            "content": f"トーン:{tone}\nタイトル:{title}\nURL:{public_url}",
        },
    ]
    try:
        raw = await llm.chat(messages)
        parsed = llm.extract_json(raw)
        if not isinstance(parsed, dict) or not parsed.get("subject") or not parsed.get("body"):
            raise ValueError("案内文の形式が不正です")
        return {**fallback, **{k: parsed[k] for k in ("subject", "body")}, "source": "llm"}
    except Exception as e:  # noqa: BLE001
        return {**fallback, "source": "template", "notes": str(e)}


MAX_PROCEDURE_FORMS = 6
MAX_PROCEDURE_TEXT = 12_000


def _simple_form(title: str, description: str, comps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": title, "description": description},
        "components": comps,
    }


def fallback_procedure_draft(text: str) -> dict[str, Any]:
    """LLM なしでも手続き第1版を組めるテンプレート。公開はしない。"""
    q = (text or "").strip()
    if any(k in q for k in ("転入", "転居", "引越", "引っ越し")):
        name = "転入・転居の手続き"
        guide_opts = ["転入", "転居"]
        forms = [
            {
                "key": "move_in",
                "definition": _simple_form(
                    "転入届",
                    "転入の届出",
                    [
                        _c("applicant", "user_info_composite", "届出人", True),
                        _c("addr", "address_composite", "新しい住所", True),
                    ],
                ),
            },
            {
                "key": "attach",
                "definition": _simple_form(
                    "添付台紙",
                    "持ち物の提出",
                    [_c("files", "file", "添付", True)],
                ),
            },
        ]
        rules = [
            {
                "component_id": "event",
                "option": "転入",
                "form_keys": ["move_in", "attach"],
                "notes": "転入届と添付を出してください。",
                "prepare": ["本人確認書類", "在留カード（該当する人）"],
            },
            {
                "component_id": "event",
                "option": "転居",
                "form_keys": ["attach"],
                "notes": "転居の場合は添付を確認してください。",
                "prepare": ["本人確認書類"],
            },
        ]
        missing = ["文書に無い分岐は足していません"]
    elif any(k in q for k in ("医療", "子ども", "小児", "助成")):
        name = "子ども医療費の手続き"
        guide_opts = ["新たに申請する", "内容を変更する"]
        forms = [
            {
                "key": "apply",
                "definition": _simple_form(
                    "医療費助成の申請",
                    "",
                    [
                        _c("applicant", "user_info_composite", "保護者", True),
                        _c("child", "text", "お子さまの氏名", True),
                        _c("bank", "financial_institution_composite", "振込先", True),
                    ],
                ),
            }
        ]
        rules = [
            {
                "component_id": "event",
                "option": "新たに申請する",
                "form_keys": ["apply"],
                "notes": "申請書を出してください。",
                "prepare": ["保険証", "振込先が分かるもの"],
            },
            {
                "component_id": "event",
                "option": "内容を変更する",
                "form_keys": ["apply"],
                "notes": "変更内容を申請書に書いてください。",
                "prepare": ["保険証"],
            },
        ]
        missing = ["審査基準はマスタに載せていません"]
    else:
        name = (q[:30] or "手続き") + ("の手続き" if "手続" not in q[:30] else "")
        guide_opts = ["該当する", "該当しない"]
        forms = [
            {
                "key": "main",
                "definition": _simple_form(
                    "届出",
                    "",
                    [
                        _c("applicant", "user_info_composite", "届出人", True),
                        _c("note", "textarea", "内容", True),
                    ],
                ),
            }
        ]
        rules = [
            {
                "component_id": "event",
                "option": "該当する",
                "form_keys": ["main"],
                "notes": "届出を出してください。",
                "prepare": ["本人確認書類"],
            }
        ]
        missing = ["文書から分岐を読み取れなかったため、仮の選択肢です"]

    guide = _simple_form(
        f"{name}の案内",
        "状況を選んでください。",
        [
            _c("event", "radio", "該当するもの", True, options=guide_opts),
        ],
    )
    return {
        "name": name,
        "description": q[:400] or None,
        "guide": guide,
        "forms": forms,
        "rules": rules,
        "missing": missing,
        "notes": "テンプレートによる第1版です。公開前に内容を確認してください。",
    }


def _definition_from_part(raw: Any, title: str, visibility: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        raw = {}
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    incoming = {
        "$version": spec.SPEC_VERSION,
        "metadata": {
            "title": str(raw.get("title") or meta.get("title") or title),
            "description": str(raw.get("description") or meta.get("description") or ""),
        },
        "components": raw.get("components") if isinstance(raw.get("components"), list) else [],
    }
    return apply_generated(incoming, visibility=visibility)


def normalize_procedure_draft(
    raw: Any, *, visibility: str = "internal"
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "手続き案の形式が不正です"
    name = str(raw.get("name") or raw.get("title") or "").strip()
    if not name:
        return None, "手続き名がありません"
    guide, gerr = _definition_from_part(raw.get("guide") or {}, f"{name}の案内", visibility)
    if gerr or guide is None:
        return None, gerr or "案内フォームの生成に失敗しました"
    has_choice = any(
        isinstance(c, dict) and c.get("type") in ("select", "radio", "checkbox")
        for c in (guide.get("components") or [])
    )
    if not has_choice:
        return None, "案内にラジオ・セレクト・チェックボックスがありません"
    forms_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw.get("forms") or []):
        if len(forms_out) >= MAX_PROCEDURE_FORMS:
            break
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or f"form{i + 1}").strip() or f"form{i + 1}"
        if key in seen:
            continue
        seen.add(key)
        title = str(item.get("title") or (item.get("metadata") or {}).get("title") or f"様式{i + 1}")
        definition, ferr = _definition_from_part(item.get("definition") or item, title, visibility)
        if ferr or definition is None:
            return None, ferr or f"様式「{title}」の生成に失敗しました"
        forms_out.append({"key": key, "definition": definition})
    if not forms_out:
        return None, "足す様式が1つもありません"
    keys = {f["key"] for f in forms_out}
    rules: list[dict[str, Any]] = []
    for item in raw.get("rules") or []:
        if not isinstance(item, dict):
            continue
        component_id = str(item.get("component_id") or "").strip()
        option = str(item.get("option") or "").strip()
        form_keys = [
            str(k).strip()
            for k in (item.get("form_keys") or item.get("form_ids") or [])
            if str(k).strip() in keys
        ]
        if not component_id or not option:
            continue
        prepare = item.get("prepare") or []
        if isinstance(prepare, str):
            prepare = [p.strip() for p in prepare.splitlines() if p.strip()]
        rules.append(
            {
                "component_id": component_id,
                "option": option,
                "form_keys": form_keys,
                "notes": str(item.get("notes") or "").strip(),
                "prepare": [str(p).strip() for p in prepare if str(p).strip()],
            }
        )
    missing = raw.get("missing") or []
    if isinstance(missing, str):
        missing = [missing]
    notes = str(raw.get("notes") or "").strip()
    return {
        "name": name,
        "description": str(raw.get("description") or "").strip() or None,
        "guide": guide,
        "forms": forms_out,
        "rules": rules,
        "missing": [str(m).strip() for m in missing if str(m).strip()],
        "notes": notes,
    }, None


async def draft_procedure(text: str, *, visibility: str = "internal") -> dict[str, Any]:
    q = (text or "").strip()
    if not q:
        raise ValueError("手引きや案内の本文は必須です")
    q = q[:MAX_PROCEDURE_TEXT]
    allowed = json.dumps(catalog_for_prompt(), ensure_ascii=False)
    system = (
        "あなたは日本の自治体向け手続き設計者です。"
        "手引きや庁内マニュアルから、未公開の手続き第1版を JSON だけで作ってください。"
        "例規から手順を作らないでください。文書に無い分岐は missing に書き、勝手に補完した箇所は notes に書いてください。"
        "キー: name, description, guide, forms, rules, missing, notes。"
        "guide と forms[].definition はフォーム定義です。"
        f"$version は {spec.SPEC_VERSION}。components は id, type, label, required, properties。"
        f"type は次だけ: {allowed}。"
        "guide には状況を聞く radio または select を必ず1つ以上入れてください。"
        "forms は最大6件。各要素は key, title, definition。"
        "rules は component_id, option, form_keys, notes, prepare。"
        "form_keys は forms[].key を指します。"
    )
    user = f"次の文書から手続き第1版を作ってください。\n{q}"
    try:
        raw = await llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            max_tokens=max(llm.DEFAULT_MAX_TOKENS, 3072),
        )
        parsed = llm.extract_json(raw)
        draft, err = normalize_procedure_draft(parsed, visibility=visibility)
        if err or draft is None:
            raise ValueError(err or "手続き案の検証に失敗しました")
        return {
            "source": "llm",
            "draft": draft,
            "notes": draft.get("notes")
            or "AI が作った第1版です。公開せず、内容を確認してください。",
            "model": llm.PATCHFORM_MODEL,
        }
    except Exception as e:  # noqa: BLE001
        draft, err = normalize_procedure_draft(
            fallback_procedure_draft(q), visibility=visibility
        )
        if err or draft is None:
            raise ValueError(err or "テンプレートの検証に失敗しました") from e
        return {
            "source": "template",
            "draft": draft,
            "notes": f"LLM を使えなかったためテンプレートを使いました（{e}）。公開前に確認してください。",
            "model": llm.PATCHFORM_MODEL,
        }
