"""マイク文字起こし。OpenAI の gpt-live-transcribe だけを使う。

ファイルの文字起こし（ローカル faster-whisper）とは別経路。
API キーはサーバーに置き、ブラウザへは出さない。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from fastapi import WebSocketDisconnect

LIVE_MODEL = "gpt-live-transcribe"
LIVE_WS_URL = "wss://api.openai.com/v1/realtime?intent=transcription"
OPENAI_API_HOST = "api.openai.com"
MAX_AUDIO_CHARS = 200_000
MAX_SESSION_SECONDS = 30 * 60
_PLACEHOLDER_KEYS = frozenset({"", "ollama"})
_DELTA = "conversation.item.input_audio_transcription.delta"
_DONE = "conversation.item.input_audio_transcription.completed"
_FAILED = "conversation.item.input_audio_transcription.failed"


class WhisperLiveError(Exception):
    """利用者に見せるメッセージと、そこまでの文字起こし。"""

    def __init__(self, message: str, transcript: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.transcript = transcript


def _usable_key(value: Any) -> str | None:
    key = str(value or "").strip()
    if key.lower() in _PLACEHOLDER_KEYS:
        return None
    return key


def is_openai_api_base(base_url: str) -> bool:
    """api.openai.com だけを OpenAI 公式とみなす。Azure や Ollama は含めない。"""
    host = (urlparse(base_url).hostname or "").lower()
    return host == OPENAI_API_HOST


def resolve_api_key(environ: Mapping[str, str]) -> str | None:
    """マイク文字起こしに使う OpenAI の API キー。無ければ None。

    優先順は WHISPER_LIVE_API_KEY、LLM_PROVIDERS 内の api.openai.com、
    OPENAI_BASE_URL が api.openai.com のときの OPENAI_API_KEY。
    """
    explicit = _usable_key(environ.get("WHISPER_LIVE_API_KEY"))
    if explicit:
        return explicit

    raw = str(environ.get("LLM_PROVIDERS") or "").strip()
    if raw:
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError:
            entries = []
        if isinstance(entries, list):
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if not is_openai_api_base(str(entry.get("base_url") or "")):
                    continue
                if entry.get("api_key_env"):
                    found = _usable_key(environ.get(str(entry["api_key_env"])))
                else:
                    found = _usable_key(entry.get("api_key"))
                if found:
                    return found

    if is_openai_api_base(str(environ.get("OPENAI_BASE_URL") or "")):
        return _usable_key(environ.get("OPENAI_API_KEY"))
    return None


def normalize_language(value: Any) -> str:
    lang = str(value or "auto").strip().lower()
    if lang in ("ja", "en", "auto"):
        return lang
    return "auto"


def session_update(language: str) -> dict[str, Any]:
    """gpt-live-transcribe のセッション設定。自動判定のときは言語ヒントを付けない。"""
    transcription: dict[str, Any] = {"model": LIVE_MODEL, "delay": "low"}
    lang = normalize_language(language)
    if lang in ("ja", "en"):
        transcription["languages"] = [lang]
    return {
        "type": "session.update",
        "session": {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": transcription,
                    "turn_detection": None,
                }
            },
        },
    }


def client_audio_event(payload: Mapping[str, Any]) -> dict[str, str] | None:
    """ブラウザの音声メッセージを OpenAI の append / commit に変換する。"""
    kind = payload.get("type")
    if kind == "commit":
        return {"type": "input_audio_buffer.commit"}
    if kind != "audio":
        return None
    audio = payload.get("audio")
    if not isinstance(audio, str):
        return None
    audio = "".join(audio.split())
    if not audio or len(audio) > MAX_AUDIO_CHARS:
        return None
    try:
        base64.b64decode(audio, validate=True)
    except Exception:  # noqa: BLE001
        return None
    return {"type": "input_audio_buffer.append", "audio": audio}


class TranscriptBook:
    """区間ごとの途中結果と確定結果。確定が来たら途中結果を置き換える。"""

    def __init__(self) -> None:
        self.partials: dict[str, str] = {}
        self.finals: dict[str, str] = {}
        self.order: list[str] = []

    def _touch(self, item_id: str) -> None:
        if item_id not in self.order:
            self.order.append(item_id)

    def apply(self, event: Mapping[str, Any]) -> dict[str, str] | None:
        kind = event.get("type")
        if kind == _DELTA:
            item_id = str(event.get("item_id") or "")
            if not item_id:
                return None
            self._touch(item_id)
            self.partials[item_id] = self.partials.get(item_id, "") + str(event.get("delta") or "")
            return {"type": "delta", "itemId": item_id, "text": self.partials[item_id]}
        if kind == _DONE:
            item_id = str(event.get("item_id") or "")
            if not item_id:
                return None
            self._touch(item_id)
            text = str(event.get("transcript") or "").strip()
            self.finals[item_id] = text
            self.partials.pop(item_id, None)
            return {"type": "transcript", "itemId": item_id, "text": text}
        if kind == _FAILED:
            return {"type": "error", "message": "この区間の文字起こしに失敗しました。話し続けるとその先は続きます。"}
        if kind == "error":
            err = event.get("error")
            message = ""
            if isinstance(err, dict):
                message = str(err.get("message") or "")
            return {
                "type": "error",
                "message": message or "OpenAI の文字起こしでエラーが発生しました。",
            }
        return None

    def text(self) -> str:
        parts: list[str] = []
        for item_id in self.order:
            if item_id in self.finals:
                parts.append(self.finals[item_id])
            elif self.partials.get(item_id):
                parts.append(self.partials[item_id])
        return "\n".join(part for part in parts if part).strip()


def format_output(text: str) -> str:
    return f"**音声の送信先**: OpenAI（{LIVE_MODEL}）\n\n{text.strip()}"


def _error_message(event: Mapping[str, Any]) -> str:
    mapped = TranscriptBook().apply(event)
    if mapped and mapped.get("message"):
        return mapped["message"]
    return "OpenAI の文字起こしでエラーが発生しました。"


def _redact(text: str) -> str:
    return re.sub(r"Bearer\s+\S+", "Bearer [redacted]", text)[:300]


def _connect(api_key: str) -> Any:
    import websockets

    headers = {"Authorization": f"Bearer {api_key}"}
    kwargs = {"open_timeout": 15, "max_size": 2**20}
    try:
        return websockets.connect(LIVE_WS_URL, additional_headers=headers, **kwargs)
    except TypeError:
        return websockets.connect(LIVE_WS_URL, extra_headers=list(headers.items()), **kwargs)


async def _next_event(upstream: Any, timeout: float) -> dict[str, Any]:
    raw = await asyncio.wait_for(upstream.recv(), timeout)
    if isinstance(raw, bytes):
        raw = raw.decode()
    event = json.loads(raw)
    if not isinstance(event, dict):
        raise WhisperLiveError("OpenAI の文字起こしから不正な応答を受け取りました。")
    return event


async def _configure(upstream: Any, language: str) -> None:
    deadline = time.monotonic() + 15
    created = False
    while time.monotonic() < deadline:
        event = await _next_event(upstream, 15)
        if event.get("type") == "error":
            raise WhisperLiveError(_error_message(event))
        if event.get("type") == "session.created":
            created = True
            break
    if not created:
        raise WhisperLiveError("OpenAI の文字起こしに接続できませんでした。")
    await upstream.send(json.dumps(session_update(language)))
    while time.monotonic() < deadline:
        event = await _next_event(upstream, 15)
        if event.get("type") == "error":
            raise WhisperLiveError(_error_message(event))
        if event.get("type") == "session.updated":
            return
    raise WhisperLiveError("OpenAI の文字起こしを開始できませんでした。")


async def _send_browser(browser: Any, payload: dict[str, str]) -> None:
    try:
        await browser.send_text(json.dumps(payload, ensure_ascii=False))
    except Exception:  # noqa: BLE001
        return


async def run_live_session(browser: Any, api_key: str, *, language: str) -> str:
    """ブラウザの PCM を OpenAI へ中継し、組み立てた文字起こしを返す。"""
    book = TranscriptBook()
    try:
        connection = _connect(api_key)
    except Exception as exc:  # noqa: BLE001
        print(f"[whisper-live] 接続の準備に失敗: {_redact(repr(exc))}")
        raise WhisperLiveError("OpenAI の文字起こしに接続できませんでした。") from exc

    try:
        async with connection as upstream:
            try:
                await _configure(upstream, language)
            except WhisperLiveError:
                raise
            except Exception as exc:  # noqa: BLE001
                print(f"[whisper-live] セッション開始に失敗: {_redact(repr(exc))}")
                raise WhisperLiveError("OpenAI の文字起こしに接続できませんでした。", book.text()) from exc

            await _send_browser(browser, {"type": "ready"})
            started = time.monotonic()
            audio_since_commit = False

            async def browser_to_upstream() -> None:
                nonlocal audio_since_commit
                while True:
                    if time.monotonic() - started > MAX_SESSION_SECONDS:
                        raise WhisperLiveError(
                            "マイクの文字起こしは30分で区切ります。ここまでの結果を保存します。",
                            book.text(),
                        )
                    try:
                        message = await browser.receive()
                    except WebSocketDisconnect:
                        if audio_since_commit:
                            await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        return
                    if message.get("type") == "websocket.disconnect":
                        if audio_since_commit:
                            await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))
                        return
                    raw = message.get("text")
                    if not isinstance(raw, str):
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload, dict):
                        continue
                    if payload.get("type") == "stop":
                        if audio_since_commit:
                            await upstream.send(json.dumps({"type": "input_audio_buffer.commit"}))
                            audio_since_commit = False
                        return
                    event = client_audio_event(payload)
                    if event is None:
                        continue
                    if event["type"] == "input_audio_buffer.commit" and not audio_since_commit:
                        continue
                    await upstream.send(json.dumps(event))
                    if event["type"] == "input_audio_buffer.append":
                        audio_since_commit = True
                    else:
                        audio_since_commit = False

            async def upstream_to_browser() -> None:
                while True:
                    event = await _next_event(upstream, MAX_SESSION_SECONDS)
                    if event.get("type") == "error":
                        mapped = book.apply(event) or {
                            "type": "error",
                            "message": "OpenAI の文字起こしでエラーが発生しました。",
                        }
                        await _send_browser(browser, mapped)
                        raise WhisperLiveError(mapped["message"], book.text())
                    mapped = book.apply(event)
                    if mapped:
                        await _send_browser(browser, mapped)

            browser_task = asyncio.create_task(browser_to_upstream())
            upstream_task = asyncio.create_task(upstream_to_browser())
            try:
                done, _pending = await asyncio.wait(
                    {browser_task, upstream_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if browser_task in done:
                    exc = browser_task.exception()
                    if exc:
                        raise exc
                    try:
                        await asyncio.wait_for(asyncio.shield(upstream_task), timeout=3)
                    except asyncio.TimeoutError:
                        upstream_task.cancel()
                else:
                    exc = upstream_task.exception()
                    browser_task.cancel()
                    if exc:
                        raise exc
            finally:
                for task in (browser_task, upstream_task):
                    if not task.done():
                        task.cancel()
                await asyncio.gather(browser_task, upstream_task, return_exceptions=True)
            return book.text()
    except WhisperLiveError as exc:
        if not exc.transcript:
            exc.transcript = book.text()
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[whisper-live] 中継に失敗: {_redact(repr(exc))}")
        raise WhisperLiveError("マイクの文字起こしが中断されました。", book.text()) from exc
