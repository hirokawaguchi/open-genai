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


def test_extract_form_titles_from_handbook() -> None:
    text = """## 障害福祉サービス等 指定申請の手引き － 目次 －

様式一覧
様式第1号　指定申請書 ・・・・ 10
様式第2号　付表（障害福祉サービス事業）
様式第2号の2　付表（障害児通所支援事業）
１ 指定申請書（様式第1号）
「誓約書」
"""
    titles = assist.extract_form_titles(text)
    assert any("指定申請書" in t and "様式第1号" in t.replace(" ", "") for t in titles)
    assert any("付表" in t and "様式第2号" in t.replace(" ", "") for t in titles)
    assert any("様式第2号の2" in t.replace(" ", "") for t in titles)
    raw = assist.fallback_procedure_draft(text)
    draft, err = assist.normalize_procedure_draft(raw)
    assert err is None and draft
    assert draft["guide"]["components"][0]["type"] == "radio"
    assert assist.ALL_FORMS_OPTION in str(draft["guide"])
    assert len(draft["forms"]) >= 3
    assert all(not f["definition"]["components"] for f in draft["forms"])
    preview = assist.preview_procedure_draft(draft)
    assert preview["navigation"]["found"] is True
    assert all(item["title_only"] for item in preview["forms"])


def test_clean_heading_keeps_katakana_long_vowel() -> None:
    # 「ー」を潰さない（チェックシート/ページ/サービスが壊れない）
    assert assist.clean_heading("申請書提出前チェックシート") == "申請書提出前チェックシート"
    assert assist.clean_heading("このページの先頭へ") == "このページの先頭へ"
    # ダッシュ区切りは従来どおり空白に潰す
    assert assist.clean_heading("指定申請の手引き － 目次 －").startswith("指定申請の手引き")
    assert "目次" not in assist.clean_heading("指定申請の手引き － 目次 －")


def test_extract_form_titles_cleans_table_rows() -> None:
    # 実在の手引き（群馬県・建設業許可）に近い markdown 表の行
    text = (
        "| 3 | 第2号 | 工事経歴書 ※業種別に作成、実績なしでも作成 | "
        "様式第2号（Excelファイル：16KB） | 様式第2号（PDFファイル：39KB） | 要 | 要 | 要 | 要 | 省略可 |\n"
        "| 11 | 第20号 | 営業の沿革 | 様式第20号（Excelファイル：48KB） | "
        "様式第20号（PDFファイル：72KB） | 要 | 要 | 省略可 |\n"
    )
    titles = assist.extract_form_titles(text)
    joined = "\n".join(titles)
    # ゴミ（パイプ・ファイルサイズ・要否）が名前に混ざらない
    assert "|" not in joined
    assert "KB" not in joined
    assert "ファイル" not in joined
    assert "要" not in joined and "省略可" not in joined
    # 様式番号 + 説明名だけが残る
    assert any(t.replace(" ", "") == "様式第2号工事経歴書" for t in titles)
    assert any(t.replace(" ", "") == "様式第20号営業の沿革" for t in titles)


def test_extract_form_titles_drops_footnote_legend() -> None:
    # 注記凡例に紛れた様式番号は様式名にしない
    text = "（注5）様式第11号に該当者無しであれば省略可 （注6）身分証明書について\n"
    titles = assist.extract_form_titles(text)
    assert all("該当者無し" not in t for t in titles)


def test_split_and_select_guide_chapters() -> None:
    text = """## 障害福祉サービス等 指定申請の手引き － 目次 －
1 はじめに ........ 1
2 様式一覧 ........ 5
## 第1 はじめに
この手引きの使い方です。
## 様式一覧
様式第1号　指定申請書
様式第2号　付表
## 審査基準
点数の付け方です。様式は出てきません。
"""
    chapters = assist.split_guide_chapters(text)
    kinds = {c["title"]: c["kind"] for c in chapters}
    assert any(c["kind"] == "toc" for c in chapters)
    assert kinds.get("様式一覧") == "body"
    selected = assist.select_guide_chapters(chapters)
    titles = [c["title"] for c in selected]
    assert any("様式" in t for t in titles)
    assert all("審査基準" not in t for t in titles)
    read = [assist.analyze_chapter(c) for c in selected]
    found = assist.merge_form_titles(*(item["titles"] for item in read))
    assert any("指定申請書" in t for t in found)


def test_fallback_generic_does_not_invent() -> None:
    raw = assist.fallback_procedure_draft("## 障害福祉サービス等 指定申請の手引き － 目次 －")
    assert raw["forms"] == []
    assert raw["rules"] == []
    draft, err = assist.normalize_procedure_draft(raw)
    assert err is None and draft
    assert "目次" not in draft["name"]
    assert "#" not in draft["name"]
    preview = assist.preview_procedure_draft(draft)
    assert preview["navigation"]["found"] is False
    assert preview["forms"] == []


def test_normalize_allows_missing_choice() -> None:
    raw = assist.fallback_procedure_draft("転入届の手引き")
    raw["guide"]["components"] = [{"id": "note", "type": "textarea", "label": "内容"}]
    draft, err = assist.normalize_procedure_draft(raw)
    assert err is None and draft
    assert assist.guide_has_choice(draft["guide"]) is False


def test_draft_procedure_reads_selected_chapters() -> None:
    async def _run() -> None:
        text = """## 障害福祉サービス等 指定申請の手引き － 目次 －
目次だけ
## 第1 はじめに
説明だけです。
## 様式一覧
様式第1号　指定申請書
様式第3号　誓約書
## 審査基準
点数の話です。
"""
        with patch("app.assist.llm.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
            result = await assist.draft_procedure(text)
        titles = [f["definition"]["metadata"]["title"] for f in result["draft"]["forms"]]
        assert any("指定申請書" in t for t in titles)
        assert any("誓約書" in t for t in titles)
        read_titles = [c["title"] for c in result["outline"]["read"]]
        assert any("様式" in t for t in read_titles)

    asyncio.run(_run())


def test_draft_procedure_reads_titles_past_toc() -> None:
    async def _run() -> None:
        text = "## 障害福祉サービス等 指定申請の手引き － 目次 －\n" + ("目次項目\n" * 800)
        text += "様式一覧\n様式第1号　指定申請書\n様式第3号　誓約書\n"
        with patch("app.assist.llm.chat", new=AsyncMock(side_effect=RuntimeError("down"))):
            result = await assist.draft_procedure(text)
        titles = [f["definition"]["metadata"]["title"] for f in result["draft"]["forms"]]
        assert any("指定申請書" in t for t in titles)
        assert any("誓約書" in t for t in titles)
        assert result["draft"]["guide"]["components"][0]["type"] == "radio"

    asyncio.run(_run())


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
    test_extract_form_titles_from_handbook()
    test_clean_heading_keeps_katakana_long_vowel()
    test_extract_form_titles_cleans_table_rows()
    test_extract_form_titles_drops_footnote_legend()
    test_split_and_select_guide_chapters()
    test_fallback_generic_does_not_invent()
    test_normalize_allows_missing_choice()
    test_draft_procedure_reads_selected_chapters()
    test_draft_procedure_reads_titles_past_toc()
    test_draft_procedure_falls_back_without_llm()
    print("ok")
