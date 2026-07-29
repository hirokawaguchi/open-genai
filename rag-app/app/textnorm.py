"""テキスト正規化（タグ名の Unicode 統一など）。

LLM / ブラウザは NFC、macOS 由来のファイル名等は NFD になりやすい。
タグ照合は常に NFC で行う。
"""

from __future__ import annotations

import unicodedata
from typing import Iterable


def normalize_tag(tag: str | None) -> str:
    """タグ名を strip + Unicode NFC に正規化する。"""
    if tag is None:
        return ""
    return unicodedata.normalize("NFC", str(tag)).strip()


def normalize_tags(tags: Iterable[str] | None) -> list[str]:
    """タグ一覧を正規化し、空を除いて順序を保ったまま重複除去する。"""
    out: list[str] = []
    for t in tags or []:
        name = normalize_tag(t)
        if name and name not in out:
            out.append(name)
    return out
