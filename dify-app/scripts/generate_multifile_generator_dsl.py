#!/usr/bin/env python3
"""Generate MultiFileGenerator.yml with large-document adaptive flow."""

from __future__ import annotations

from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "dsl" / "MultiFileGenerator.yml"

PREPARE_CODE = r'''
import json
import re

MAX_INLINE = 60000
CHUNK_SIZE = 6000
PART_SIZE = 90000
OUTLINE_MAX_CHARS = 8000
OUTLINE_MAX_ITEMS = 80
OUTLINE_PREVIEW = 60
HEADING_RE = re.compile(
    r"^(#{1,6}\s+\S+|第[0-9０-９一二三四五六七八九十百千]+[章節編条項]|■\s*\S+|【[^】]+】)"
)


def split_fixed(text: str, size: int = CHUNK_SIZE):
    text = text or ""
    if not text.strip():
        return [("(空)", "")]
    parts = []
    i = 0
    n = 1
    while i < len(text):
        parts.append((f"区間{n}", text[i : i + size]))
        i += size
        n += 1
    return parts


def split_by_headings(text: str):
    lines = (text or "").split("\n")
    sections = []
    current_title = "(冒頭)"
    current = []
    for line in lines:
        if HEADING_RE.match(line.strip()):
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
    return sections


def chunk_body(body: str):
    sections = split_by_headings(body)
    if len(sections) <= 1 and len(body or "") > CHUNK_SIZE:
        sections = split_fixed(body)
    if not sections:
        sections = [("(空)", "(空のファイル)")]
    out = []
    for title, text in sections:
        if len(text) <= int(CHUNK_SIZE * 1.5):
            out.append((title, text))
        else:
            for t, p in split_fixed(text):
                out.append((f"{title}/{t}", p))
    return out


def build_outline(file_chunks):
    lines = []
    items = 0
    for label, pairs in file_chunks:
        lines.append(f"## {label}")
        for cid, title, text in pairs:
            if items >= OUTLINE_MAX_ITEMS:
                total = sum(len(pairs) for _, pairs in file_chunks)
                lines.append(f"...他 {max(total - items, 0)} チャンク略")
                s = "\n".join(lines)
                return s[:OUTLINE_MAX_CHARS]
            preview = (text or "").replace("\n", " ").replace("\r", " ")[:OUTLINE_PREVIEW]
            lines.append(f"- [{cid}] {title}: {preview}")
            items += 1
            s = "\n".join(lines)
            if len(s) >= OUTLINE_MAX_CHARS:
                return s[:OUTLINE_MAX_CHARS]
    return "\n".join(lines) if lines else "(入力ファイルなし)"


def split_parts(full: str):
    full = full or ""
    return (
        full[0:PART_SIZE],
        full[PART_SIZE : PART_SIZE * 2],
        full[PART_SIZE * 2 : PART_SIZE * 3],
    )


def main(texts, prompt: str, output_filename: str, output_format: str) -> dict:
    if texts is None:
        texts = []
    if isinstance(texts, str):
        texts = [texts]
    joined_parts = []
    file_chunks = []
    meta = []
    cid = 0
    for i, t in enumerate(texts):
        body = (t or "").strip()
        label = f"ファイル{i + 1}"
        joined_parts.append(f"### {label}\n\n{body if body else '(空のファイル)'}")
        pairs = []
        for title, text in chunk_body(body):
            pairs.append((cid, title, text))
            meta.append(
                {
                    "id": cid,
                    "file_index": i + 1,
                    "file_label": label,
                    "title": title,
                    "start": 0,
                    "length": len(text or ""),
                }
            )
            cid += 1
        file_chunks.append((label, pairs))
    full = "\n\n---\n\n".join(joined_parts) if joined_parts else "(入力ファイルなし)"
    char_count = len(full)
    is_large = char_count > MAX_INLINE
    outline = build_outline(file_chunks)
    p1, p2, p3 = split_parts(full)
    # 小容量時のみ全文を context_small に載せる（Dify出力上限対策）
    context_small = full if not is_large else ""
    # Dify のコードノード出力上限対策で本文は 3 パート(=PART_SIZE*3)までしか
    # 後段へ渡せない。超過分は黙って欠落するため、ここで可視化する。
    part_capacity = PART_SIZE * 3
    kept_chars = min(char_count, part_capacity)
    truncated = char_count > part_capacity
    notes = []
    if is_large:
        notes.append(
            f"資料が大きいため、関連区間の抽出または代表区間の要約に基づいて"
            f"生成しています（全 {cid} 区間）"
        )
    if truncated:
        notes.append(
            f"処理上限を超えたため先頭 {kept_chars} 文字のみを対象にしました"
            f"（元 {char_count} 文字）。対象範囲を絞るか分割してお試しください"
        )
    coverage_note = ("／".join(notes) + "。") if notes else ""
    fmt = (output_format or "markdown").strip().lower() or "markdown"
    if fmt not in ("markdown", "html", "text", "json", "docx", "pptx"):
        fmt = "markdown"
    name = (output_filename or "").strip() or "generated"
    return {
        "context_small": context_small,
        "text_part1": p1,
        "text_part2": p2,
        "text_part3": p3,
        "outline": outline,
        "chunks_meta_json": json.dumps(meta, ensure_ascii=False)[:90000],
        "char_count": char_count,
        "kept_chars": kept_chars,
        "truncated": "true" if truncated else "false",
        "coverage_note": coverage_note,
        "chunk_count": cid,
        "is_large": "true" if is_large else "false",
        "prompt": (prompt or "").strip(),
        "filename": name,
        "output_format": fmt,
        "file_count": len(texts),
    }
'''.strip("\n")

SEARCH_PARSE_CODE = r'''
import json
import re

def main(text: str, context_small: str) -> dict:
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    need = "false"
    query = ""
    try:
        m = re.search(r"\{[\s\S]*\}", s)
        obj = json.loads(m.group(0) if m else s)
        raw = obj.get("need_search")
        need = "true" if raw in (True, "true", "True", 1, "1") else "false"
        q = obj.get("search_query")
        query = "" if q is None else str(q).strip()
    except Exception:
        need = "false"
        query = ""
    if need == "true" and not query:
        need = "false"
    return {
        "need_search": need,
        "search_query": query,
        "working_context": (context_small or "").strip(),
    }
'''.strip("\n")

