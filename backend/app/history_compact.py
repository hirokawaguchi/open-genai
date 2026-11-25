"""長い会話を、選択中のモデルへ送る前に畳む。

直近と最新の発話だけを原文で残し、それより前は要約へ置き換える。
要約は呼び出し側が渡すモデル（選択中のモデルとは別）で作る。
同じ前半を毎ターン要約し直さないよう、要約はプロセス内にキャッシュする。
続きのターンでは、前回の要約に新しくあふれた分だけを足す。

環境変数（未設定時は括弧内）:
- CHAT_HISTORY_COMPACT_CHARS (30000。0 以下で無効)
- CHAT_HISTORY_RECENT_CHARS (8000)
- CHAT_HISTORY_SUMMARY_CHARS (1500)
- CHAT_HISTORY_SUMMARY_CHUNK (12000)
- CHAT_HISTORY_SUMMARY_CALLS (4)
- CHAT_HISTORY_SUMMARY_MODEL (未設定なら DEFAULT_MODEL)
"""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from typing import Any, Awaitable, Callable

# これを超えた会話だけ畳む。監査上、入力の大半は 3 万字を超える少数のスレッドだった。
_DEFAULT_COMPACT_CHARS = 30_000
# 原文で残す、最新発話より前の直近分。
_DEFAULT_RECENT_CHARS = 8_000
# 要約本文の上限。選択中のモデルへ載る量をここで止める。
_DEFAULT_SUMMARY_CHARS = 1_500
# 要約 1 回に渡す文字数。
_DEFAULT_CHUNK_CHARS = 12_000
# すでに長い会話を初めて畳むとき、要約呼び出しが延々と続かないようにする。
_DEFAULT_SUMMARY_CALLS = 4
# 過去の画像を直近枠に残さないための重み。最新の発話に付いた画像はこの対象外。
_IMAGE_WEIGHT = 16_000
_CACHE_MAX = 1024

SummaryFn = Callable[[list[dict[str, Any]]], Awaitable[str]]

_CACHE: OrderedDict[str, str] = OrderedDict()

_SUMMARY_HEADER = (
    "これまでの会話の要約です。前半のやり取りを畳んだ背景であり、"
    "新しい依頼ではありません。\n"
)


