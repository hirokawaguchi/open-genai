"""Markdown 章から deck JSON を組み立てる（LLM は枚割りと layout、本文は機械充填）。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from app.llm import chat, llm_enabled
from app.pptx_catalog import (
    DEFAULT_LAYOUT,
    DIAGRAM_LAYOUTS,
    LAYOUT_IDS,
    NUMERIC_LAYOUTS,
    SELECTION_GUIDE,
    content_nonempty,
    normalize_layout,
)
from app.pptx_layouts import validate_deck

log = logging.getLogger("procuretech-generate")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)>\s]+)>?")
_NUMBER_RE = re.compile(r"([0-9]+(?:\.[0-9]+)?\s*%|[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?)")
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]+?)```", re.I)


@dataclass
class SourceBlock:
    filename: str
    heading: str
    text: str
    images: list[str] = field(default_factory=list)
    bullets: list[str] = field(default_factory=list)


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


def parse_source_blocks(name: str, sections: list[dict[str, Any]]) -> list[SourceBlock]:
    blocks: list[SourceBlock] = []
    for sec in sections:
        filename = str(sec.get("filename") or "section.md")
        content = str(sec.get("content") or "")
        current = SourceBlock(filename=filename, heading="", text="")
        paragraphs: list[str] = []
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
                if current.heading or paragraphs or current.images or current.bullets:
                    current.text = "\n".join(paragraphs).strip()
                    blocks.append(current)
                    paragraphs = []
                current = SourceBlock(filename=filename, heading=hm.group(2).strip(), text="")
                continue
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
        current.text = "\n".join(paragraphs).strip()
        if current.heading or current.text or current.bullets or current.images:
            blocks.append(current)
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
    if images:
        return "fullscreen-photo" if previous != "fullscreen-photo" else "numbered-feature-cards"
    if _NUMBER_RE.search(blob) and any(k in heading for k in ("規模", "KPI", "KGI", "目標", "件数", "数値")):
        return "kpi-three-col" if previous != "kpi-three-col" else "text-data-emphasis"
    if any(k in heading for k in ("手順", "フロー", "プロセス", "工程")):
        return "step-flow"
    if any(k in heading for k in ("比較", "更改", "Before", "After")):
        return "before-after-split"
    if any(k in heading for k in ("課題", "問題", "ペイン")):
        return "user-pain-points"
    if any(k in heading for k in ("スケジュール", "日程", "計画")):
        return "schedule-list"
    rotate = [
        "parallel-items",
        "numbered-feature-cards",
        "three-column",
        "three-step-column",
        "checklist-table",
        "qa-grid",
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
    original = _plain_source(
        "\n".join(x for x in (block.text, "\n".join(f"・ {b}" for b in block.bullets)) if x)
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
        lines.append(f"{i}. file={block.filename} heading={block.heading or '(無題)'}{imgs}")
        if excerpt:
            lines.append(f"   抜粋: {excerpt}")
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
        if not (block.text or block.bullets or _content_images(block.images)):
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


def plan_deck(
    name: str,
    sections: list[dict[str, Any]],
    assets: dict[str, bytes] | None = None,
    *,
    complete: Any = chat,
) -> dict[str, Any] | None:
    """LLM で構成し、失敗時は None（呼び出し側が決定論変換へ落とす）。"""
    if not llm_enabled():
        log.info("pptx plan skipped (GENERATE_PPTX_LLM=0)")
        return None
    blocks = parse_source_blocks(name, sections)
    image_paths = sorted({img for b in blocks for img in b.images} | set((assets or {}).keys()))
    user = (
        f"{_outline_for_prompt(name, blocks)}\n"
        f"利用可能な画像: {', '.join(image_paths) or 'なし'}\n\n"
        "次の JSON だけを返してください。説明文は不要です。\n"
        '{"slides":[{"type":"cover|section|content","title":"...",'
        '"layout":"(content のみ)","source":{"filename":"...","heading":"..."}}]}\n'
        "規則:\n"
        "- 本文は書かない。source で章・節を指す。content は空でよい。\n"
        "- 見出し（# / ## / ###）ごとに最低 1 枚。長い節は分割する。\n"
        "- 同じ layout を連続で使わない。カード・手順・表・図を散らす。\n"
        "- 「ご清聴ありがとうございました」などの締めスライドは作らない。\n"
        "- layout は次のいずれか: " + ", ".join(LAYOUT_IDS) + "\n"
        f"{SELECTION_GUIDE}\n"
        "- 無い数値・固有名を作らない。\n"
        "- 画像がある図的な節は fullscreen-photo を優先する。\n"
    )
    try:
        text = complete(
            [
                {
                    "role": "system",
                    "content": "あなたはスライド構成だけを返す。本文の創作はしない。JSON のみ。",
                },
                {"role": "user", "content": user},
            ]
        )
        data = _parse_llm_json(text)
        if not data:
            log.warning("pptx plan: LLM 応答を JSON として読めませんでした")
            return None
        planned = data.get("slides")
        if not isinstance(planned, list):
            log.warning("pptx plan: slides 配列がありません")
            return None
        deck = _complete_slides(name, planned, blocks)
        if deck:
            log.info("pptx plan: %s slides", len(deck.get("slides") or []))
        else:
            log.warning("pptx plan: 検証後の deck が空です")
        return deck
    except Exception as exc:  # noqa: BLE001
        log.warning("pptx plan failed: %s", exc)
        return None
