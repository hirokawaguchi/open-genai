"""分野定義と LLM メッセージ組み立てのテスト。"""

from app import excel, sections


def test_four_sections_defined_with_expected_cells():
    keys = [s.key for s in sections.SECTIONS]
    assert keys == ["background", "business", "actualsystem", "goal"]
    write_cells = {s.key: s.write_cell for s in sections.SECTIONS}
    assert write_cells == {
        "background": "B10",
        "business": "B14",
        "actualsystem": "B19",
        "goal": "B23",
    }
    # 書き込みセルはすべて Excel 側の対象セルに含まれる
    for s in sections.SECTIONS:
        assert s.write_cell in excel.CONTENT_CELLS


def test_build_messages_injects_only_filled_context():
    section = sections.get_section("actualsystem")
    assert section is not None
    current = {"B10": "背景あり", "B14": "", "B19": "現行あり", "B23": ""}
    msgs = sections.build_llm_messages(section, current, [], extra_user="こんにちは")

    assert msgs[0]["role"] == "system"
    assert msgs[1]["content"] == section.intro
    # 空欄 B14 は注入されず、記入済み B10/B19 のみ注入される
    injected = [m["content"] for m in msgs if m["role"] == "user"]
    assert any("背景あり" in c for c in injected)
    assert any("現行あり" in c for c in injected)
    assert not any("B14" in c for c in injected)
    # 末尾は追加ユーザー発話
    assert msgs[-1] == {"role": "user", "content": "こんにちは"}


def test_system_prompt_enforces_japanese_and_no_meta():
    section = sections.get_section("background")
    assert section is not None
    msgs = sections.build_llm_messages(section, {"B10": ""}, [])
    system = msgs[0]
    assert system["role"] == "system"
    # 日本語のみ・メタ発言禁止の厳守事項が付与される
    assert "日本語のみ" in system["content"]
    assert "メタ的な発言は禁止" in system["content"]
    # 元の分野プロンプトも保持
    assert "ブレーンストーミング" in system["content"]


def test_no_trigger_word_in_system_prompts():
    # トリガーワードは廃止。対話用システムプロンプトに書式トリガーを残さない。
    for s in sections.SECTIONS:
        assert "まとめて" not in s.system_prompt
        assert "「書き出し」を依頼されたら" not in s.system_prompt


def test_each_section_has_finalize_prompt():
    for s in sections.SECTIONS:
        assert s.finalize_prompt
        # 整形指示側にタイトルと本文限定の指示が含まれる
        assert "本文" in s.finalize_prompt


def test_build_messages_appends_history_in_order():
    section = sections.get_section("background")
    assert section is not None
    history = [
        {"role": "user", "content": "u1"},
        {"role": "assistant", "content": "a1"},
    ]
    msgs = sections.build_llm_messages(section, {"B10": ""}, history)
    tail = [(m["role"], m["content"]) for m in msgs[-2:]]
    assert tail == [("user", "u1"), ("assistant", "a1")]


def test_public_sections_shape():
    pub = sections.public_sections()
    assert len(pub) == 4
    first = pub[0]
    assert {"key", "title", "item_no", "write_cell", "description", "chat_placeholder"} <= set(
        first.keys()
    )
