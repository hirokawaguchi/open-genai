"""チャットフローの streaming 実行（_run_chat_stream）の単体テスト。

Dify への SSE 接続を差し替え、`message` 断片が逐次 delta として yield され、
最後に集約済みの done（全文・出典・ファイル）が来ることを検証する。エラー
イベントは `_run_chat` と同じく AppInvokeError に分類されることも確認する。
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path

import httpx

_MAIN = Path(__file__).resolve().parents[1] / "app" / "main.py"


def _load_main():
    spec = importlib.util.spec_from_file_location("dify_app_main", _MAIN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dify_app_main"] = mod
    spec.loader.exec_module(mod)
    return mod


class _FakeStreamResponse:
    """httpx の streaming レスポンスを模した非同期コンテキストマネージャ。"""

    def __init__(self, status_code: int, lines: list[str]) -> None:
        self.status_code = status_code
        self._lines = lines

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self) -> bytes:
        return b""


class _FakeAsyncClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    def stream(self, *_a: object, **_k: object) -> _FakeStreamResponse:
        return self._response


def _sse(lines: list[str]) -> list[str]:
    """SSE の data: 行に整形する。"""
    return [f"data: {ln}" for ln in lines]


class RunChatStreamTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.main = _load_main()

    def _patch_httpx(self, status_code: int, lines: list[str]) -> None:
        response = _FakeStreamResponse(status_code, lines)
        fake = types.SimpleNamespace(
            AsyncClient=lambda *a, **k: _FakeAsyncClient(response),
            HTTPError=httpx.HTTPError,
        )
        self._orig_httpx = self.main.httpx
        self.main.httpx = fake
        self.addCleanup(lambda: setattr(self.main, "httpx", self._orig_httpx))

    def _collect(self, *, conversation_id: str = "") -> list[dict]:
        async def _run() -> list[dict]:
            out: list[dict] = []
            async for ev in self.main._run_chat_stream(
                base="https://dify.example/v1",
                api_key="app-test",
                query="こんにちは",
                inputs={},
                user="u",
                conversation_id=conversation_id,
                files=[],
            ):
                out.append(ev)
            return out

        return asyncio.run(_run())

    def test_message_chunks_yield_deltas_then_done(self) -> None:
        self._patch_httpx(
            200,
            _sse(
                [
                    '{"event":"workflow_started","conversation_id":"conv-1"}',
                    '{"event":"message","answer":"大分","conversation_id":"conv-1"}',
                    '{"event":"message","answer":"市"}',
                    '{"event":"message","answer":"です"}',
                    '{"event":"message_end"}',
                ]
            ),
        )
        events = self._collect()
        deltas = [e for e in events if e["type"] == "delta"]
        dones = [e for e in events if e["type"] == "done"]
        convs = [e for e in events if e["type"] == "conversation"]
        # 会話IDは delta より前に 1 回だけ早期通知される
        self.assertEqual(len(convs), 1)
        self.assertEqual(convs[0]["conversation_id"], "conv-1")
        self.assertLess(events.index(convs[0]), events.index(deltas[0]))
        self.assertEqual([d["text"] for d in deltas], ["大分", "市", "です"])
        self.assertEqual(len(dones), 1)
        done = dones[0]
        self.assertEqual(done["answer"], "大分市です")
        # 会話 ID は SSE 内の conversation_id を引き継ぐ
        self.assertEqual(done["conversation_id"], "conv-1")
        self.assertEqual(done["files"], [])

    def test_continuation_does_not_reemit_conversation(self) -> None:
        # 既存会話の継続（conversation_id 指定済み）では conversation を再通知しない
        self._patch_httpx(
            200,
            _sse(
                [
                    '{"event":"message","answer":"A","conversation_id":"conv-x"}',
                    '{"event":"message_end"}',
                ]
            ),
        )
        events = self._collect(conversation_id="conv-x")
        convs = [e for e in events if e["type"] == "conversation"]
        self.assertEqual(convs, [])

    def test_empty_answer_chunks_are_skipped(self) -> None:
        self._patch_httpx(
            200,
            _sse(
                [
                    '{"event":"message","answer":"","conversation_id":"c"}',
                    '{"event":"message","answer":"A"}',
                ]
            ),
        )
        events = self._collect()
        deltas = [e for e in events if e["type"] == "delta"]
        self.assertEqual([d["text"] for d in deltas], ["A"])

    def test_error_event_raises_app_invoke_error(self) -> None:
        self._patch_httpx(
            200,
            _sse(['{"event":"error","message":"boom"}']),
        )
        with self.assertRaises(self.main.AppInvokeError) as ctx:
            self._collect()
        self.assertEqual(ctx.exception.code, "WORKFLOW_ERROR")

    def test_non_200_status_raises_connection(self) -> None:
        self._patch_httpx(502, [])
        with self.assertRaises(self.main.AppInvokeError) as ctx:
            self._collect()
        self.assertEqual(ctx.exception.code, "CONNECTION")

    def test_run_chat_saves_conversation_early(self) -> None:
        # 同期経路も、会話IDが判明した時点で session→conversation を即保存する
        self._patch_httpx(
            200,
            _sse(
                [
                    '{"event":"message","answer":"A","conversation_id":"conv-sync"}',
                    '{"event":"message","answer":"B"}',
                    '{"event":"message_end"}',
                ]
            ),
        )
        saved: list[tuple[str, str]] = []
        orig = self.main._save_conversation_id
        self.main._save_conversation_id = lambda s, c: saved.append((s, c))
        self.addCleanup(lambda: setattr(self.main, "_save_conversation_id", orig))

        async def _run():
            return await self.main._run_chat(
                base="https://dify.example/v1",
                api_key="app-test",
                query="hi",
                inputs={},
                user="u",
                conversation_id="",
                files=[],
                session_id="sess-1",
            )

        answer, conv_id, _files, _cits = asyncio.run(_run())
        self.assertEqual(answer, "AB")
        self.assertEqual(conv_id, "conv-sync")
        # 早期保存が 1 回だけ行われる（イベント毎の重複保存はしない）
        self.assertEqual(saved, [("sess-1", "conv-sync")])


if __name__ == "__main__":
    unittest.main()
