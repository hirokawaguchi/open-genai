"""ページ配列から TOC ツリーを構築する。

PoC 方針:
- Markdown 見出しがあれば階層ノード化
- なければページ単位（短い連続ページは結合）のフラット〜浅いツリー
- 要約は本文先頭のヒューリスティック（任意で LLM 要約）
"""

from __future__ import annotations

import os
import re
from typing import Any

# True のときページ／節要約を LLM で生成（遅い・要 Ollama）
TREE_USE_LLM_SUMMARY = os.environ.get("TREE_USE_LLM_SUMMARY", "0").strip() in (
    "1",
    "true",
    "True",
    "yes",
)
SUMMARY_CHARS = int(os.environ.get("TREE_SUMMARY_CHARS", "240"))
# 連続する短いページをまとめる閾値
MERGE_PAGE_CHARS = int(os.environ.get("TREE_MERGE_PAGE_CHARS", "400"))

_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)


def _heuristic_summary(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= SUMMARY_CHARS:
        return t
    return t[: SUMMARY_CHARS - 1] + "…"


async def _maybe_llm_summary(title: str, text: str) -> str:
    if not TREE_USE_LLM_SUMMARY:
        return _heuristic_summary(text)
    try:
        from . import embeddings

        excerpt = text[:2000]
        prompt = (
            "次の文書セクションを1〜2文の日本語で要約してください。"
            "見出し以外の固有情報（条番号・議題・結論）を残してください。\n\n"
            f"# 見出し\n{title}\n\n# 本文\n{excerpt}"
        )
        out = await embeddings.generate(
            [{"role": "user", "content": prompt}]
        )
        return (out or "").strip() or _heuristic_summary(text)
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] tree summary LLM 失敗、ヒューリスティックにフォールバック: {e}")
        return _heuristic_summary(text)


def _page_map(pages: list[dict[str, Any]]) -> dict[int, str]:
    return {int(p["page"]): (p.get("text") or "") for p in pages}


def _text_for_range(pmap: dict[int, str], start: int, end: int) -> str:
    parts = [pmap[i] for i in range(start, end + 1) if i in pmap and pmap[i]]
    return "\n\n".join(parts)


def _build_from_markdown(pages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    """全文に Markdown 見出しがあれば階層ツリーを返す。無ければ None。"""
    pmap = _page_map(pages)
    if not pages:
        return None

    # ページ境界を保持した連結（見出し位置 → page 推定用）
    offsets: list[tuple[int, int]] = []  # (char_start, page)
    chunks: list[str] = []
    pos = 0
    for p in sorted(pages, key=lambda x: int(x["page"])):
        t = p.get("text") or ""
        offsets.append((pos, int(p["page"])))
        chunks.append(t)
        pos += len(t) + 2  # \n\n
    full = "\n\n".join(chunks)
    matches = list(_MD_HEADING.finditer(full))
    if len(matches) < 2:
        return None

    def page_at(char_idx: int) -> int:
        page = offsets[0][1]
        for start, pg in offsets:
            if start <= char_idx:
                page = pg
            else:
                break
        return page

    # 仮ノード（page_end は次見出し直前まで）
    raw: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        page_start = page_at(m.start())
        page_end = page_at(max(body_start, body_end - 1))
        raw.append(
            {
                "level": level,
                "title": title,
                "page_start": page_start,
                "page_end": max(page_start, page_end),
                "body": full[body_start:body_end].strip(),
            }
        )

    nodes: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []  # (level, node_id)
    for i, item in enumerate(raw):
        node_id = f"n{i + 1}"
        while stack and stack[-1][0] >= item["level"]:
            stack.pop()
        parent_id = stack[-1][1] if stack else None
        nodes.append(
            {
                "node_id": node_id,
                "title": item["title"],
                "summary": "",  # 後で埋める
                "page_start": item["page_start"],
                "page_end": item["page_end"],
                "parent_id": parent_id,
                "sort_order": i,
                "_body": item["body"] or _text_for_range(
                    pmap, item["page_start"], item["page_end"]
                ),
            }
        )
        stack.append((item["level"], node_id))
    return nodes


def _build_from_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ページを浅いツリーにする（短いページは結合）。"""
    if not pages:
        return []
    ordered = sorted(pages, key=lambda x: int(x["page"]))
    groups: list[tuple[int, int, str]] = []
    cur_start = int(ordered[0]["page"])
    cur_end = cur_start
    cur_parts = [ordered[0].get("text") or ""]

    def flush() -> None:
        nonlocal cur_start, cur_end, cur_parts
        text = "\n\n".join(p for p in cur_parts if p).strip()
        groups.append((cur_start, cur_end, text))

    for p in ordered[1:]:
        pg = int(p["page"])
        t = p.get("text") or ""
        # 直前グループが短ければ結合
        so_far = sum(len(x) for x in cur_parts)
        if so_far < MERGE_PAGE_CHARS:
            cur_end = pg
            cur_parts.append(t)
        else:
            flush()
            cur_start = pg
            cur_end = pg
            cur_parts = [t]
    flush()

    # ルート + 各グループを子に
    nodes: list[dict[str, Any]] = [
        {
            "node_id": "root",
            "title": "文書全体",
            "summary": "",
            "page_start": int(ordered[0]["page"]),
            "page_end": int(ordered[-1]["page"]),
            "parent_id": None,
            "sort_order": 0,
            "_body": "",
        }
    ]
    for i, (ps, pe, text) in enumerate(groups, start=1):
        title = f"p.{ps}" if ps == pe else f"p.{ps}-{pe}"
        # 本文先頭行をタイトル候補に
        first_line = next(
            (ln.strip() for ln in text.splitlines() if ln.strip()),
            title,
        )
        if 0 < len(first_line) <= 40:
            title = first_line
        nodes.append(
            {
                "node_id": f"n{i}",
                "title": title,
                "summary": "",
                "page_start": ps,
                "page_end": pe,
                "parent_id": "root",
                "sort_order": i,
                "_body": text,
            }
        )
    return nodes


async def build_tree_nodes(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """ページ配列から tree_nodes 行相当のリストを返す。"""
    nodes = _build_from_markdown(pages)
    if not nodes:
        nodes = _build_from_pages(pages)

    # ルート要約用に全文の先頭も用意
    pmap = _page_map(pages)
    for n in nodes:
        body = n.pop("_body", None)
        if body is None:
            body = _text_for_range(pmap, n["page_start"], n["page_end"])
        if n["node_id"] == "root" and not body:
            body = _text_for_range(pmap, n["page_start"], n["page_end"])
        n["summary"] = await _maybe_llm_summary(n["title"], body)
    return nodes
