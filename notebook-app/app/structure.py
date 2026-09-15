"""ページ配列から節ノードを作る（rag-app tree_builder と同系統のヒューリスティック）。"""

from __future__ import annotations

import re
from typing import Any

SUMMARY_CHARS = 240
MERGE_PAGE_CHARS = 400

_MD_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*$", re.MULTILINE)
_TOKEN_SPLIT = re.compile(r"[はがをにのへとでも、。！？?\s　]+")
_JP_HEAD = re.compile(
    r"^(第[0-9０-９一二三四五六七八九十百]+(?:条の[0-9０-９]+|[条項章節款編])"
    r"|様式第[0-9０-９]+号"
    r"|別[表紙](?:第?[0-9０-９]+号?)?)"
    r"(?:[　\s（(].*)?$"
)
_NUM_HEAD = re.compile(r"^[0-9０-９]{1,2}[\.．、\)]\s+\S.{0,36}$")


def heuristic_summary(text: str, *, limit: int = SUMMARY_CHARS) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= limit:
        return t
    return t[: limit - 1] + "…"


def _page_map(pages: list[dict[str, Any]]) -> dict[int, str]:
    return {int(p["page"]): (p.get("text") or "") for p in pages}


def _text_for_range(pmap: dict[int, str], start: int, end: int) -> str:
    parts = [pmap[i] for i in range(start, end + 1) if i in pmap and pmap[i]]
    return "\n\n".join(parts)


def _build_from_markdown(pages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    pmap = _page_map(pages)
    if not pages:
        return None
    offsets: list[tuple[int, int]] = []
    chunks: list[str] = []
    pos = 0
    for p in sorted(pages, key=lambda x: int(x["page"])):
        t = p.get("text") or ""
        offsets.append((pos, int(p["page"])))
        chunks.append(t)
        pos += len(t) + 2
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

    raw: list[dict[str, Any]] = []
    for i, m in enumerate(matches):
        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        page_start = page_at(m.start())
        page_end = page_at(max(body_start, body_end - 1))
        raw.append(
            {
                "title": m.group(2).strip(),
                "page_start": page_start,
                "page_end": max(page_start, page_end),
                "text": full[body_start:body_end].strip()
                or _text_for_range(pmap, page_start, page_end),
            }
        )
    return [
        {
            "title": item["title"],
            "text": item["text"],
            "summary": heuristic_summary(item["text"]),
            "page_start": item["page_start"],
            "page_end": item["page_end"],
        }
        for item in raw
        if (item["text"] or "").strip()
    ]


def _is_office_heading(line: str) -> bool:
    t = (line or "").strip()
    if not t or len(t) > 80:
        return False
    if _JP_HEAD.match(t):
        return True
    if _NUM_HEAD.match(t) and not t.endswith("。"):
        return True
    return False


def _heading_title(line: str) -> str:
    t = re.sub(r"\s+", " ", (line or "").strip())
    return t[:40]


def _build_from_office_headings(pages: list[dict[str, Any]]) -> list[dict[str, Any]] | None:
    pmap = _page_map(pages)
    if not pages:
        return None
    offsets: list[tuple[int, int]] = []
    chunks: list[str] = []
    pos = 0
    for p in sorted(pages, key=lambda x: int(x["page"])):
        t = p.get("text") or ""
        offsets.append((pos, int(p["page"])))
        chunks.append(t)
        pos += len(t) + 2
    full = "\n\n".join(chunks)
    starts: list[tuple[int, str]] = []
    cursor = 0
    for raw_line in full.splitlines(keepends=True):
        line = raw_line.strip()
        if _is_office_heading(line):
            starts.append((cursor, _heading_title(line)))
        cursor += len(raw_line)
    if len(starts) < 2:
        return None

    def page_at(char_idx: int) -> int:
        page = offsets[0][1]
        for start, pg in offsets:
            if start <= char_idx:
                page = pg
            else:
                break
        return page

    raw: list[dict[str, Any]] = []
    for i, (start, title) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(full)
        page_start = page_at(start)
        page_end = page_at(max(start, end - 1))
        body = full[start:end].strip()
        raw.append(
            {
                "title": title,
                "page_start": page_start,
                "page_end": max(page_start, page_end),
                "text": body or _text_for_range(pmap, page_start, page_end),
            }
        )
    return [
        {
            "title": item["title"],
            "text": item["text"],
            "summary": heuristic_summary(item["text"]),
            "page_start": item["page_start"],
            "page_end": item["page_end"],
        }
        for item in raw
        if (item["text"] or "").strip()
    ]


def _build_from_pages(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
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
        if sum(len(x) for x in cur_parts) < MERGE_PAGE_CHARS:
            cur_end = pg
            cur_parts.append(t)
        else:
            flush()
            cur_start = pg
            cur_end = pg
            cur_parts = [t]
    flush()

    nodes: list[dict[str, Any]] = []
    for ps, pe, text in groups:
        if not text.strip():
            continue
        title = f"p.{ps}" if ps == pe else f"p.{ps}-{pe}"
        first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), title)
        if 0 < len(first_line) <= 40:
            title = first_line
        nodes.append(
            {
                "title": title,
                "text": text,
                "summary": heuristic_summary(text),
                "page_start": ps,
                "page_end": pe,
            }
        )
    return nodes


def build_nodes(pages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return (
        _build_from_markdown(pages)
        or _build_from_office_headings(pages)
        or _build_from_pages(pages)
    )


def sample_nodes(nodes: list[dict[str, Any]], limit: int = 8) -> list[dict[str, Any]]:
    if len(nodes) <= limit:
        return nodes
    if limit <= 2:
        return [nodes[0], nodes[-1]][:limit]
    mid = len(nodes) // 2
    picked = [nodes[0], nodes[mid], nodes[-1]]
    for n in nodes:
        if n not in picked:
            picked.append(n)
        if len(picked) >= limit:
            break
    return picked


def briefing_from_nodes(filename: str, nodes: list[dict[str, Any]]) -> dict[str, Any]:
    outline = [str(n.get("title") or "").strip() for n in nodes if n.get("title")]
    sampled = sample_nodes(nodes, 8)
    blob = "\n".join(str(n.get("summary") or n.get("text") or "") for n in sampled)
    seen: set[str] = set()
    terms: list[str] = []
    for part in _TOKEN_SPLIT.split(blob):
        t = part.strip()
        if len(t) < 2 or t.isdigit() or t in seen:
            continue
        if len(t) > 12:
            t = t[:12]
        seen.add(t)
        terms.append(t)
        if len(terms) >= 12:
            break
    return {
        "summary": heuristic_summary(blob, limit=400) or filename,
        "terms": terms,
        "outline": outline[:40],
    }
