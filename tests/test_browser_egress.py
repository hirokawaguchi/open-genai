from __future__ import annotations

from conftest import load_service_module

egress = load_service_module("browser-app/app/egress.py")


def test_public_ipv4_https_is_allowed() -> None:
    decision = egress.decide("1.1.1.1", 443, [])
    assert decision.allowed is True
    assert decision.connect_ip == "1.1.1.1"
    assert decision.reason == "allow"


def test_public_hostname_uses_resolved_address() -> None:
    decision = egress.decide("example.jp", 80, ["1.1.1.1"])
    assert decision.allowed is True
    assert decision.connect_ip == "1.1.1.1"


def test_private_and_metadata_addresses_are_denied() -> None:
    for host in (
        "10.1.2.3",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "100.64.0.1",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:127.0.0.1",
        "::ffff:10.1.1.1",
    ):
        decision = egress.decide(host, 443, [])
        assert decision.allowed is False, host
        assert decision.reason == "private-ip"


def test_decimal_and_octal_loopback_are_denied() -> None:
    assert egress.decide("2130706433", 80, []).reason == "private-ip"
    assert egress.decide("0177.0.0.1", 443, []).reason == "private-ip"
    assert egress.decide("0x7f000001", 443, []).reason == "private-ip"


def test_non_http_port_is_denied() -> None:
    decision = egress.decide("1.1.1.1", 22, [])
    assert decision.allowed is False
    assert decision.reason == "port"


def test_mixed_resolution_is_denied() -> None:
    decision = egress.decide("example.jp", 443, ["1.1.1.1", "10.0.0.1"])
    assert decision.allowed is False
    assert decision.reason == "private-ip"


def test_unresolved_name_is_denied() -> None:
    decision = egress.decide("example.jp", 443, [])
    assert decision.allowed is False
    assert decision.reason == "dns"


def test_local_names_are_denied_without_dns() -> None:
    for host in ("localhost", "backend.internal", "printer.local"):
        assert egress.needs_dns(host) is False
        assert egress.decide(host, 80, ["1.1.1.1"]).reason == "private-ip"


def test_literal_ignores_extra_addresses() -> None:
    decision = egress.decide("1.1.1.1", 443, ["10.0.0.1"])
    assert decision.allowed is True
    assert decision.connect_ip == "1.1.1.1"


def test_ipv4_mapped_public_connects_as_ipv4() -> None:
    decision = egress.decide("::ffff:1.1.1.1", 443, [])
    assert decision.allowed is True
    assert decision.connect_ip == "1.1.1.1"


def test_empty_host_is_denied() -> None:
    assert egress.decide("  ", 443, []).reason == "empty-host"


def test_split_host_port() -> None:
    assert egress.split_host_port("example.jp:443", 80) == ("example.jp", 443)
    assert egress.split_host_port("[::1]:443", 80) == ("::1", 443)
    assert egress.split_host_port("example.jp", 80) == ("example.jp", 80)
