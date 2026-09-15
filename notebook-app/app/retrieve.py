"""ノート内ノードから設問に効く節を選ぶ。保存時に切らず、検索時だけ予算を使う。"""

from __future__ import annotations

import re
from typing import Any

CHAR_BUDGET = 12_000
MAX_NODES = 12
_SPLIT = re.compile(r"[はがをにのへとでも、。！？?\s　]+")
_STOP = frozenset(
    {
        "です",
        "ます",
        "した",
        "する",
        "こと",
        "ため",
        "もの",
        "よう",
        "この",
        "その",
        "どの",
        "それ",
        "これ",
        "あれ",
        "なに",
        "何か",
        "どう",
        "どんな",
        "して",
        "いる",
        "ある",
        "ない",
        "なる",
        "できる",
        "である",
    }
)
_EXPAND: dict[str, tuple[str, ...]] = {
    "対象": ("対象者", "補助対象", "交付対象"),
    "対象者": ("対象", "補助対象"),
    "金額": ("額", "支給額", "補助額", "交付額"),
    "いくら": ("金額", "額", "支給額"),
    "期限": ("期日", "期間", "まで"),
    "要件": ("条件", "資格"),
    "目的": ("趣旨", "概要"),
}


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for part in _SPLIT.split(text or ""):
        part = part.strip().lower()
        if len(part) < 2:
            continue
        out.add(part)
        for n in (2, 3):
            if len(part) < n:
                continue
            for i in range(len(part) - n + 1):
                out.add(part[i : i + n])
    return out


def _query_tokens(query: str) -> set[str]:
    raw = _tokens(query)
    extra: set[str] = set()
    for t in raw:
        extra.update(_EXPAND.get(t, ()))
    return {t for t in (raw | extra) if t not in _STOP and len(t) >= 2}


def _score(query: str, node: dict[str, Any]) -> float:
    q = _query_tokens(query)
    if not q:
        return 0.0
    title = str(node.get("title") or "")
    summary = str(node.get("summary") or "")
    text = str(node.get("text") or "")
    hay = _tokens(f"{title} {summary} {text}")
    if not hay:
        return 0.0
    hit = 0.0
    for t in q:
        if t in hay:
            hit += 2.0 if len(t) >= 3 else 0.6
    score = hit / max(len(q), 1)
    if q & _tokens(title):
        score += 0.45
    blob = title + summary + text
    if any(len(t) >= 3 and t in blob for t in q):
        score += 0.2
    return score


def select_nodes(
    query: str,
    nodes: list[dict[str, Any]],
    *,
    budget: int = CHAR_BUDGET,
) -> list[dict[str, Any]]:
    """設問との重なり順で節を取る。ヒットがあるときは無関係な節を捨てる。"""
    usable = [n for n in nodes if (n.get("text") or "").strip()]
    if not usable:
        return []
    scored = [(_score(query, n), n) for n in usable]
    hits = [(s, n) for s, n in scored if s > 0]
    if hits:
        ranked = [n for _, n in sorted(hits, key=lambda x: x[0], reverse=True)][:MAX_NODES]
    else:
        ranked = usable[:3]
    picked: list[dict[str, Any]] = []
    used = 0
    for n in ranked:
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
