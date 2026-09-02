from __future__ import annotations

from conftest import load_service_module


def test_is_image_prompt_task_by_request_id() -> None:
    llm = load_service_module("backend/app/llm.py")
    assert llm._is_image_prompt_task([], "/image") is True
    assert llm._is_image_prompt_task([], "/image/abc") is True
    assert llm._is_image_prompt_task([], "/chat") is False


def test_is_image_prompt_task_by_system_prompt() -> None:
    llm = load_service_module("backend/app/llm.py")
    messages = [
        {
            "role": "system",
            "content": "あなたはStable Diffusionのプロンプトを生成するAIアシスタントです。",
        }
    ]
    assert llm._is_image_prompt_task(messages) is True
    assert llm._is_image_prompt_task([{"role": "user", "content": "柴犬"}]) is False


def test_image_prompt_extra_body_uses_json_schema() -> None:
    llm = load_service_module("backend/app/llm.py")
    extra = llm._image_prompt_extra_body()
    assert extra["response_format"]["type"] == "json_schema"
    schema = extra["response_format"]["json_schema"]["schema"]
    assert "prompt" in schema["properties"]
    assert "negativePrompt" in schema["required"]


def test_chat_payload_merges_image_extra_after_provider() -> None:
    llm = load_service_module("backend/app/llm.py")
    provider = llm.Provider(
        name="t",
        base_url="http://example",
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    payload = llm._chat_payload(
        provider,
        "qwen3.6-35b-a3b",
        [{"role": "user", "content": "hi"}],
        stream=True,
        extra=llm._image_prompt_extra_body(),
    )
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}
    assert payload["response_format"]["type"] == "json_schema"