def clear_summary_cache() -> None:
    _CACHE.clear()


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _message_text(message: dict[str, Any]) -> str:
    """要約とキャッシュキー用の本文。画像の実データは含めない。"""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                parts.append(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                parts.append("［画像添付］")
        return "\n".join(parts)
    if content is None:
        return ""
    return str(content)


def _message_chars(message: dict[str, Any]) -> int:
    content = message.get("content")
    if isinstance(content, list):
        total = 0
        for part in content:
            if not isinstance(part, dict):
                continue
            if part.get("type") == "text":
                total += len(str(part.get("text") or ""))
            elif part.get("type") == "image_url":
                total += _IMAGE_WEIGHT
        return total
    return len(_message_text(message))


def _fingerprint(message: dict[str, Any]) -> str:
    marks: list[str] = []
    content = message.get("content")
    if isinstance(content, list):
        for part in content:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            url = str((part.get("image_url") or {}).get("url") or "")
            marks.append(hashlib.sha256(url.encode()).hexdigest()[:12])
    role = str(message.get("role") or "")
    body = _message_text(message)
    return role + "\n" + body + "\n" + ",".join(marks)


def _prefix_keys(texts: list[str]) -> list[str]:
    digest = hashlib.sha256()
    keys: list[str] = []
    for text in texts:
        digest.update(b"\0")
        digest.update(text.encode("utf-8"))
        keys.append(digest.hexdigest())
    return keys


def _remember(key: str, summary: str) -> None:
    _CACHE[key] = summary
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


def _format_turn(message: dict[str, Any]) -> str:
    role = message.get("role")
    if role == "user":
        label = "利用者"
    elif role == "assistant":
        label = "アシスタント"
    else:
        label = str(role or "発言")
    return f"{label}: {_message_text(message)}"


def _pack(texts: list[str], chunk: int) -> list[list[str]]:
    groups: list[list[str]] = []
    buf: list[str] = []
    filled = 0
    for text in texts:
        remaining = text
        while remaining:
            room = chunk - filled
            if buf and room <= 0:
                groups.append(buf)
                buf = []
                filled = 0
                room = chunk
            piece = remaining[:room]
            buf.append(piece)
            filled += len(piece)
            remaining = remaining[len(piece) :]
            if filled >= chunk:
                groups.append(buf)
                buf = []
                filled = 0
    if buf:
        groups.append(buf)
    return groups


def _take_front(texts: list[str], limit: int) -> list[str]:
    picked: list[str] = []
    filled = 0
    for text in texts:
        if filled >= limit:
            break
        piece = text[: limit - filled]
        picked.append(piece)
        filled += len(piece)
    return picked


def _take_back(texts: list[str], limit: int) -> list[str]:
    picked: list[str] = []
    filled = 0
    for text in reversed(texts):
        if filled >= limit:
            break
        room = limit - filled
        piece = text[-room:] if len(text) > room else text
        picked.append(piece)
        filled += len(piece)
    picked.reverse()
    return picked


def _groups(texts: list[str]) -> tuple[list[list[str]], bool]:
    chunk = _int_env("CHAT_HISTORY_SUMMARY_CHUNK", _DEFAULT_CHUNK_CHARS)
    if chunk < 500:
        chunk = _DEFAULT_CHUNK_CHARS
    calls = _int_env("CHAT_HISTORY_SUMMARY_CALLS", _DEFAULT_SUMMARY_CALLS)
    if calls < 1:
        calls = _DEFAULT_SUMMARY_CALLS
    total = sum(len(text) for text in texts)
    if total <= chunk * calls:
        return _pack(texts, chunk), False
    head = _take_front(texts, chunk)
    tail = _take_back(texts, chunk * (calls - 1))
    covered = sum(len(piece) for piece in head) + sum(len(piece) for piece in tail)
    if covered >= total:
        return _pack(texts, chunk), False
    return _pack(head, chunk) + _pack(tail, chunk), True


async def _fold(summary: str, texts: list[str], complete: SummaryFn) -> tuple[str, int]:
    groups, omitted = _groups(texts)
    limit = _int_env("CHAT_HISTORY_SUMMARY_CHARS", _DEFAULT_SUMMARY_CHARS)
    if limit < 200:
        limit = _DEFAULT_SUMMARY_CHARS
    calls = 0
    noted = False
    for group in groups:
        extra = ""
        if omitted and not noted:
            extra = "中間のやり取りは長いため、先頭付近と直前だけを渡しています。\n"
            noted = True
        body = "\n".join(group)
        prompt = (
            "これまでの会話を、この後の回答に必要な範囲で要約してください。\n"
            "固有名詞、数値、日付、決定、利用者の依頼と制約、未解決の点を残してください。\n"
            f"要約は日本語で{limit}字以内にしてください。前置きは書かないでください。\n"
            f"{extra}"
            "既存の要約:\n"
            f"{summary or 'なし'}\n\n"
            "新たに畳む会話:\n"
            f"{body}"
        )
        try:
            got = (
                await complete(
                    [
                        {
                            "role": "system",
                            "content": "会話の要約係です。依頼された要約だけを返します。",
                        },
                        {"role": "user", "content": prompt},
                    ]
                )
            ).strip()
        except Exception as exc:  # noqa: BLE001 - 要約不能でも本回答は続ける
            print(f"[llm] history summary failed: {type(exc).__name__}")
            if not summary:
                summary = "前半の会話は長いため省略しました。"
            break
        calls += 1
        if got:
            summary = got[:limit]
    return summary.strip()[:limit], calls


async def _summarize_older(
    older: list[dict[str, Any]], complete: SummaryFn
) -> tuple[str, int]:
    texts = [_format_turn(message) for message in older]
    keys = _prefix_keys([_fingerprint(message) for message in older])
    final = keys[-1]
    cached = _CACHE.get(final)
    if cached is not None:
        _CACHE.move_to_end(final)
        return cached, 0

    start = 0
    summary = ""
    for index in range(len(keys) - 2, -1, -1):
        hit = _CACHE.get(keys[index])
        if hit is None:
            continue
        _CACHE.move_to_end(keys[index])
        start = index + 1
        summary = hit
        break

    calls = 0
    if texts[start:]:
        summary, calls = await _fold(summary, texts[start:], complete)
    if summary:
        _remember(final, summary)
    return summary, calls


def _split(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]] | None:
    """畳む必要があるとき (systems, older, recent_prior, latest) を返す。"""
    compact_at = _int_env("CHAT_HISTORY_COMPACT_CHARS", _DEFAULT_COMPACT_CHARS)
    if compact_at <= 0 or len(messages) <= 1:
        return None
    systems = [message for message in messages if message.get("role") == "system"]
    dialogue = [message for message in messages if message.get("role") != "system"]
    if len(dialogue) <= 1:
        return None
    total = sum(_message_chars(message) for message in messages)
    if total <= compact_at:
        return None

    latest = dialogue[-1]
    prior = dialogue[:-1]
    budget = max(0, _int_env("CHAT_HISTORY_RECENT_CHARS", _DEFAULT_RECENT_CHARS))
    recent_rev: list[dict[str, Any]] = []
    for message in reversed(prior):
        size = _message_chars(message)
        if size > budget:
            break
        recent_rev.append(message)
        budget -= size
    recent_prior = list(reversed(recent_rev))
    older = prior[: len(prior) - len(recent_prior)]
    if not older:
        return None
    return systems, older, recent_prior, latest


async def compact_history(
    messages: list[dict[str, Any]], complete: SummaryFn
) -> list[dict[str, Any]]:
    """しきい値を超えた会話の前半を要約へ置き換える。

    最新の発話は常に原文のまま残す。要約に失敗しても、前半の原文は送らない。
    """
    split = _split(messages)
    if split is None:
        return messages
    systems, older, recent_prior, latest = split
    summary, calls = await _summarize_older(older, complete)
    if not summary:
        summary = "前半の会話は長いため省略しました。"
    print(
        "[llm] history compact "
        f"messages={len(messages)} older={len(older)} "
        f"recent={len(recent_prior)} summary_chars={len(summary)} calls={calls}"
    )
    return [
        *systems,
        {"role": "system", "content": _SUMMARY_HEADER + summary},
        *recent_prior,
        latest,
    ]
