"""工程1-2: フォーム JSON 契約の検証。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import spec


def _comp(cid: str, ctype: str, **kwargs: object) -> dict:
    base = {"id": cid, "type": ctype, "label": kwargs.pop("label", cid), "required": False}
    base.update(kwargs)
    return base


def test_empty_definition_ok() -> None:
    d, err = spec.validate_definition(spec.empty_definition("申請"))
    assert err is None
    assert d is not None
    assert d["$version"] == spec.SPEC_VERSION
    assert d["components"] == []


def test_unknown_type_rejected() -> None:
    raw = spec.empty_definition()
    raw["components"] = [_comp("c1", "unknown", label="謎")]
    _d, err = spec.validate_definition(raw)
    assert err and "未知" in err


def test_disabled_type_rejected() -> None:
    spec.CATALOG["text"]["enabled"] = False
    try:
        raw = spec.empty_definition()
        raw["components"] = [_comp("c1", "text", label="テキスト")]
        _d, err = spec.validate_definition(raw)
        assert err and "まだ利用できません" in err
    finally:
        spec.CATALOG["text"]["enabled"] = True


def test_duplicate_id_rejected() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp("same", "text", label="A"),
        _comp("same", "text", label="B"),
    ]
    _d, err = spec.validate_definition(raw)
    assert err and "重複" in err


def test_select_needs_options() -> None:
    raw = spec.empty_definition()
    raw["components"] = [_comp("c1", "select", label="区分")]
    _d, err = spec.validate_definition(raw)
    assert err and "選択肢" in err


def test_basic_types_accepted() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp("name", "text", label="氏名", required=True),
        _comp("note", "textarea", label="備考"),
        _comp("mail", "email", label="メール"),
        _comp("tel", "phone", label="電話"),
        _comp("age", "number", label="年齢"),
        _comp("kind", "select", label="区分", properties={"options": ["A", "B"]}),
        _comp("ok", "radio", label="可否", properties={"options": ["可", "否"]}),
        _comp("tags", "checkbox", label="対象", properties={"options": ["1", "2"]}),
        _comp("day", "date", label="希望日"),
        _comp("att", "file", label="添付"),
    ]
    d, err = spec.validate_definition(raw)
    assert err is None
    assert d is not None
    assert [c["type"] for c in d["components"]] == [
        "text",
        "textarea",
        "email",
        "phone",
        "number",
        "select",
        "radio",
        "checkbox",
        "date",
        "file",
    ]


def test_answers_required() -> None:
    definition, err = spec.validate_definition(
        {
            "$version": spec.SPEC_VERSION,
            "metadata": {"title": "t"},
            "components": [_comp("name", "text", label="氏名", required=True)],
        }
    )
    assert err is None and definition
    _a, aerr = spec.validate_answers(definition, {})
    assert aerr and "必須" in aerr


def test_answers_email_and_select() -> None:
    definition, err = spec.validate_definition(
        {
            "$version": spec.SPEC_VERSION,
            "metadata": {"title": "t"},
            "components": [
                _comp("mail", "email", label="メール", required=True),
                _comp("kind", "select", label="区分", properties={"options": ["A", "B"]}),
            ],
        }
    )
    assert err is None and definition
    _a, aerr = spec.validate_answers(definition, {"mail": "not-mail"})
    assert aerr and "メール" in aerr
    cleaned, aerr = spec.validate_answers(
        definition, {"mail": "a@example.jp", "kind": "A"}
    )
    assert aerr is None
    assert cleaned == {"mail": "a@example.jp", "kind": "A"}


def test_visible_when() -> None:
    definition, err = spec.validate_definition(
        {
            "$version": spec.SPEC_VERSION,
            "metadata": {"title": "t"},
            "components": [
                _comp(
                    "need",
                    "radio",
                    label="必要",
                    properties={"options": ["はい", "いいえ"]},
                    required=True,
                ),
                _comp(
                    "detail",
                    "text",
                    label="詳細",
                    required=True,
                    visibleWhen={"field": "need", "eq": "はい"},
                ),
            ],
        }
    )
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(definition, {"need": "いいえ"})
    assert aerr is None
    assert "detail" not in cleaned
    _c, aerr = spec.validate_answers(definition, {"need": "はい"})
    assert aerr and "必須" in aerr


def test_visible_when_in_and_number() -> None:
    definition, err = spec.validate_definition(
        {
            "$version": spec.SPEC_VERSION,
            "metadata": {"title": "t"},
            "components": [
                _comp("kind", "checkbox", label="区分", properties={"options": ["A", "B", "C"]}),
                _comp("qty", "number", label="数量", required=True),
                _comp(
                    "note",
                    "text",
                    label="備考",
                    required=True,
                    visibleWhen=[
                        {"field": "kind", "in": ["A", "B"]},
                        {"field": "qty", "eq": "2"},
                    ],
                ),
            ],
        }
    )
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(definition, {"kind": ["A"], "qty": 3})
    assert aerr is None
    assert "note" not in cleaned
    cleaned, aerr = spec.validate_answers(definition, {"kind": ["C"], "qty": 2})
    assert aerr is None
    assert "note" not in cleaned
    _c, aerr = spec.validate_answers(definition, {"kind": ["A"], "qty": 2})
    assert aerr and "必須" in aerr
    cleaned, aerr = spec.validate_answers(
        definition, {"kind": ["A"], "qty": 2, "note": "詳細"}
    )
    assert aerr is None and cleaned["note"] == "詳細"


def test_composites_and_formula() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        {
            "id": "addr",
            "type": "address_composite",
            "label": "住所",
            "required": True,
        },
        {
            "id": "qty",
            "type": "number",
            "label": "数量",
            "required": True,
        },
        {
            "id": "total",
            "type": "calculated",
            "label": "合計",
            "properties": {"formula": "{{qty}} * 100"},
        },
    ]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    _a, aerr = spec.validate_answers(definition, {"addr": {"city": "港区"}, "qty": 2})
    assert aerr and "必須" in aerr
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "addr": {
                "postal_code": "105-0001",
                "prefecture": "東京都",
                "city": "港区",
                "street": "1-2-3",
            },
            "qty": 2,
        },
    )
    assert aerr is None and cleaned
    assert cleaned["total"] == 200.0
    _bad, berr = spec.validate_answers(
        {
            **definition,
            "components": [
                *definition["components"][:-1],
                {
                    "id": "evil",
                    "type": "calculated",
                    "label": "不正",
                    "properties": {"formula": "{{qty}} + __import__('os').system('id')"},
                },
            ],
        },
        {
            "addr": {
                "prefecture": "東京都",
                "city": "港区",
                "street": "1-2-3",
            },
            "qty": 2,
        },
    )
    assert berr and "計算式が不正" in berr


def _valid_mynumber() -> str:
    first11 = "12345678901"
    total = 0
    for i in range(1, 12):
        p = int(first11[11 - i])
        q = i + 1 if i <= 6 else i - 5
        total += p * q
    c = total % 11
    check = 0 if c <= 1 else 11 - c
    return first11 + str(check)


def test_mynumber_internal_only() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        {"id": "mn", "type": "mynumber", "label": "個人番号", "required": True}
    ]
    _d, err = spec.validate_definition(raw, visibility="public")
    assert err and "庁内専用" in err
    definition, err = spec.validate_definition(raw, visibility="internal")
    assert err is None and definition
    mn = _valid_mynumber()
    assert spec.mynumber_check_digit_ok(mn)
    cleaned, aerr = spec.validate_answers(definition, {"mn": mn})
    assert aerr is None and cleaned
    _c, aerr = spec.validate_answers(definition, {"mn": "123456789012"})
    assert aerr and "検査数字" in aerr


def test_catalog_enabled_only_in_public() -> None:
    types = {c["type"] for c in spec.catalog_public()}
    assert "text" in types
    assert "mynumber" in types
    assert "image_recognition" in types
    assert "location" in types
    assert set(spec.enabled_types()) == types
    assert types == {t for t, meta in spec.CATALOG.items() if meta["enabled"]}


def test_location_qr_and_ai_fields() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        {"id": "loc", "type": "location", "label": "位置", "required": True},
        {"id": "qr", "type": "qr_scanner", "label": "QR", "required": True},
        {"id": "img", "type": "image_recognition", "label": "画像", "required": True},
        {
            "id": "pic",
            "type": "image_display",
            "label": "案内図",
            "properties": {"src": "https://example.lg.jp/map.png"},
        },
    ]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "loc": {"lat": "35.0", "lng": "139.0"},
            "qr": " https://example.lg.jp ",
            "img": {"filename": "card.jpg", "extracted": "氏名 山田"},
        },
    )
    assert aerr is None and cleaned
    assert cleaned["loc"] == {"lat": 35.0, "lng": 139.0}
    assert cleaned["qr"] == "https://example.lg.jp"
    assert cleaned["img"]["extracted"] == "氏名 山田"
    bad = spec.empty_definition()
    bad["components"] = [
        {
            "id": "pic",
            "type": "image_display",
            "label": "案内図",
            "properties": {"src": "javascript:alert(1)"},
        }
    ]
    _d, berr = spec.validate_definition(bad)
    assert berr and "画像 URL" in berr


def test_file_and_signature_values() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp("att", "file", label="添付", required=True),
        _comp("sign", "signature_pad", label="署名", required=True),
    ]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "att": {"file_id": "11111111-1111-1111-1111-111111111111", "filename": "a.pdf", "size": 12},
            "sign": {"file_id": "22222222-2222-2222-2222-222222222222", "filename": "sign.png"},
        },
    )
    assert aerr is None and cleaned
    assert cleaned["att"]["file_id"].startswith("1111")
    assert cleaned["sign"]["filename"] == "sign.png"
    _c, aerr = spec.validate_answers(definition, {"att": "", "sign": "not-an-image"})
    assert aerr and "必須" in aerr


def test_hide_label_persisted() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp("agree", "checkbox", label="同意", hide_label=True, properties={"options": ["同意する"]})
    ]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    assert definition["components"][0]["hide_label"] is True


def test_financial_yuucho_and_codes() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp("bank", "financial_institution_composite", label="振込先", required=True)
    ]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    _a, aerr = spec.validate_answers(definition, {"bank": {"bank_name": "みずほ"}})
    assert aerr and "必須" in aerr
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "bank": {
                "bank_code": "0001",
                "bank_name": "みずほ",
                "branch_code": "001",
                "branch_name": "本店",
                "account_type": "普通",
                "account_number": "1234567",
                "account_holder": "ヤマダタロウ",
            }
        },
    )
    assert aerr is None and cleaned
    _bad, berr = spec.validate_answers(
        definition,
        {"bank": {"bank_code": "1", "bank_name": "みずほ", "account_number": "1", "account_holder": "A"}},
    )
    assert berr and "金融機関コード" in berr
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "bank": {
                "is_yuucho": "1",
                "yuucho_symbol": "10170",
                "yuucho_number": "12345671",
                "account_holder": "ヤマダタロウ",
            }
        },
    )
    assert aerr is None and cleaned
    assert cleaned["bank"]["branch_code"] == "017"
    assert cleaned["bank"]["account_number"] == "2345671"
    assert cleaned["bank"]["bank_code"] == "9900"


def test_user_info_gender_and_birth() -> None:
    raw = spec.empty_definition()
    raw["components"] = [_comp("who", "user_info_composite", label="申請者", required=True)]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "who": {
                "last_name": "山田",
                "first_name": "太郎",
                "gender": "男",
                "birth_date": "1990-01-02",
            }
        },
    )
    assert aerr is None and cleaned
    _c, aerr = spec.validate_answers(
        definition,
        {"who": {"last_name": "山田", "first_name": "太郎", "gender": "不明"}},
    )
    assert aerr and "性別" in aerr


def test_user_info_can_hide_gender_and_birth() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp(
            "who",
            "user_info_composite",
            label="申請者",
            required=True,
            properties={"show_gender": False, "show_birth_date": False},
        )
    ]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "who": {
                "last_name": "山田",
                "first_name": "太郎",
                "gender": "不明",
                "birth_date": "not-a-date",
            }
        },
    )
    assert aerr is None and cleaned
    assert "gender" not in cleaned["who"]
    assert "birth_date" not in cleaned["who"]


def test_corporate_check_digit() -> None:
    raw = spec.empty_definition()
    raw["components"] = [_comp("co", "company_info_composite", label="法人", required=True)]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(
        definition,
        {"co": {"company_name": "国税庁", "corporate_number": "7000012050002"}},
    )
    assert aerr is None and cleaned
    _c, aerr = spec.validate_answers(
        definition,
        {"co": {"company_name": "例", "corporate_number": "1234567890123"}},
    )
    assert aerr and "検査数字" in aerr


def test_canonicalize_fullwidth_and_hyphens() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp("tel", "phone", label="電話"),
        _comp("addr", "address_composite", label="住所"),
        _comp("co", "company_info_composite", label="法人"),
    ]
    definition, err = spec.validate_definition(raw)
    assert err is None and definition
    cleaned, aerr = spec.validate_answers(
        definition,
        {
            "tel": "０３−１２３４ー５６７８",
            "addr": {
                "postal_code": "１０５０００１",
                "prefecture": "東京都",
                "city": "港区",
                "street": "１ー２−３",
            },
            "co": {"company_name": "例", "corporate_number": "7000012050002"},
        },
    )
    assert aerr is None and cleaned
    assert cleaned["tel"] == "03-1234-5678"
    assert cleaned["addr"]["postal_code"] == "105-0001"
    assert cleaned["addr"]["street"] == "1-2-3"


def test_imi_subfields_kept_and_unknown_dropped() -> None:
    raw = spec.empty_definition()
    raw["components"] = [
        _comp(
            "home",
            "address_composite",
            label="住所",
            imi_type=" ic:住所 ",
            imi_subfields={
                "postal_code": " ic:郵便番号 ",
                "unknown": "ic:無視",
                "city": "",
            },
        ),
        _comp("name", "text", label="氏名", imi_type="ic:氏名", imi_subfields={"last_name": "x"}),
    ]
    d, err = spec.validate_definition(raw)
    assert err is None and d
    home = d["components"][0]
    assert home["imi_type"] == "ic:住所"
    assert home["imi_subfields"] == {"postal_code": "ic:郵便番号"}
    assert d["components"][1]["imi_subfields"] == {}


if __name__ == "__main__":
    test_empty_definition_ok()
    test_unknown_type_rejected()
    test_disabled_type_rejected()
    test_duplicate_id_rejected()
    test_select_needs_options()
    test_basic_types_accepted()
    test_answers_required()
    test_answers_email_and_select()
    test_visible_when()
    test_visible_when_in_and_number()
    test_composites_and_formula()
    test_mynumber_internal_only()
    test_catalog_enabled_only_in_public()
    test_location_qr_and_ai_fields()
    test_file_and_signature_values()
    test_hide_label_persisted()
    test_financial_yuucho_and_codes()
    test_user_info_gender_and_birth()
    test_user_info_can_hide_gender_and_birth()
    test_corporate_check_digit()
    test_canonicalize_fullwidth_and_hyphens()
    test_imi_subfields_kept_and_unknown_dropped()
    print("ok")
