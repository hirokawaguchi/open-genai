"""URL（Web ページ）取得と HTML→テキスト抽出。

6-(26) RAG での本市ホームページ（URL）取り込み用。サーバからの外部疎通が
可能な構成を前提とする。HTML からの本文抽出は軽量な正規表現ベース（依存追加なし）。
"""

from __future__ import annotations

import html as _html
import os
import re

from shared import ssrfguard

URL_FETCH_TIMEOUT = float(os.environ.get("URL_FETCH_TIMEOUT", "30"))
URL_MAX_BYTES = int(os.environ.get("URL_MAX_BYTES", str(5 * 1024 * 1024)))
URL_USER_AGENT = os.environ.get("URL_USER_AGENT", "OpenGENAI-RAG-Crawler/1.0")
# 取り込み許可ホスト（カンマ区切り, 空=内部宛先のみ拒否）。行政ドメイン等に限定推奨。
URL_FETCH_ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.environ.get("URL_FETCH_ALLOWED_HOSTS", "").split(",")
    if h.strip()
}
_CHARSET_RE = re.compile(r"charset=([\w\-]+)", re.IGNORECASE)

_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style|noscript|template)[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTINL_RE = re.compile(r"\n{3,}")


def html_to_text(content: str) -> str:
    """HTML から本文テキストを抽出する（script/style 除去・タグ除去・空白整理）。"""
    if not content:
        return ""
    # <br>, </p>, </div>, 見出し, <li> などは改行に寄せる
    text = re.sub(r"(?i)<br\s*/?>", "\n", content)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6]|section|article)>", "\n", text)
    text = _SCRIPT_STYLE_RE.sub(" ", text)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    # 空白・改行の整理
    lines = [_WS_RE.sub(" ", ln).strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return _MULTINL_RE.sub("\n\n", text).strip()


def extract_title(content: str) -> str:
    m = _TITLE_RE.search(content or "")
    if not m:
        return ""
    return _html.unescape(_TAG_RE.sub("", m.group(1))).strip()


async def fetch_url(url: str) -> tuple[str, str]:
    """URL を取得して (本文テキスト, タイトル) を返す。

    HTML はテキスト抽出、その他 text/* はそのまま。バイナリは空を返す。
    SSRF 対策として shared.ssrfguard 経由で取得する（内部宛先拒否・DNS ピニング・
    リダイレクト都度検証）。
    """
    raw, ctype = await ssrfguard.fetch(
        url,
        allowed_hosts=URL_FETCH_ALLOWED_HOSTS or None,
        max_bytes=URL_MAX_BYTES,
        timeout=URL_FETCH_TIMEOUT,
        user_agent=URL_USER_AGENT,
    )
    ctype = (ctype or "").lower()
    m = _CHARSET_RE.search(ctype)
    encoding = m.group(1) if m else "utf-8"
    try:
        body = raw.decode(encoding, "ignore")
    except (LookupError, UnicodeDecodeError):
        body = raw.decode("utf-8", "ignore")

    if "html" in ctype or body.lstrip()[:1] == "<":
        return html_to_text(body), extract_title(body)
    if ctype.startswith("text/") or not ctype:
        return body.strip(), ""
    # HTML/テキスト以外（PDF 等のバイナリ）は本モジュールでは対象外
    return "", ""
