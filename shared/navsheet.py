"""ナビゲーションシート（xlsx）の読み書き。

先頭シートの契約:

- ``B1``: 種別マーカー ``hearing-sheet``（systemplan / global と同じ。旧 ``navigation-sheet`` も読む）
- A 列ラベル ``ナビゲーション`` の B セル: Markdown 表（項目 | 値）
- A 列ラベル ``生成指示`` の B セル: generate-app への処理指示

旧 A/B 行形式は扱わない。
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from typing import Any

NAV_LABEL = "ナビゲーション"
INSTRUCTION_LABEL = "生成指示"
MARKER = "hearing-sheet"
LEGACY_MARKERS = ("navigation-sheet",)
SHEET_NAME = "ヒアリングシート"

_ROW_RE = re.compile(
    r"^\|\s*(?P<label>(?:\\\||[^|])*?)\s*\|\s*(?P<value>(?:\\\||[^|])*?)\s*\|\s*$"
)


@dataclass
class NavRow:
    label: str
    value: str


@dataclass
class NavSheet:
    rows: list[NavRow] = field(default_factory=list)
    instruction: str = ""


def escape_cell(text: str) -> str:
    return (text or "").replace("|", "\\|").replace("\n", "<br>")


def unescape_cell(text: str) -> str:
    return (text or "").replace("<br>", "\n").replace("\\|", "|")


def table_to_markdown(rows: list[NavRow] | list[dict[str, str]]) -> str:
    lines = ["| 項目 | 値 |", "| --- | --- |"]
    for row in rows:
        if isinstance(row, dict):
            label = str(row.get("label") or "")
            value = str(row.get("value") or "")
        else:
            label = row.label
            value = row.value
        lines.append(f"| {escape_cell(label)} | {escape_cell(value)} |")
    return "\n".join(lines)


def markdown_to_rows(text: str) -> list[NavRow]:
    rows: list[NavRow] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line.startswith("|"):
            continue
        m = _ROW_RE.match(line)
        if not m:
            continue
        label = unescape_cell(m.group("label")).strip()
        value = unescape_cell(m.group("value")).strip()
        if label in ("項目", "---") or set(label) <= {"-", ":"}:
            continue
        if not label and not value:
            continue
        rows.append(NavRow(label=label, value=value))
    return rows


def _cell_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def parse_workbook(raw: bytes) -> NavSheet:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        nav = ""
        instruction = ""
        for row in ws.iter_rows(min_col=1, max_col=2, values_only=True):
            label = _cell_text(row[0]).strip() if row else ""
            value = _cell_text(row[1]) if row and len(row) > 1 else ""
            if label == NAV_LABEL:
                nav = value
            elif label == INSTRUCTION_LABEL:
                instruction = value
        return NavSheet(rows=markdown_to_rows(nav), instruction=instruction.strip())
    finally:
        wb.close()


def write_workbook(sheet: NavSheet) -> bytes:
    import openpyxl
    from openpyxl.styles import Alignment, Font
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = SHEET_NAME
    ws["A1"] = "種別"
    ws["B1"] = MARKER
    ws["A2"] = NAV_LABEL
    ws["B2"] = table_to_markdown(sheet.rows)
    ws["A3"] = INSTRUCTION_LABEL
    ws["B3"] = sheet.instruction or ""
    header = Font(bold=True)
    wrap = Alignment(wrap_text=True, vertical="top")
    for cell in ("A1", "A2", "A3"):
        ws[cell].font = header
    ws["B2"].alignment = wrap
    ws["B3"].alignment = wrap
    ws.column_dimensions[get_column_letter(1)].width = 16
    ws.column_dimensions[get_column_letter(2)].width = 80
    ws.row_dimensions[2].height = 160
    ws.row_dimensions[3].height = 80
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def empty_workbook() -> bytes:
    return write_workbook(NavSheet(rows=[], instruction=""))


def slug_for(label: str, index: int) -> str:
    text = re.sub(r"[^\w]+", "-", (label or "").strip(), flags=re.UNICODE)
    text = text.strip("-").lower() or f"item-{index}"
    return text[:40]
