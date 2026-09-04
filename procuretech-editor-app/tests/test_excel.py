"""B1 マーカー検証（systemplan / global）のテスト。"""

import base64
import io

import openpyxl
import pytest

from app import excel


def _xlsx_with_marker(marker: str | None) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    if marker is not None:
        ws["B1"] = marker
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_read_marker_lowercases():
    assert excel.read_marker(_xlsx_with_marker("SystemPlan")) == "systemplan"


def test_validate_type_systemplan_ok():
    raw = _xlsx_with_marker("systemplan")
    assert excel.validate_type(raw, "systemplan") == "情報化企画書"


def test_validate_type_global_ok():
    raw = _xlsx_with_marker("global")
    assert excel.validate_type(raw, "global") == "全般的事項"


def test_validate_type_mismatch_raises():
    raw = _xlsx_with_marker("global")
    with pytest.raises(excel.ExcelError):
        excel.validate_type(raw, "systemplan")


def test_validate_type_unknown_expected():
    raw = _xlsx_with_marker("systemplan")
    with pytest.raises(excel.ExcelError):
        excel.validate_type(raw, "unknown")


def test_decode_upload_strips_data_url_prefix():
    raw = b"hello-bytes"
    b64 = "data:application/octet-stream;base64," + base64.b64encode(raw).decode()
    assert excel.decode_upload(b64) == raw


def test_decode_upload_rejects_empty():
    with pytest.raises(excel.ExcelError):
        excel.decode_upload("")


def test_decode_upload_size_limit():
    b64 = base64.b64encode(b"x" * 100).decode()
    with pytest.raises(excel.ExcelError):
        excel.decode_upload(b64, max_bytes=10)


def test_load_invalid_xlsx_raises():
    with pytest.raises(excel.ExcelError):
        excel.read_marker(b"not-a-zip")
