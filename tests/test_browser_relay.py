import asyncio

from conftest import load_service_module

relay = load_service_module("backend/app/browser_relay.py")


class FakeUpstream:
    def __init__(self) -> None:
        self.sent: list[object] = []
        self.items: asyncio.Queue[object | None] = asyncio.Queue()
        self.closed = False

    def __aiter__(self) -> "FakeUpstream":
        return self

    async def __anext__(self) -> object:
        item = await self.items.get()
        if item is None:
            raise StopAsyncIteration
        return item

    async def send(self, data: object) -> None:
        self.sent.append(data)

    async def close(self) -> None:
        self.closed = True
        await self.items.put(None)

    async def push(self, item: object) -> None:
        await self.items.put(item)


def test_relay_paths() -> None:
    assert relay.is_relay_path("/browser/sessions/abc/stream")
    assert relay.is_relay_path("/browser/sessions/abc/input")
    assert relay.is_relay_path("/browser/sessions/abc/audio/stream")
    assert relay.is_relay_path("/browser/sessions/abc/audio/input")
    assert not relay.is_relay_path("/browser/sessions/abc/downloads")
    assert not relay.is_relay_path("/browser/ws")


def test_frames_roundtrip() -> None:
    encoded = relay.encode_frames(
        [(relay.TEXT, "準備".encode()), (relay.BINARY, b"\x00\x01")]
    )
    assert relay.decode_frames(encoded) == [
        (relay.TEXT, "準備".encode()),
        (relay.BINARY, b"\x00\x01"),
    ]


def test_frames_reject_a_short_body() -> None:
    try:
        relay.decode_frames(b"\x01\x00\x00\x00\x02x")
    except ValueError:
        return
    raise AssertionError("short frame was accepted")


def test_pull_coalesces_queued_frames() -> None:
    async def scenario() -> None:
        upstream = FakeUpstream()
        item = relay.BrowserRelay(upstream, hold_sec=0.2, coalesce_sec=0.05, idle_sec=5)
        await upstream.push('{"type":"ready"}')
        await upstream.push(b"\x10\x20")
        payload = await item.pull()
        await item.close()
        assert payload is not None
        kinds = [kind for kind, _payload in relay.decode_frames(payload)]
        assert kinds == [relay.TEXT, relay.BINARY]

    asyncio.run(scenario())


def test_pull_returns_empty_when_idle_and_none_when_closed() -> None:
    async def scenario() -> None:
        upstream = FakeUpstream()
        item = relay.BrowserRelay(upstream, hold_sec=0.05, coalesce_sec=0.01, idle_sec=5)
        assert await item.pull() == b""
        await item.close()
        assert await item.pull() is None

    asyncio.run(scenario())


def test_send_frames_keeps_text_and_binary() -> None:
    async def scenario() -> None:
        upstream = FakeUpstream()
        item = relay.BrowserRelay(upstream, hold_sec=0.05, coalesce_sec=0.01, idle_sec=5)
        await item.send_frames([(relay.BINARY, b"abc"), (relay.TEXT, "ok".encode())])
        await item.close()
        assert upstream.sent == [b"abc", "ok"]

    asyncio.run(scenario())


def test_hub_sends_session_id_once() -> None:
    async def scenario() -> None:
        upstream = FakeUpstream()

        async def connect(_url: str, _headers: dict[str, str]) -> FakeUpstream:
            return upstream

        hub = relay.RelayHub(connect)
        opened: list[str] = []
        first = await hub.open(
            "user",
            "sess-1",
            "screen",
            "ws://browser-app/ws",
            {},
            on_open=lambda: opened.append("open"),
        )
        second = await hub.open(
            "user",
            "sess-1",
            "screen",
            "ws://browser-app/ws",
            {},
            on_open=lambda: opened.append("again"),
        )
        assert first is second
        assert opened == ["open"]
        assert upstream.sent == ['{"sessionId": "sess-1"}']
        await hub.close_session("user", "sess-1")
        assert upstream.closed

    asyncio.run(scenario())
