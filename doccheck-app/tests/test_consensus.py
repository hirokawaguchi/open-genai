"""合意判定の単体テスト（pytest 不要の簡易ランナー）。"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.consensus import (
    evaluate_consensus,
    export_column_names,
    join_adjacent_parts,
    merge_export_fields,
    normalize_text,
    unique_answers,
)


def test_normalize() -> None:
    assert normalize_text("ＡＢ　１２") == "AB12"
    assert normalize_text("2024年1月2日", field_type="date") == "2024-1-2"


def test_adopt_with_internal() -> None:
    answers = [
        {"answer_text": "山田", "tier": "external", "checker_key": "g1"},
        {"answer_text": "山田", "tier": "internal", "checker_user_id": "staff"},
        {"answer_text": "やまだ", "tier": "external", "checker_key": "g2"},
    ]
    r = evaluate_consensus(answers, assignee_count=3)
    assert r["status"] == "adopted"
    assert r["adopted_text"] == "山田"


def test_same_person_counts_once() -> None:
    answers = [
        {"answer_text": "山田", "tier": "external", "checker_key": "same"},
        {"answer_text": "山田", "tier": "external", "checker_key": "same"},
        {"answer_text": "山田", "tier": "external", "checker_key": "same"},
    ]
    assert len(unique_answers(answers)) == 1
    r = evaluate_consensus(answers, min_agree=2, assignee_count=3)
    # 同一人物 1 票だけでは採用されない
    assert r["status"] == "pending"


def test_solo_assignee() -> None:
    answers = [
        {"answer_text": "太郎", "tier": "internal", "checker_user_id": "solo"},
    ]
    r = evaluate_consensus(answers, min_agree=2, assignee_count=1)
    assert r["status"] == "adopted"
    assert r["reason"] == "solo"


def test_unanimous_external() -> None:
    answers = [
        {"answer_text": "Tokyo", "tier": "external", "checker_key": "a"},
        {"answer_text": "Tokyo", "tier": "external", "checker_key": "b"},
        {"answer_text": "Tokyo", "tier": "external", "checker_key": "c"},
    ]
    r = evaluate_consensus(answers, assignee_count=3)
    assert r["status"] == "adopted"


def test_arbitration() -> None:
    answers = [
        {"answer_text": "A", "tier": "external", "checker_key": "a"},
        {"answer_text": "B", "tier": "external", "checker_key": "b"},
        {"answer_text": "C", "tier": "internal", "checker_user_id": "c"},
    ]
    r = evaluate_consensus(answers, assignee_count=3)
    assert r["status"] == "needs_arbitration"


def test_choice_multi_normalize_order_insensitive() -> None:
    a = normalize_text("該当する | 要確認", field_type="choice_multi")
    b = normalize_text("要確認 | 該当する", field_type="choice_multi")
    assert a == b
    # 重複と空白は正規化で吸収
    c = normalize_text(" 該当する |該当する ", field_type="choice_multi")
    assert c == normalize_text("該当する", field_type="choice_multi")


def test_choice_multi_consensus() -> None:
    answers = [
        {"answer_text": "A | B", "tier": "external", "checker_key": "x"},
        {"answer_text": "B | A", "tier": "internal", "checker_user_id": "y"},
    ]
    r = evaluate_consensus(answers, field_type="choice_multi", assignee_count=2)
    assert r["status"] == "adopted"


def test_blank_consensus_adopts_empty() -> None:
    # 全員が「空欄」を選ぶと確定した空文字として採用される
    answers = [
        {"is_blank": True, "tier": "external", "checker_key": "a"},
        {"is_blank": True, "tier": "external", "checker_key": "b"},
        {"is_blank": True, "tier": "internal", "checker_user_id": "c"},
    ]
    r = evaluate_consensus(answers, assignee_count=3)
    assert r["status"] == "adopted"
    assert r["adopted_text"] == ""


def test_blank_vs_value_goes_to_arbitration() -> None:
    # 空欄票と値の票が割れたら裁定へ。候補に空欄が含まれる
    answers = [
        {"is_blank": True, "tier": "external", "checker_key": "a"},
        {"answer_text": "山田", "tier": "external", "checker_key": "b"},
        {"answer_text": "田中", "tier": "internal", "checker_user_id": "c"},
    ]
    r = evaluate_consensus(answers, assignee_count=3)
    assert r["status"] == "needs_arbitration"
    assert any(c.get("is_blank") for c in r["candidates"])


def test_blank_solo_adopts_empty() -> None:
    answers = [{"is_blank": True, "tier": "internal", "checker_user_id": "solo"}]
    r = evaluate_consensus(answers, min_agree=2, assignee_count=1)
    assert r["status"] == "adopted"
    assert r["adopted_text"] == ""


def test_join_adjacent_overlap() -> None:
    assert join_adjacent_parts(["東京都港区", "港区芝", "芝公園"]) == "東京都港区芝公園"
    assert join_adjacent_parts(["ABC", "DEF"]) == "ABCDEF"


def test_merge_multiline_and_parts() -> None:
    regions = [
        {
            "name": "住所-L1-P1",
            "group_name": "住所",
            "line_index": 0,
            "part_index": 0,
            "status": "adopted",
            "adopted_text": "東京都",
            "ocr_text": "東京都",
            "is_trap": False,
        },
        {
            "name": "住所-L1-P2",
            "group_name": "住所",
            "line_index": 0,
            "part_index": 1,
            "status": "adopted",
            "adopted_text": "港区芝",
            "ocr_text": "港区芝",
            "is_trap": False,
        },
        {
            "name": "住所-L2-P1",
            "group_name": "住所",
            "line_index": 1,
            "part_index": 0,
            "status": "adopted",
            "adopted_text": "1-2-3",
            "ocr_text": "1-2-3",
            "is_trap": False,
        },
        {
            "name": "氏名",
            "status": "adopted",
            "adopted_text": "山田",
            "is_trap": False,
        },
    ]
    fields = merge_export_fields(regions)
    by_name = {f["name"]: f for f in fields}
    assert by_name["住所"]["value"] == "東京都港区芝\n1-2-3"
    assert by_name["氏名"]["value"] == "山田"
    assert export_column_names(regions) == ["住所", "氏名"]


def test_single_line_split_binds_by_group_id() -> None:
    # 出力項目名（group_name）が偶然同じでも、group_id が違えば別項目
    regions = [
        {
            "name": "金額-P1",
            "group_id": "A",
            "group_name": "金額",
            "line_index": 0,
            "part_index": 0,
            "status": "adopted",
            "adopted_text": "1",
            "is_trap": False,
        },
        {
            "name": "金額-P2",
            "group_id": "A",
            "group_name": "金額",
            "line_index": 0,
            "part_index": 1,
            "status": "adopted",
            "adopted_text": "00",
            "is_trap": False,
        },
        {
            "name": "金額-P1",
            "group_id": "B",
            "group_name": "金額",
            "line_index": 0,
            "part_index": 0,
            "status": "adopted",
            "adopted_text": "2",
            "is_trap": False,
        },
        {
            "name": "金額-P2",
            "group_id": "B",
            "group_name": "金額",
            "line_index": 0,
            "part_index": 1,
            "status": "adopted",
            "adopted_text": "00",
            "is_trap": False,
        },
    ]
    fields = merge_export_fields(regions)
    # group_id A / B が別項目として残る（名前一致でも混ざらない）
    assert len(fields) == 2
    values = sorted(f["value"] for f in fields)
    assert values == ["100", "200"]


def test_multiline_split_binds_by_name() -> None:
    # 複数行は group_id を持たず、出力項目名で行をまたいで結合
    regions = [
        {
            "name": "住所-L1-P1",
            "group_name": "住所",
            "line_index": 0,
            "part_index": 0,
            "status": "adopted",
            "adopted_text": "東京都",
            "is_trap": False,
        },
        {
            "name": "住所-L1-P2",
            "group_name": "住所",
            "line_index": 0,
            "part_index": 1,
            "status": "adopted",
            "adopted_text": "港区",
            "is_trap": False,
        },
        {
            "name": "住所-L2-P1",
            "group_name": "住所",
            "line_index": 1,
            "part_index": 0,
            "status": "adopted",
            "adopted_text": "1-2-3",
            "is_trap": False,
        },
    ]
    fields = merge_export_fields(regions)
    assert len(fields) == 1
    assert fields[0]["name"] == "住所"
    assert fields[0]["value"] == "東京都港区\n1-2-3"


if __name__ == "__main__":
    test_normalize()
    test_adopt_with_internal()
    test_same_person_counts_once()
    test_solo_assignee()
    test_unanimous_external()
    test_arbitration()
    test_blank_consensus_adopts_empty()
    test_blank_vs_value_goes_to_arbitration()
    test_blank_solo_adopts_empty()
    test_join_adjacent_overlap()
    test_merge_multiline_and_parts()
    test_choice_multi_normalize_order_insensitive()
    test_choice_multi_consensus()
    test_single_line_split_binds_by_group_id()
    test_multiline_split_binds_by_name()
    print("ok")
