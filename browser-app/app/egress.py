"""Chromium の出口判定。

公開 IP の HTTP/HTTPS（80 と 443）だけを許可する。プライベート IP、
ループバック、リンクローカル、メタデータアドレスへは届かない。

サイトカタログへ切り替えるときは `decide` の許可条件だけを差し替える。
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

_SHARED = ipaddress.ip_network("100.64.0.0/10")
_BLOCKED_SUFFIXES = (".local", ".localhost", ".internal")
_BLOCKED_NAMES = {"localhost", "localhost.localdomain"}


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    connect_ip: str | None = None


def _unwrap(ip: ipaddress.IPv4Address | ipaddress.IPv6Address):
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def is_public(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    ip = _unwrap(ip)
    if not ip.is_global:
        return False
    if isinstance(ip, ipaddress.IPv4Address) and ip in _SHARED:
        return False
    return True


def clean_host(host: str) -> str | None:
    text = (host or "").strip().rstrip(".").lower()
    if not text or len(text) > 253:
        return None
    if any(ch in text for ch in " \t\r\n/@\\"):
        return None
    return text


def _blocked_name(host: str) -> bool:
    if host in _BLOCKED_NAMES:
        return True
    return any(host.endswith(suffix) for suffix in _BLOCKED_SUFFIXES)


def _dotted_quad(host: str) -> ipaddress.IPv4Address | None:
    parts = host.split(".")
    if len(parts) != 4:
        return None
    nums: list[int] = []
    for part in parts:
        if not part.isdigit():
            return None
        base = 8 if len(part) > 1 and part.startswith("0") else 10
        try:
            num = int(part, base)
        except ValueError:
            return None
        if num > 255:
            return None
        nums.append(num)
    return ipaddress.IPv4Address(".".join(str(num) for num in nums))


def literal_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return _unwrap(ipaddress.ip_address(host))
    except ValueError:
        pass
    dotted = _dotted_quad(host)
    if dotted is not None:
        return dotted
    if re.fullmatch(r"\d+", host):
        num = int(host)
        if 0 <= num <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(num)
        return None
    if re.fullmatch(r"0x[0-9a-f]+", host):
        num = int(host, 16)
        if 0 <= num <= 0xFFFFFFFF:
            return ipaddress.IPv4Address(num)
    return None


def needs_dns(host: str) -> bool:
    """名前解決が必要なホストか。リテラルと、名前だけで拒否できるものは不要。"""
    cleaned = clean_host(host)
    if cleaned is None or _blocked_name(cleaned):
        return False
    return literal_ip(cleaned) is None


def decide(host: str, port: int, addresses: list[str]) -> Decision:
    """接続してよいかを返す。addresses はホスト名の解決結果。

    リテラル IP はその値だけで判定する。ホスト名は、解決結果のどれか一つでも
    公開 IP でなければ拒否する（DNS 再解決で内部 IP が混ざった場合を含む）。
    """
    cleaned = clean_host(host)
    if cleaned is None:
        return Decision(False, "empty-host")
    if port not in (80, 443):
        return Decision(False, "port")
    if _blocked_name(cleaned):
        return Decision(False, "private-ip")

    literal = literal_ip(cleaned)
    if literal is not None:
        if not is_public(literal):
            return Decision(False, "private-ip")
        return Decision(True, "allow", str(literal))

    if not addresses:
        return Decision(False, "dns")

    chosen: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None
    for raw in addresses:
        try:
            ip = _unwrap(ipaddress.ip_address(raw))
        except ValueError:
            return Decision(False, "dns")
        if not is_public(ip):
            return Decision(False, "private-ip")
        if chosen is None or (
            isinstance(ip, ipaddress.IPv4Address) and isinstance(chosen, ipaddress.IPv6Address)
        ):
            chosen = ip
    if chosen is None:
        return Decision(False, "dns")
    return Decision(True, "allow", str(chosen))


def split_host_port(target: str, default_port: int) -> tuple[str, int] | None:
    """CONNECT 先の `host:port` または `[ipv6]:port` を分ける。"""
    text = (target or "").strip()
    if not text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return None
        host = text[1:end]
        rest = text[end + 1 :]
        if not rest:
            return host, default_port
        if not rest.startswith(":"):
            return None
        try:
            return host, int(rest[1:])
        except ValueError:
            return None
    if text.count(":") == 1:
        host, port_text = text.rsplit(":", 1)
        try:
            return host, int(port_text)
        except ValueError:
            return None
    return text, default_port