PLAN_PARSE_CODE = r'''
import json
import re

def main(text: str, chunk_count) -> dict:
    s = (text or "").strip()
    if s.startswith("```"):
        lines = s.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        s = "\n".join(lines).strip()
    coverage = "partial"
    chunk_ids = []
    need = "false"
    query = ""
    try:
        m = re.search(r"\{[\s\S]*\}", s)
        obj = json.loads(m.group(0) if m else s)
        cov = str(obj.get("coverage") or "partial").strip().lower()
        coverage = "full" if cov == "full" else "partial"
        ids = obj.get("chunk_ids") or []
        if isinstance(ids, list):
            for x in ids:
                try:
                    chunk_ids.append(int(x))
                except Exception:
                    pass
        raw = obj.get("need_search")
        need = "true" if raw in (True, "true", "True", 1, "1") else "false"
        q = obj.get("search_query")
        query = "" if q is None else str(q).strip()
    except Exception:
        coverage = "partial"
        chunk_ids = []
        need = "false"
        query = ""
    if need == "true" and not query:
        need = "false"
    try:
        total = int(chunk_count or 0)
    except Exception:
        total = 0
    if coverage == "partial" and not chunk_ids and total > 0:
        chunk_ids = list(range(min(12, total)))
    if coverage == "full":
        chunk_ids = list(range(total)) if total > 0 else []
    chunk_ids = chunk_ids[:12] if coverage == "partial" else chunk_ids
    return {
        "coverage": coverage,
        "chunk_ids_json": json.dumps(chunk_ids, ensure_ascii=False),
        "need_search": need,
        "search_query": query,
    }
'''.strip("\n")

CHUNK_HELPER = r'''
import re

CHUNK_SIZE = 6000
HEADING_RE = re.compile(
    r"^(#{1,6}\s+\S+|第[0-9０-９一二三四五六七八九十百千]+[章節編条項]|■\s*\S+|【[^】]+】)"
)

def _split_fixed(text, size=CHUNK_SIZE):
    text = text or ""
    if not text.strip():
        return [("(空)", "")]
    parts = []
    i = 0
    n = 1
    while i < len(text):
        parts.append((f"区間{n}", text[i:i+size]))
        i += size
        n += 1
    return parts

def _chunk_body(body):
    lines = (body or "").split("\n")
    sections = []
    current_title = "(冒頭)"
    current = []
    for line in lines:
        if HEADING_RE.match(line.strip()):
            if current:
                b = "\n".join(current).strip()
                if b:
                    sections.append((current_title, b))
            current_title = line.strip()[:80]
            current = [line]
        else:
            current.append(line)
    if current:
        b = "\n".join(current).strip()
        if b:
            sections.append((current_title, b))
    if len(sections) <= 1 and len(body or "") > CHUNK_SIZE:
        sections = _split_fixed(body)
    if not sections:
        sections = [("(空)", "(空のファイル)")]
    out = []
    for title, text in sections:
        if len(text) <= int(CHUNK_SIZE * 1.5):
            out.append((title, text))
        else:
            for t, p in _split_fixed(text):
                out.append((f"{title}/{t}", p))
    return out

def rebuild_chunks(text_part1, text_part2, text_part3):
    full = (text_part1 or "") + (text_part2 or "") + (text_part3 or "")
    # ファイル見出しで分割
    blocks = re.split(r"\n\n---\n\n", full) if full else []
    chunks = []
    cid = 0
    for bi, block in enumerate(blocks or [full]):
        m = re.match(r"### (ファイル\d+)\n\n([\s\S]*)", block or "")
        if m:
            label, body = m.group(1), m.group(2)
        else:
            label, body = f"ファイル{bi+1}", block or ""
        for title, text in _chunk_body(body):
            chunks.append({"id": cid, "file_label": label, "title": title, "text": text})
            cid += 1
    return chunks
'''

ASSEMBLE_CODE = (CHUNK_HELPER + r'''
import json

MAX_INLINE = 60000

def main(text_part1: str, text_part2: str, text_part3: str, chunk_ids_json: str, need_search: str, search_query: str) -> dict:
    chunks = rebuild_chunks(text_part1, text_part2, text_part3)
    try:
        ids = json.loads(chunk_ids_json or "[]")
    except Exception:
        ids = []
    by_id = {int(c["id"]): c for c in chunks}
    parts = []
    size = 0
    for i in ids:
        try:
            cid = int(i)
        except Exception:
            continue
        c = by_id.get(cid)
        if not c:
            continue
        block = f"### {c.get('file_label','')} / {c.get('title','')}\n\n{(c.get('text') or '').strip()}"
        if size and size + len(block) + 5 > MAX_INLINE:
            break
        parts.append(block)
        size += len(block) + 5
    ctx = "\n\n---\n\n".join(parts) if parts else "(選択チャンクなし)"
    return {
        "working_context": ctx[:90000],
        "need_search": need_search or "false",
        "search_query": search_query or "",
    }
''').strip("\n")

TO_ARRAY_CODE = (CHUNK_HELPER + r'''
MAX_CHUNKS_FOR_ITER = 15
MAX_CHUNK_CHARS = 5000

def main(text_part1: str, text_part2: str, text_part3: str, need_search: str, search_query: str) -> dict:
    chunks = rebuild_chunks(text_part1, text_part2, text_part3)
    if not chunks:
        return {
            "chunk_texts": ["(入力チャンクなし)"],
            "need_search": need_search or "false",
            "search_query": search_query or "",
        }
    # Iteration 出力上限対策: 均等サンプルで最大15チャンク
    n = len(chunks)
    if n <= MAX_CHUNKS_FOR_ITER:
        chosen = chunks
    else:
        idxs = sorted({int(i * (n - 1) / (MAX_CHUNKS_FOR_ITER - 1)) for i in range(MAX_CHUNKS_FOR_ITER)})
        chosen = [chunks[i] for i in idxs]
    texts = []
    for c in chosen:
        body = (c.get("text") or "").strip()[:MAX_CHUNK_CHARS]
        texts.append(f"[{c.get('file_label','')} / {c.get('title','')}]\n{body}")
    return {
        "chunk_texts": texts,
        "need_search": need_search or "false",
        "search_query": search_query or "",
    }
''').strip("\n")

MERGE_SUMMARIES_CODE = r'''
def main(summaries, need_search: str, search_query: str) -> dict:
    if summaries is None:
        summaries = []
    if isinstance(summaries, str):
        summaries = [summaries]
    parts = []
    for i, s in enumerate(summaries):
        body = (s or "").strip()
        if body:
            parts.append(f"### チャンク要約 {i + 1}\n\n{body}")
    ctx = "\n\n---\n\n".join(parts) if parts else "(要約結果なし)"
    return {
        "working_context": ctx,
        "need_search": need_search or "false",
        "search_query": search_query or "",
    }
'''.strip("\n")

SYNC_CODE = r'''
def main(working_context: str, need_search: str, search_query: str) -> dict:
    return {
        "working_context": (working_context or "").strip(),
        "need_search": need_search or "false",
        "search_query": search_query or "",
    }
'''.strip("\n")

ENRICH_CODE = r'''
def main(context: str, search_text: str, search_query: str) -> dict:
    ctx = (context or "").strip()
    hit = (search_text or "").strip()
    q = (search_query or "").strip()
    if hit:
        enriched = (
            f"{ctx}\n\n---\n\n## Web検索結果\n\n"
            f"クエリ: {q}\n\n{hit}"
        )
    else:
        enriched = ctx
    return {"enriched_context": enriched}
'''.strip("\n")

