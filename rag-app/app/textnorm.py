"""テキスト正規化（タグ名・ファイル名の Unicode 統一など）。

LLM / ブラウザは NFC、macOS 由来のファイル名等は NFD になりやすい。
タグ・source（ファイル名）の照合は常に NFC で行う。
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


def normalize_source(source: str | None) -> str:
    """ファイル名/URL（source）を strip + Unicode NFC に正規化する。"""
    if source is None:
        return ""
    return unicodedata.normalize("NFC", str(source)).strip()


def source_match_forms(source: str | None) -> list[str]:
    """Qdrant 等の厳密一致向けに、NFC/NFD/生値の候補を返す。"""
    raw = (source or "").strip()
    if not raw:
        return []
    forms: list[str] = []
    for form in (raw, normalize_source(raw), unicodedata.normalize("NFD", raw)):
        if form and form not in forms:
            forms.append(form)
    return forms
