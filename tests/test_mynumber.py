from __future__ import annotations

from shared.mynumber import calc_check_digit, find_valid_mynumbers, is_valid_mynumber


def test_calc_check_digit_known_examples() -> None:
    assert calc_check_digit("12345678901") == 8
    assert calc_check_digit("99999999999") == 6


def test_is_valid_mynumber() -> None:
    assert is_valid_mynumber("123456789018")
    assert is_valid_mynumber("999999999996")
    assert not is_valid_mynumber("123456789019")  # 検査数字違い
    assert not is_valid_mynumber("111111111111")  # 形式は12桁だが検査不一致
    assert not is_valid_mynumber("123")
    # 000000000000 は検査数字上は合法（余り0→検査数字0）なのでここでは扱わない


def test_find_valid_mynumbers_in_text() -> None:
    text = "連絡先 123456789018 と無効 123456789012 です"
    assert find_valid_mynumbers(text) == ["123456789018"]
