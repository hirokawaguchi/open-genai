"""WebSocket の Upgrade が手前で落ちたときの画面・音声の中継。

ブラウザとの間は通常の HTTP で完結させる。応答を保留し、データが揃ったか
一定時間で返す。browser-app との間は今まで通り WebSocket のままにする。
テキストの制御メッセージとバイナリは、種別 1 バイトと長さ 4 バイトを付けてまとめる。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Awaitable, Callable

TEXT = 1
BINARY = 2
HEADER = 5
MAX_FRAME = 1024 * 1024
MAX_BODY = 1024 * 1024
MAX_PULL = 256 * 1024
HOLD_SEC = 15.0
COALESCE_SEC = 0.05
IDLE_SEC = 25.0


class RelayError(Exception):
    pass


class RelayUnavailable(RelayError):
    pass


class RelayClosed(RelayError):
    pass


def is_relay_path(path: str) -> bool:
    """画面と音声の HTTP 中継。アカウント単位の回数制限とアクセス監査から外す。"""
    parts = [part for part in path.split("/") if part]
    if len(parts) < 4 or parts[0] != "browser" or parts[1] != "sessions":
        return False
    if len(parts) == 4 and parts[3] in {"stream", "input"}:
        return True
    return len(parts) == 5 and parts[3] == "audio" and parts[4] in {"stream", "input"}


def encode_frames(frames: list[tuple[int, bytes]]) -> bytes:
    out = bytearray()
    for kind, payload in frames:
        if kind not in (TEXT, BINARY) or len(payload) > MAX_FRAME:
            raise ValueError("frame")
        out.append(kind)
        out += len(payload).to_bytes(4, "big")
        out += payload
    return bytes(out)


def decode_frames(data: bytes) -> list[tuple[int, bytes]]:
    frames: list[tuple[int, bytes]] = []
    index = 0
    total = len(data)
    while index < total:
        if index + HEADER > total:
            raise ValueError("frame")
        kind = data[index]
        length = int.from_bytes(data[index + 1 : index + 5], "big")
        index += HEADER
        if kind not in (TEXT, BINARY) or length > MAX_FRAME or index + length > total:
            raise ValueError("frame")
        frames.append((kind, bytes(data[index : index + length])))
        index += length
    return frames


async def connect_upstream(url: str, headers: dict[str, str]) -> Any:
    import websockets

    try:
        return await websockets.connect(url, additional_headers=headers)
    except TypeError:
        return await websockets.connect(url, extra_headers=list(headers.items()))


class BrowserRelay:
    """browser-app への WebSocket を、HTTP の取り出しと書き込みで共有する。"""

    def __init__(
        self,
        upstream: Any,
        *,
        on_close: Callable[[], None] | None = None,
        hold_sec: float = HOLD_SEC,
        coalesce_sec: float = COALESCE_SEC,
        idle_sec: float = IDLE_SEC,
    ) -> None:
        self.upstream = upstream
        self.hold_sec = hold_sec
        self.coalesce_sec = coalesce_sec
        self.idle_sec = idle_sec
        self.queue: asyncio.Queue[tuple[int, bytes] | None] = asyncio.Queue(maxsize=128)
        self.closed = asyncio.Event()
        self.last_used = time.monotonic()
        self._on_close = on_close
        self._shut = False
        self._send_lock = asyncio.Lock()
        self._reader = asyncio.create_task(self._read())
        self._watch = asyncio.create_task(self._watch())

    def touch(self) -> None:
        self.last_used = time.monotonic()

    async def _read(self) -> None:
        try:
            async for message in self.upstream:
                if self.closed.is_set():
                    return
                if isinstance(message, str):
                    item: tuple[int, bytes] = (TEXT, message.encode("utf-8"))
                elif isinstance(message, bytes):
                    item = (BINARY, message)
                else:
                    continue
                await self.queue.put(item)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001 - 上流が切れたら次の取り出しで閉じる
            pass
        finally:
            if not self._shut:
                await self.close()

    async def _watch(self) -> None:
        try:
            while not self.closed.is_set():
                await asyncio.sleep(5)
                if time.monotonic() - self.last_used > self.idle_sec:
                    await self.close()
                    return
        except asyncio.CancelledError:
            return

    async def _close_upstream(self) -> None:
        closer = getattr(self.upstream, "close", None)
        if closer is None:
            return
        result = closer()
        if asyncio.iscoroutine(result):
            try:
                await result
            except Exception:  # noqa: BLE001
                pass

    def _signal_end(self) -> None:
        while True:
            try:
                self.queue.put_nowait(None)
                return
            except asyncio.QueueFull:
                try:
                    self.queue.get_nowait()
                except asyncio.QueueEmpty:
                    return

    def _fire_close(self) -> None:
        callback = self._on_close
        self._on_close = None
        if callback is None:
            return
        try:
            callback()
        except Exception:  # noqa: BLE001
            pass

    async def close(self) -> None:
        """上流を閉じ、待ちの取り出しへ終端を渡す。読み取り側から呼んでも止まらない。"""
        if self._shut:
            await self.closed.wait()
            return
        self._shut = True
        current = asyncio.current_task()
        if self._watch is not current:
            self._watch.cancel()
        if self._reader is not current:
            self._reader.cancel()
        try:
            await self._close_upstream()
        except Exception:  # noqa: BLE001
            pass
        self.closed.set()
        self._signal_end()
        self._fire_close()

    async def pull(self) -> bytes | None:
        """次のフレーム群。無ければ空、上流が終わっていれば None。"""
        self.touch()
        try:
            first = await asyncio.wait_for(self.queue.get(), self.hold_sec)
        except asyncio.TimeoutError:
            self.touch()
            if self.closed.is_set() and self.queue.empty():
                return None
            return b""
        if first is None:
            return None
        frames = [first]
        size = HEADER + len(first[1])
        deadline = time.monotonic() + self.coalesce_sec
        while size < MAX_PULL:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            try:
                nxt = await asyncio.wait_for(self.queue.get(), timeout)
            except asyncio.TimeoutError:
                break
            if nxt is None:
                self.queue.put_nowait(None)
                break
            frames.append(nxt)
            size += HEADER + len(nxt[1])
        self.touch()
        return encode_frames(frames)

    async def send_frames(self, frames: list[tuple[int, bytes]]) -> None:
        self.touch()
        if self.closed.is_set():
            raise RelayClosed()
        async with self._send_lock:
            for kind, payload in frames:
                if self.closed.is_set():
                    raise RelayClosed()
                if kind == TEXT:
                    await self.upstream.send(payload.decode("utf-8"))
                elif kind == BINARY:
                    await self.upstream.send(payload)
                else:
                    raise ValueError("frame")


class RelayHub:
    def __init__(self, connect: Callable[[str, dict[str, str]], Awaitable[Any]] | None = None) -> None:
        self._connect = connect or connect_upstream
        self._relays: dict[tuple[str, str, str], BrowserRelay] = {}
        self._pending: dict[tuple[str, str, str], asyncio.Task[BrowserRelay]] = {}
        self._lock = asyncio.Lock()

    async def open(
        self,
        user_id: str,
        session_id: str,
        channel: str,
        url: str,
        headers: dict[str, str],
        *,
        on_open: Callable[[], None] | None = None,
        on_close: Callable[[], None] | None = None,
    ) -> BrowserRelay:
        key = (user_id, session_id, channel)
        async with self._lock:
            current = self._relays.get(key)
            if current is not None and not current.closed.is_set():
                return current
            pending = self._pending.get(key)
            if pending is None:
                pending = asyncio.create_task(
                    self._connect_one(key, session_id, url, headers, on_open, on_close)
                )
                self._pending[key] = pending
        try:
            return await asyncio.shield(pending)
        finally:
            async with self._lock:
                if self._pending.get(key) is pending and pending.done():
                    self._pending.pop(key, None)

    async def _connect_one(
        self,
        key: tuple[str, str, str],
        session_id: str,
        url: str,
        headers: dict[str, str],
        on_open: Callable[[], None] | None,
        on_close: Callable[[], None] | None,
    ) -> BrowserRelay:
        opened = False

        def wrapped_close() -> None:
            self._relays.pop(key, None)
            if opened and on_close is not None:
                on_close()

        try:
            upstream = await self._connect(url, headers)
        except Exception as exc:  # noqa: BLE001
            raise RelayUnavailable(str(exc)) from exc
        relay = BrowserRelay(upstream, on_close=wrapped_close)
        try:
            await upstream.send(json.dumps({"sessionId": session_id}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            await relay.close()
            raise RelayUnavailable(str(exc)) from exc
        opened = True
        async with self._lock:
            self._relays[key] = relay
        if on_open is not None:
            on_open()
        return relay

    async def close_session(self, user_id: str, session_id: str) -> None:
        async with self._lock:
            relays = [
                relay
                for key, relay in self._relays.items()
                if key[0] == user_id and key[1] == session_id
            ]
        for relay in relays:
            await relay.close()


hub = RelayHub()
