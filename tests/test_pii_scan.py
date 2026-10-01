from __future__ import annotations

import json
import sqlite3

import pytest

from shared import pii_scan as pii_mod
from shared.pii_scan import (
    CAT_ADDRESS,
    CAT_MYNUMBER,
    CAT_PHONE,
    format_categories,
    load_pii_settings,
    scan,
)


def test_scan_phone_and_mynumber() -> None:
    text = "連絡先は 090-1234-5678、番号 123456789018 です"
    result = scan(text, enable_ner=False, check_mynumber=True)
    assert CAT_PHONE in result["categories"]
    assert CAT_MYNUMBER in result["categories"]
    assert format_categories(result["categories"]).count("・") >= 1


def test_scan_invalid_mynumber_ignored() -> None:
    text = "無効な12桁 123456789019 のみ"
    result = scan(text, enable_ner=False, check_mynumber=True)
    assert CAT_MYNUMBER not in result["categories"]


def test_scan_address_pattern() -> None:
    text = "送付先: 大分県大分市荷揚町2番31号"
    result = scan(text, enable_ner=False, check_mynumber=False)
    assert CAT_ADDRESS in result["categories"]


def test_scan_uuid_not_phone() -> None:
    text = "id=550e8400-e29b-41d4-a716-446655440000"
    result = scan(text, enable_ner=False, check_mynumber=True)
    assert result["categories"] == []


def test_format_categories_order() -> None:
    assert format_categories(["電話番号", "マイナンバー"]) == "電話番号・マイナンバー"


def test_scan_person_name_with_ginza() -> None:
    """GiNZA 導入時のみ氏名 NER を検証する。"""
    pii_mod._nlp = None
    pii_mod._nlp_failed = False
    if pii_mod._get_nlp() is None:
        pytest.skip("ja_ginza 未導入")
    result = scan(
        "申請者は山田太郎です。電話は090-1234-5678です。",
        enable_ner=True,
        check_mynumber=False,
    )
    assert "氏名" in result["categories"]
    assert "電話番号" in result["categories"]
    assert any(h["category"] == "氏名" and "山田" in h["match"] for h in result["hits"])
    assert any(h["category"] == "電話番号" for h in result["hits"])


def test_load_pii_settings_defaults_when_no_db(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NGWORD_DB_PATH", str(tmp_path / "missing.db"))
    out = load_pii_settings()
    assert out["check_mynumber"] is True
    assert out["scan_knowledge_pii"] is True


def test_load_pii_settings_per_tenant(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "ngwords.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE ngword_rules_v2 ("
        " tenantId TEXT PRIMARY KEY, rules TEXT NOT NULL, updatedDate TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO ngword_rules_v2 (tenantId, rules, updatedDate) VALUES (?, ?, ?)",
        (
            pii_mod.DEFAULT_TENANT_ID,
            json.dumps({"scan_knowledge_pii": False, "check_mynumber": False}),
            "1",
        ),
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("NGWORD_DB_PATH", str(db_path))

    # 既定の棟は保存した設定（無効）を読む。
    default_out = load_pii_settings(pii_mod.DEFAULT_TENANT_ID)
    assert default_out["scan_knowledge_pii"] is False
    assert default_out["check_mynumber"] is False

    # 行の無い棟は既定（有効）に戻る。
    other_out = load_pii_settings("00000000-0000-0000-0000-00000000ffff")
    assert other_out["scan_knowledge_pii"] is True
    assert other_out["check_mynumber"] is True


def test_scan_rejects_ner_false_positives() -> None:
    """組織略称や AI 用語を氏名扱いにしない。"""
    pii_mod._nlp = None
    pii_mod._nlp_failed = False
    if pii_mod._get_nlp() is None:
        pytest.skip("ja_ginza 未導入")
    text = (
        "生成AI・AIエージェントの急速な進展を踏まえ、府省庁初のOSPO。"
        "右中央の吹き出しには連携とある。"
    )
    result = scan(text, enable_ner=True, check_mynumber=False)
    assert "氏名" not in result["categories"]
