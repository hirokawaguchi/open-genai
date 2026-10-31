"""思考タグを利用者向け本文から除く。"""

from app.think_text import ThinkTagSplitter, strip_think_tags


def test_strip_think_block_keeps_the_answer() -> None:
    text = "<think>\n英語の下書き。\n</think>\n\n## 大分市のデジタル政策\n本文"
    assert strip_think_tags(text) == "## 大分市のデジタル政策\n本文"


def test_strip_thinking_tag_and_multiple_blocks() -> None:
    text = "<thinking>a</thinking>前<think>b</think>後"
    assert strip_think_tags(text) == "前後"


def test_strip_unclosed_think_drops_the_tail() -> None:
    assert strip_think_tags("本文<think>まだ考えている") == "本文"


def test_plain_text_is_unchanged() -> None:
    text = "  そのまま  "
    assert strip_think_tags(text) == text


def test_splitter_hides_think_split_across_chunks() -> None:
    splitter = ThinkTagSplitter()
    assert splitter.feed("hello <thi") == "hello "
    assert splitter.feed("nk>\nsecret</thi") == ""
    assert splitter.feed("nk>\n## 回答") == "\n## 回答"
    assert splitter.finish() == ""
