from __future__ import annotations

import socket

import pytest

import ssrfguard


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("169.254.169.254", False),
        ("not-an-ip", False),
    ],
)
def test_ip_is_public(ip: str, expected: bool) -> None:
    assert ssrfguard.ip_is_public(ip) is expected


@pytest.mark.parametrize(
    ("ip", "expected"),
    [
        ("8.8.8.8", True),
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("192.168.1.1", True),
        ("169.254.169.254", False),
        ("not-an-ip", False),
    ],
)
def test_ip_is_safe_for_trusted_host(ip: str, expected: bool) -> None:
    assert ssrfguard.ip_is_safe_for_trusted_host(ip) is expected


def test_validate_and_pin_rejects_non_http_scheme() -> None:
    with pytest.raises(ssrfguard.SsrfBlocked, match="http\\(s\\)"):
        ssrfguard._validate_and_pin("file:///etc/passwd", None)


def test_validate_and_pin_rejects_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port))]

    monkeypatch.setattr(ssrfguard.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ssrfguard.SsrfBlocked, match="内部宛先"):
        ssrfguard._validate_and_pin("http://example.com/path", None)


def test_validate_and_pin_honors_allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(ssrfguard.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ssrfguard.SsrfBlocked, match="許可されていないホスト"):
        ssrfguard._validate_and_pin("http://example.com/", ["allowed.example"])

    ip_url, headers, sni = ssrfguard._validate_and_pin(
        "http://allowed.example/data",
        ["allowed.example"],
    )
    assert "93.184.216.34" in ip_url
    assert headers["Host"] == "allowed.example"
    assert sni == "allowed.example"


def test_validate_and_pin_allowlisted_host_may_resolve_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ローカル/セルフホスト Dify（host.docker.internal 等）向け。"""

    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.65.254", port))]

    monkeypatch.setattr(ssrfguard.socket, "getaddrinfo", fake_getaddrinfo)

    # allowlist 無しでは private 拒否
    with pytest.raises(ssrfguard.SsrfBlocked, match="内部宛先"):
        ssrfguard._validate_and_pin("http://host.docker.internal:8088/files/a.docx", None)

    ip_url, headers, sni = ssrfguard._validate_and_pin(
        "http://host.docker.internal:8088/files/a.docx",
        ["host.docker.internal", "files.dify.ai"],
    )
    assert "192.168.65.254:8088" in ip_url
    assert headers["Host"] == "host.docker.internal:8088"
    assert sni == "host.docker.internal"


def test_validate_and_pin_allowlisted_still_blocks_link_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", port))]

    monkeypatch.setattr(ssrfguard.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ssrfguard.SsrfBlocked, match="内部宛先"):
        ssrfguard._validate_and_pin(
            "http://metadata.example/",
            ["metadata.example"],
        )
