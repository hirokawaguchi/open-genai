from __future__ import annotations

from types import SimpleNamespace

from conftest import load_service_module


def _mod():
    return load_service_module("backend/app/artifact_delivery.py")


def _req(host: str = "", *, forwarded: str | None = None):
    headers = {"host": host}
    if forwarded is not None:
        headers["x-forwarded-host"] = forwarded
    return SimpleNamespace(headers=headers)


def test_normalize_mode_accepts_three_and_falls_back() -> None:
    mod = _mod()
    assert mod.normalize_mode("open") == "open"
    assert mod.normalize_mode("carrier") == "carrier"
    assert mod.normalize_mode("AUTO") == "auto"
    assert mod.normalize_mode("unknown") == "open"
    assert mod.normalize_mode(None) == "open"


def test_lgwan_fqdn_is_suffix_not_substring() -> None:
    mod = _mod()
    assert mod.is_lgwan_fqdn("tenant.example.lgwan.jp")
    assert mod.is_lgwan_fqdn("ops.example.lgwan.jp")
    assert mod.is_lgwan_fqdn("lgwan.jp")
    assert mod.is_lgwan_fqdn("TENANT.EXAMPLE.LGWAN.JP")
    assert not mod.is_lgwan_fqdn("tenant.example.jp")
    assert not mod.is_lgwan_fqdn("notlgwan.jp")
    assert not mod.is_lgwan_fqdn("lgwan.jp.example.com")
    assert not mod.is_lgwan_fqdn("")


def test_open_and_carrier_ignore_host() -> None:
    mod = _mod()
    lgwan = _req("tenant.example.lgwan.jp")
    inet = _req("tenant.example.jp")
    assert mod.resolve_delivery("open", lgwan) == "open"
    assert mod.resolve_delivery("carrier", inet) == "carrier"


def test_auto_uses_forwarded_host_suffix() -> None:
    mod = _mod()
    lgwan = _req("backend:8000", forwarded="tenant.example.lgwan.jp")
    inet = _req("backend:8000", forwarded="tenant.example.jp")
    assert mod.resolve_delivery("auto", lgwan) == "carrier"
    assert mod.resolve_delivery("auto", inet) == "open"
    assert mod.use_carrier("auto", lgwan)
    assert not mod.use_carrier("auto", inet)
