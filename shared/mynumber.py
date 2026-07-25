"""個人番号（マイナンバー）の検査用数字（チェックデジット）検証。

総務省令の算式:
  - 検査用数字以外の 11 桁について、最下位を 1 桁目とした n 桁目の数字を Pn
  - 1≦n≦6 のとき Qn = n+1、7≦n≦11 のとき Qn = n-5
  - 検査用数字 = 11 - (Σ Pn×Qn を 11 で割った余り)
    ただし余り ≦ 1 のときは 0
"""

from __future__ import annotations

import re

_TWELVE_DIGITS = re.compile(r"\d{12}")


def calc_check_digit(first11: str) -> int:
    """左 11 桁から検査用数字（0–9）を求める。不正なら -1。"""
    if not re.fullmatch(r"\d{11}", first11 or ""):
        return -1
    digits = [int(c) for c in first11]
    total = 0
    for n in range(1, 12):
        pn = digits[11 - n]  # 最下位が n=1
        qn = (n + 1) if n <= 6 else (n - 5)
        total += pn * qn
    rem = total % 11
    return 0 if rem <= 1 else 11 - rem


def is_valid_mynumber(value: str) -> bool:
    """12 桁文字列が個人番号の検査用数字と一致するか。"""
    if not re.fullmatch(r"\d{12}", value or ""):
        return False
    expected = calc_check_digit(value[:11])
    return expected >= 0 and int(value[11]) == expected


def find_valid_mynumbers(text: str) -> list[str]:
    """テキスト中の、検査用数字が一致する 12 桁連続数字を列挙する。"""
    if not text:
        return []
    return [m.group(0) for m in _TWELVE_DIGITS.finditer(text) if is_valid_mynumber(m.group(0))]
