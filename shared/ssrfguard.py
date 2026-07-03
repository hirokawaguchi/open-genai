"""SSRF 対策付きの HTTP 取得ユーティリティ（backend / rag-app 共用）。

サーバ側から外部 URL を取得する箇所（成果物ファイル再ホスト、RAG の URL 取込）で、
内部ネットワーク・クラウドメタデータ等への到達を防ぐ。

対策:
- スキームは http/https のみ。
- ホスト名を解決し、**解決された全 IP が公開アドレス**であることを要求（プライベート/
  ループバック/リンクローカル/予約/マルチキャスト等は拒否）。
- **DNS リバインディング対策**: 検証済み IP へ接続を固定（URL のホストを IP へ書換え、
  Host ヘッダと TLS SNI は元のホスト名を維持して証明書検証を保つ）。
- リダイレクトは自動追従せず、各ホップの遷移先を**都度再検証**する。
- 応答サイズに上限を設ける（ストリームで超過時に中断）。
- allowlist（ホスト名の集合）が指定された場合は、そのホストのみ許可。
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterable
from urllib.parse import urljoin, urlparse

import httpx


class SsrfBlocked(Exception):
    """取得先が安全でないため取得を拒否したことを表す。"""


def ip_is_public(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _resolve_public_ip(host: str, port: int) -> str:
    """host を解決し、全 IP が公開なら最初の IP を返す。1つでも内部なら拒否。"""
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        raise SsrfBlocked(f"名前解決に失敗: {host}") from e
    addrs = [info[4][0] for info in infos]
    if not addrs:
        raise SsrfBlocked(f"解決アドレスなし: {host}")
    for addr in addrs:
        if not ip_is_public(addr):
            raise SsrfBlocked(f"内部宛先は不可: {host} -> {addr}")
    return addrs[0]


def _validate_and_pin(url: str, allowed_hosts: Iterable[str] | None) -> tuple[str, dict, str]:
    """URL を検証し、(接続用 IP URL, ヘッダ, sni_hostname) を返す。"""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfBlocked("http(s) 以外は不可")
    host = (parsed.hostname or "").lower()
    if not host:
        raise SsrfBlocked("ホスト名なし")
    allow = {h.strip().lower() for h in (allowed_hosts or ()) if h and h.strip()}
    if allow and host not in allow:
        raise SsrfBlocked(f"許可されていないホスト: {host}")
    port = parsed.port or _default_port(parsed.scheme)
    ip = _resolve_public_ip(host, port)
    # 接続先を検証済み IP に固定（IPv6 は角括弧で囲う）
    netloc_ip = f"[{ip}]" if ":" in ip else ip
    if parsed.port:
        netloc_ip = f"{netloc_ip}:{parsed.port}"
    ip_url = parsed._replace(netloc=netloc_ip).geturl()
    # Host ヘッダは元のホスト（必要なら非既定ポートを付す）
    host_header = host if not parsed.port else f"{host}:{parsed.port}"
    return ip_url, {"Host": host_header}, host


async def fetch(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
    max_bytes: int = 50 * 1024 * 1024,
    max_redirects: int = 3,
    timeout: float = 60.0,
    user_agent: str = "OpenGENAI-fetch/1.0",
) -> tuple[bytes, str]:
    """SSRF 対策付きで URL を取得し (本文, Content-Type) を返す。

    危険な宛先は SsrfBlocked を送出。通信失敗は httpx.HTTPError を送出。
    """
    current = url
    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(max_redirects + 1):
            ip_url, headers, sni = _validate_and_pin(current, allowed_hosts)
            headers["User-Agent"] = user_agent
            req = client.build_request("GET", ip_url, headers=headers)
            # 検証済みホスト名で TLS を行い証明書検証を維持する
            req.extensions["sni_hostname"] = sni
            resp = await client.send(req, stream=True, follow_redirects=False)
            try:
                if resp.is_redirect:
                    loc = resp.headers.get("location")
                    if not loc:
                        raise SsrfBlocked("リダイレクト先が不明")
                    current = urljoin(current, loc)
                    continue
                if resp.status_code != 200:
                    raise httpx.HTTPStatusError(
                        f"status {resp.status_code}", request=req, response=resp
                    )
                mime = resp.headers.get("content-type", "")
                clen = resp.headers.get("content-length")
                if clen and clen.isdigit() and int(clen) > max_bytes:
                    raise SsrfBlocked(f"サイズ上限超過: {clen} bytes")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf.extend(chunk)
                    if len(buf) > max_bytes:
                        raise SsrfBlocked("サイズ上限超過（ストリーム中断）")
                return bytes(buf), mime
            finally:
                await resp.aclose()
    raise SsrfBlocked("リダイレクト回数の上限に達しました")
