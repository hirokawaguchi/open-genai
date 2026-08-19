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
    return {
        "id": cid,
        "type": ctype,
        "label": label,
        "required": required,
        "placeholder": "",
        "properties": props,
    }


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
