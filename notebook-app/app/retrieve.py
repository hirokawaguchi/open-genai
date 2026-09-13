"""ノート内ノードから設問に効く節を選ぶ。保存時に切らず、検索時だけ予算を使う。"""

from __future__ import annotations

import re
from typing import Any

CHAR_BUDGET = 24_000
_TOKEN = re.compile(r"[A-Za-z0-9\u3040-\u30ff\u4e00-\u9fff]{2,}")


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _TOKEN.finditer(text or "")}


def _score(query: str, node: dict[str, Any]) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    hay = _tokens(
        f"{node.get('title') or ''} {node.get('summary') or ''} {node.get('text') or ''}"
    )
    if not hay:
        return 0.0
    hit = len(q & hay)
    return hit / max(len(q), 1) + min(len((node.get("text") or "")) / 8000.0, 0.2)


def select_nodes(
    query: str,
    nodes: list[dict[str, Any]],
    *,
    budget: int = CHAR_BUDGET,
) -> list[dict[str, Any]]:
    """小さければ全文、大きければ設問との重なり順で節を取る。"""
    usable = [n for n in nodes if (n.get("text") or "").strip()]
    if not usable:
        return []
    total = sum(len(str(n.get("text") or "")) for n in usable)
    if total <= budget:
        return usable
    ranked = sorted(usable, key=lambda n: _score(query, n), reverse=True)
    picked: list[dict[str, Any]] = []
    used = 0
    for n in ranked:
        if _score(query, n) <= 0 and picked:
            continue
        text = str(n.get("text") or "")
        if used and used + len(text) > budget:
            remain = budget - used
            if remain < 400:
                break
            n = {**n, "text": text[:remain] + "\n…(以下省略)"}
            picked.append(n)
            break
        picked.append(n)
        used += len(text)
        if used >= budget:
            break
    return picked or ranked[:3]


_CITE_NUM = re.compile(r"\[(\d+)\]")
_CITE_MARK = re.compile(r"\[\s*\d+(?:\s*[,、]\s*\d+)*\s*\]")


def format_material(nodes: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    blocks: list[str] = []
    cites: list[dict[str, Any]] = []
    for i, n in enumerate(nodes, start=1):
        source = str(n.get("source") or "資料")
        title = str(n.get("title") or "").strip()
        loc = ""
        ps, pe = n.get("page_start"), n.get("page_end")
        if ps:
            loc = f" p.{ps}" if ps == pe or not pe else f" p.{ps}-{pe}"
        label = f"{source}" + (f" / {title}" if title else "") + loc
        blocks.append(f"[{i}] ({label})\n{n.get('text') or ''}")
        cites.append({"n": i, "display_name": label, "text": str(n.get("text") or "")})
    return "\n\n".join(blocks), cites


def cited_numbers(text: str) -> set[int]:
    return {int(m) for m in _CITE_NUM.findall(text or "")}


def filter_used_citations(
    answer: str, cites: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    used = cited_numbers(answer)
    out: list[dict[str, Any]] = []
    for c in cites:
        try:
            n = int(c.get("n") or 0)
        except (TypeError, ValueError):
            n = 0
        if n and n in used:
            out.append(c)
    return out


def strip_citation_marks(text: str) -> str:
    cleaned = _CITE_MARK.sub("", text or "")
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r" {2,}", " ", cleaned)
    return cleaned.strip()
