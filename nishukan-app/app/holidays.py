"""日本の祝日。休日カレンダーから、期枠の休みを起こす。"""

from __future__ import annotations

from datetime import date

import jpholiday


def holidays_between(start: date, end: date) -> list[tuple[date, str]]:
    """start 以上 end 以下の祝日を日付順で返す。振替休日と国民の休日を含む。"""
    found = [(day, name) for day, name in jpholiday.between(start, end)]
    found.sort(key=lambda item: item[0])
    return found
