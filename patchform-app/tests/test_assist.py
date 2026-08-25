"""工程4: AI 生成のテンプレート・マージ・検証（LLM なし）。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import assist, spec


def test_fallback_and_llm_get_default_imi() -> None:
    d = assist.fallback_definition("事業者の届出")
    company = next(c for c in d["components"] if c["type"] == "company_info_composite")
    mail = next(c for c in d["components"] if c["type"] == "email")
    assert company["imi_type"] == "ic:法人"
    assert company["imi_subfields"]["company_name"] == "ic:名称"
    assert company["imi_subfields"]["representative"] == "ic:氏名"
    assert mail["imi_type"] == "ic:電子メール"
    normalized, err = spec.validate_definition(d)
    assert err is None and normalized
    assert normalized["components"][0]["imi_type"] == "ic:法人"

    raw = {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": "届出"},
        "components": [
            {"id": "mail", "type": "email", "label": "メール"},
            {
                "id": "co",
                "type": "company_info_composite",
                "label": "法人",
                "imi_type": "ic:組織",
                "imi_subfields": {"company_name": "ic:商号又は名称"},
            },
        ],
    }
    filled, ferr = assist.apply_generated(raw, visibility="internal")
    assert ferr is None and filled
    by_id = {c["id"]: c for c in filled["components"]}
    assert by_id["mail"]["imi_type"] == "ic:電子メール"
    assert by_id["co"]["imi_type"] == "ic:組織"
    assert by_id["co"]["imi_subfields"]["company_name"] == "ic:商号又は名称"
    assert by_id["co"]["imi_subfields"]["corporate_number"] == "ic:法人番号"


def test_merge_keeps_custom_imi() -> None:
    current = {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": "旧"},
        "components": [
            {
                "id": "keep_me",
                "type": "email",
                "label": "メールアドレス",
                "imi_type": "ic:連絡先",
            }
        ],
    }
    incoming = {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": "新"},
        "components": [{"id": "new_id", "type": "email", "label": "メールアドレス"}],
    }
    merged = assist.merge_definition(current, incoming)
    assert merged["components"][0]["id"] == "keep_me"
    assert merged["components"][0]["imi_type"] == "ic:連絡先"


def test_fallback_medical() -> None:
    d = assist.fallback_definition("子ども医療費の申請を作りたい")
    types = [c["type"] for c in d["components"]]
    assert "user_info_composite" in types
    assert "address_composite" in types
    assert "financial_institution_composite" in types
    normalized, err = spec.validate_definition(d)
    assert err is None and normalized


def test_merge_keeps_id() -> None:
    current = {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": "旧"},
        "components": [{"id": "keep_me", "type": "text", "label": "氏名", "required": True}],
    }
    incoming = {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": "新"},
        "components": [{"id": "new_id", "type": "text", "label": "氏名", "required": True}],
    }
    merged = assist.merge_definition(current, incoming)
    assert merged["components"][0]["id"] == "keep_me"
    assert merged["metadata"]["title"] == "新"


def test_apply_rejects_disabled() -> None:
    spec.CATALOG["text"]["enabled"] = False
    try:
        raw = {
            "$version": spec.SPEC_VERSION,
            "metadata": {"title": "x"},
            "components": [{"id": "m", "type": "text", "label": "テキスト"}],
        }
        _d, err = assist.apply_generated(raw, visibility="internal")
        assert err and "まだ利用できません" in err
    finally:
        spec.CATALOG["text"]["enabled"] = True


def test_generate_falls_back_without_llm() -> None:
    async def _run() -> None:
        with patch("app.assist.llm.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
            result = await assist.generate_form("補助金の申請")
        assert result["source"] == "template"
        assert result["definition"]["components"]
        types = [c["type"] for c in result["definition"]["components"]]
        assert "financial_institution_composite" in types

    asyncio.run(_run())


def test_generate_uses_llm_when_valid() -> None:
    payload = {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": "届出", "description": ""},
        "components": [
            {"id": "name", "type": "text", "label": "氏名", "required": True},
            {
                "id": "kind",
                "type": "select",
                "label": "区分",
                "required": True,
                "properties": {"options": ["新規", "変更"]},
            },
        ],
    }

    async def _run() -> None:
        with patch(
            "app.assist.llm.chat",
            new=AsyncMock(return_value=__import__("json").dumps(payload)),
        ):
            result = await assist.generate_form("届出を作って")
        assert result["source"] == "llm"
        assert result["definition"]["metadata"]["title"] == "届出"

    asyncio.run(_run())


def test_invite_fallback() -> None:
    out = assist.fallback_invite("申請", "https://example.lg.jp/public/f/x")
    assert "申請" in out["subject"]
    assert "https://example.lg.jp/public/f/x" in out["body"]


def test_fallback_procedure_move() -> None:
    raw = assist.fallback_procedure_draft("転入届の手引き。転入と転居。")
    assert raw["name"] == "転入・転居の手続き"
    draft, err = assist.normalize_procedure_draft(raw)
    assert err is None and draft
    assert draft["guide"]["components"][0]["type"] == "radio"
    keys = {f["key"] for f in draft["forms"]}
    assert keys == {"move_in", "attach"}
    assert draft["rules"][0]["form_keys"] == ["move_in", "attach"]


def test_normalize_procedure_requires_choice() -> None:
    raw = assist.fallback_procedure_draft("届出の手引き")
    raw["guide"]["components"] = [{"id": "note", "type": "textarea", "label": "内容"}]
    _draft, err = assist.normalize_procedure_draft(raw)
    assert err and "ラジオ" in err


def test_draft_procedure_falls_back_without_llm() -> None:
    async def _run() -> None:
        with patch("app.assist.llm.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
            result = await assist.draft_procedure("子ども医療費の手引き")
        assert result["source"] == "template"
        assert result["draft"]["name"] == "子ども医療費の手続き"
        assert result["draft"]["forms"]

    asyncio.run(_run())


if __name__ == "__main__":
    test_fallback_and_llm_get_default_imi()
    test_merge_keeps_custom_imi()
    test_fallback_medical()
    test_merge_keeps_id()
    test_apply_rejects_disabled()
    test_generate_falls_back_without_llm()
    test_generate_uses_llm_when_valid()
    test_invite_fallback()
    test_fallback_procedure_move()
    test_normalize_procedure_requires_choice()
    test_draft_procedure_falls_back_without_llm()
    print("ok")
