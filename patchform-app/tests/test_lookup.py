"""郵便番号・法人番号照会とゆうちょ換算。"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import lookup


class _Resp:
    def __init__(self, data: dict, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self) -> dict:
        return self._data


class _Client:
    def __init__(self, resp: _Resp) -> None:
        self.resp = resp

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_a: object) -> bool:
        return False

    async def get(self, *_a: object, **_k: object) -> _Resp:
        return self.resp


def test_corporate_check_digit() -> None:
    assert lookup.corporate_check_digit_ok("7000012050002")
    assert not lookup.corporate_check_digit_ok("1234567890123")
    assert not lookup.corporate_check_digit_ok("700001205000")


def test_yuucho_to_branch() -> None:
    out = lookup.yuucho_to_branch("10170", "12345671")
    assert out["bank_code"] == "9900"
    assert out["bank_name"] == "ゆうちょ銀行"
    assert out["branch_code"] == "017"
    assert out["account_number"] == "2345671"
    short = lookup.yuucho_to_branch("018", "123456")
    assert short["branch_code"] == "018"
    assert short["account_number"] == "0123456"


async def test_lookup_postal_mocked() -> None:
    resp = _Resp(
        {
            "status": 200,
            "results": [{"address1": "東京都", "address2": "千代田区", "address3": "千代田"}],
        }
    )
    with patch("app.lookup.httpx.AsyncClient", return_value=_Client(resp)):
        data, err = await lookup.lookup_postal("100-0001")
    assert err is None and data
    assert data["prefecture"] == "東京都"
    assert data["city"] == "千代田区"
    assert data["street"] == "千代田"


async def test_lookup_corporate_mocked() -> None:
    resp = _Resp({"hojin-infos": [{"name": "国税庁"}]})
    with (
        patch.dict("os.environ", {"PATCHFORM_GBIZ_TOKEN": "test-token"}),
        patch("app.lookup.httpx.AsyncClient", return_value=_Client(resp)),
    ):
        data, err = await lookup.lookup_corporate("7000012050002")
    assert err is None and data
    assert data["company_name"] == "国税庁"


async def test_lookup_corporate_skips_without_token() -> None:
    with (
        patch.dict("os.environ", {"PATCHFORM_GBIZ_TOKEN": ""}),
        patch("app.lookup.httpx.AsyncClient") as client,
    ):
        data, err = await lookup.lookup_corporate("7000012050002")
    assert err is None and data
    assert data["company_name"] == ""
    client.assert_not_called()


async def test_lookup_corporate_upstream_error() -> None:
    with (
        patch.dict("os.environ", {"PATCHFORM_GBIZ_TOKEN": "test-token"}),
        patch("app.lookup.httpx.AsyncClient", return_value=_Client(_Resp({}, 500))),
    ):
        data, err = await lookup.lookup_corporate("7000012050002")
    assert err is None and data
    assert data["company_name"] == ""


if __name__ == "__main__":
    import asyncio

    test_corporate_check_digit()
    test_yuucho_to_branch()
    asyncio.run(test_lookup_postal_mocked())
    asyncio.run(test_lookup_corporate_mocked())
    asyncio.run(test_lookup_corporate_skips_without_token())
    asyncio.run(test_lookup_corporate_upstream_error())
    print("ok")
