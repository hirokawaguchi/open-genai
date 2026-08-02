"""チャット添付の「その場マップリデュース」。

大きな添付を 1 回の LLM コンテキストに丸ごと載せる（＝30k で黙って切る）代わりに、
チャンク化 → 読み計画 → 抜粋/バッチ要約で圧縮した作業コンテキストを作る。

MultiFileGenerator（Dify DSL）と同じ意味の処理（chunk / plan / assemble / summarize）を、
backend の自前 LLM 上で行う。Dify の「90k×3・Iteration 15」制約には縛られない。
索引を作らないため、ナレッジ登録（構造化/ベクトル hybrid）とは別物（1 リクエスト内で完結）。

LLM 呼び出しは注入（`llm` 引数）にして、モジュール単体でテストできるようにしている。
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Awaitable, Callable

# しきい値以下は従来どおり全文をそのまま注入する（MultiFileGenerator の MAX_INLINE に合わせる）。
CHAT_DOC_INLINE_CHARS = int(os.environ.get("CHAT_DOC_INLINE_CHARS", "60000"))
# チャンク長（MultiFileGenerator の CHUNK_SIZE 相当）。
CHAT_DOC_CHUNK_SIZE = int(os.environ.get("CHAT_DOC_CHUNK_SIZE", "6000"))
# full 要約時のバッチ件数（自前 LLM なので 15 固定サンプルに縛られない）。
CHAT_DOC_SUMMARY_BATCH = int(os.environ.get("CHAT_DOC_SUMMARY_BATCH", "8"))
# partial 抜粋で選ぶチャンク数の上限。
CHAT_DOC_MAX_SELECT = int(os.environ.get("CHAT_DOC_MAX_SELECT", "12"))
# 作業コンテキストの最大文字数（最終プロンプトの肥大を防ぐ）。
CHAT_DOC_WORKING_MAX = int(os.environ.get("CHAT_DOC_WORKING_MAX", "60000"))
# 見出し分割が目次行などで細切れになったときの上限。超えたら固定長分割へフォールバック。
CHAT_DOC_MAX_CHUNKS = int(os.environ.get("CHAT_DOC_MAX_CHUNKS", "60"))
# full 要約時に実際に LLM へ渡すチャンク数の上限（均等サンプル）。
CHAT_DOC_MAX_SUMMARY_CHUNKS = int(os.environ.get("CHAT_DOC_MAX_SUMMARY_CHUNKS", "24"))

_OUTLINE_PREVIEW = 80
_OUTLINE_MAX_CHARS = 8000

# モデル束縛済みの LLM 呼び出し: messages -> 応答テキスト。
LLMCall = Callable[[list[dict[str, Any]]], Awaitable[str]]

_HEADING_RE = re.compile(
    r"^(#{1,6}\s+\S+|第[0-9０-９一二三四五六七八九十百千]+[章節編条項]|■\s*\S+|【[^】]+】)"
)


def _split_fixed(text: str, size: int) -> list[tuple[str, str]]:
    text = text or ""
    if not text.strip():
        return [("(空)", "")]
    parts: list[tuple[str, str]] = []
    i = 0
    n = 1
    while i < len(text):
        parts.append((f"区間{n}", text[i : i + size]))
        i += size
        n += 1
    return parts


def _chunks_from_sections(
    sections: list[tuple[str, str]], size: int
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    cid = 0
    for title, body in sections:
        if len(body) <= int(size * 1.5):
            chunks.append({"id": cid, "title": title, "text": body})
            cid += 1
        else:
            for sub_title, part in _split_fixed(body, size):
                chunks.append(
                    {"id": cid, "title": f"{title}/{sub_title}", "text": part}
                )
                cid += 1
    return chunks


def _sample_chunks(
    chunks: list[dict[str, Any]], limit: int
) -> list[dict[str, Any]]:
    """順序を保ったまま最大 limit 件へ均等サンプルし、id を振り直す。"""
    n = len(chunks)
    if n <= limit or limit <= 0:
        return chunks
    if limit == 1:
        idxs = [0]
    else:
        idxs = sorted({int(i * (n - 1) / (limit - 1)) for i in range(limit)})
    sampled = [chunks[i] for i in idxs]
    for i, c in enumerate(sampled):
        c = dict(c)
        c["id"] = i
        sampled[i] = c
    return sampled


def chunk_document(
    text: str, size: int | None = None
) -> list[dict[str, Any]]:
    """見出し優先・長すぎる節は固定長で分割してチャンク列を返す。

    PDF 目次のように見出し正規表現へ大量ヒットすると数千チャンクになり得るため、
    CHAT_DOC_MAX_CHUNKS を超える場合は固定長分割へフォールバックする。
    """
    size = CHAT_DOC_CHUNK_SIZE if size is None else size
    lines = (text or "").split("\n")
    sections: list[tuple[str, str]] = []
    current_title = "(冒頭)"
    current: list[str] = []
    for line in lines:
        if _HEADING_RE.match(line.strip()):
            if current:
                body = "\n".join(current).strip()
                if body:
                    sections.append((current_title, body))
            current_title = line.strip()[:80]
            current = [line]
        else:
            current.append(line)
    if current:
        body = "\n".join(current).strip()
        if body:
            sections.append((current_title, body))
    if len(sections) <= 1 and len(text or "") > size:
        sections = _split_fixed(text, size)
    if not sections:
        sections = [("(空)", (text or "").strip() or "(空)")]

    chunks = _chunks_from_sections(sections, size)
    # 目次行の誤分割などで細切れになったら固定長へ。それでも多いときは幅を広げて件数を抑える。
    if len(chunks) > CHAT_DOC_MAX_CHUNKS:
        adaptive = max(
            size,
            (len(text or "") + CHAT_DOC_MAX_CHUNKS - 1) // CHAT_DOC_MAX_CHUNKS,
        )
        chunks = _chunks_from_sections(_split_fixed(text, adaptive), adaptive)
    return chunks


def build_outline(chunks: list[dict[str, Any]]) -> str:
    """読み計画 LLM に渡す短縮アウトライン（本文は載せない）。"""
    lines: list[str] = []
    for c in chunks:
        preview = (c.get("text") or "").replace("\n", " ").replace("\r", " ")
        lines.append(f"- [{c['id']}] {c.get('title', '')}: {preview[:_OUTLINE_PREVIEW]}")
        if sum(len(x) for x in lines) >= _OUTLINE_MAX_CHARS:
            lines.append("...（以降のアウトラインは省略）")
            break
    return "\n".join(lines) if lines else "(空)"


def _strip_code_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        body = s.split("\n")
        if body and body[0].startswith("```"):
            body = body[1:]
        if body and body[-1].strip() == "```":
            body = body[:-1]
        s = "\n".join(body).strip()
    return s


def parse_plan(text: str, total: int) -> tuple[str, list[int]]:
    """読み計画 LLM の出力を `(coverage, chunk_ids)` に正規化する。

    パースできない場合は full（全区間を要約＝取りこぼしを作らない）にフォールバック。
    """
    s = _strip_code_fence(text)
    try:
        m = re.search(r"\{[\s\S]*\}", s)
        obj = json.loads(m.group(0) if m else s)
    except Exception:  # noqa: BLE001
        return "full", list(range(total))

    cov = str(obj.get("coverage") or "").strip().lower()
    coverage = "full" if cov == "full" else "partial"
    ids: list[int] = []
    raw_ids = obj.get("chunk_ids") or []
    if isinstance(raw_ids, list):
        for x in raw_ids:
            try:
                v = int(x)
            except (TypeError, ValueError):
                continue
            if 0 <= v < total and v not in ids:
                ids.append(v)
    if coverage == "partial" and not ids:
        # 選定できなければ全区間要約に倒す（黙って先頭だけ、にしない）
        return "full", list(range(total))
    if coverage == "partial":
        ids = ids[:CHAT_DOC_MAX_SELECT]
    else:
        ids = list(range(total))
    return coverage, ids


def assemble_selected(
    chunks: list[dict[str, Any]],
    ids: list[int],
    cap: int | None = None,
) -> str:
    cap = CHAT_DOC_WORKING_MAX if cap is None else cap
    by_id = {int(c["id"]): c for c in chunks}
    parts: list[str] = []
    size = 0
    for i in ids:
        c = by_id.get(int(i))
        if not c:
            continue
        block = f"### {c.get('title', '')}\n\n{(c.get('text') or '').strip()}"
        if size and size + len(block) + 5 > cap:
            break
        parts.append(block)
        size += len(block) + 5
    return "\n\n---\n\n".join(parts) if parts else "(選択チャンクなし)"


def _batches(items: list[Any], n: int) -> list[list[Any]]:
    n = max(1, n)
    return [items[i : i + n] for i in range(0, len(items), n)]


async def summarize_full(
    chunks: list[dict[str, Any]],
    question: str,
    llm: LLMCall,
    *,
    cap: int | None = None,
) -> str:
    """全チャンクをバッチ要約し、質問に関係する情報を落とさずまとめる。

    チャンク数が多すぎるときは均等サンプルしてから要約し、LLM 呼び出し爆発を防ぐ。
    """
    cap = CHAT_DOC_WORKING_MAX if cap is None else cap
    work = _sample_chunks(chunks, CHAT_DOC_MAX_SUMMARY_CHUNKS)
    summaries: list[str] = []
    for batch in _batches(work, CHAT_DOC_SUMMARY_BATCH):
        joined = "\n\n".join(
            f"[{c['id']} {c.get('title', '')}]\n{(c.get('text') or '').strip()}"
            for c in batch
        )
        messages = [
            {
                "role": "system",
                "text": (
                    "あなたは資料の要約者です。後続の質問に答えるための素材を作ります。"
                    "質問に関係し得る事実・数値・固有名詞・条件を落とさず、簡潔にまとめてください。"
                    "推測や創作はしないでください。"
                ),
            },
            {
                "role": "user",
                "text": (
                    f"## 質問\n\n{(question or '(指定なし)').strip()}\n\n"
                    f"## 要約対象（原文の一部）\n\n{joined}"
                ),
            },
        ]
        # system/user は OpenAI 形式へ寄せる（llm 側が content を期待）
        oai = [{"role": mm["role"], "content": mm["text"]} for mm in messages]
        try:
            s = (await llm(oai)).strip()
        except Exception:  # noqa: BLE001 - 要約失敗時は原文冒頭で代替（欠落させない）
            s = joined[
                : cap // max(1, len(_batches(work, CHAT_DOC_SUMMARY_BATCH)))
            ]
        if s:
            summaries.append(s)
    merged = "\n\n---\n\n".join(
        f"### 区間要約 {i + 1}\n\n{s}" for i, s in enumerate(summaries)
    )
    return merged[:cap] if merged else "(要約結果なし)"


async def _plan_reading(
    question: str, outline: str, total: int, llm: LLMCall
) -> tuple[str, list[int]]:
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは大規模資料の読み計画プランナーです。本文は見えません。"
                "アウトラインだけを見て、質問に答えるのに必要な範囲を決めます。\n"
                "- 特定箇所で足りる → coverage=partial と必要な chunk_ids（最大"
                f"{CHAT_DOC_MAX_SELECT}）\n"
                "- 全体把握・全体要約が必要 → coverage=full（chunk_ids は空でよい）\n"
                "出力は JSON のみ。解説やコードフェンスは禁止。"
                'Schema: {"coverage":"partial|full","chunk_ids":[0]}'
            ),
        },
        {
            "role": "user",
            "content": (
                f"## 質問\n\n{(question or '(指定なし)').strip()}\n\n"
                f"## アウトライン（全 {total} 区間）\n\n{outline}"
            ),
        },
    ]
    try:
        raw = await llm(messages)
    except Exception:  # noqa: BLE001
        return "full", list(range(total))
    return parse_plan(raw, total)


async def condense_document(
    name: str,
    text: str,
    question: str,
    llm: LLMCall,
) -> tuple[str, str]:
    """添付 1 件を作業コンテキストへ圧縮する。

    戻り値 `(working_context, note)`:
    - 小さい添付はそのまま全文（note は空）
    - 大きい添付は抜粋 or 要約に圧縮し、note に「どう参照したか」を記す
    """
    text = (text or "").strip()
    if len(text) <= CHAT_DOC_INLINE_CHARS:
        return text, ""

    chunks = chunk_document(text)
    total = len(chunks)
    outline = build_outline(chunks)
    coverage, ids = await _plan_reading(question, outline, total, llm)

    if coverage == "full":
        sampled_n = min(total, CHAT_DOC_MAX_SUMMARY_CHUNKS)
        ctx = await summarize_full(chunks, question, llm)
        if sampled_n < total:
            note = (
                f"添付「{name}」は大きいため全 {total} 区間のうち"
                f"代表 {sampled_n} 区間を要約して参照しました"
            )
        else:
            note = f"添付「{name}」は大きいため全 {total} 区間を要約して参照しました"
    else:
        ctx = assemble_selected(chunks, ids)
        note = (
            f"添付「{name}」は大きいため関連 {len(ids)} 区間を抜粋して参照しました"
            f"（全 {total} 区間）"
        )
    return ctx, note
