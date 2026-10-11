"""手続きマスタの対応表（和集合）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import procedure, spec


def test_resolve_union_and_dedupe() -> None:
    mapping = {
        "rules": [
            {
                "component_id": "event",
                "option": "転入",
                "form_ids": ["a", "attach"],
                "notes": "転入の案内",
                "prepare": ["住民票"],
                "refs": [],
            },
            {
                "component_id": "event",
                "option": "転居",
                "form_ids": ["b"],
                "notes": "転居の案内",
                "prepare": ["本人確認"],
                "refs": [],
            },
            {
                "component_id": "has_child",
                "option": "あり",
                "form_ids": ["attach", "child"],
                "notes": "子どもがいる場合",
                "prepare": ["住民票"],
                "refs": ["手引き p.3"],
            },
        ]
    }
    out = procedure.resolve_bundle(
        mapping, {"event": "転入", "has_child": "あり"}
    )
    assert out["form_ids"] == ["a", "attach", "child"]
    assert out["notes"] == ["転入の案内", "子どもがいる場合"]
    assert out["prepare"] == ["住民票"]
    assert out["refs"] == ["手引き p.3"]


def test_resolve_checkbox() -> None:
    mapping, err = procedure.normalize_mapping(
        {
            "rules": [
                {
                    "component_id": "kinds",
                    "option": "転入",
                    "form_ids": ["a"],
                    "notes": "",
                    "prepare": [],
                }
            ]
        }
    )
    assert err is None
    out = procedure.resolve_bundle(mapping, {"kinds": ["転居", "転入"]})
    assert out["form_ids"] == ["a"]
    empty = procedure.resolve_bundle(mapping, {"kinds": ["転居"]})
    assert empty["form_ids"] == []


def test_mapping_warnings() -> None:
    definition = {
        "components": [
            {
                "id": "event",
                "type": "radio",
                "label": "事由",
                "properties": {"options": ["転入", "転居"]},
            }
        ]
    }
    mapping, _err = procedure.normalize_mapping(
        {
            "rules": [
                {"component_id": "event", "option": "転出", "form_ids": []},
                {"component_id": "missing", "option": "x", "form_ids": []},
            ]
        }
    )
    warnings = procedure.mapping_warnings(mapping, definition)
    assert any("転出" in w for w in warnings)
    assert any("missing" in w for w in warnings)
    fields = procedure.choice_fields(definition)
    assert fields[0]["options"] == ["転入", "転居"]


def test_normalize_answers_label_and_free_text() -> None:
    fields = [
        {
            "id": "event",
            "type": "radio",
            "label": "該当するもの",
            "options": ["転入", "転居"],
        },
        {
            "id": "kinds",
            "type": "checkbox",
            "label": "対象",
            "options": ["子ども", "高齢者"],
        },
    ]
    answers, notes = procedure.normalize_answers(
        fields, {"該当するもの": " 転入 ", "対象": ["子ども"]}
    )
    assert answers == {"event": "転入", "kinds": ["子ども"]}
    assert notes == []

    coerced = procedure.coerce_answers('{"event":"転居"}')
    assert coerced == {"event": "転居"}
    free, free_notes = procedure.normalize_answers(fields, "転入")
    assert free == {"event": "転入"}
    assert free_notes == []


def test_option_label_and_value() -> None:
    items = spec.option_items(["転入の届出|tennyu", "転居"])
    assert items == [
        {"value": "tennyu", "label": "転入の届出"},
        {"value": "転居", "label": "転居"},
    ]
    definition = {
        "components": [
            {
                "id": "event",
                "type": "radio",
                "label": "事由",
                "properties": {"options": items},
            }
        ]
    }
    fields = procedure.choice_fields(definition)
    assert fields[0]["options"] == ["tennyu", "転居"]
    answers, notes = procedure.normalize_answers(fields, {"事由": "転入の届出"})
    assert answers == {"event": "tennyu"}
    assert notes == []
    mapping, err = procedure.normalize_mapping(
        {"rules": [{"component_id": "event", "option": "tennyu", "form_ids": ["f1"]}]}
    )
    assert err is None
    resolved = procedure.resolve_bundle(mapping, {"event": "tennyu"})
    assert resolved["form_ids"] == ["f1"]
    assert procedure.mapping_warnings(mapping, definition) == []


def test_review_stays_on_its_slot() -> None:
    mapping, err = procedure.normalize_mapping(
        {
            "rules": [
                {
                    "component_id": "who",
                    "option": "子ども",
                    "form_ids": ["form-a"],
                    "prepare": ["勤務証明書"],
                    "reviews": [
                        {
                            "slot_id": "attach:勤務証明書",
                            "formal": ["file_present", "not-a-check", "pdf_or_image"],
                            "content": [{"id": "name", "text": "勤務先名が読める"}],
                        },
                        {
                            "slot_id": "attach:診断書",
                            "formal": ["file_present"],
                            "content": [{"text": "これは残さない"}],
                        },
                    ],
                    "cross": [{"id": "same", "text": "氏名が一致する"}],
                }
            ],
            "review": {
                "slots": [
                    {
                        "slot_id": "yoshiki:guide",
                        "formal": ["file_present"],
                        "content": [{"id": "g", "text": "案内の氏名がある"}],
                    }
                ],
                "cross": [],
            },
        }
    )
    assert err is None
    rule = mapping["rules"][0]
    assert rule["reviews"] == [
        {
            "slot_id": "attach:勤務証明書",
            "formal": ["file_present", "pdf_or_image"],
            "content": [{"id": "name", "text": "勤務先名が読める"}],
        }
    ]
    assert rule["cross"] == [{"id": "same", "text": "氏名が一致する"}]
    assert mapping["review"]["slots"][0]["slot_id"] == "yoshiki:guide"

    snap = procedure.review_snapshot(
        mapping,
        {"who": "子ども"},
        [
            {
                "slot_id": "attach:勤務証明書",
                "title": "勤務証明書",
                "kind": "attach",
                "file_id": "",
                "mime": "",
                "status": "none",
            }
        ],
    )
    assert [s["slot_id"] for s in snap["slots"]] == ["yoshiki:guide", "attach:勤務証明書"]
    cert = snap["slots"][1]
    assert cert["formal"][0]["result"] == "fail"
    assert cert["formal"][1]["result"] == "unknown"
    assert cert["content"][0]["text"] == "勤務先名が読める"
    assert cert["content"][0]["finding"]["result"] == "unknown"
    assert snap["cross"][0]["text"] == "氏名が一致する"
    assert snap["cross"][0]["finding"]["source"] == ""

    other = procedure.review_snapshot(mapping, {"who": "保護者の病気"}, [])
    assert [s["slot_id"] for s in other["slots"]] == ["yoshiki:guide"]
    assert other["cross"] == []


if __name__ == "__main__":
    test_resolve_union_and_dedupe()
    test_resolve_checkbox()
    test_mapping_warnings()
    test_normalize_answers_label_and_free_text()
    test_option_label_and_value()
    test_review_stays_on_its_slot()
    print("ok")