SKIP_CODE = r'''
def main(context: str) -> dict:
    return {"enriched_context": (context or "").strip()}
'''.strip("\n")

FINALIZE_CODE = r'''
def main(text: str, filename: str, output_format: str, coverage_note: str = "") -> dict:
    content = (text or "").strip()
    if content.startswith("```"):
        lines = content.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    fmt = (output_format or "markdown").strip().lower() or "markdown"
    ext_map = {
        "markdown": ".md",
        "html": ".html",
        "text": ".txt",
        "json": ".json",
        "docx": ".docx",
        "pptx": ".pptx",
    }
    mime_map = {
        "markdown": "text/markdown",
        "html": "text/html",
        "text": "text/plain",
        "json": "application/json",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    ext = ext_map.get(fmt, ".md")
    mime = mime_map.get(fmt, "text/markdown")

    name = (filename or "generated").strip() or "generated"
    if "." in name:
        stem = name.rsplit(".", 1)[0] or "generated"
    else:
        stem = name
    full_name = stem + ext

    # 注意文はファイル本文(content)を汚さない（json/html を壊さない）よう
    # 表示用テキスト(result_text)にのみ前置する。
    note = (coverage_note or "").strip()
    if note:
        result_text = f"> ※ {note}\n\n{content}"
    else:
        result_text = content
    return {
        "content": content,
        "result_text": result_text,
        "filename": full_name,
        "filename_stem": stem,
        "mime_type": mime,
        "output_format": fmt,
    }
'''.strip("\n")


def indent_block(code: str, spaces: int = 10) -> str:
    pad = " " * spaces
    return "\n".join(pad + line if line else "" for line in code.split("\n"))


def edge(eid, source, target, source_type, target_type, handle="source", z=0, **extra):
    data = {
        "isInIteration": extra.get("isInIteration", False),
        "isInLoop": False,
        "sourceType": source_type,
        "targetType": target_type,
    }
    if extra.get("iteration_id"):
        data["iteration_id"] = extra["iteration_id"]
        data["isInIteration"] = True
    lines = [
        "    - data:",
        f"        isInIteration: {'true' if data['isInIteration'] else 'false'}",
        "        isInLoop: false",
    ]
    if data.get("iteration_id"):
        lines.append(f"        iteration_id: '{data['iteration_id']}'")
    lines += [
        f"        sourceType: {source_type}",
        f"        targetType: {target_type}",
        f"      id: {eid}",
        f"      source: '{source}'" if not str(source).endswith("start") or str(source).startswith("175") else f"      source: {source}",
    ]
    # fix source formatting - Dify uses quoted numeric ids
    lines[-1] = f"      source: '{source}'"
    if str(source).endswith("start") and not str(source)[0].isdigit():
        pass
    # special case iteration start id without quotes issues - use as-is with quotes always
    lines += [
        f"      sourceHandle: '{handle}'" if handle != "source" else "      sourceHandle: source",
        f"      target: '{target}'",
        "      targetHandle: target",
        "      type: custom",
        f"      zIndex: {z}",
    ]
    if handle == "source":
        # rewrite sourceHandle line
        for i, ln in enumerate(lines):
            if ln.startswith("      sourceHandle:"):
                lines[i] = "      sourceHandle: source"
    # Fix source for iteration start: 1750000000026start
    if str(source).endswith("start"):
        for i, ln in enumerate(lines):
            if ln.startswith("      source:"):
                lines[i] = f"      source: {source}"
    return "\n".join(lines)


