"""外部 Word 変換 API クライアントのテスト（httpx MockTransport でスタブ化）。"""

import asyncio

import httpx
import pytest

from app import convert


def test_bool_str():
    assert convert._bool_str(True) == "true"
    assert convert._bool_str(False) == "false"
    assert convert._bool_str(None) == "false"


def test_not_configured_raises(monkeypatch):
    monkeypatch.setattr(convert, "EDITOR_CONVERT_URL", "")
    with pytest.raises(convert.ConvertError):
        asyncio.run(
            convert.start_conversion(b"zip", project_name="p", username="u")
        )


def _install_mock(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient  # パッチ前の実クラスを退避（自己再帰防止）

    def factory(**kwargs):
        kwargs.pop("timeout", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(convert.httpx, "AsyncClient", factory)
    monkeypatch.setattr(convert, "EDITOR_CONVERT_URL", "http://convert.test")


def test_start_conversion_returns_request_id(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, json={"request_id": "req-1", "status": "processing"})

    _install_mock(monkeypatch, handler)
    res = asyncio.run(
        convert.start_conversion(
            b"zipbytes",
            project_name="案件",
            username="user-a",
            options={"allow_rfi": False},
        )
    )
    assert res["request_id"] == "req-1"
    assert seen["path"] == "/api/convert-markdown"
    # multipart にファイルとフラグが載る
    assert b"allow_specification" in seen["body"]
    assert b"false" in seen["body"]  # allow_rfi=False


def test_start_conversion_error_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "だめ"})

    _install_mock(monkeypatch, handler)
    with pytest.raises(convert.ConvertError, match="だめ"):
        asyncio.run(convert.start_conversion(b"z", project_name="p", username="u"))


def test_get_status(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/conversion-status/req-9"
        return httpx.Response(200, json={"status": "success", "nextcloud_path": "x/y"})

    _install_mock(monkeypatch, handler)
    res = asyncio.run(convert.get_status("req-9"))
    assert res["status"] == "success"
