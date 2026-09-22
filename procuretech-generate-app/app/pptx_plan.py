"""Markdown 章から deck JSON を組み立てる。

機械が見出し・リスト・表・コードの骨格を取り、LLM は節ごとに
{role, points} へ圧縮する。文書全体の「ストーリー（タイトル列）」は作らない。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from typing import Any

from app.llm import (
    chat,
    compose_model,
    llm_enabled,
    pptx_freeform_enabled,
    review_enabled,
)
from app.pptx_catalog import (
    DIAGRAM_LAYOUTS,
    NUMERIC_LAYOUTS,
    content_nonempty,
)
from app.compose_formats import _TABLE_LINE_RE, parse_gfm_table
from app.pptx_layouts import validate_deck

log = logging.getLogger("procuretech-generate")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_NUMBERED_RE = re.compile(r"^(\s*)(\d+)[.)]\s+(.*)$")
_LABEL_RE = re.compile(r"^\*\*(.+?)\*\*\s*[:：]?\s*(.*)$")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)>\s]+)>?")
_NUMBER_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?\s*%|[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.I)


TABLE_LAYOUTS = frozenset(
    {"axis-table", "comparison-table", "checklist-table", "pricing-table"}
)

# 文書種別ではなく、どの文書にもある節の役割。
ROLES = frozenset(
    {
        "explanation",
        "procedure",
        "definition",
        "comparison",
        "numeric",
        "caution",
        "attachment",
    }
)
DEFAULT_ROLE = "explanation"
_ROLE_ALIASES = {
    "explain": "explanation",
    "description": "explanation",
    "steps": "procedure",
    "process": "procedure",
    "table": "definition",
    "glossary": "definition",
    "compare": "comparison",
    "kpi": "numeric",
    "number": "numeric",
    "warning": "caution",
    "note": "caution",
    "code": "attachment",
    "prompt": "attachment",
}


@dataclass
class SectionNotes:
    role: str
    points: list[str]
    title: str = ""
    figure: str = ""
    figure_caption: str = ""


@dataclass
class SourceBlock:
    filename: str
    heading: str
    text: str
    images: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)
    # フェンスコード（コマンド等）。従来は捨てていたが、手順書ではこれが本文の主役なので保持する。
    code_blocks: list[str] = field(default_factory=list)
    mermaid_blocks: list[str] = field(default_factory=list)


def _rel_of(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def _is_waiting_image(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1].lower()
    return "waiting" in name


def _content_images(paths: list[str]) -> list[str]:
    return [p for p in paths if p and not _is_waiting_image(p)]


def _plain_source(text: str) -> str:
    """ノート用。画像記法・フェンス・見出し記号を除いた本文だけにする。"""
    cleaned = _IMAGE_RE.sub("", text or "")
    cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)
    cleaned = re.sub(r"\*\*(.+?)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"^#{1,6}\s+", "", cleaned, flags=re.M)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _finish_block(
    current: SourceBlock,
    paragraphs: list[str],
    table_buf: list[str],
    blocks: list[SourceBlock],
) -> None:
    parsed = parse_gfm_table(table_buf)
    table_buf.clear()
    if parsed:
        current.tables.append(parsed)
    current.text = "\n".join(paragraphs).strip()
    if (
        current.heading
        or current.text
        or current.bullets
        or current.images
        or current.tables
        or current.code_blocks
        or current.mermaid_blocks
    ):
        blocks.append(current)


def parse_source_blocks(name: str, sections: list[dict[str, Any]]) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    for sec in sections:
        filename = str(sec.get("filename") or "section.md")
        content = str(sec.get("content") or "")
        current = SourceBlock(filename=filename, heading="", text="")
        paragraphs: list[str] = []
        table_buf: list[str] = []
        in_code = False
        code_lang = ""
        code_lines: list[str] = []
        for raw in content.splitlines():
            stripped = raw.strip()
            if stripped.startswith("```"):
                if in_code:
                    code_text = "\n".join(code_lines).strip()
                    if code_text and code_lang == "mermaid":
                        current.mermaid_blocks.append(code_text)
                    elif code_text:
                        current.code_blocks.append(code_text)
                    in_code, code_lang, code_lines = False, "", []
                else:
                    in_code, code_lang, code_lines = True, stripped[3:].strip().lower(), []
                continue
            if in_code:
                code_lines.append(raw)
                continue
            hm = _HEADING_RE.match(stripped)
            if hm:
                _finish_block(current, paragraphs, table_buf, blocks)
                paragraphs = []
                current = SourceBlock(filename=filename, heading=hm.group(2).strip(), text="")
                continue
            if _TABLE_LINE_RE.match(stripped):
                table_buf.append(stripped)
                continue
            if table_buf:
                parsed = parse_gfm_table(table_buf)
                table_buf.clear()
                if parsed:
                    current.tables.append(parsed)
            images = list(_IMAGE_RE.finditer(stripped))
            for im in images:
                rel = _rel_of(im.group(2))
                if not _is_waiting_image(rel):
                    current.images.append(rel)
            if images and _IMAGE_RE.sub("", stripped).strip() == "":
                continue
            bm = _BULLET_RE.match(raw)
            if bm:
                current.bullets.append(bm.group(2).strip())
                continue
            nm = _NUMBERED_RE.match(raw)
            if nm:
                current.bullets.append(nm.group(3).strip())
                continue
            if stripped:
                paragraphs.append(stripped)
        _finish_block(current, paragraphs, table_buf, blocks)
    if not blocks:
        blocks.append(SourceBlock(filename="document.md", heading=name, text=name))
    return blocks


def _find_block(blocks: list[SourceBlock], source: Any) -> SourceBlock | None:
    if not isinstance(source, dict):
        return blocks[0] if blocks else None
    filename = str(source.get("filename") or "")
    heading = str(source.get("heading") or source.get("title") or "")
    for block in blocks:
        if filename and block.filename != filename:
            continue
        if heading and heading not in (block.heading,):
            if heading not in block.heading and block.heading not in heading:
                continue
        return block
    if filename:
        for block in blocks:
            if block.filename == filename:
                return block
    if heading:
        for block in blocks:
            if heading in block.heading or block.heading in heading:
                return block
    return blocks[0] if blocks else None


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[。．\n])", text) if p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def _clip(text: str, limit: int) -> str:
    s = _plain_source(text).replace("\n", "")
    if len(s) <= limit:
        return s
    return s[: max(limit - 1, 1)] + "…"


_KV_SEP_RE = re.compile(r"[：:]\s*|\s*[—―–]\s*|\s*→\s*")


def _split_kv(text: str) -> tuple[str, str]:
    """「項目：内容」形式を (項目, 内容) に分ける。区切りが無ければ (全文, "")。"""
    s = _plain_source(text).replace("\n", "").strip()
    m = _KV_SEP_RE.search(s)
    if not m or m.start() == 0:
        return s, ""
    return s[: m.start()].strip(), s[m.end():].strip()


def _block_key(block: SourceBlock) -> tuple[str, str]:
    return (block.filename, block.heading)


def _normalize_role(raw: Any) -> str:
    name = str(raw or "").strip().lower()
    name = _ROLE_ALIASES.get(name, name)
    return name if name in ROLES else DEFAULT_ROLE


_BRANCH_MARK_RE = re.compile(r"[├└]|分岐|経路")


def _looks_like_branch(block: SourceBlock) -> bool:
    """完成イメージのような分岐図。矢印や樹形があればフロー型にする。"""
    blob = f"{block.heading}\n{block.text}\n{' '.join(block.bullets)}"
    if _BRANCH_MARK_RE.search(blob):
        return True
    return blob.count("→") >= 2 or blob.count("↓") >= 2


def _flow_nodes(block: SourceBlock, bullets: list[str]) -> list[str]:
    nodes: list[str] = []
    for raw in (block.text or "").splitlines():
        if not any(ch in raw for ch in ("→", "↓", "├", "└")):
            continue
        cleaned = re.sub(r"[├└│｜|─\-]+", " ", raw)
        cleaned = re.sub(r"[→↓]+", " ", cleaned)
        cleaned = _plain_source(cleaned).replace("\n", "").strip()
        if cleaned:
            nodes.append(_clip(cleaned, 28))
    if len(nodes) >= 2:
        return nodes[:6]
    return [_clip(b, 22) for b in bullets[:6] if b]


def _flow_content(block: SourceBlock, bullets: list[str]) -> dict[str, Any]:
    nodes = _flow_nodes(block, bullets)
    if not nodes:
        nodes = [s for s in _sentences(_plain_source(block.text))[:5] if s]
    steps = [{"n": str(i + 1), "title": n, "text": "", "heading": n, "label": n} for i, n in enumerate(nodes)]
    if _looks_like_branch(block) and len(steps) >= 3:
        return {"mode": "branch", "steps": steps, "items": steps, "branches": steps[1:]}
    return {"steps": steps, "items": steps}


def _guess_role(block: SourceBlock) -> str:
    """機械の役割推定。文書タイプは見ない。"""
    heading = block.heading or ""
    blob = f"{heading}\n{block.text}\n{' '.join(block.bullets)}"
    if block.code_blocks and not (block.bullets or block.tables or len(_plain_source(block.text)) > 80):
        return "attachment"
    if block.tables and not (block.bullets or _content_images(block.images) or len(_plain_source(block.text)) > 80):
        return "definition"
    if any(k in heading for k in ("手順", "フロー", "プロセス", "工程", "完成イメージ", "分岐", "経路")):
        return "procedure"
    if _looks_like_branch(block):
        return "procedure"
    if any(k in heading for k in ("比較", "更改", "Before", "After", "対比")):
        return "comparison"
    if any(k in heading for k in ("注意", "例外", "禁止", "警告")):
        return "caution"
    if _NUMBER_RE.search(blob) and any(k in heading for k in ("規模", "KPI", "KGI", "目標", "件数", "数値")):
        return "numeric"
    if any(k in heading for k in ("用語", "定義", "一覧")):
        return "definition"
    return DEFAULT_ROLE


def _role_to_layout(role: str, block: SourceBlock, previous: str) -> str:
    if _content_images(block.images):
        return "fullscreen-photo" if previous != "fullscreen-photo" else "fullwidth-points"
    role = _normalize_role(role)
    if role == "procedure":
        return "step-flow" if _looks_like_branch(block) else "chevron-steps"
    if role == "definition":
        return "axis-table" if block.tables else "fullwidth-points"
    if role == "comparison":
        return "before-after-split"
    if role == "numeric":
        from app.pptx_repair import looks_like_meta

        if looks_like_meta(block.heading, block.text, *block.bullets):
            return "axis-table"
        return "chart-insight" if previous != "chart-insight" else "kpi-three-col"
    if role == "caution":
        return "fullwidth-points"
    if role == "attachment":
        return "fullwidth-points"
    return "fullwidth-points"


def _suggest_layout(block: SourceBlock, previous: str) -> str:
    return _role_to_layout(_guess_role(block), block, previous)


def _fill_content(layout: str, block: SourceBlock) -> dict[str, Any]:
    bullets = [_plain_source(b) for b in block.bullets if _plain_source(b)]
    if not bullets:
        bullets = [s for s in _sentences(_plain_source(block.text))[:6] if s]
    # 貼り付け用プロンプト等のフェンスはノートに残し、スライド本文へは載せない。
    if block.code_blocks and not bullets:
        bullets = ["貼り付け用の文面はノートの原文を参照"]
    images = _content_images(block.images)
    numbers = _NUMBER_RE.findall(block.text + "\n" + "\n".join(block.bullets))

    if layout == "fullwidth-points":
        pts = bullets or [s for s in _sentences(_plain_source(block.text))[:8] if s]
        return {"points": [_clip(p, 80) for p in pts[:12]]}
    if layout == "axis-table":
        if block.tables:
            table = block.tables[0]
            rows = [[_plain_source(str(c)) for c in row] for row in (table.get("rows") or [])[:12]]
            rows = [r for r in rows if any(c.strip() for c in r)]
            if rows:
                return {
                    "headers": [_plain_source(str(h)) for h in table.get("headers") or []],
                    "rows": rows,
                }
        src_bullets = bullets or _sentences(_plain_source(block.text))
        kv = [_split_kv(b) for b in src_bullets[:10]]
        if any(v for _, v in kv):
            # 「項目：内容」で書けるものは 2 列に。空列を作らない。
            return {
                "headers": ["項目", "内容"],
                "rows": [[_clip(k, 24), _clip(v, 44)] for k, v in kv if k],
            }
        # 分割できないときは単列にして空欄を出さない。
        return {"headers": ["ポイント"], "rows": [[_clip(b, 60)] for b in src_bullets[:10]]}
    if layout == "premise-conclusion":
        mid = max(len(bullets) // 2, 1)
        left_pts, right_pts = bullets[:mid], bullets[mid:] or bullets[:1]
        return {
            # 左は単列（空の 2 列目を作らない）。
            "left": {"header": "前提", "rows": [[_clip(p, 30)] for p in left_pts[:6]]},
            "right": {"header": "意味合い", "bullets": [_clip(p, 48) for p in right_pts[:5]]},
        }
    if layout in {"chevron-steps", "step-flow", "step-up", "three-step-column"}:
        flow = _flow_content(block, bullets)
        if layout == "chevron-steps":
            flow.pop("mode", None)
            flow.pop("branches", None)
        return flow
    if layout == "chart-insight" and numbers:
        labels = [b[:12] for b in (bullets or ["A", "B"])][:4]
        vals: list[float] = []
        for n in numbers[: len(labels) or 2]:
            try:
                vals.append(float(str(n).replace("%", "").replace(",", "")))
            except ValueError:
                vals.append(0)
        while len(labels) < 2:
            labels.append(f"項目{len(labels) + 1}")
        while len(vals) < len(labels):
            vals.append(0)
        return {
            "labels": labels,
            "values": vals,
            "insight": {"header": "意味合い", "bullets": bullets[:3] or [_clip(block.text, 40)]},
        }
    if layout == "fullscreen-photo" and images:
        return {"image": images[0], "headline": block.heading, "subMessages": []}
    if layout in NUMERIC_LAYOUTS and numbers:
        if layout == "kpi-three-col":
            items = []
            labels = bullets or [block.heading]
            for i, num in enumerate(numbers[:3]):
                items.append({"value": num, "label": labels[i] if i < len(labels) else block.heading})
            return {"items": items}
        if layout == "text-data-emphasis":
            return {
                "narrative": _clip(block.text or (bullets[0] if bullets else block.heading), 80),
                "bigNumber": numbers[0],
                "bigNumberLabel": _clip(bullets[1] if len(bullets) > 1 else block.heading, 20),
            }
        if layout == "horizontal-bar-ranking":
            items = []
            for i, num in enumerate(numbers[:6]):
                try:
                    value = float(str(num).replace("%", "").replace(",", ""))
                except ValueError:
                    value = 0
                label = bullets[i] if i < len(bullets) else f"項目{i + 1}"
                items.append({"label": label, "value": value})
            return {"items": items}
        if layout in {"pie-chart-highlight", "doughnut-three-col", "two-col-text-chart", "stacked-bar-chart"}:
            labels = [b[:12] for b in (bullets or ["A", "B", "C"])][:3]
            vals = []
            for n in numbers[: len(labels)]:
                try:
                    vals.append(float(str(n).replace("%", "").replace(",", "")))
                except ValueError:
                    vals.append(0)
            while len(vals) < len(labels):
                vals.append(0)
            if layout == "two-col-text-chart":
                return {
                    "left": {"heading": _clip(block.heading, 24), "body": _clip(block.text, 80)},
                    "right": {"chartType": "bar", "data": {"labels": labels, "values": vals}},
                }
            if layout == "stacked-bar-chart":
                return {"categories": labels, "series": [{"name": "値", "values": vals}]}
            if layout == "doughnut-three-col":
                return {"charts": [{"title": block.heading, "labels": labels, "values": vals}]}
            return {
                "data": {"labels": labels, "values": vals},
                "highlight": {"value": numbers[0], "message": bullets[0] if bullets else block.heading},
            }
        if layout == "kpi-formula":
            return {
                "kpiName": block.heading,
                "numerator": bullets[0] if bullets else "分子",
                "denominator": bullets[1] if len(bullets) > 1 else "分母",
            }

    if layout in {"checklist-table", "schedule-list"}:
        items = [{"label": _clip(b, 40), "checked": False, "note": ""} for b in bullets[:8]]
        if layout == "schedule-list":
            return {"phases": [{"phase": _clip(b, 24), "period": "", "owner": "", "details": ""} for b in bullets[:6]]}
        return {"headers": ["項目", "状態", "備考"], "items": items}

    if layout in {"comparison-table", "before-after-split"}:
        if layout == "comparison-table" and block.tables:
            table = block.tables[0]
            headers = [_plain_source(str(h)) for h in table.get("headers") or []]
            raw_rows = table.get("rows") or []
            if len(headers) >= 3:
                return {
                    "beforeTitle": headers[1] if len(headers) > 1 else "現状",
                    "afterTitle": headers[2] if len(headers) > 2 else "更改後",
                    "rows": [
                        {
                            "category": _plain_source(str(r[0])) if r else "",
                            "before": _plain_source(str(r[1])) if len(r) > 1 else "",
                            "after": _plain_source(str(r[2])) if len(r) > 2 else "",
                        }
                        for r in raw_rows[:12]
                    ],
                }
            return {
                "headers": headers,
                "rows": [[_plain_source(str(c)) for c in row] for row in raw_rows[:12]],
            }
        mid = max(len(bullets) // 2, 1)
        before, after = bullets[:mid], bullets[mid:] or bullets[:1]
        if layout == "before-after-split":
            return {"before": {"title": "現状", "points": before}, "after": {"title": "更改後", "points": after}}
        rows = []
        for i, b in enumerate(before):
            rows.append({"category": b, "before": b, "after": after[i] if i < len(after) else ""})
        return {"beforeTitle": "現状", "afterTitle": "更改後", "rows": rows}

    if layout == "qa-grid":
        items = []
        for i in range(0, min(len(bullets), 8), 2):
            items.append({"q": bullets[i], "a": bullets[i + 1] if i + 1 < len(bullets) else ""})
        if not items and block.text:
            items = [{"q": _clip(block.heading, 24), "a": _clip(block.text, 60)}]
        return {"items": items[:4]}

    if layout == "quote":
        src = bullets[0] if bullets else _plain_source(block.text)
        return {"text": _clip(src, 80), "author": "", "role": ""}

    if layout == "chat-dialogue":
        msgs = []
        for i, b in enumerate(bullets[:4]):
            msgs.append({"speaker": "質問" if i % 2 == 0 else "回答", "text": b})
        if not msgs:
            msgs = [{"speaker": "本文", "text": block.text[:160] or block.heading}]
        return {"messages": msgs}

    if layout in {"ceo-message"}:
        return {"name": _clip(block.heading, 20), "role": "", "message": _clip(block.text or " ".join(bullets), 90)}

    if layout in {"member-grid", "member-three-col"}:
        return {"members": [{"name": b, "role": "", "bio": ""} for b in bullets[:4]]}

    if layout == "case-two-col":
        return {
            "companyName": block.heading,
            "info": [{"key": "概要", "value": _clip(block.text or (bullets[0] if bullets else ""), 60)}],
            "metrics": [{"key": "要点", "value": bullets[1] if len(bullets) > 1 else ""}],
        }

    if layout in {"year-list", "timeline", "vertical-timeline"}:
        items = []
        for b in bullets[:6]:
            items.append({"date": "", "title": _clip(b, 22), "label": _clip(b, 22), "description": "", "heading": _clip(b, 22)})
        return {"items": items, "steps": items}

    if layout == "logo-wall":
        return {"logos": [{"name": b} for b in bullets[:8]]}

    if images and layout in DIAGRAM_LAYOUTS:
        return {"image": images[0], "headline": block.heading, "subMessages": bullets[:2]}

    items = []
    for b in bullets[:6]:
        items.append({"heading": _clip(b, 24), "description": _clip(b, 90) if len(b) > 24 else "", "title": _clip(b, 24)})
    if not items and block.text:
        for s in _sentences(_plain_source(block.text))[:6]:
            items.append({"heading": _clip(s, 24), "description": _clip(s, 90)})
    if images and not items:
        return {"image": images[0], "headline": _clip(block.heading, 28)}
    return {"items": items}


def _attach_notes(
    slide: dict[str, Any], block: SourceBlock | None, points: list[str] | None = None
) -> None:
    """ノート＝整理ノート（要点）＋原文。閾値は設けず、内容があれば常に付ける。"""
    if not block:
        return
    table_txt = ""
    for table in block.tables:
        headers = [str(h) for h in table.get("headers") or []]
        rows = [" | ".join(headers)]
        for row in table.get("rows") or []:
            rows.append(" | ".join(str(c) for c in row))
        table_txt = "\n".join(x for x in (table_txt, "\n".join(rows)) if x)
    original = _plain_source(
        "\n".join(x for x in (block.text, "\n".join(f"・ {b}" for b in block.bullets), table_txt) if x)
    )
    # コマンド等は字面が重要なので _plain_source を通さずそのまま残す。
    if block.code_blocks:
        original = "\n".join(x for x in (original, *block.code_blocks) if x)
    heading = block.heading or "本文"
    parts: list[str] = []
    if points:
        parts.append("整理ノート\n" + "\n".join(f"・ {p}" for p in points))
    mermaid = ""
    content = slide.get("content")
    if isinstance(content, dict):
        mermaid = str(content.get("mermaid") or "").strip()
    if mermaid:
        parts.append("図のMermaid\n" + mermaid)
    if original:
        parts.append(f"元の本文（{heading}）\n{original}")
    if not parts:
        return
    slide["notes"] = "\n\n".join(parts)


# 1 回の JSON で全節をまとめると、節数が多い/長い実文書ではモデル出力が破綻して
# 全滅しやすい。小さなバッチに分けて各回を確実にする（1 バッチ失敗は他に波及しない）。
_NOTES_BATCH = 4


def _mk_sub(on_progress: Any, lo: float, hi: float) -> Any:
    """全体 0-1 のうち [lo,hi] 区間へ写像するサブ進捗コールバックを作る。"""
    if not on_progress:
        return None

    def sub(frac: float, label: str) -> None:
        on_progress(lo + (hi - lo) * max(0.0, min(1.0, frac)), label)

    return sub


def _notes_for_batch(
    complete: Any, name: str, subset: list[SourceBlock]
) -> dict[tuple[str, str], SectionNotes]:
    outline = _outline_for_prompt(name, subset)
    try:
        data = _call_json(
            complete,
            "あなたは日本語の要点整理係。各節の役割と要点だけを返す。本文は書かない。JSON のみ。",
            (
                f"{outline}\n\n"
                "各節を次の JSON だけに圧縮する。\n"
                '{"slides":[{"source":{"filename":"...","heading":"..."},'
                '"role":"explanation","title":"任意の短い見出し",'
                '"figure":"","figure_caption":"",'
                '"points":["要点1","要点2"]}]}\n'
                "- role は explanation / procedure / definition / comparison / numeric / caution / attachment。\n"
                "- 分からなければ explanation。手順は procedure。用語・表だけの一覧は definition。\n"
                "- 対比は comparison。件数・割合など短い指標は numeric。文書番号・版数・日付・所要時間の欄は definition。\n"
                "- 注意・例外は caution。貼付文・コードだけは attachment。\n"
                "- figure は見出し語ではなく中身で判断する。関係・分岐・完成イメージ・構成を図で見せるべきなら flowchart（流れ以外は sequence）。\n"
                "- 表・短い手順の列挙・数値・文章だけの説明は figure を空文字。\n"
                "- figure_caption は図の題（ここに○○の図を入れる、の○○）。\n"
                "- points はスライドに載せる密度を保つ。原文にある事実だけ。新しい数値・固有名を作らない。\n"
                "- 表・用語一覧は列名の列挙で終わらせない。各行の値を残す（最大8行）。\n"
                "- 手順は各ステップを残す。目的だけの1点に潰さない。\n"
                "- 「表にまとめられている」など中身の無い要約は禁止。\n"
                "- コードやプロンプトの貼付文は points に載せない。\n"
                "- title は任意。見出しのコピーにせず、ですます禁止。\n"
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("notes batch failed: %s", exc)
        return {}
    if not data or not isinstance(data.get("slides"), list):
        return {}
    from app.pptx_figure import _normalize_figure

    organized: dict[tuple[str, str], SectionNotes] = {}
    for s in data["slides"]:
        if not isinstance(s, dict):
            continue
        block = _find_block(subset, s.get("source"))
        if not block:
            continue
        raw_points = s.get("points")
        if not isinstance(raw_points, list):
            raw_points = []
        allowed = _block_allowed(name, block)
        points: list[str] = []
        for p in raw_points:
            text = _plain_source(str(p or "")).replace("\n", "").strip()
            if not text or _introduces_novel_facts(text, allowed):
                continue
            points.append(text)
        title = str(s.get("title") or "").strip()
        if title and _introduces_novel_facts(title, allowed):
            title = ""
        figure = _normalize_figure(s.get("figure"))
        caption = str(s.get("figure_caption") or "").strip()
        if caption and _introduces_novel_facts(caption, allowed):
            caption = ""
        if points or figure:
            organized[_block_key(block)] = SectionNotes(
                role=_normalize_role(s.get("role")),
                points=_enrich_notes(points, block) or _mechanical_notes(block),
                title=title,
                figure=figure,
                figure_caption=caption,
            )
    return organized


def _table_cells(block: SourceBlock) -> list[str]:
    cells: list[str] = []
    for table in block.tables:
        for h in table.get("headers") or []:
            text = _plain_source(str(h)).strip()
            if text:
                cells.append(text)
        for row in table.get("rows") or []:
            for c in row:
                text = _plain_source(str(c)).strip()
                if text:
                    cells.append(text)
    return cells


def _block_allowed(name: str, block: SourceBlock) -> str:
    return _allowed_text(
        name,
        block.heading,
        block.text,
        "\n".join(block.bullets),
        "\n".join(_table_cells(block)),
        "\n".join(block.code_blocks),
        "\n".join(block.mermaid_blocks),
    )


def _table_row_points(block: SourceBlock, limit: int = 8) -> list[str]:
    """表の各行を、スライドに載せる要点にする。列名だけの要約は作らない。"""
    points: list[str] = []
    for table in block.tables:
        for row in (table.get("rows") or [])[:limit]:
            cells = [_plain_source(str(c)).replace("\n", "").strip() for c in row]
            cells = [c for c in cells if c]
            if cells:
                points.append(_clip(" / ".join(cells), 80))
    return points


def _covers_table_rows(points: list[str], block: SourceBlock) -> bool:
    blob = "\n".join(points)
    found = False
    for table in block.tables:
        for row in table.get("rows") or []:
            for c in row:
                cell = _plain_source(str(c)).strip()
                if len(cell) >= 2 and cell in blob:
                    found = True
                    break
            if found:
                break
        if found:
            break
    return found or not any(table.get("rows") for table in block.tables)


def _is_table_meta_point(text: str, block: SourceBlock) -> bool:
    """「表がある」だけで行の値を含まない要点。"""
    if not block.tables:
        return False
    blob = text.strip()
    headers = {_plain_source(str(h)).strip() for t in block.tables for h in (t.get("headers") or [])}
    for cell in _table_cells(block):
        if len(cell) >= 4 and cell not in headers and cell in blob:
            return False
    if blob.startswith("表（") and "行）" in blob:
        return True
    return any(m in blob for m in ("表に", "表形式", "列挙", "表で構成", "一覧を示す"))


def _enrich_notes(points: list[str], block: SourceBlock) -> list[str]:
    """スライドに載せる事実が落ちていれば、原文の行・手順で補う。"""
    kept = [p for p in points if p and not _is_table_meta_point(p, block)]
    row_pts = _table_row_points(block)
    if row_pts and not _covers_table_rows(kept, block):
        kept = row_pts + kept
    steps = [_plain_source(b).replace("\n", "").strip() for b in block.bullets]
    steps = [s for s in steps if s]
    if len(steps) >= 2:
        blob = "\n".join(kept)
        if not any(s[:8] in blob for s in steps if len(s) >= 4):
            kept = steps[:8] + kept
    out: list[str] = []
    seen: set[str] = set()
    for item in kept:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out[:12]


def _mechanical_notes(block: SourceBlock) -> list[str]:
    """LLM が空のときの整理ノート。手順書の目的・番号付き手順・表題を要点にする。"""
    points: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        item = _plain_source(text).replace("\n", "").strip()
        if not item or item in seen:
            return
        seen.add(item)
        points.append(_clip(item, 72))

    for raw in block.bullets[:8]:
        _add(raw)
    for line in (block.text or "").splitlines():
        stripped = line.strip()
        lab = _LABEL_RE.match(stripped)
        if lab:
            label, rest = lab.group(1).strip(), lab.group(2).strip()
            if rest:
                _add(f"{label}: {rest}")
            elif label:
                _add(label)
            continue
        if stripped.startswith("**") and stripped.endswith("**") and len(stripped) > 4:
            _add(stripped.strip("*"))
    for row_pt in _table_row_points(block):
        _add(row_pt)
    if block.code_blocks:
        pointer = "貼り付け用の文面はノートの原文を参照"
        if pointer not in points:
            if len(points) >= 8:
                points[-1] = pointer
            else:
                points.append(pointer)
    if not points:
        for s in _sentences(_plain_source(block.text))[:4]:
            _add(s)
    return points[:12]


def _plan_notes(
    complete: Any,
    name: str,
    blocks: list[SourceBlock],
    on_progress: Any = None,
) -> dict[tuple[str, str], SectionNotes]:
    """節ごとに {role, points} を取る。LLM は圧縮だけ。失敗した節は機械推定。"""
    organized: dict[tuple[str, str], SectionNotes] = {}
    total = max(len(blocks), 1)
    for i in range(0, len(blocks), _NOTES_BATCH):
        subset = blocks[i : i + _NOTES_BATCH]
        if complete:
            organized.update(_notes_for_batch(complete, name, subset))
        for block in subset:
            key = _block_key(block)
            if not organized.get(key):
                mechanical = _mechanical_notes(block)
                if mechanical:
                    organized[key] = SectionNotes(role=_guess_role(block), points=mechanical)
            elif organized.get(key):
                notes = organized[key]
                organized[key] = SectionNotes(
                    role=notes.role,
                    points=_enrich_notes(notes.points, block),
                    title=notes.title,
                    figure=notes.figure,
                    figure_caption=notes.figure_caption,
                )
        if on_progress:
            done = min(i + _NOTES_BATCH, len(blocks))
            on_progress(done / total, f"要点を整理 ({done}/{len(blocks)})")
    return organized


def _outline_for_prompt(
    name: str, blocks: list[SourceBlock], *, excerpts: bool = True
) -> str:
    lines = [f"文書名: {name}", "章・節:"]
    for i, block in enumerate(blocks, 1):
        flags = []
        if block.images:
            flags.append(f"画像:{','.join(block.images)}")
        if block.tables:
            flags.append("表あり")
        if block.code_blocks:
            flags.append("貼付文あり")
        if block.mermaid_blocks:
            flags.append("図あり")
        extra = f" {' '.join(flags)}" if flags else ""
        lines.append(f"{i}. file={block.filename} heading={block.heading or '(無題)'}{extra}")
        if excerpts:
            excerpt = (block.text or " ".join(block.bullets))[:280]
            if excerpt:
                lines.append(f"   抜粋: {excerpt}")
            if block.mermaid_blocks:
                lines.append(f"   図: {block.mermaid_blocks[0][:160]}")
            if block.tables:
                headers = block.tables[0].get("headers") or []
                lines.append(f"   表列: {', '.join(str(h) for h in headers)}")
                for row in (block.tables[0].get("rows") or [])[:4]:
                    lines.append(f"   表行: {' | '.join(str(c) for c in row)}")
    return "\n".join(lines)


def _planned_from_blocks(name: str, blocks: list[SourceBlock]) -> list[dict[str, Any]]:
    """見出し骨格。空の親見出しは落とす。"""
    planned: list[dict[str, Any]] = [{"type": "cover", "title": name, "subtitle": ""}]
    for block in blocks:
        if not (
            block.text
            or block.bullets
            or block.tables
            or block.code_blocks
            or block.mermaid_blocks
            or _content_images(block.images)
        ):
            continue
        planned.append(
            {
                "type": "content",
                "title": block.heading or name,
                "source": {"filename": block.filename, "heading": block.heading},
            }
        )
    return planned


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    m = _JSON_FENCE_RE.search(raw)
    if m:
        raw = m.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


_FREEFORM_GUIDE = (
    "スライドのコンテンツ領域は 12 列 × 6 行のグリッド（左右余白・本文開始位置は固定）。"
    "各要素に col(0-11), row(0-5), colspan(1-12), rowspan(1-6) を付け、重ならないように置く。\n"
    "配置は横帯か左右2列で揃える。左上と右下だけに置いて斜めにしない。\n"
    "KPI は上段に横並び（row 0-1）。表・本文は下段に全幅（row 2-5）。比較は左右2列。\n"
    "カード（box+fill=surface）の羅列は使わない。\n"
    "kind: heading(見出し, text) / text(本文, text) / bullets(箇条書き, bullets[]) / "
    "box(面パネル+任意text) / kpi(大きな数値, value,label) / table(headers[],rows[][]) / "
    "image(assets の相対パス, image)。\n"
    "style: tone∈{ink,body,muted,accent}, size∈{small,body,head,title,metric}, bold(bool), "
    "align∈{left,center,right}, fill∈{none,surface,accent}。\n"
    "配色は DADS のトークンのみ（任意色・角丸は使わない）。原文にある事実だけを使い、"
    "新しい数値・固有名を作らない。"
    "スライド題名はヘッダーに既にあるので、同じ文言の heading は置かない。"
    "KPI は短い数値（50%、3件）だけ。文書番号・日付・固有名は table か bullets。"
)


def _ground_strings(values: list[str], allowed: str) -> list[str]:
    out: list[str] = []
    for v in values:
        text = _plain_source(str(v or "")).replace("\n", "").strip()
        if not text or _introduces_novel_facts(text, allowed):
            continue
        out.append(text)
    return out


def _ground_element(el: dict[str, Any], allowed: str) -> dict[str, Any] | None:
    """要素内テキストを原文グラウンディングし、空なら None。座標/スタイルは温存。"""
    kind = str(el.get("kind") or "text").strip().lower()
    keep: dict[str, Any] = {
        k: el.get(k)
        for k in ("kind", "col", "row", "colspan", "rowspan", "style")
        if el.get(k) is not None
    }
    keep["kind"] = kind
    if kind in ("heading", "text", "box"):
        vals = _ground_strings([el.get("text") or ""], allowed)
        if not vals:
            return None
        keep["text"] = vals[0]
    elif kind == "bullets":
        vals = _ground_strings([str(b) for b in (el.get("bullets") or [])], allowed)
        if not vals:
            return None
        keep["bullets"] = vals
    elif kind == "kpi":
        value = _ground_strings([el.get("value") or el.get("text") or ""], allowed)
        if not value:
            return None
        keep["value"] = value[0]
        lbl = _ground_strings([el.get("label") or ""], allowed)
        keep["label"] = lbl[0] if lbl else ""
    elif kind == "table":
        headers = _ground_strings([str(h) for h in (el.get("headers") or [])], allowed)
        rows = []
        for r in el.get("rows") or []:
            cells = _ground_strings(
                [str(c) for c in (r if isinstance(r, list) else [r])], allowed
            )
            if cells:
                rows.append(cells)
        if not headers and not rows:
            return None
        keep["headers"] = headers
        keep["rows"] = rows
    elif kind == "image":
        rel = str(el.get("image") or el.get("src") or "").strip()
        if not rel:
            return None
        keep["image"] = rel
    else:
        return None
    return keep


def _compose_freeform(
    complete: Any,
    name: str,
    block: SourceBlock,
    points: list[str] | None,
    title: str,
) -> dict[str, Any] | None:
    """LLM にスライドの要素配置（グリッド）を作らせる。原文グラウンディング＋失敗で None。"""
    pts = points or list(block.bullets) or _sentences(_plain_source(block.text))[:6]
    excerpt = _plain_source(block.text)[:600]
    code = "\n".join(block.code_blocks)[:600]
    user = (
        f"{_FREEFORM_GUIDE}\n\n"
        f"スライドのタイトル: {title}\n"
        "要点:\n" + "\n".join(f"- {p}" for p in pts[:8]) + "\n"
        + (f"原文抜粋:\n{excerpt}\n" if excerpt else "")
        + (f"コマンド等:\n{code}\n" if code else "")
        + "\n次の JSON だけを返す。題名と同じ heading は含めない。\n"
        '{"elements":[{"kind":"bullets","col":0,"row":0,"colspan":6,"rowspan":6,"bullets":["..."]}]}\n'
    )
    try:
        text = complete(
            [
                {"role": "system", "content": "あなたはスライド構成係。JSON のみを返す。"},
                {"role": "user", "content": user},
            ],
            model=compose_model(),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("freeform compose failed: %s", exc)
        return None
    data = _parse_llm_json(text)
    if not data or not isinstance(data.get("elements"), list):
        return None
    table_txt = " ".join(
        " ".join(str(c) for c in (t.get("headers") or [])) for t in block.tables
    )
    allowed = _allowed_text(
        name,
        block.heading,
        block.text,
        "\n".join(block.bullets),
        "\n".join(points or []),
        table_txt,
        "\n".join(block.code_blocks),
    )
    kept: list[dict[str, Any]] = []
    for el in data["elements"]:
        if not isinstance(el, dict):
            continue
        grounded = _ground_element(el, allowed)
        if grounded:
            kept.append(grounded)
        if len(kept) >= 14:
            break
    return {"elements": kept} if kept else None


_MAX_POINTS = 6
_MAX_TABLE_ROWS = 8


def _chunks(items: list[Any], n: int) -> list[list[Any]]:
    return [items[i : i + n] for i in range(0, len(items), n)] or [[]]


def _split_dense(
    layout: str, content: dict[str, Any], title: str
) -> list[tuple[str, dict[str, Any], str]]:
    """溢れたら縮小せず枚を分ける。"""
    if layout == "axis-table":
        rows = list(content.get("rows") or [])
        if len(rows) > _MAX_TABLE_ROWS:
            headers = content.get("headers")
            out: list[tuple[str, dict[str, Any], str]] = []
            for i, part in enumerate(_chunks(rows, _MAX_TABLE_ROWS)):
                ttl = title if i == 0 else f"{title}（続き）"
                out.append((layout, {**content, "headers": headers, "rows": part}, ttl))
            return out
    if layout == "fullwidth-points":
        pts = [str(p) for p in (content.get("points") or []) if str(p).strip()]
        if len(pts) > _MAX_POINTS:
            return [
                (layout, {"points": part}, title if i == 0 else f"{title}（続き）")
                for i, part in enumerate(_chunks(pts, _MAX_POINTS))
            ]
    if layout in {"chevron-steps", "step-flow", "step-up", "three-step-column"}:
        steps = list(content.get("steps") or content.get("items") or [])
        if len(steps) > 3:
            return [
                (layout, {**content, "steps": part, "items": part}, title if i == 0 else f"{title}（続き）")
                for i, part in enumerate(_chunks(steps, 3))
            ]
    items = content.get("items")
    if isinstance(items, list) and len(items) > _MAX_POINTS:
        return [
            (layout, {**content, "items": part}, title if i == 0 else f"{title}（続き）")
            for i, part in enumerate(_chunks(items, _MAX_POINTS))
        ]
    return [(layout, content, title)]


def _fill_block(block: SourceBlock, points: list[str] | None) -> SourceBlock:
    """整理ノートがあれば、それを bullets にした複製で充填する（原文は温存）。"""
    if not points:
        return block
    return replace(block, bullets=list(points))


def _placeholder_content(heading: str) -> tuple[str, dict[str, Any]]:
    """本文を抽出できないときの代替。空スライドにせず、ノート参照の断りを出す。"""
    log.info("pptx: 本文を抽出できずプレースホルダ表示: %s", heading)
    return (
        "fullwidth-points",
        {"points": ["この節の詳細はノート（原文）を参照してください。"]},
    )


def _default_freeform(block: SourceBlock, points: list[str] | None) -> dict[str, Any]:
    """機械配置。上段に横並び、下段に全幅。斜め（左上と右下だけ）には置かない。"""
    from app.pptx_repair import is_metric_value, looks_like_meta

    pts = [p for p in (points or list(block.bullets) or _sentences(_plain_source(block.text))) if p][:8]
    numbers = [
        n
        for n in _NUMBER_RE.findall(block.text + "\n" + "\n".join(block.bullets) + "\n" + "\n".join(pts))
        if is_metric_value(n)
    ]
    elements: list[dict[str, Any]] = []
    if numbers and not looks_like_meta(block.heading, block.text, *block.bullets, *pts):
        span = max(4, 12 // min(len(numbers), 3))
        for i, num in enumerate(numbers[:3]):
            elements.append(
                {
                    "kind": "kpi",
                    "col": i * span,
                    "row": 0,
                    "colspan": span,
                    "rowspan": 2,
                    "value": num,
                    "label": _clip(pts[i] if i < len(pts) else block.heading, 20),
                }
            )
        if block.tables:
            table = block.tables[0]
            elements.append(
                {
                    "kind": "table",
                    "col": 0,
                    "row": 2,
                    "colspan": 12,
                    "rowspan": 4,
                    "headers": [str(h) for h in table.get("headers") or []],
                    "rows": [[str(c) for c in row] for row in (table.get("rows") or [])[:6]],
                }
            )
        elif pts:
            elements.append(
                {"kind": "bullets", "col": 0, "row": 2, "colspan": 12, "rowspan": 4, "bullets": pts[:6]}
            )
    elif block.tables:
        if pts:
            elements.append(
                {"kind": "bullets", "col": 0, "row": 0, "colspan": 12, "rowspan": 2, "bullets": pts[:4]}
            )
        table = block.tables[0]
        elements.append(
            {
                "kind": "table",
                "col": 0,
                "row": 2,
                "colspan": 12,
                "rowspan": 4,
                "headers": [str(h) for h in table.get("headers") or []],
                "rows": [[str(c) for c in row] for row in (table.get("rows") or [])[:8]],
            }
        )
    else:
        elements.append(
            {"kind": "bullets", "col": 0, "row": 0, "colspan": 12, "rowspan": 6, "bullets": pts[:6] or [block.heading]}
        )
    return {"elements": elements}


def _maybe_freeform(
    complete: Any,
    name: str,
    block: SourceBlock,
    points: list[str] | None,
    title: str,
) -> tuple[str, dict[str, Any]] | None:
    """フェーズ B が有効なら freeform 配置を試す。失敗時は階層の機械配置。"""
    if not pptx_freeform_enabled():
        return None
    if complete:
        try:
            elements = _compose_freeform(complete, name, block, points, title)
        except Exception as exc:  # noqa: BLE001
            log.warning("freeform skipped: %s", exc)
            elements = None
        if elements:
            return "freeform", elements
    return "freeform", _default_freeform(block, points)


def _slide_body(
    layout: str, block: SourceBlock, points: list[str] | None
) -> tuple[str, dict[str, Any]]:
    filled = _fill_block(block, points)
    content = _fill_content(layout, filled)
    if layout in TABLE_LAYOUTS and not (content.get("rows") or []):
        layout = "fullwidth-points"
        content = _fill_content(layout, filled)
    return layout, content


def _variants_for_block(
    name: str,
    block: SourceBlock,
    notes: SectionNotes | None,
    previous_layout: str,
    assets: dict[str, bytes] | None,
    complete: Any,
) -> tuple[list[tuple[str, dict[str, Any], str]], list[str] | None]:
    from app.pptx_figure import figure_content

    from app.pptx_repair import strip_title_echo

    points = notes.points if notes else None
    title = str((notes.title if notes else "") or block.heading or name)
    fig = figure_content(block, notes, assets)
    if fig:
        variants = [("figure-frame", fig, title)]
    else:
        layout = _role_to_layout(notes.role if notes else _guess_role(block), block, previous_layout)
        if (
            points
            and layout in TABLE_LAYOUTS
            and (block.bullets or block.code_blocks or len(_plain_source(block.text)) > 80)
        ):
            layout = "fullwidth-points"
        free = _maybe_freeform(complete, name, block, points, title)
        if free:
            variants = [(*free, title)]
        else:
            layout, content = _slide_body(layout, block, points)
            if not content_nonempty(content):
                layout, content = _placeholder_content(block.heading or name)
            variants = _split_dense(layout, content, title)
    return [(lay, strip_title_echo(ttl, cont), ttl) for lay, cont, ttl in variants], points


def _complete_slides(
    name: str,
    planned: list[dict[str, Any]],
    blocks: list[SourceBlock],
    organized: dict[tuple[str, str], SectionNotes] | None = None,
    complete: Any = None,
    on_progress: Any = None,
    assets: dict[str, bytes] | None = None,
) -> dict[str, Any] | None:
    organized = organized or {}
    slides: list[dict[str, Any]] = []
    covered: set[tuple[str, str]] = set()
    previous_layout = ""
    # 進捗用に、本文スライドの総数（planned の content + 未カバー節）を見積もる。
    planned_content = sum(
        1 for r in planned if isinstance(r, dict) and str(r.get("type") or "content") == "content"
    )
    total_content = max(planned_content + len(blocks), 1)
    built = 0

    def _tick(block: SourceBlock) -> None:
        nonlocal built
        built += 1
        if on_progress:
            on_progress(built / total_content, f"スライドを構成 ({built}/{total_content})")
    if not planned or planned[0].get("type") != "cover":
        slides.append({"type": "cover", "title": name, "subtitle": ""})
    for raw in planned:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "content")
        if kind == "cover":
            title = str(raw.get("title") or name)
            subtitle = str(raw.get("subtitle") or "")
            existing = next((s for s in slides if s.get("type") == "cover"), None)
            if existing:
                existing["title"] = title or existing["title"]
                existing["subtitle"] = subtitle
            else:
                slides.insert(0, {"type": "cover", "title": title, "subtitle": subtitle})
            continue
        if kind == "ending":
            # 営業デッキの「ご清聴」締めは付けない。文書の章だけをスライドにする。
            continue
        if kind == "section":
            title = str(raw.get("title") or "")
            if not title:
                continue
            slides.append({"type": "section", "title": title, "subtitle": str(raw.get("subtitle") or "")})
            continue
        block = _find_block(blocks, raw.get("source"))
        if not block:
            continue
        notes = organized.get(_block_key(block))
        variants, points = _variants_for_block(
            name, block, notes, previous_layout, assets, complete
        )
        for lay, cont, ttl in variants:
            slide = {
                "type": "content" if kind != "case-study" else "case-study",
                "title": ttl,
                "layout": lay,
                "content": cont,
            }
            _attach_notes(slide, block, points)
            slides.append(slide)
            previous_layout = lay
        covered.add(_block_key(block))
        _tick(block)
    for block in blocks:
        if _block_key(block) in covered:
            continue
        if not (
            block.text
            or block.bullets
            or block.tables
            or block.code_blocks
            or block.mermaid_blocks
            or _content_images(block.images)
        ):
            continue
        notes = organized.get(_block_key(block))
        variants, points = _variants_for_block(
            name, block, notes, previous_layout, assets, complete
        )
        for lay, cont, ttl in variants:
            slide = {
                "type": "content",
                "title": ttl,
                "layout": lay,
                "content": cont,
            }
            _attach_notes(slide, block, points)
            slides.append(slide)
            previous_layout = lay
        _tick(block)
    return validate_deck({"slides": slides})


_NOVEL_KATA_RE = re.compile(r"[ァ-ヴー]{3,}")
_NOVEL_LATIN_RE = re.compile(r"[A-Za-z]{4,}")
_NOVEL_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def _allowed_text(*parts: Any) -> str:
    return "\n".join(str(p or "") for p in parts)


def _introduces_novel_facts(text: str, allowed: str) -> bool:
    """新しい数値やカタカナ固有名が allowed に無いとき True。"""
    for num in _NOVEL_NUM_RE.findall(text or ""):
        if num not in allowed:
            return True
    for token in _NOVEL_KATA_RE.findall(text or ""):
        if token not in allowed:
            return True
    for token in _NOVEL_LATIN_RE.findall(text or ""):
        if token not in allowed:
            return True
    return False


def _call_json(complete: Any, system: str, user: str) -> dict[str, Any] | None:
    text = complete([{"role": "system", "content": system}, {"role": "user", "content": user}])
    return _parse_llm_json(text)


def _review_payload(deck: dict[str, Any]) -> str:
    lines = ["タイトル一覧:"]
    pages: list[dict[str, Any]] = []
    for i, slide in enumerate(deck.get("slides") or []):
        title = str(slide.get("title") or "")
        lines.append(f"{i}. {title}")
        pages.append(
            {
                "index": i,
                "type": slide.get("type"),
                "title": title,
                "layout": slide.get("layout"),
                "content": slide.get("content") if isinstance(slide.get("content"), dict) else {},
                "notes": slide.get("notes") or "",
            }
        )
    return json.dumps({"outline": lines, "slides": pages}, ensure_ascii=False)


def _apply_review(deck: dict[str, Any], review: dict[str, Any]) -> dict[str, Any]:
    slides = list(deck.get("slides") or [])
    changes = review.get("changes")
    if not isinstance(changes, list):
        return deck
    for change in changes:
        if not isinstance(change, dict):
            continue
        if change.get("adopt") is False:
            continue
        try:
            idx = int(change.get("index"))
        except (TypeError, ValueError):
            continue
        if idx < 0 or idx >= len(slides):
            continue
        slide = slides[idx]
        allowed = _allowed_text(
            slide.get("title"),
            slide.get("notes"),
            json.dumps(slide.get("content") or {}, ensure_ascii=False),
        )
        new_title = change.get("title")
        if isinstance(new_title, str) and new_title.strip():
            if _introduces_novel_facts(new_title, allowed):
                log.info("pptx review: drop title with novel facts at %s", idx)
            else:
                slide["title"] = new_title.strip()
        content = slide.get("content") if isinstance(slide.get("content"), dict) else None
        right = change.get("right") or change.get("insight")
        if content and isinstance(right, dict):
            bullets = right.get("bullets")
            if isinstance(bullets, list):
                cleaned = []
                for b in bullets:
                    text = str(b or "").strip()
                    if not text or _introduces_novel_facts(text, allowed):
                        continue
                    cleaned.append(text)
                if cleaned:
                    if isinstance(content.get("right"), dict):
                        content["right"]["bullets"] = cleaned
                    elif isinstance(content.get("insight"), dict):
                        content["insight"]["bullets"] = cleaned
                    else:
                        content["insight"] = {"header": "意味合い", "bullets": cleaned}
                    slide["content"] = content
    return {"slides": slides}


def plan_deck(
    name: str,
    sections: list[dict[str, Any]],
    assets: dict[str, bytes] | None = None,
    *,
    complete: Any = chat,
    on_progress: Any = None,
) -> dict[str, Any] | None:
    """見出し骨格のうえに、節ごとの {role, points} を載せる。失敗時は None。"""
    if not llm_enabled():
        log.info("pptx plan skipped (GENERATE_PPTX_LLM=0)")
        return None

    def op(frac: float, label: str) -> None:
        if on_progress:
            on_progress(frac, label)
    blocks = parse_source_blocks(name, sections)
    try:
        op(0.05, "構成を準備")
        planned = _planned_from_blocks(name, blocks)
        op(0.15, "見出しを整理")
        organized = _plan_notes(
            complete, name, blocks, on_progress=_mk_sub(on_progress, 0.15, 0.7)
        )
        deck = _complete_slides(
            name,
            planned,
            blocks,
            organized,
            complete=complete,
            on_progress=_mk_sub(on_progress, 0.7, 0.9),
            assets=assets,
        )
        if not deck:
            log.warning("pptx plan: 検証後の deck が空です")
            return None
        from app.pptx_repair import repair_deck

        deck = repair_deck(deck) or deck
        op(0.9, "推敲")
        if review_enabled():
            try:
                review = _call_json(
                    complete,
                    "資料の作り方は知らない。日本語と論理だけを見る。JSON のみ。",
                    (
                        "次のデッキを読み、タイトルのですます・個数・ラベル前置き、"
                        "タイトルと本文の食い違い、根拠のない評価語を指摘する。\n"
                        "新しい数値・固有名は提案しない。不採用は adopt:false。\n"
                        '{"changes":[{"index":1,"adopt":true,"title":"直した主張",'
                        '"right":{"bullets":["意味合い"]}}]}\n\n'
                        f"{_review_payload(deck)}\n"
                    ),
                )
                if review:
                    deck = _apply_review(deck, review)
                    deck = repair_deck(deck) or deck
                    deck = validate_deck(deck) or deck
            except Exception as exc:  # noqa: BLE001
                log.warning("pptx plan: レビュー失敗（Pass2 までを採用）: %s", exc)
        log.info("pptx plan: %s slides", len(deck.get("slides") or []))
        return deck
    except Exception as exc:  # noqa: BLE001
        log.warning("pptx plan failed: %s", exc)
        return None