def main() -> None:
    # Rebuild edges more carefully with a helper
    def E(eid, src, tgt, st, tt, handle="source", z=0, iter_id=None):
        src_line = f"      source: {src}" if str(src).endswith("start") else f"      source: '{src}'"
        sh = "source" if handle == "source" else f"'{handle}'"
        block = f"""    - data:
        isInIteration: {'true' if iter_id else 'false'}
        isInLoop: false
"""
        if iter_id:
            block += f"        iteration_id: '{iter_id}'\n"
        block += f"""        sourceType: {st}
        targetType: {tt}
      id: {eid}
{src_line}
      sourceHandle: {sh}
      target: '{tgt}'
      targetHandle: target
      type: custom
      zIndex: {z}"""
        return block

    edges = [
        E("edge-start-extract", "1750000000001", "1750000000002", "start", "document-extractor"),
        E("edge-extract-prep", "1750000000002", "1750000000003", "document-extractor", "code"),
        E("edge-prep-size", "1750000000003", "1750000000020", "code", "if-else"),
        # small path
        E("edge-size-small", "1750000000020", "1750000000004", "if-else", "llm", handle="false"),
        E("edge-small-parse", "1750000000004", "1750000000005", "llm", "code"),
        E("edge-small-aggctx", "1750000000005", "1750000000029", "code", "variable-aggregator"),
        E("edge-small-aggneed", "1750000000005", "1750000000031", "code", "variable-aggregator"),
        E("edge-small-aggquery", "1750000000005", "1750000000032", "code", "variable-aggregator"),
        # large path
        E("edge-size-large", "1750000000020", "1750000000021", "if-else", "llm", handle="true"),
        E("edge-read-parse", "1750000000021", "1750000000022", "llm", "code"),
        E("edge-parse-cov", "1750000000022", "1750000000023", "code", "if-else"),
        E("edge-cov-partial", "1750000000023", "1750000000024", "if-else", "code", handle="false"),
        E("edge-partial-aggctx", "1750000000024", "1750000000029", "code", "variable-aggregator"),
        E("edge-partial-aggneed", "1750000000024", "1750000000031", "code", "variable-aggregator"),
        E("edge-partial-aggquery", "1750000000024", "1750000000032", "code", "variable-aggregator"),
        E("edge-cov-full", "1750000000023", "1750000000025", "if-else", "code", handle="full"),
        E("edge-full-iter", "1750000000025", "1750000000026", "code", "iteration"),
        E(
            "edge-iter-start-llm",
            "1750000000026start",
            "1750000000027",
            "iteration-start",
            "llm",
            z=1002,
            iter_id="1750000000026",
        ),
        E("edge-iter-merge", "1750000000026", "1750000000028", "iteration", "code"),
        E("edge-merge-aggctx", "1750000000028", "1750000000029", "code", "variable-aggregator"),
        E("edge-merge-aggneed", "1750000000028", "1750000000031", "code", "variable-aggregator"),
        E("edge-merge-aggquery", "1750000000028", "1750000000032", "code", "variable-aggregator"),
        # sync aggregators then search
        E("edge-ctx-sync", "1750000000029", "1750000000033", "variable-aggregator", "code"),
        E("edge-need-sync", "1750000000031", "1750000000033", "variable-aggregator", "code"),
        E("edge-query-sync", "1750000000032", "1750000000033", "variable-aggregator", "code"),
        E("edge-sync-searchif", "1750000000033", "1750000000006", "code", "if-else"),
        E("edge-if-tavily", "1750000000006", "1750000000007", "if-else", "tool", handle="true"),
        E("edge-tavily-enrich", "1750000000007", "1750000000008", "tool", "code"),
        E("edge-if-pass", "1750000000006", "1750000000009", "if-else", "code", handle="false"),
        E("edge-enrich-agg", "1750000000008", "1750000000010", "code", "variable-aggregator"),
        E("edge-pass-agg", "1750000000009", "1750000000010", "code", "variable-aggregator"),
        E("edge-agg-gen", "1750000000010", "1750000000011", "variable-aggregator", "llm"),
        E("edge-gen-finalize", "1750000000011", "1750000000012", "llm", "code"),
        E("edge-finalize-format", "1750000000012", "1750000000013", "code", "if-else"),
        E("edge-format-docx", "1750000000013", "1750000000014", "if-else", "tool", handle="case_docx"),
        E("edge-format-pptx", "1750000000013", "1750000000015", "if-else", "tool", handle="case_pptx"),
        E("edge-format-plain", "1750000000013", "1750000000016", "if-else", "tool", handle="false"),
        E("edge-docx-agg", "1750000000014", "1750000000017", "tool", "variable-aggregator"),
        E("edge-pptx-agg", "1750000000015", "1750000000017", "tool", "variable-aggregator"),
        E("edge-plain-agg", "1750000000016", "1750000000017", "tool", "variable-aggregator"),
        E("edge-agg-end", "1750000000017", "1750000000018", "variable-aggregator", "end"),
    ]

    # Problem: multiple edges from 0005/0024/0028 to three aggregators - Dify usually allows one outgoing edge per handle.
    # Need a pack node that goes to a single "route" code, OR use one aggregator with multiple inputs and single path through a dummy.
    # Better: each path ends in one code node that outputs all three fields, then ONE edge to a "fan-in" using three aggregators
    # fed as variables - but each source can only have one outgoing edge in many graph UIs.
    #
    # Fix: add a code/pass node is wrong. Use variable-aggregator that collects working_context only from three paths,
    # and have need_search/search_query also as outputs of those same three nodes - Dify variable-aggregator can list
    # multiple sources. Each source node can connect to multiple targets in Dify workflow graphs (multiple edges from same source).
    # DeepResearch has multiple edges from same LLM. So multiple outgoing edges OK.

    yaml_doc = f"""app:
  description: |
    複数ドキュメントと指示から新規ファイルを生成するワークフロー。
    必要に応じて Tavily で Web 検索し、markdown / html / text / json / docx / pptx で出力する。
    大きな入力は指示に応じて関連箇所の選択、またはチャンク要約で処理する（全文を最初の LLM に渡さない）。
    html は単一自己完結ファイル（デジタル庁デザインシステム風）。依存: File Tools, Markdown Exporter, Tavily, Azure OpenAI。Tavily は認証（APIキー）設定が必要。
  icon: 📎
  icon_background: '#E4FBCC'
  icon_type: emoji
  mode: workflow
  name: MultiFileGenerator
  use_icon_as_answer_icon: false
dependencies:
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: kurokobo/file_tools:0.0.2@8bde7b4d2c30cf22e8f6ce851572af244f7a5776addab94330b820dc2160726c
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: bowenliang123/md_exporter:3.6.9@3f027d63e80b44d5d5a9f706871afaef37905b8f8a89a2d152dc530211a8acb1
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: langgenius/tavily:0.1.2@aa7a8744b2ccf3a7aec818da6c504997a6319b29040e541bfc73b4fbaa9e98d9
- current_identifier: null
  type: marketplace
  value:
    marketplace_plugin_unique_identifier: langgenius/azure_openai:0.0.28@9b0339feb86b34393abd921e9cc906192fc46daad3a0f15c1d2a35ba20e8f704
kind: app
version: 0.6.0
workflow:
  conversation_variables: []
  environment_variables: []
  features:
    file_upload:
      allowed_file_extensions:
      - .TXT
      - .MD
      - .MARKDOWN
      - .PDF
      - .HTML
      - .XLSX
      - .XLS
      - .DOCX
      - .CSV
      - .EML
      - .MSG
      - .PPTX
      - .PPT
      - .XML
      - .EPUB
      allowed_file_types:
      - document
      allowed_file_upload_methods:
      - local_file
      - remote_url
      enabled: false
      fileUploadConfig:
        attachment_image_file_size_limit: 2
        audio_file_size_limit: 50
        batch_count_limit: 5
        file_size_limit: 15
        file_upload_limit: 50
        image_file_batch_limit: 10
        image_file_size_limit: 10
        single_chunk_attachment_limit: 10
        video_file_size_limit: 100
        workflow_file_upload_limit: 10
      image:
        enabled: false
        number_limits: 3
        transfer_methods:
        - local_file
        - remote_url
      number_limits: 10
    opening_statement: ''
    retriever_resource:
      enabled: false
    sensitive_word_avoidance:
      enabled: false
    speech_to_text:
      enabled: false
    suggested_questions: []
    suggested_questions_after_answer:
      enabled: false
    text_to_speech:
      enabled: false
      language: ''
      voice: ''
  graph:
    edges:
{chr(10).join(edges)}
    nodes:
    - data:
        desc: 複数ファイル・指示・出力形式を受け取る
        selected: false
        title: 開始
        type: start
        variables:
        - allowed_file_extensions: []
          allowed_file_types:
          - document
          allowed_file_upload_methods:
          - local_file
          - remote_url
          label: 入力ファイル（複数可）
          max_length: 10
          number_limits: 10
          options: []
          required: true
          type: file-list
          variable: input_files
        - label: 指示（プロンプト）
          max_length: 8000
          options: []
          required: true
          type: paragraph
          variable: prompt
        - default: generated
          label: 出力ファイル名（拡張子なし可）
          max_length: 200
          options: []
          required: false
          type: text-input
          variable: output_filename
        - default: markdown
          label: 出力形式
          options:
          - markdown
          - html
          - text
          - json
          - docx
          - pptx
          required: false
          type: select
          variable: output_format
      height: 220
      id: '1750000000001'
      position:
        x: 0
        y: 280
      positionAbsolute:
        x: 0
        y: 280
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: アップロード文書からテキストを抽出
        is_array_file: true
        selected: false
        title: 文書抽出
        type: document-extractor
        variable_selector:
        - '1750000000001'
        - input_files
      height: 90
      id: '1750000000002'
      position:
        x: 280
        y: 320
      positionAbsolute:
        x: 280
        y: 320
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(PREPARE_CODE)}
        code_language: python3
        desc: チャンク化・短縮アウトライン・本文分割・サイズ判定
        outputs:
          context_small:
            children: null
            type: string
          text_part1:
            children: null
            type: string
          text_part2:
            children: null
            type: string
          text_part3:
            children: null
            type: string
          outline:
            children: null
            type: string
          chunks_meta_json:
            children: null
            type: string
          char_count:
            children: null
            type: number
          kept_chars:
            children: null
            type: number
          truncated:
            children: null
            type: string
          coverage_note:
            children: null
            type: string
          chunk_count:
            children: null
            type: number
          is_large:
            children: null
            type: string
          prompt:
            children: null
            type: string
          filename:
            children: null
            type: string
          output_format:
            children: null
            type: string
          file_count:
            children: null
            type: number
        selected: false
        title: 文書準備
        type: code
        variables:
        - value_selector:
          - '1750000000002'
          - text
          variable: texts
        - value_selector:
          - '1750000000001'
          - prompt
          variable: prompt
        - value_selector:
          - '1750000000001'
          - output_filename
          variable: output_filename
        - value_selector:
          - '1750000000001'
          - output_format
          variable: output_format
      height: 54
      id: '1750000000003'
      position:
        x: 560
        y: 320
      positionAbsolute:
        x: 560
        y: 320
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        cases:
        - case_id: 'true'
          conditions:
          - comparison_operator: is
            id: cond-is-large
            value: 'true'
            varType: string
            variable_selector:
            - '1750000000003'
            - is_large
          id: 'true'
          logical_operator: and
        desc: 合算文字数が大きいとき読み計画へ
        selected: false
        title: 大容量？
        type: if-else
      height: 126
      id: '1750000000020'
      position:
        x: 840
        y: 300
      positionAbsolute:
        x: 840
        y: 300
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: 小容量時のみ。参照資料だけで足りるか判定
        model:
          completion_params:
            temperature: 0
          mode: chat
          name: gpt-4.1
          provider: langgenius/azure_openai/azure_openai
        prompt_template:
        - id: mfg-plan-sys
          role: system
          text: |
            あなたは調査プランナーです。ユーザー指示と参照資料を見て、Web検索が必要かどうかを判定してください。

            ## 判定基準
            - 参照資料だけで指示を十分に満たせる → need_search=false
            - 最新情報・外部事実・資料にない補足が必要 → need_search=true
            - 迷ったら need_search=false（不要な検索を避ける）

            ## 出力（厳守）
            - JSON オブジェクトのみ。解説・コードフェンス禁止
            - Schema: {{"need_search":true|false,"search_query":"string|null"}}
            - need_search=true のとき search_query は短い日本語検索クエリ
            - need_search=false のとき search_query は null
        - id: mfg-plan-user
          role: user
          text: |
            ## 指示

            {{{{#1750000000003.prompt#}}}}

            ## 参照資料（{{{{#1750000000003.file_count#}}}} 件）

            {{{{#1750000000003.context_small#}}}}
        selected: false
        title: 検索要否判定
        type: llm
        variables: []
        vision:
          enabled: false
      height: 90
      id: '1750000000004'
      position:
        x: 1120
        y: 120
      positionAbsolute:
        x: 1120
        y: 120
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(SEARCH_PARSE_CODE)}
        code_language: python3
        desc: 小容量パスの判定パースと working_context 設定
        outputs:
          need_search:
            children: null
            type: string
          search_query:
            children: null
            type: string
          working_context:
            children: null
            type: string
        selected: false
        title: 小容量パック
        type: code
        variables:
        - value_selector:
          - '1750000000004'
          - text
          variable: text
        - value_selector:
          - '1750000000003'
          - context_small
          variable: context_small
      height: 54
      id: '1750000000005'
      position:
        x: 1400
        y: 120
      positionAbsolute:
        x: 1400
        y: 120
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: 大容量時。アウトラインだけで読む範囲と検索要否を決める
        model:
          completion_params:
            temperature: 0
          mode: chat
          name: gpt-4.1
          provider: langgenius/azure_openai/azure_openai
        prompt_template:
        - id: mfg-readplan-sys
          role: system
          text: |
            あなたは大規模資料の読み計画プランナーです。本文は見えません。アウトラインだけを見て判断します。

            ## 方針
            - 指示が特定箇所で足りる → coverage=partial と必要な chunk_ids（最大12）
            - 全体要約・全体再構成など全体把握が必要 → coverage=full（chunk_ids は空でよい）
            - Web検索が必要なら need_search=true と短い search_query
            - 迷ったら need_search=false

            ## 出力（厳守）
            - JSON のみ。解説・コードフェンス禁止
            - Schema: {{"coverage":"partial"|"full","chunk_ids":[0],"need_search":true|false,"search_query":"string|null","rationale":"string"}}
        - id: mfg-readplan-user
          role: user
          text: |
            ## 指示

            {{{{#1750000000003.prompt#}}}}

            ## チャンク数

            {{{{#1750000000003.chunk_count#}}}}

            ## アウトライン

            {{{{#1750000000003.outline#}}}}
        selected: false
        title: 読み計画
        type: llm
        variables: []
        vision:
          enabled: false
      height: 90
      id: '1750000000021'
      position:
        x: 1120
        y: 420
      positionAbsolute:
        x: 1120
        y: 420
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(PLAN_PARSE_CODE)}
        code_language: python3
        desc: 読み計画 JSON をパース
        outputs:
          coverage:
            children: null
            type: string
          chunk_ids_json:
            children: null
            type: string
          need_search:
            children: null
            type: string
          search_query:
            children: null
            type: string
        selected: false
        title: 計画パース
        type: code
        variables:
        - value_selector:
          - '1750000000021'
          - text
          variable: text
        - value_selector:
          - '1750000000003'
          - chunk_count
          variable: chunk_count
      height: 54
      id: '1750000000022'
      position:
        x: 1400
        y: 420
      positionAbsolute:
        x: 1400
        y: 420
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        cases:
        - case_id: full
          conditions:
          - comparison_operator: is
            id: cond-coverage-full
            value: full
            varType: string
            variable_selector:
            - '1750000000022'
            - coverage
          id: full
          logical_operator: and
        desc: full ならチャンク要約、それ以外は選択組み立て
        selected: false
        title: カバレッジ
        type: if-else
      height: 126
      id: '1750000000023'
      position:
        x: 1680
        y: 400
      positionAbsolute:
        x: 1680
        y: 400
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(ASSEMBLE_CODE)}
        code_language: python3
        desc: 選択チャンクを結合して working_context を作る
        outputs:
          working_context:
            children: null
            type: string
          need_search:
            children: null
            type: string
          search_query:
            children: null
            type: string
        selected: false
        title: 選択チャンク組み立て
        type: code
        variables:
        - value_selector:
          - '1750000000003'
          - text_part1
          variable: text_part1
        - value_selector:
          - '1750000000003'
          - text_part2
          variable: text_part2
        - value_selector:
          - '1750000000003'
          - text_part3
          variable: text_part3
        - value_selector:
          - '1750000000022'
          - chunk_ids_json
          variable: chunk_ids_json
        - value_selector:
          - '1750000000022'
          - need_search
          variable: need_search
        - value_selector:
          - '1750000000022'
          - search_query
          variable: search_query
      height: 54
      id: '1750000000024'
      position:
        x: 1960
        y: 520
      positionAbsolute:
        x: 1960
        y: 520
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(TO_ARRAY_CODE)}
        code_language: python3
        desc: 全チャンクを Iteration 用配列にする
        outputs:
          chunk_texts:
            children: null
            type: array[string]
          need_search:
            children: null
            type: string
          search_query:
            children: null
            type: string
        selected: false
        title: 要約対象配列
        type: code
        variables:
        - value_selector:
          - '1750000000003'
          - text_part1
          variable: text_part1
        - value_selector:
          - '1750000000003'
          - text_part2
          variable: text_part2
        - value_selector:
          - '1750000000003'
          - text_part3
          variable: text_part3
        - value_selector:
          - '1750000000022'
          - need_search
          variable: need_search
        - value_selector:
          - '1750000000022'
          - search_query
          variable: search_query
      height: 54
      id: '1750000000025'
      position:
        x: 1960
        y: 320
      positionAbsolute:
        x: 1960
        y: 320
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: チャンクごとに短く要約する
        error_handle_mode: terminated
        height: 220
        is_parallel: false
        iterator_selector:
        - '1750000000025'
        - chunk_texts
        output_selector:
        - '1750000000027'
        - text
        output_type: array[string]
        parallel_nums: 5
        selected: false
        start_node_id: 1750000000026start
        title: チャンク要約 Iteration
        type: iteration
        width: 420
      height: 220
      id: '1750000000026'
      position:
        x: 2240
        y: 260
      positionAbsolute:
        x: 2240
        y: 260
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 420
      zIndex: 1
    - data:
        desc: ''
        isInIteration: true
        selected: false
        title: ''
        type: iteration-start
      draggable: false
      height: 48
      id: 1750000000026start
      parentId: '1750000000026'
      position:
        x: 24
        y: 68
      positionAbsolute:
        x: 2264
        y: 328
      selectable: false
      sourcePosition: right
      targetPosition: left
      type: custom-iteration-start
      width: 44
      zIndex: 1002
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: 1チャンクを指示観点で要約
        isInIteration: true
        iteration_id: '1750000000026'
        model:
          completion_params:
            temperature: 0
          mode: chat
          name: gpt-4.1
          provider: langgenius/azure_openai/azure_openai
        prompt_template:
        - id: mfg-chunk-sum-sys
          role: system
          text: |
            あなたは資料要約者です。与えられたチャンクを、後段のファイル生成に使えるよう簡潔に要約してください。
            - 事実・固有名詞・数値・見出し構造を優先して残す
            - 前置きやメタ説明は不要。要約本文のみ
        - id: mfg-chunk-sum-user
          role: user
          text: |
            ## ユーザー指示（観点）

            {{{{#1750000000003.prompt#}}}}

            ## チャンク本文

            {{{{#1750000000026.item#}}}}
        selected: false
        title: チャンク要約
        type: llm
        variables: []
        vision:
          enabled: false
      height: 90
      id: '1750000000027'
      parentId: '1750000000026'
      position:
        x: 120
        y: 68
      positionAbsolute:
        x: 2360
        y: 328
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
      zIndex: 1002
    - data:
        code: |
{indent_block(MERGE_SUMMARIES_CODE)}
        code_language: python3
        desc: Iteration の要約結果を結合
        outputs:
          working_context:
            children: null
            type: string
          need_search:
            children: null
            type: string
          search_query:
            children: null
            type: string
        selected: false
        title: 要約統合
        type: code
        variables:
        - value_selector:
          - '1750000000026'
          - output
          variable: summaries
        - value_selector:
          - '1750000000025'
          - need_search
          variable: need_search
        - value_selector:
          - '1750000000025'
          - search_query
          variable: search_query
      height: 54
      id: '1750000000028'
      position:
        x: 2720
        y: 320
      positionAbsolute:
        x: 2720
        y: 320
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        advanced_settings: null
        desc: 小容量/部分/要約の working_context を集約
        output_type: string
        selected: false
        title: 作業コンテキスト集約
        type: variable-aggregator
        variables:
        - - '1750000000005'
          - working_context
        - - '1750000000024'
          - working_context
        - - '1750000000028'
          - working_context
      height: 110
      id: '1750000000029'
      position:
        x: 3000
        y: 200
      positionAbsolute:
        x: 3000
        y: 200
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        advanced_settings: null
        desc: need_search を集約
        output_type: string
        selected: false
        title: 検索要否集約
        type: variable-aggregator
        variables:
        - - '1750000000005'
          - need_search
        - - '1750000000024'
          - need_search
        - - '1750000000028'
          - need_search
      height: 110
      id: '1750000000031'
      position:
        x: 3000
        y: 360
      positionAbsolute:
        x: 3000
        y: 360
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        advanced_settings: null
        desc: search_query を集約
        output_type: string
        selected: false
        title: 検索クエリ集約
        type: variable-aggregator
        variables:
        - - '1750000000005'
          - search_query
        - - '1750000000024'
          - search_query
        - - '1750000000028'
          - search_query
      height: 110
      id: '1750000000032'
      position:
        x: 3000
        y: 520
      positionAbsolute:
        x: 3000
        y: 520
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(SYNC_CODE)}
        code_language: python3
        desc: 集約結果を同期して後段へ渡す
        outputs:
          working_context:
            children: null
            type: string
          need_search:
            children: null
            type: string
          search_query:
            children: null
            type: string
        selected: false
        title: 経路同期
        type: code
        variables:
        - value_selector:
          - '1750000000029'
          - output
          variable: working_context
        - value_selector:
          - '1750000000031'
          - output
          variable: need_search
        - value_selector:
          - '1750000000032'
          - output
          variable: search_query
      height: 54
      id: '1750000000033'
      position:
        x: 3280
        y: 360
      positionAbsolute:
        x: 3280
        y: 360
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        cases:
        - case_id: 'true'
          conditions:
          - comparison_operator: is
            id: cond-need-search
            value: 'true'
            varType: string
            variable_selector:
            - '1750000000033'
            - need_search
          id: 'true'
          logical_operator: and
        desc: need_search=true のときだけ検索する
        selected: false
        title: 検索する？
        type: if-else
      height: 126
      id: '1750000000006'
      position:
        x: 3560
        y: 340
      positionAbsolute:
        x: 3560
        y: 340
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: 必要時のみ Web 検索
        provider_id: tavily
        provider_name: tavily
        provider_type: builtin
        selected: false
        title: Tavily Search
        tool_configurations:
          days: 7
          exclude_domains: null
          include_answer: 1
          include_domains: null
          include_image_descriptions: 0
          include_images: 0
          include_raw_content: 0
          max_results: 5
          search_depth: basic
          topic: general
        tool_label: Tavily Search
        tool_name: tavily_search
        tool_parameters:
          query:
            type: mixed
            value: '{{{{#1750000000033.search_query#}}}}'
        type: tool
      height: 200
      id: '1750000000007'
      position:
        x: 3840
        y: 180
      positionAbsolute:
        x: 3840
        y: 180
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(ENRICH_CODE)}
        code_language: python3
        desc: 作業コンテキストに検索結果を追記
        outputs:
          enriched_context:
            children: null
            type: string
        selected: false
        title: 検索結果を結合
        type: code
        variables:
        - value_selector:
          - '1750000000033'
          - working_context
          variable: context
        - value_selector:
          - '1750000000007'
          - text
          variable: search_text
        - value_selector:
          - '1750000000033'
          - search_query
          variable: search_query
      height: 54
      id: '1750000000008'
      position:
        x: 4120
        y: 200
      positionAbsolute:
        x: 4120
        y: 200
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(SKIP_CODE)}
        code_language: python3
        desc: 検索なしで作業コンテキストのみを渡す
        outputs:
          enriched_context:
            children: null
            type: string
        selected: false
        title: 検索スキップ
        type: code
        variables:
        - value_selector:
          - '1750000000033'
          - working_context
          variable: context
      height: 54
      id: '1750000000009'
      position:
        x: 3840
        y: 440
      positionAbsolute:
        x: 3840
        y: 440
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        advanced_settings: null
        desc: 検索あり/なしのコンテキストを集約
        output_type: string
        selected: false
        title: コンテキスト集約
        type: variable-aggregator
        variables:
        - - '1750000000008'
          - enriched_context
        - - '1750000000009'
          - enriched_context
      height: 90
      id: '1750000000010'
      position:
        x: 4400
        y: 320
      positionAbsolute:
        x: 4400
        y: 320
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        context:
          enabled: false
          variable_selector: []
        desc: 指示と参照（＋必要なら検索結果）から本文を生成
        model:
          completion_params:
            temperature: 0.3
          mode: chat
          name: gpt-4.1
          provider: langgenius/azure_openai/azure_openai
        prompt_template:
        - id: mfg-gen-sys
          role: system
          text: |
            あなたは複数の参照資料を読み、ユーザー指示に従って新しいファイル本文を作成するアシスタントです。

            ## 共通ルール
            - 前置き・後書き・説明文は書かない（本文のみ）
            - 参照資料や検索結果にない事実を捏造しない。不足は「要確認」と明記
            - コードフェンスで全体を囲まない

            ## 出力形式別ルール
            - markdown / docx: 見出し・箇条書きを使った Markdown
            - text: プレーンテキスト
            - json: 有効な JSON のみ
            - pptx: Pandoc スライド形式。各スライドを --- で区切る。1枚目はタイトル、以降は箇条書き中心。1スライドあたり要点は多くしすぎない
            - html: 単一の自己完結 HTML のみ（<!DOCTYPE html> から終了タグまで）。以下を厳守する。
              - 外部リソース禁止（stylesheet / script / font / 画像の http(s) URL・CDN・Web フォント読込なし）
              - <script> 禁止。本文要素に style= 属性を付けない
              - 分離: 装飾は head 内の <style> のみ。構造は header / main / section / nav 等のセマンティック HTML。コンテンツは本文テキストのみ
              - 体裁はデジタル庁デザインシステム / digital.go.jp に寄せる（完全準拠ではなくトーン）。読みやすさ・コントラスト・余白を優先
              - :root に CSS 変数（プライマリ青系、背景白〜ごく薄いグレー、本文ほぼ黒、リンク青、ボーダー薄灰）
              - font-family: "Noto Sans JP", "Hiragino Sans", "Yu Gothic UI", "Yu Gothic", sans-serif
              - 1カラム・本文最大幅を抑える。長い資料は nav 目次＋各 section に id。ヘッダーはシンプルなプライマリ色の帯＋タイトル
              - 避ける: 派手な LP、ダークモード既定、紫グラデ、グロー、カード多用、丸ピル装飾の羅列
              - コンテンツは参照資料に基づく。装飾用のダミー文を入れない
        - id: mfg-gen-user
          role: user
          text: |
            ## 出力形式

            {{{{#1750000000003.output_format#}}}}

            ## 指示

            {{{{#1750000000003.prompt#}}}}

            ## 参照資料（検索結果があれば含む）

            {{{{#1750000000010.output#}}}}
        selected: false
        title: ファイル生成 LLM
        type: llm
        variables: []
        vision:
          enabled: false
      height: 90
      id: '1750000000011'
      position:
        x: 4680
        y: 320
      positionAbsolute:
        x: 4680
        y: 320
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        code: |
{indent_block(FINALIZE_CODE)}
        code_language: python3
        desc: 本文整形とファイル名・形式の確定
        outputs:
          content:
            children: null
            type: string
          result_text:
            children: null
            type: string
          filename:
            children: null
            type: string
          filename_stem:
            children: null
            type: string
          mime_type:
            children: null
            type: string
          output_format:
            children: null
            type: string
        selected: false
        title: 出力整形
        type: code
        variables:
        - value_selector:
          - '1750000000011'
          - text
          variable: text
        - value_selector:
          - '1750000000003'
          - filename
          variable: filename
        - value_selector:
          - '1750000000003'
          - output_format
          variable: output_format
        - value_selector:
          - '1750000000003'
          - coverage_note
          variable: coverage_note
      height: 54
      id: '1750000000012'
      position:
        x: 4960
        y: 320
      positionAbsolute:
        x: 4960
        y: 320
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        cases:
        - case_id: case_docx
          conditions:
          - comparison_operator: is
            id: cond-docx
            value: docx
            varType: string
            variable_selector:
            - '1750000000012'
            - output_format
          id: case_docx
          logical_operator: and
        - case_id: case_pptx
          conditions:
          - comparison_operator: is
            id: cond-pptx
            value: pptx
            varType: string
            variable_selector:
            - '1750000000012'
            - output_format
          id: case_pptx
          logical_operator: and
        desc: 出力形式に応じて変換ツールを分岐
        selected: false
        title: 出力形式分岐
        type: if-else
      height: 180
      id: '1750000000013'
      position:
        x: 5240
        y: 280
      positionAbsolute:
        x: 5240
        y: 280
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: Markdown を DOCX に変換
        is_team_authorization: true
        paramSchemas: []
        params:
          md_text: ''
          output_filename: ''
        plugin_id: bowenliang123/md_exporter
        plugin_unique_identifier: bowenliang123/md_exporter:3.6.9@3f027d63e80b44d5d5a9f706871afaef37905b8f8a89a2d152dc530211a8acb1
        provider_icon: ''
        provider_id: bowenliang123/md_exporter/md_exporter
        provider_name: bowenliang123/md_exporter/md_exporter
        provider_type: builtin
        selected: false
        title: DOCX 変換
        tool_configurations:
          enable_toc:
            type: constant
            value: 'false'
        tool_description: Markdown を DOCX に変換する
        tool_label: Markdown ⮕ DOCX
        tool_name: md_to_docx
        tool_node_version: '2'
        tool_parameters:
          md_text:
            type: mixed
            value: '{{{{#1750000000012.content#}}}}'
          output_filename:
            type: mixed
            value: '{{{{#1750000000012.filename_stem#}}}}'
        type: tool
      height: 120
      id: '1750000000014'
      position:
        x: 5520
        y: 80
      positionAbsolute:
        x: 5520
        y: 80
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: Markdown を PPTX に変換
        is_team_authorization: true
        paramSchemas: []
        params:
          md_text: ''
          output_filename: ''
        plugin_id: bowenliang123/md_exporter
        plugin_unique_identifier: bowenliang123/md_exporter:3.6.9@3f027d63e80b44d5d5a9f706871afaef37905b8f8a89a2d152dc530211a8acb1
        provider_icon: ''
        provider_id: bowenliang123/md_exporter/md_exporter
        provider_name: bowenliang123/md_exporter/md_exporter
        provider_type: builtin
        selected: false
        title: PPTX 変換
        tool_configurations: {{}}
        tool_description: Markdown を PPTX に変換する
        tool_label: Markdown ⮕ PPTX
        tool_name: md_to_pptx
        tool_node_version: '2'
        tool_parameters:
          md_text:
            type: mixed
            value: '{{{{#1750000000012.content#}}}}'
          output_filename:
            type: mixed
            value: '{{{{#1750000000012.filename_stem#}}}}'
        type: tool
      height: 120
      id: '1750000000015'
      position:
        x: 5520
        y: 280
      positionAbsolute:
        x: 5520
        y: 280
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: markdown / html / text / json をファイル保存
        is_team_authorization: true
        paramSchemas: []
        params:
          content: ''
          encoding: ''
          filename: ''
          format: ''
          mime_type: ''
        plugin_id: kurokobo/file_tools
        plugin_unique_identifier: kurokobo/file_tools:0.0.2@8bde7b4d2c30cf22e8f6ce851572af244f7a5776addab94330b820dc2160726c
        provider_icon: ''
        provider_id: kurokobo/file_tools/file_tools
        provider_name: kurokobo/file_tools/file_tools
        provider_type: builtin
        selected: false
        title: テキストファイル保存
        tool_configurations:
          format:
            type: constant
            value: text
        tool_description: テキストをファイルとして保存
        tool_label: ファイルとして保存
        tool_name: save_as_file
        tool_node_version: '2'
        tool_parameters:
          content:
            type: mixed
            value: '{{{{#1750000000012.content#}}}}'
          encoding:
            type: mixed
            value: utf-8
          filename:
            type: mixed
            value: '{{{{#1750000000012.filename#}}}}'
          mime_type:
            type: mixed
            value: '{{{{#1750000000012.mime_type#}}}}'
        type: tool
      height: 120
      id: '1750000000016'
      position:
        x: 5520
        y: 480
      positionAbsolute:
        x: 5520
        y: 480
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        advanced_settings: null
        desc: 形式別の成果物ファイルを集約
        output_type: array[file]
        selected: false
        title: 成果物集約
        type: variable-aggregator
        variables:
        - - '1750000000014'
          - files
        - - '1750000000015'
          - files
        - - '1750000000016'
          - files
      height: 110
      id: '1750000000017'
      position:
        x: 5800
        y: 300
      positionAbsolute:
        x: 5800
        y: 300
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    - data:
        desc: 生成本文と成果物ファイルを返す
        outputs:
        - value_selector:
          - '1750000000012'
          - result_text
          value_type: string
          variable: result
        - value_selector:
          - '1750000000017'
          - output
          value_type: array[file]
          variable: generated_file
        - value_selector:
          - '1750000000012'
          - filename
          value_type: string
          variable: filename
        - value_selector:
          - '1750000000033'
          - need_search
          value_type: string
          variable: searched
        selected: false
        title: 終了
        type: end
      height: 160
      id: '1750000000018'
      position:
        x: 6080
        y: 280
      positionAbsolute:
        x: 6080
        y: 280
      selected: false
      sourcePosition: right
      targetPosition: left
      type: custom
      width: 244
    viewport:
      x: -100
      y: 20
      zoom: 0.35
  rag_pipeline_variables: []
"""

    # Fix f-string over-escaping: we used {{{{ for Jinja which becomes {{ in output - good for YAML
    # But Schema: {{"need_search"... became Schema: {"need_search" - good
    # tool values '{{{{#...#}}}}' become '{{#...#}}' - good
    # Empty dict {{}} becomes {} - good

    # Graph sync issue: search-if depends on need aggregator, but working_context and search_query
    # aggregators may not have run if we only edge from need aggregator. In Dify, aggregators
    # receive values when upstream nodes complete via edges. We have edges from pack nodes to
    # all three aggregators. But search-if only waits for need aggregator. The enrich node
    # reads working_context aggregator - that must be populated. Since pack nodes fan-out to
    # all three aggs before need-agg → search-if, all should be ready when any path completes
    # all three edges... Actually in parallel edge execution, need-agg might fire search-if
    # before ctx-agg finishes if edges are concurrent. Safer: chain aggregators.
    #
    # Fix graph: pack → ctx_agg → query_agg → need_agg → search_if
    # And remove direct pack→need/query edges; instead:
    # pack → ctx_agg (multiple inputs)
    # Also need query and need from same packs - use ONE pack code and ONE multi-output approach
    # with a single "join" code that doesn't work across branches.
    #
    # Simpler sync fix: edge ctx_agg → query_agg → need_agg → search_if
    # And packs only connect to ctx_agg. But then need_search isn't in ctx_agg.
    #
    # Best sync: each pack connects only to a single "path join" variable aggregator isn't enough.
    # Use: packs → ctx_agg, and also packs → need_agg, packs → query_agg (3 edges).
    # Then: ctx_agg → bridge code that just passes, taking need from need_agg... circular.
    #
    # Chain: 
    #   packs → ctx_agg
    #   packs → need_agg  
    #   packs → query_agg
    #   ctx_agg → sync1 (code: pass-through context, reads need/query from aggs)
    # That still races.
    #
    # Dify runs node when all incoming edges ready. So if search-if has incoming from need_agg ONLY,
    # enrich has no edge from ctx_agg - it just variable-refs ctx_agg. Variable refs don't wait!
    # So we need explicit edge: ctx_agg → search-if (or enrich), and query_agg → search-if.
    #
    # Make search-if wait by using a sync code node:
    #   inputs: working_context (0029), need_search (0031), search_query (0032)
    #   edges: 0029→0033, 0031→0033, 0032→0033 → 0006
    # Dify code nodes typically need all variable selectors available; multiple incoming edges
    # from three aggregators to sync code, then to if-else.

    OUT.write_text(yaml_doc, encoding="utf-8")
    print(f"Wrote {OUT} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
