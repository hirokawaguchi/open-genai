from shared.navsheet import (
    MARKER,
    NavRow,
    NavSheet,
    markdown_to_rows,
    parse_workbook,
    table_to_markdown,
    write_workbook,
)


def test_roundtrip_markdown_and_xlsx():
    rows = [
        NavRow(label="課題は何か", value="予算不足"),
        NavRow(label="パイプ|あり", value="改行\nあり"),
    ]
    md = table_to_markdown(rows)
    parsed = markdown_to_rows(md)
    assert parsed[0].label == "課題は何か"
    assert parsed[0].value == "予算不足"
    assert parsed[1].label == "パイプ|あり"
    assert "改行" in parsed[1].value

    raw = write_workbook(NavSheet(rows=rows, instruction="関係者向けに要約する"))
    sheet = parse_workbook(raw)
    assert sheet.instruction == "関係者向けに要約する"
    assert [r.label for r in sheet.rows] == ["課題は何か", "パイプ|あり"]

    import openpyxl
    import io

    wb = openpyxl.load_workbook(io.BytesIO(raw))
    try:
        assert wb.active["B1"].value == MARKER
    finally:
        wb.close()
