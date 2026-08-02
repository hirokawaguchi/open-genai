"""チャット添付マップリデュースの単体テスト。

LLM 呼び出しは注入するため、実 API なしで chunk / plan / assemble / summarize を検証する。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app import doc_mapreduce as dm


def _fake_llm(plan_response: str):
    """system プロンプトで読み計画/要約を判別する擬似 LLM を返す。"""
    calls: dict[str, int] = {"plan": 0, "summary": 0}

    async def _llm(messages):
        sys = messages[0].get("content", "") if messages else ""
        if "読み計画" in sys:
            calls["plan"] += 1
            return plan_response
        calls["summary"] += 1
        return f"要約{calls['summary']}"

    return _llm, calls


def test_small_doc_is_inlined_without_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dm, "CHAT_DOC_INLINE_CHARS", 100)
    llm, calls = _fake_llm("{}")
    ctx, note = asyncio.run(dm.condense_document("a.txt", "短い本文", "質問", llm))
    assert ctx == "短い本文"
    assert note == ""
    assert calls == {"plan": 0, "summary": 0}


def test_chunk_document_fixed_split() -> None:
    chunks = dm.chunk_document("あ" * 25, size=10)
    assert len(chunks) == 3
    assert "".join(c["text"] for c in chunks) == "あ" * 25
    assert [c["id"] for c in chunks] == [0, 1, 2]


def test_chunk_document_falls_back_when_headings_explode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """目次のように見出しが大量ヒットしたら件数上限内の固定長分割へフォールバックする。"""
    monkeypatch.setattr(dm, "CHAT_DOC_MAX_CHUNKS", 5)
    monkeypatch.setattr(dm, "CHAT_DOC_CHUNK_SIZE", 20)
    # 【…】行が見出し扱いされ、細切れになる入力
    body = "\n".join(f"【見出し{i}】\n本文{i}です" for i in range(30))
    chunks = dm.chunk_document(body)
    assert len(chunks) <= 5
    assert len(chunks) >= 1


def test_summarize_full_samples_when_too_many_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dm, "CHAT_DOC_INLINE_CHARS", 20)
    monkeypatch.setattr(dm, "CHAT_DOC_CHUNK_SIZE", 10)
    monkeypatch.setattr(dm, "CHAT_DOC_SUMMARY_BATCH", 2)
    monkeypatch.setattr(dm, "CHAT_DOC_MAX_SUMMARY_CHUNKS", 4)
    body = "あ" * 100  # 10 チャンク → サンプル 4 → バッチ2で 2 回要約
    plan = json.dumps({"coverage": "full", "chunk_ids": []})
    llm, calls = _fake_llm(plan)
    ctx, note = asyncio.run(dm.condense_document("big.txt", body, "全体要約", llm))
    assert calls["plan"] == 1
    assert calls["summary"] == 2
    assert "代表 4 区間" in note
    assert "区間要約" in ctx


def test_parse_plan_partial_selects_ids() -> None:
    coverage, ids = dm.parse_plan('{"coverage":"partial","chunk_ids":[0,2,9]}', total=5)
    assert coverage == "partial"
    # total=5 の範囲外(9)は除外
    assert ids == [0, 2]


def test_parse_plan_falls_back_to_full_on_garbage() -> None:
    coverage, ids = dm.parse_plan("これはJSONではない", total=3)
    assert coverage == "full"
    assert ids == [0, 1, 2]


def test_parse_plan_partial_without_ids_becomes_full() -> None:
    coverage, ids = dm.parse_plan('{"coverage":"partial","chunk_ids":[]}', total=4)
    assert coverage == "full"
    assert ids == [0, 1, 2, 3]


def test_large_doc_partial_assembles_selected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dm, "CHAT_DOC_INLINE_CHARS", 20)
    monkeypatch.setattr(dm, "CHAT_DOC_CHUNK_SIZE", 10)
    body = "".join(f"chunk{i}____" for i in range(6))  # 60 文字 → 6 チャンク
    plan = json.dumps({"coverage": "partial", "chunk_ids": [1, 3]})
    llm, calls = _fake_llm(plan)
    ctx, note = asyncio.run(dm.condense_document("big.txt", body, "質問", llm))
    assert "chunk1" in ctx
    assert "chunk3" in ctx
    assert "chunk0" not in ctx
    assert calls["plan"] == 1
    assert calls["summary"] == 0
    assert "2 区間を抜粋" in note


def test_large_doc_full_summarizes_all_batches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(dm, "CHAT_DOC_INLINE_CHARS", 20)
    monkeypatch.setattr(dm, "CHAT_DOC_CHUNK_SIZE", 10)
    monkeypatch.setattr(dm, "CHAT_DOC_SUMMARY_BATCH", 2)
    body = "あ" * 60  # 6 チャンク → バッチ2で 3 回要約
    plan = json.dumps({"coverage": "full", "chunk_ids": []})
    llm, calls = _fake_llm(plan)
    ctx, note = asyncio.run(dm.condense_document("big.txt", body, "全体要約", llm))
    assert calls["plan"] == 1
    assert calls["summary"] == 3
    assert "区間要約" in ctx
    assert "全 6 区間を要約" in note


def test_full_summary_survives_llm_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """要約 LLM が落ちても原文断片で代替し、黙って欠落させない。"""
    monkeypatch.setattr(dm, "CHAT_DOC_INLINE_CHARS", 20)
    monkeypatch.setattr(dm, "CHAT_DOC_CHUNK_SIZE", 10)

    async def _llm(messages):
        sys = messages[0].get("content", "") if messages else ""
        if "読み計画" in sys:
            return json.dumps({"coverage": "full", "chunk_ids": []})
        raise RuntimeError("boom")

    ctx, note = asyncio.run(dm.condense_document("big.txt", "い" * 60, "質問", _llm))
    assert ctx and ctx != "(要約結果なし)"
    assert "要約" in note


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
