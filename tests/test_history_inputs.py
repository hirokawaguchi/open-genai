from __future__ import annotations

from app.exapp_history import history_inputs


def test_history_inputs_strips_file_content() -> None:
    slim = history_inputs(
        {
            "language": "auto",
            "files": [
                {
                    "key": "audio",
                    "files": [{"filename": "a.mp3", "content": "AAAA"}],
                }
            ],
        }
    )
    assert slim["language"] == "auto"
    assert slim["files"][0]["files"][0]["filename"] == "a.mp3"
    assert slim["files"][0]["files"][0]["content"] == ""


def test_history_inputs_leaves_non_file_payloads() -> None:
    payload = {"language": "ja"}
    assert history_inputs(payload) == payload
    assert history_inputs("x") == "x"
