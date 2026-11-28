import io

from app.preview import office_preview


def test_markdown_is_not_an_office_preview():
    assert office_preview("翻訳.md", "# 見出し".encode()) is None


def test_xlsx_preview_keeps_cell_text():
    import openpyxl

    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "一覧"
    sheet["A1"] = "項目"
    sheet["B1"] = "内容"
    buf = io.BytesIO()
    book.save(buf)
    preview = office_preview("台帳.xlsx", buf.getvalue())
    assert preview is not None
    assert preview["kind"] == "sheets"
    assert preview["sheets"][0]["name"] == "一覧"
    assert preview["sheets"][0]["rows"][0] == ["項目", "内容"]
