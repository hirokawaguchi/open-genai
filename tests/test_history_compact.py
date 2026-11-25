"""長い会話を要約へ畳む処理の単体テスト。要約モデルは注入する。"""

from __future__ import annotations

import asyncio

import pytest

from app import history_compact as hc


def _user(text: str) -> dict:
    return {"role": "user", "content": text}


def _assistant(text: str) -> dict:
    return {"role": "assistant", "content": text}


def _texts(messages: list[dict]) -> str:
    return "\n".join(hc._message_text(message) for message in messages)


def test_short_history_is_unchanged() -> None:
    hc.clear_summary_cache()

    async def complete(messages):
        raise AssertionError("short history must not be summarized")

    messages = [
        {"role": "system", "content": "助手です"},
        _user("こんにちは"),
        _assistant("はい"),
        _user("続き"),
    ]
    out = asyncio.run(hc.compact_history(messages, complete))
    assert out == messages


def test_single_huge_message_stays_intact() -> None:
    hc.clear_summary_cache()

    async def complete(messages):
        raise AssertionError("the current request is not summarized")

    messages = [_user("あ" * 50_000)]
    out = asyncio.run(hc.compact_history(messages, complete))
    assert out == messages


def test_long_history_keeps_latest_and_drops_older(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_HISTORY_COMPACT_CHARS", "50")
    monkeypatch.setenv("CHAT_HISTORY_RECENT_CHARS", "30")
    monkeypatch.setenv("CHAT_HISTORY_SUMMARY_CHARS", "200")
    hc.clear_summary_cache()
    seen: list[str] = []

    async def complete(messages):
        seen.append(messages[-1]["content"])
        return "決定事項はAです"

    older = _user("あ" * 80)
    recent = _assistant("直近の回答")
    latest = _user("最新の質問")
    out = asyncio.run(
        hc.compact_history(
            [{"role": "system", "content": "規則"}, older, recent, latest],
            complete,
        )
    )
    assert len(seen) == 1
    assert "あ" * 80 in seen[0]
    assert "最新の質問" not in seen[0]
    joined = _texts(out)
    assert "あ" * 80 not in joined
    assert "規則" in joined
    assert "直近の回答" in joined
    assert "最新の質問" in joined
    assert "決定事項はAです" in joined
    assert out[0]["role"] == "system"
    assert out[1]["role"] == "system"
    assert out[-1] == latest


def test_followup_summarizes_only_the_new_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_HISTORY_COMPACT_CHARS", "100")
    monkeypatch.setenv("CHAT_HISTORY_RECENT_CHARS", "20")
    monkeypatch.setenv("CHAT_HISTORY_SUMMARY_CHARS", "500")
    hc.clear_summary_cache()
    seen: list[str] = []

    async def complete(messages):
        seen.append(messages[-1]["content"])
        return f"要約{len(seen)}"

    first_old = _user("甲" * 200)
    second_old = _user("乙" * 200)
    latest = _user("質問")
    asyncio.run(hc.compact_history([first_old, second_old, latest], complete))
    extra = _user("丙" * 200)
    asyncio.run(hc.compact_history([first_old, second_old, extra, latest], complete))

    assert len(seen) == 2
    assert "甲" * 200 in seen[0]
    assert "甲" * 200 not in seen[1]
    assert "乙" * 200 not in seen[1]
    assert "丙" * 200 in seen[1]
    assert "要約1" in seen[1]


def test_summary_failure_still_omits_older_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_HISTORY_COMPACT_CHARS", "50")
    monkeypatch.setenv("CHAT_HISTORY_RECENT_CHARS", "10")
    hc.clear_summary_cache()

    async def complete(messages):
        raise RuntimeError("down")

    older = _user("秘" * 100)
    latest = _user("質問")
    out = asyncio.run(hc.compact_history([older, latest], complete))
    assert "秘" * 100 not in _texts(out)
    assert out[-1]["content"] == "質問"
    assert "省略" in _texts(out)


def test_older_image_is_not_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_HISTORY_COMPACT_CHARS", "100")
    monkeypatch.setenv("CHAT_HISTORY_RECENT_CHARS", "1000")
    hc.clear_summary_cache()

    async def complete(messages):
        return "画像の話題"

    older = {
        "role": "user",
        "content": [
            {"type": "text", "text": "古い図"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        ],
    }
    latest = {
        "role": "user",
        "content": [
            {"type": "text", "text": "この図で"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,BBBB"}},
        ],
    }
    out = asyncio.run(hc.compact_history([older, latest], complete))
    dumped = str(out)
    assert "AAAA" not in dumped
    assert "BBBB" in dumped
    assert out[-1] == latest


def test_cold_start_caps_summary_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHAT_HISTORY_COMPACT_CHARS", "50")
    monkeypatch.setenv("CHAT_HISTORY_RECENT_CHARS", "10")
    monkeypatch.setenv("CHAT_HISTORY_SUMMARY_CHUNK", "500")
    monkeypatch.setenv("CHAT_HISTORY_SUMMARY_CALLS", "2")
    hc.clear_summary_cache()
    calls = 0

    async def complete(messages):
        nonlocal calls
        calls += 1
        return "S" + str(calls)

    older = [_user("あ" * 1000) for _ in range(5)]
    latest = _user("質問")
    out = asyncio.run(hc.compact_history([*older, latest], complete))
    assert calls <= 2
    assert out[-1]["content"] == "質問"
    assert "あ" * 1000 not in _texts(out)


def test_one_huge_older_message_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_HISTORY_COMPACT_CHARS", "50")
    monkeypatch.setenv("CHAT_HISTORY_RECENT_CHARS", "10")
    monkeypatch.setenv("CHAT_HISTORY_SUMMARY_CHUNK", "500")
    monkeypatch.setenv("CHAT_HISTORY_SUMMARY_CALLS", "2")
    hc.clear_summary_cache()
    calls = 0

    async def complete(messages):
        nonlocal calls
        calls += 1
        return "短い要約"

    out = asyncio.run(hc.compact_history([_user("あ" * 5000), _user("質問")], complete))
    assert calls <= 2
    assert "あ" * 5000 not in _texts(out)
    assert out[-1]["content"] == "質問"


def test_prepare_uses_summary_model_not_the_selected_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from conftest import load_service_module

    monkeypatch.setenv("CHAT_HISTORY_COMPACT_CHARS", "80")
    monkeypatch.setenv("CHAT_HISTORY_RECENT_CHARS", "10")
    monkeypatch.setenv("CHAT_HISTORY_SUMMARY_MODEL", "cheap-model")
    llm = load_service_module("backend/app/llm.py")
    seen: dict[str, object] = {}

    async def fake_complete(messages, model_id, temperature=0.0, max_tokens=None):
        seen["model"] = model_id
        seen["max_tokens"] = max_tokens
        return "畳んだ"

    monkeypatch.setattr(llm, "_complete", fake_complete)
    messages = [
        _user("う" * 100),
        _assistant("え" * 100),
        _user("最新"),
    ]
    out, notes = asyncio.run(
        llm._prepare_openai_messages(messages, {"modelId": "claude-sonnet-4-6"})
    )
    assert seen["model"] == "cheap-model"
    assert seen["max_tokens"] == 1024
    assert notes == []
    assert "う" * 100 not in _texts(out)
    assert out[-1]["content"] == "最新"
