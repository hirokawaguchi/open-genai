from __future__ import annotations

from app.whisper_live import (
    TranscriptBook,
    _client_disconnected,
    client_audio_event,
    format_output,
    normalize_language,
    resolve_api_key,
    session_update,
)


def test_resolve_api_key_uses_explicit_openai_key() -> None:
    key = resolve_api_key(
        {
            "WHISPER_LIVE_API_KEY": "sk-live",
            "OPENAI_BASE_URL": "http://host.docker.internal:11434/v1",
            "OPENAI_API_KEY": "ollama",
        }
    )
    assert key == "sk-live"


def test_resolve_api_key_rejects_ollama_and_azure() -> None:
    assert resolve_api_key({"OPENAI_BASE_URL": "http://ollama:11434/v1", "OPENAI_API_KEY": "ollama"}) is None
    assert (
        resolve_api_key(
            {
                "OPENAI_BASE_URL": "https://example.openai.azure.com/openai/deployments/gpt",
                "OPENAI_API_KEY": "azure-key",
            }
        )
        is None
    )
    assert resolve_api_key({"WHISPER_LIVE_API_KEY": "ollama"}) is None


def test_resolve_api_key_reads_openai_provider() -> None:
    environ = {
        "LLM_PROVIDERS": (
            '[{"name":"ollama","base_url":"http://ollama:11434/v1","api_key":"ollama"},'
            '{"name":"openai","base_url":"https://api.openai.com/v1","api_key_env":"OPENAI_PROVIDER_API_KEY"}]'
        ),
        "OPENAI_PROVIDER_API_KEY": "sk-provider",
        "OPENAI_BASE_URL": "",
        "OPENAI_API_KEY": "ollama",
    }
    assert resolve_api_key(environ) == "sk-provider"


def test_resolve_api_key_uses_default_when_base_is_openai() -> None:
    assert (
        resolve_api_key(
            {
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
                "OPENAI_API_KEY": "sk-default",
            }
        )
        == "sk-default"
    )


def test_session_update_sets_language_hint_only_when_chosen() -> None:
    auto = session_update("auto")
    chosen = session_update("ja")
    auto_tx = auto["session"]["audio"]["input"]["transcription"]
    chosen_tx = chosen["session"]["audio"]["input"]["transcription"]
    assert auto_tx["model"] == "gpt-live-transcribe"
    assert "languages" not in auto_tx
    assert chosen_tx["languages"] == ["ja"]
    assert chosen["session"]["audio"]["input"]["turn_detection"] is None
    assert normalize_language("fr") == "auto"


def test_client_disconnected_matches_fastapi_name_without_import() -> None:
    class WebSocketDisconnect(Exception):
        pass

    assert _client_disconnected(WebSocketDisconnect())
    assert not _client_disconnected(RuntimeError("boom"))


def test_client_audio_event_rejects_invalid_audio() -> None:
    assert client_audio_event({"type": "audio", "audio": "!!!!"}) is None
    assert client_audio_event({"type": "audio", "audio": "A" * 200_001}) is None
    assert client_audio_event({"type": "commit"}) == {"type": "input_audio_buffer.commit"}


def test_transcript_book_replaces_partial_with_final() -> None:
    book = TranscriptBook()
    first = book.apply(
        {
            "type": "conversation.item.input_audio_transcription.delta",
            "item_id": "item_1",
            "delta": "こんにちは",
        }
    )
    assert first == {"type": "delta", "itemId": "item_1", "text": "こんにちは"}
    book.apply(
        {
            "type": "conversation.item.input_audio_transcription.delta",
            "item_id": "item_1",
            "delta": "、本日は",
        }
    )
    done = book.apply(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item_1",
            "transcript": "こんにちは、本日は",
        }
    )
    assert done == {"type": "transcript", "itemId": "item_1", "text": "こんにちは、本日は"}
    assert book.text() == "こんにちは、本日は"
    assert "gpt-live-transcribe" in format_output(book.text())
