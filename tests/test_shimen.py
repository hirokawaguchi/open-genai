from app.shimen import clean_rewrite


def test_clean_rewrite_strips_quotes() -> None:
    assert clean_rewrite("  「短い見出し」  ") == "短い見出し"
    assert clean_rewrite('"Hello"') == "Hello"
    assert clean_rewrite("本文のまま") == "本文のまま"


def test_clean_rewrite_empty() -> None:
    assert clean_rewrite("   ") == ""
    assert clean_rewrite("") == ""
