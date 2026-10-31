"""モデルが本文に混ぜる思考タグを、利用者向けテキストから除く。"""

from __future__ import annotations

import re

_THINK_BLOCK = re.compile(
    r"<think(?:ing)?>[\s\S]*?</think(?:ing)?>",
    re.IGNORECASE,
)
_THINK_OPEN = re.compile(r"<think(?:ing)?>", re.IGNORECASE)
_THINK_CLOSE = re.compile(r"</think(?:ing)?>", re.IGNORECASE)

_OPEN_TAGS = ("<thinking>", "<think>")
_CLOSE_TAGS = ("</thinking>", "</think>")


def strip_think_tags(text: str) -> str:
    """`<think>` / `<thinking>` の中身を除き、残った本文だけを返す。"""
    if not isinstance(text, str) or "<" not in text:
        return text
    cleaned = _THINK_BLOCK.sub("", text)
    opened = _THINK_OPEN.search(cleaned)
    if opened:
        cleaned = cleaned[: opened.start()]
    if cleaned == text:
        return text
    return cleaned.strip()


def _hold_partial_tag(buf: str, tags: tuple[str, ...]) -> str:
    """末尾がタグの途中なら、その部分だけ次の断片まで残す。"""
    lower = buf.lower()
    idx = lower.rfind("<")
    if idx < 0:
        return ""
    tail = lower[idx:]
    for tag in tags:
        if tag.startswith(tail) and tail != tag:
            return buf[idx:]
    return ""


class ThinkTagSplitter:
    """ストリーム断片から思考タグの中身を除き、今出してよい本文だけ返す。"""

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""
        self._buf += chunk
        return self._drain(final=False)

    def finish(self) -> str:
        text = self._drain(final=True)
        return text

    def _drain(self, final: bool) -> str:
        out: list[str] = []
        while self._buf:
            if self._in_think:
                closed = _THINK_CLOSE.search(self._buf)
                if not closed:
                    if final:
                        self._buf = ""
                    else:
                        self._buf = _hold_partial_tag(self._buf, _CLOSE_TAGS)
                    break
                self._buf = self._buf[closed.end() :]
                self._in_think = False
                continue
            opened = _THINK_OPEN.search(self._buf)
            if not opened:
                if final:
                    out.append(self._buf)
                    self._buf = ""
                else:
                    hold = _hold_partial_tag(self._buf, _OPEN_TAGS)
                    emit = self._buf[: len(self._buf) - len(hold)]
                    self._buf = hold
                    out.append(emit)
                break
            out.append(self._buf[: opened.start()])
            self._buf = self._buf[opened.end() :]
            self._in_think = True
        return "".join(out)
