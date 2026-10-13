from __future__ import annotations

from conftest import load_service_module


def test_repetition_detects_hai_loop() -> None:
    llm = load_service_module("backend/app/llm.py")
    assert llm._repetition_detected("前文です。" + "はい、" * 40) is True


def test_repetition_ignores_normal_backchannel() -> None:
    llm = load_service_module("backend/app/llm.py")
    text = "はい、承知しました。次に資料の2ページを確認します。はい、その点は前回も出ました。"
    assert llm._repetition_detected(text) is False
    assert llm._repetition_detected("はい、" * 5) is False


def test_repetition_ignores_punctuation_only() -> None:
    llm = load_service_module("backend/app/llm.py")
    assert llm._repetition_detected("、" * 200) is False


def test_repetition_guard_trips_across_chunks() -> None:
    llm = load_service_module("backend/app/llm.py")
    guard = llm._RepetitionGuard()
    assert guard.push("文字起こしを修正します。") is False
    tripped = False
    for _ in range(50):
        if guard.push("はい、"):
            tripped = True
            break
    assert tripped is True
