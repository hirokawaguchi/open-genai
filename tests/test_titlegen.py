from __future__ import annotations

import json

from app import titlegen


def test_clean_title_strips_output_tags() -> None:
    assert titlegen.clean_title("<output>会議の議事録</output>") == "会議の議事録"


def test_clean_title_takes_first_line_and_trims_quotes() -> None:
    assert titlegen.clean_title('"東京の天気"\n2行目は無視') == "東京の天気"


def test_clean_title_returns_empty_on_japanese_refusal() -> None:
    assert titlegen.clean_title("申し訳ありませんが、お答えできません。") == ""


def test_clean_title_returns_empty_on_english_refusal() -> None:
    assert titlegen.clean_title("I'm sorry, but I can't help with that.") == ""


def test_clean_title_returns_empty_on_blank() -> None:
    assert titlegen.clean_title("   ") == ""


def test_clean_title_keeps_normal_title() -> None:
    assert titlegen.clean_title("補助金の申請方法について") == "補助金の申請方法について"


def test_fallback_extracts_user_messages_block() -> None:
    prompt = "<user-messages>\n確定申告のやり方を教えて\n</user-messages>"
    assert titlegen.fallback_title_from_prompt(prompt) == "確定申告のやり方を教えて"


def test_fallback_truncates_to_30_chars() -> None:
    long = "あ" * 60
    prompt = f"<user-messages>\n{long}\n</user-messages>"
    assert titlegen.fallback_title_from_prompt(prompt) == "あ" * 30


def test_fallback_empty_prompt_returns_placeholder() -> None:
    assert titlegen.fallback_title_from_prompt("") == "無題"


def test_fallback_empty_user_messages_returns_placeholder() -> None:
    prompt = "<user-messages>\n\n</user-messages>"
    assert titlegen.fallback_title_from_prompt(prompt) == "無題"


def test_fallback_supports_legacy_conversation_json() -> None:
    messages = [
        {"role": "user", "content": "経費精算の締め日はいつ？"},
        {"role": "assistant", "content": "月末です。"},
    ]
    prompt = f"<conversation>{json.dumps(messages, ensure_ascii=False)}</conversation>"
    assert titlegen.fallback_title_from_prompt(prompt) == "経費精算の締め日はいつ？"
