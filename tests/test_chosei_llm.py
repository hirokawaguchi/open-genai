from __future__ import annotations

import json

from conftest import load_service_module


def test_chosei_extra_body_defaults_to_thinking_off(monkeypatch) -> None:
    monkeypatch.delenv("CHOSEI_EXTRA_BODY", raising=False)
    llm = load_service_module("chosei-app/app/llm.py")
    assert llm._extra_body() == {"chat_template_kwargs": {"enable_thinking": False}}


def test_chosei_extra_body_from_env(monkeypatch) -> None:
    monkeypatch.setenv(
        "CHOSEI_EXTRA_BODY",
        json.dumps({"chat_template_kwargs": {"enable_thinking": True}}),
    )
    llm = load_service_module("chosei-app/app/llm.py")
    assert llm._extra_body()["chat_template_kwargs"]["enable_thinking"] is True


def test_chosei_message_text_prefers_content() -> None:
    llm = load_service_module("chosei-app/app/llm.py")
    assert llm._message_text({"content": "ok", "reasoning_content": "think"}) == "ok"
    assert llm._message_text({"content": "", "reasoning_content": "think"}) == "think"
