"""Markdown 章から deck JSON を組み立てる（LLM は枚割りと layout、本文は機械充填）。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.llm import chat, llm_enabled, review_enabled
from app.pptx_catalog import (
    DEFAULT_LAYOUT,
    DIAGRAM_LAYOUTS,
    LAYOUT_IDS,
    NUMERIC_LAYOUTS,
    SELECTION_GUIDE,
    content_nonempty,
    normalize_layout,
)
from app.compose_formats import _TABLE_LINE_RE, parse_gfm_table
from app.pptx_layouts import validate_deck
from app.pptx_rules import rules_excerpt

log = logging.getLogger("procuretech-generate")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)>\s]+)>?")
_NUMBER_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?\s*%|[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.I)


TABLE_LAYOUTS = frozenset(
    {"axis-table", "comparison-table", "checklist-table", "pricing-table"}
)


@dataclass
class SourceBlock:
    filename: str
    heading: str
    text: str
    images: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)
    tables: list[dict[str, Any]] = field(default_factory=list)


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
    if current.heading or current.text or current.bullets or current.images or current.tables:
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
        for raw in content.splitlines():
            stripped = raw.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
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


def _block_key(block: SourceBlock) -> tuple[str, str]:
    return (block.filename, block.heading)


def _suggest_layout(block: SourceBlock, previous: str) -> str:
    """章の性質と直前 layout から、連続しない見せ方を選ぶ。"""
    heading = block.heading or ""
    blob = f"{heading}\n{block.text}\n{' '.join(block.bullets)}"
    images = _content_images(block.images)
    if block.tables and not images:
        return "axis-table" if previous != "axis-table" else "comparison-table"
    if images:
        return "fullscreen-photo" if previous != "fullscreen-photo" else "numbered-feature-cards"
    if _NUMBER_RE.search(blob) and any(k in heading for k in ("規模", "KPI", "KGI", "目標", "件数", "数値")):
        return "chart-insight" if previous != "chart-insight" else "kpi-three-col"
    if any(k in heading for k in ("手順", "フロー", "プロセス", "工程")):
        return "chevron-steps"
    if any(k in heading for k in ("比較", "更改", "Before", "After")):
        return "before-after-split"
    if any(k in heading for k in ("課題", "問題", "ペイン", "前提", "結論")):
        return "premise-conclusion"
    if any(k in heading for k in ("スケジュール", "日程", "計画")):
        return "schedule-list"
    rotate = [
        "axis-table",
        "premise-conclusion",
        "parallel-items",
        "numbered-feature-cards",
        "checklist-table",
    ]
    for name in rotate:
        if name != previous:
            return name
    return DEFAULT_LAYOUT


def _fill_content(layout: str, block: SourceBlock) -> dict[str, Any]:
    bullets = [_plain_source(b) for b in block.bullets if _plain_source(b)]
    if not bullets:
        bullets = [s for s in _sentences(_plain_source(block.text))[:6] if s]
    images = _content_images(block.images)
    numbers = _NUMBER_RE.findall(block.text + "\n" + "\n".join(block.bullets))

    if layout == "axis-table":
        if block.tables:
            table = block.tables[0]
            return {
                "headers": [_plain_source(str(h)) for h in table.get("headers") or []],
                "rows": [[_plain_source(str(c)) for c in row] for row in (table.get("rows") or [])[:12]],
            }
        headers = ["項目", "内容"]
        rows = [[_clip(b, 28), ""] for b in bullets[:8]]
        if not rows and block.text:
            rows = [[_clip(s, 28), ""] for s in _sentences(_plain_source(block.text))[:6]]
        return {"headers": headers, "rows": rows}
    if layout == "premise-conclusion":
        mid = max(len(bullets) // 2, 1)
        left_pts, right_pts = bullets[:mid], bullets[mid:] or bullets[:1]
        return {
            "left": {"header": "前提", "rows": [[_clip(p, 20), ""] for p in left_pts[:5]]},
            "right": {"header": "意味合い", "bullets": [_clip(p, 40) for p in right_pts[:4]]},
        }
    if layout == "chevron-steps":
        steps = []
        for i, b in enumerate(bullets[:6] or _sentences(_plain_source(block.text))[:5]):
            steps.append({"n": str(i + 1), "title": _clip(b, 16), "text": _clip(b, 28) if len(b) > 16 else ""})
        return {"steps": steps}
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

    if layout in {"year-list", "timeline", "vertical-timeline", "step-flow", "step-up", "three-step-column"}:
        items = []
        for b in bullets[:6]:
            items.append({"date": "", "title": _clip(b, 22), "label": _clip(b, 22), "description": "", "heading": _clip(b, 22)})
        return {"items": items, "steps": items}

    if layout == "logo-wall":
        return {"logos": [{"name": b} for b in bullets[:8]]}

    if images and layout in DIAGRAM_LAYOUTS:
        return {"image": images[0], "headline": block.heading, "subMessages": bullets[:2]}

    items = []
    for b in bullets[:4]:
        items.append({"heading": _clip(b, 22), "description": _clip(b, 56) if len(b) > 22 else "", "title": _clip(b, 22)})
    if not items and block.text:
        for s in _sentences(_plain_source(block.text))[:4]:
            items.append({"heading": _clip(s, 22), "description": _clip(s, 56)})
    if images and not items:
        return {"image": images[0], "headline": _clip(block.heading, 28)}
    return {"items": items}


def _attach_notes(slide: dict[str, Any], block: SourceBlock | None) -> None:
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
    if not original:
        return
    if len(original) < 20:
        return
    heading = block.heading or "本文"
    slide["notes"] = f"元の本文（{heading}）\n{original}"


def _outline_for_prompt(name: str, blocks: list[SourceBlock]) -> str:
    lines = [f"文書名: {name}", "章・節:"]
    for i, block in enumerate(blocks, 1):
        imgs = f" 画像:{','.join(block.images)}" if block.images else ""
        excerpt = (block.text or " ".join(block.bullets))[:280]
        table_note = " 表あり" if block.tables else ""
        lines.append(f"{i}. file={block.filename} heading={block.heading or '(無題)'}{imgs}{table_note}")
        if excerpt:
            lines.append(f"   抜粋: {excerpt}")
        if block.tables:
            headers = block.tables[0].get("headers") or []
            lines.append(f"   表列: {', '.join(str(h) for h in headers)}")
    return "\n".join(lines)


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


def _complete_slides(
    name: str, planned: list[dict[str, Any]], blocks: list[SourceBlock]
) -> dict[str, Any] | None:
    slides: list[dict[str, Any]] = []
    covered: set[tuple[str, str]] = set()
    previous_layout = ""
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
        layout = normalize_layout(raw.get("layout"))
        if block and _content_images(block.images) and layout in DIAGRAM_LAYOUTS:
            layout = "fullscreen-photo"
        if block and layout in NUMERIC_LAYOUTS and not _NUMBER_RE.search(block.text + " ".join(block.bullets)):
            layout = _suggest_layout(block, previous_layout)
        if block and block.tables and layout not in TABLE_LAYOUTS:
            layout = "axis-table"
        if not block:
            continue
        # LLM が本文を返しても使わない。要点は機械充填、全文はノート。
        content = _fill_content(layout, block)
        if not content_nonempty(content):
            continue
        slide = {
            "type": "content" if kind != "case-study" else "case-study",
            "title": str(raw.get("title") or block.heading or name),
            "layout": layout,
            "content": content,
        }
        _attach_notes(slide, block)
        slides.append(slide)
        covered.add(_block_key(block))
        previous_layout = layout
    for block in blocks:
        if _block_key(block) in covered:
            continue
        if not (block.text or block.bullets or block.tables or _content_images(block.images)):
            continue
        layout = _suggest_layout(block, previous_layout)
        content = _fill_content(layout, block)
        if not content_nonempty(content):
            continue
        slide = {
            "type": "content",
            "title": block.heading or name,
            "layout": layout,
            "content": content,
        }
        _attach_notes(slide, block)
        slides.append(slide)
        previous_layout = layout
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


def _merge_layouts(planned: list[dict[str, Any]], layout_slides: list[Any], blocks: list[SourceBlock]) -> list[dict[str, Any]]:
    extras: list[dict[str, Any]] = []
    for raw in layout_slides:
        if not isinstance(raw, dict):
            continue
        layout = raw.get("layout")
        if not layout:
            continue
        matched = False
        block = _find_block(blocks, raw.get("source")) if raw.get("source") else None
        for item in planned:
            if item.get("type") in {"cover", "section", "ending"}:
                continue
            src = item.get("source") if isinstance(item.get("source"), dict) else {}
            same_src = block and _find_block(blocks, src) is block
            same_title = str(raw.get("title") or "") and str(raw.get("title")) == str(item.get("title") or "")
            if (same_src or same_title) and not item.get("_laid"):
                item["layout"] = layout
                item["_laid"] = True
                matched = True
                break
        if not matched:
            extras.append(raw)
    for extra in extras:
        planned.append(extra)
    for item in planned:
        item.pop("_laid", None)
    return planned


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
) -> dict[str, Any] | None:
    """3 パス（ストーリーライン → layout → 伏せたレビュー）。失敗時は None。"""
    if not llm_enabled():
        log.info("pptx plan skipped (GENERATE_PPTX_LLM=0)")
        return None
    blocks = parse_source_blocks(name, sections)
    image_paths = sorted({img for b in blocks for img in b.images} | set((assets or {}).keys()))
    outline = _outline_for_prompt(name, blocks)
    rules = rules_excerpt()
    try:
        story = _call_json(
            complete,
            "あなたはタイトル列だけを返す。本文は書かない。JSON のみ。",
            (
                f"{rules}\n\n{outline}\n"
                f"利用可能な画像: {', '.join(image_paths) or 'なし'}\n\n"
                "次の JSON だけを返す。\n"
                '{"slides":[{"type":"cover|section|content","title":"主張タイトル",'
                '"source":{"filename":"...","heading":"..."}}]}\n'
                "規則:\n"
                "- タイトルは結論。ですます禁止。個数（3つの理由）禁止。ラベル前置き禁止。\n"
                "- 見出しごとに最低 1 枚。source で章を指す。本文・layout は書かない。\n"
                "- 無い数値・固有名を作らない。ご清聴締めは作らない。\n"
            ),
        )
        if not story or not isinstance(story.get("slides"), list):
            log.warning("pptx plan: ストーリーラインを JSON として読めませんでした")
            return None
        planned = [s for s in story["slides"] if isinstance(s, dict)]
        try:
            laid = _call_json(
                complete,
                "あなたは layout だけを返す。本文は書かない。JSON のみ。",
                (
                    f"{rules}\n\n{SELECTION_GUIDE}\n"
                    f"layout は次のいずれか: {', '.join(LAYOUT_IDS)}\n\n"
                    f"タイトル列:\n{json.dumps(planned, ensure_ascii=False)}\n"
                    "次の JSON だけを返す。各 content に layout と source を付ける。\n"
                    '{"slides":[{"type":"content","title":"...","layout":"axis-table",'
                    '"source":{"filename":"...","heading":"..."}}]}\n'
                    "- 基本形を先に当てる。同じ layout を連続で使わない。\n"
                    "- 画像がある図的な節は fullscreen-photo。数値が無いのにチャート系を選ばない。\n"
                ),
            )
            if laid and isinstance(laid.get("slides"), list):
                planned = _merge_layouts(planned, laid["slides"], blocks)
        except Exception as exc:  # noqa: BLE001
            log.warning("pptx plan: layout パス失敗（機械選択へ）: %s", exc)
        deck = _complete_slides(name, planned, blocks)
        if not deck:
            log.warning("pptx plan: 検証後の deck が空です")
            return None
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
                    deck = validate_deck(deck) or deck
            except Exception as exc:  # noqa: BLE001
                log.warning("pptx plan: レビュー失敗（Pass2 までを採用）: %s", exc)
        log.info("pptx plan: %s slides", len(deck.get("slides") or []))
        return deck
    except Exception as exc:  # noqa: BLE001
        log.warning("pptx plan failed: %s", exc)
        return None
