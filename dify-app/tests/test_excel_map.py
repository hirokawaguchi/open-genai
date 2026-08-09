"""excel_map セル抽出・注入・書き戻しの単体テスト（opt-in・後方互換）。"""

from __future__ import annotations

import base64
import io
import unittest
from pathlib import Path
import sys

_APP = Path(__file__).resolve().parents[1] / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

from excel_map import (  # noqa: E402
    apply_excel_map,
    build_filled_excel_artifact,
    extract_excel_cells,
    fill_excel_cells,
    is_xlsx_fill_mode,
    parse_cell_ref,
    resolve_excel_write_values,
)


def _xlsx_b64(cells: dict[str, object], sheet: str = "Sheet1") -> str:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for coord, value in cells.items():
        ws[coord] = value
    buf = io.BytesIO()
    wb.save(buf)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _xlsx_bytes(cells: dict[str, object], sheet: str = "Sheet1") -> bytes:
    return base64.b64decode(_xlsx_b64(cells, sheet))


class ParseCellRefTest(unittest.TestCase):
    def test_plain(self) -> None:
        self.assertEqual(parse_cell_ref("b2"), (None, "B2"))

    def test_sheet(self) -> None:
        self.assertEqual(parse_cell_ref("Sheet1!C5"), ("Sheet1", "C5"))

    def test_quoted_sheet(self) -> None:
        self.assertEqual(parse_cell_ref("'様式'!A1"), ("様式", "A1"))

    def test_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_cell_ref("not-a-cell")


class ExtractExcelCellsTest(unittest.TestCase):
    def test_extract_with_default_sheet(self) -> None:
        raw = _xlsx_bytes({"B2": "事業A", "C5": "企画課"}, "様式")
        out = extract_excel_cells(
            raw,
            {"title": "B2", "dept": "C5"},
            default_sheet="様式",
        )
        self.assertEqual(out["title"], "事業A")
        self.assertEqual(out["dept"], "企画課")

    def test_extract_sheet_in_ref(self) -> None:
        raw = _xlsx_bytes({"A1": "hello"}, "Data")
        out = extract_excel_cells(raw, {"x": "Data!A1"})
        self.assertEqual(out["x"], "hello")


class FillExcelCellsTest(unittest.TestCase):
    def test_write_and_reread(self) -> None:
        raw = _xlsx_bytes({"D20": "old"}, "様式")
        filled = fill_excel_cells(
            raw,
            {"summary": "D20"},
            {"summary": "新しい要約"},
            default_sheet="様式",
        )
        out = extract_excel_cells(
            filled, {"summary": "D20"}, default_sheet="様式"
        )
        self.assertEqual(out["summary"], "新しい要約")


class ApplyExcelMapTest(unittest.TestCase):
    def test_noop_without_map(self) -> None:
        inputs = {"title": "keep", "files": []}
        out, consumed, template = apply_excel_map(inputs, {})
        self.assertEqual(out, inputs)
        self.assertEqual(consumed, [])
        self.assertIsNone(template)

    def test_inject_and_consume_file(self) -> None:
        b64 = _xlsx_b64({"B2": "タイトル", "C5": "部署"})
        inputs = {
            "files": [
                {
                    "key": "form_xlsx",
                    "files": [{"filename": "form.xlsx", "content": b64}],
                }
            ]
        }
        cfg = {
            "excel_map": {"title": "B2", "dept": "C5"},
            "excel_var": "form_xlsx",
        }
        out, consumed, template = apply_excel_map(inputs, cfg)
        self.assertEqual(out["title"], "タイトル")
        self.assertEqual(out["dept"], "部署")
        self.assertEqual(consumed, ["form_xlsx"])
        self.assertNotIn("files", out)
        self.assertIsNotNone(template)
        assert template is not None
        self.assertTrue(len(template.raw) > 0)

    def test_does_not_overwrite_existing(self) -> None:
        b64 = _xlsx_b64({"B2": "from-excel"})
        inputs = {
            "title": "from-form",
            "files": [
                {
                    "key": "form_xlsx",
                    "files": [{"filename": "form.xlsx", "content": b64}],
                }
            ],
        }
        cfg = {"excel_map": {"title": "B2"}}
        out, _, _ = apply_excel_map(inputs, cfg)
        self.assertEqual(out["title"], "from-form")

    def test_forward_keeps_file(self) -> None:
        b64 = _xlsx_b64({"B2": "x"})
        inputs = {
            "files": [
                {
                    "key": "form_xlsx",
                    "files": [{"filename": "form.xlsx", "content": b64}],
                }
            ]
        }
        cfg = {"excel_map": {"title": "B2"}, "excel_forward": True}
        out, consumed, _ = apply_excel_map(inputs, cfg)
        self.assertEqual(out["title"], "x")
        self.assertEqual(consumed, [])
        self.assertIn("files", out)

    def test_xlsx_fill_keeps_template_without_read_map(self) -> None:
        b64 = _xlsx_b64({"D20": ""})
        inputs = {
            "files": [
                {
                    "key": "form_xlsx",
                    "files": [{"filename": "form.xlsx", "content": b64}],
                }
            ]
        }
        cfg = {
            "output_mode": "xlsx_fill",
            "excel_write_map": {"summary": "D20"},
        }
        out, consumed, template = apply_excel_map(inputs, cfg)
        self.assertEqual(consumed, ["form_xlsx"])
        self.assertIsNotNone(template)
        self.assertNotIn("files", out)


class ResolveWriteValuesTest(unittest.TestCase):
    def test_from_workflow_field(self) -> None:
        cfg = {
            "excel_write_map": {"summary": "D20", "result": "D21"},
        }
        values = resolve_excel_write_values(
            cfg=cfg,
            workflow_outputs={
                "excel_values": {"summary": "要約", "result": "結果"},
                "result": "表示用テキスト",
            },
        )
        self.assertEqual(values["summary"], "要約")
        self.assertEqual(values["result"], "結果")

    def test_from_answer_json(self) -> None:
        cfg = {"excel_write_map": {"summary": "D20"}}
        values = resolve_excel_write_values(
            cfg=cfg,
            answer_text='下書きです。\n```json\n{"summary":"確定要約"}\n```\n',
        )
        self.assertEqual(values["summary"], "確定要約")

    def test_fallback_inputs(self) -> None:
        cfg = {"excel_write_map": {"title": "B2"}}
        values = resolve_excel_write_values(
            cfg=cfg,
            inputs={"title": "事業A"},
        )
        self.assertEqual(values["title"], "事業A")


class BuildArtifactTest(unittest.TestCase):
    def test_build_artifact(self) -> None:
        from excel_map import ExcelTemplate

        raw = _xlsx_bytes({"D20": "old"})
        template = ExcelTemplate(raw=raw, filename="form.xlsx")
        cfg = {
            "output_mode": "xlsx_fill",
            "excel_write_map": {"summary": "D20"},
            "excel_output_filename": "out.xlsx",
        }
        self.assertTrue(is_xlsx_fill_mode(cfg))
        art = build_filled_excel_artifact(template, cfg, {"summary": "新"})
        self.assertIsNotNone(art)
        assert art is not None
        self.assertEqual(art["display_name"], "out.xlsx")
        self.assertIn("spreadsheetml", art["mime_type"])
        filled = base64.b64decode(art["content"])
        self.assertEqual(
            extract_excel_cells(filled, {"summary": "D20"})["summary"], "新"
        )


if __name__ == "__main__":
    unittest.main()
