"""描画前に、枠から溢れる・空のレイアウトを直す。"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.dads import PPTX_TYPE, pptx_content_width
from app.pptx_catalog import content_nonempty, normalize_layout
from app.pptx_layouts import _needs_autofit, validate_deck

log = logging.getLogger("procuretech-generate")

_WS_RE = re.compile(r"\s+")
_MARK_RE = re.compile(r"[*_`#\[\]【】「」『』（）()［］<>＜＞・。．.：:：／/]+")


def _norm_title(text: Any) -> str:
    s = _MARK_RE.sub("", str(text or ""))
    return _WS_RE.sub("", s).strip()


def _echoes_title(text: Any, title: str) -> bool:
    a, b = _norm_title(text), _norm_title(title)
    return bool(a) and bool(b) and a == b


_METRIC_RE = re.compile(
    r"^[\d.,]+\s*(%|％|件|人|円|万円|億円|分|時間|年|回|社|校|か所|箇所)?$"
)
_META_KEYS = ("文書番号", "版数", "作成日", "改訂日", "所要時間", "対象研修", "文書名")


def looks_like_meta(*texts: str) -> bool:
    blob = "\n".join(str(t or "") for t in texts)
    return sum(1 for k in _META_KEYS if k in blob) >= 2


def is_metric_value(text: Any) -> bool:
    """大きく出してよい短い指標か。文書番号・日付・固有名は否。"""
    s = str(text or "").strip()
    if not s or len(s) > 8:
        return False
    return bool(_METRIC_RE.match(s))


def _kpi_pairs(content: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for el in content.get("elements") or []:
        if not isinstance(el, dict):
            continue
        if str(el.get("kind") or "").strip().lower() != "kpi":
            continue
        value = str(el.get("value") or el.get("text") or "").strip()
        label = str(el.get("label") or "").strip()
        if label or value:
            rows.append([label or "項目", value])
    for item in content.get("items") or []:
        if not isinstance(item, dict):
            continue
        if "value" not in item and "label" not in item:
            continue
        value = str(item.get("value") or "").strip()
        label = str(item.get("label") or "").strip()
        if label or value:
            rows.append([label or "項目", value])
    big = str(content.get("bigNumber") or "").strip()
    if big:
        rows.append([str(content.get("bigNumberLabel") or "指標"), big])
    return rows


def _kpi_broken(content: dict[str, Any]) -> bool:
    pairs = _kpi_pairs(content)
    if not pairs:
        return False
    if len(pairs) > 3:
        return True
    if any(not is_metric_value(value) for _, value in pairs):
        return True
    n = len(pairs)
    width = (pptx_content_width() - 0.2 * max(n - 1, 0)) / n
    return any(
        _needs_autofit(value, max(width - 0.2, 0.8), 0.9, PPTX_TYPE["metric"]) for _, value in pairs
    )


def strip_title_echo(title: str, content: dict[str, Any]) -> dict[str, Any]:
    """スライド題名と同じ見出し・要点を本文から除く（題名帯と二重にしない）。"""
    if not title or not content:
        return content
    out = dict(content)
    for key in ("headline", "heading", "caption"):
        if key in out and _echoes_title(out.get(key), title):
            out[key] = ""
    if isinstance(out.get("points"), list):
        out["points"] = [p for p in out["points"] if not _echoes_title(p, title)]
    if isinstance(out.get("elements"), list):
        cleaned: list[Any] = []
        for el in out["elements"]:
            if not isinstance(el, dict):
                cleaned.append(el)
                continue
            kind = str(el.get("kind") or "").strip().lower()
            label = el.get("text") or el.get("heading") or el.get("label") or el.get("value")
            if kind in {"heading", "text", "box"} and _echoes_title(label, title):
                continue
            if kind == "bullets":
                bullets = [b for b in (el.get("bullets") or []) if not _echoes_title(b, title)]
                el = {**el, "bullets": bullets}
            cleaned.append(el)
        out["elements"] = cleaned
    for key in ("items", "steps", "members", "branches"):
        raw = out.get(key)
        if not isinstance(raw, list):
            continue
        items: list[Any] = []
        for item in raw:
            if isinstance(item, dict):
                item = dict(item)
                for hk in ("heading", "title", "label", "text", "name"):
                    if _echoes_title(item.get(hk), title):
                        item[hk] = ""
                items.append(item)
            elif not _echoes_title(item, title):
                items.append(item)
        out[key] = items
    for side in ("left", "right"):
        block = out.get(side)
        if isinstance(block, dict) and _echoes_title(block.get("header"), title):
            out[side] = {**block, "header": ""}
    return out

_TABLE_LAYOUTS = frozenset({"axis-table", "comparison-table", "pricing-table"})
_FLOW_LAYOUTS = frozenset({"chevron-steps", "step-flow", "step-up", "three-step-column"})
_CARD_LAYOUTS = frozenset(
    {"parallel-items", "numbered-feature-cards", "three-column", "three-step-column", "awards-parallel"}
)
_MAX_FLOW = 3


def _flow_items(content: dict[str, Any]) -> list[dict[str, str]]:
    raw = content.get("steps") or content.get("items") or content.get("branches") or []
    if not isinstance(raw, list):
        raw = [raw]
    out: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if isinstance(item, dict):
            heading = str(
                item.get("title") or item.get("heading") or item.get("label") or item.get("text") or ""
            ).strip()
            body = str(item.get("text") or item.get("description") or item.get("body") or "").strip()
            if body == heading:
                body = ""
        else:
            heading, body = str(item).strip(), ""
        if heading or body:
            out.append({"heading": heading or body, "body": body if heading else ""})
    return out


def _flow_label_fits(n: int, text: str) -> bool:
    """シェブロン／プロセス箱に 22pt で収まるか。"""
    if n <= 0 or not (text or "").strip():
        return True
    width = (11.9 - 0.12 * max(n - 1, 0)) / n - 0.4
    return not _needs_autofit(text, max(width, 0.8), 0.5, PPTX_TYPE["card_head"])


def _points_from_notes(notes: str) -> list[str]:
    text = notes or ""
    if "整理ノート" not in text:
        return []
    chunk = text.split("整理ノート", 1)[1]
    for stop in ("図のMermaid", "元の本文"):
        chunk = chunk.split(stop, 1)[0]
    out: list[str] = []
    for line in chunk.splitlines():
        item = line.strip().lstrip("・●- ").strip()
        if item:
            out.append(item)
    return out


def _points_from_content(content: dict[str, Any], notes: str) -> list[str]:
    points = [str(p).strip() for p in (content.get("points") or []) if str(p).strip()]
    if points:
        return points
    items = _flow_items(content)
    if items:
        return [x["heading"] if not x["body"] else f"{x['heading']} {x['body']}".strip() for x in items]
    kpis = _kpi_pairs(content)
    if kpis:
        return [f"{lab} / {val}".strip(" /") for lab, val in kpis if lab or val]
    rows = content.get("rows") or []
    if isinstance(rows, list) and rows:
        out: list[str] = []
        for row in rows:
            if isinstance(row, list):
                cells = [str(c).strip() for c in row if str(c).strip()]
                if cells:
                    out.append(" / ".join(cells))
            elif isinstance(row, dict):
                cells = [str(v).strip() for v in row.values() if str(v).strip()]
                if cells:
                    out.append(" / ".join(cells))
        if out:
            return out
    from_notes = _points_from_notes(notes)
    if from_notes:
        return from_notes
    alt = str(content.get("alt") or content.get("caption") or content.get("narrative") or "").strip()
    return [alt] if alt else []


def _fullwidth(slide: dict[str, Any], points: list[str]) -> list[dict[str, Any]]:
    title = str(slide.get("title") or "")
    kept = [p for p in points if p][:12]
    if not kept:
        kept = ["この節の詳細はノート（原文）を参照してください。"]
    slides: list[dict[str, Any]] = []
    for i in range(0, len(kept), 6):
        part = kept[i : i + 6]
        page = dict(slide)
        page["layout"] = "fullwidth-points"
        page["content"] = {"points": part}
        page["title"] = title if i == 0 else f"{title}（続き）"
        slides.append(page)
    return slides


def _diagnose(slide: dict[str, Any]) -> str:
    """直す理由。空なら健全。"""
    layout = normalize_layout(slide.get("layout"))
    content = slide.get("content") if isinstance(slide.get("content"), dict) else {}
    if layout == "figure-frame":
        return ""
    if layout in {"freeform", "kpi-three-col", "text-data-emphasis"} and _kpi_broken(content):
        return "kpi-overflow"
    if layout in _TABLE_LAYOUTS and not (content.get("rows") or []):
        return "empty-table"
    if layout in _FLOW_LAYOUTS:
        items = _flow_items(content)
        if not items:
            return "empty-flow"
        n = min(len(items), _MAX_FLOW)
        if any(not _flow_label_fits(n, it["heading"]) for it in items):
            return "flow-overflow"
        if len(items) > _MAX_FLOW:
            return "flow-split"
        return ""
    if layout in _CARD_LAYOUTS:
        items = _flow_items(content)
        if not items:
            return "empty-cards"
        if len(items) >= 3:
            width = (pptx_content_width() - 0.4) / len(items[:4]) - 0.35
            if any(not _flow_label_fits(len(items[:4]), it["heading"]) for it in items):
                return "card-overflow"
            if any(_needs_autofit(it["body"], max(width, 1.0), 2.2, PPTX_TYPE["body"]) for it in items if it["body"]):
                return "card-overflow"
        return ""
    if not content_nonempty(content):
        return "empty-content"
    return ""


def _repair_slide(slide: dict[str, Any]) -> list[dict[str, Any]]:
    reason = _diagnose(slide)
    if not reason:
        return [slide]
    content = slide.get("content") if isinstance(slide.get("content"), dict) else {}
    notes = str(slide.get("notes") or "")
    points = _points_from_content(content, notes)
    if reason == "flow-split":
        items = _flow_items(content)
        n = _MAX_FLOW
        if any(not _flow_label_fits(n, it["heading"]) for it in items):
            log.info("pptx repair: %s → fullwidth (%s)", slide.get("title"), reason)
            return _fullwidth(slide, points)
        pages: list[dict[str, Any]] = []
        title = str(slide.get("title") or "")
        for i in range(0, len(items), n):
            part = items[i : i + n]
            page = dict(slide)
            steps = [{"n": str(j + 1), "title": it["heading"], "text": it["body"]} for j, it in enumerate(part)]
            page["content"] = {**content, "steps": steps, "items": steps}
            page["title"] = title if i == 0 else f"{title}（続き）"
            pages.append(page)
        log.info("pptx repair: %s split %s", title, reason)
        return pages
    if reason == "kpi-overflow":
        pairs = _kpi_pairs(content)
        if pairs:
            extra = [
                str(b).strip()
                for el in (content.get("elements") or [])
                if isinstance(el, dict) and str(el.get("kind") or "").lower() == "bullets"
                for b in (el.get("bullets") or [])
                if str(b).strip()
            ]
            rows = [[lab, val] for lab, val in pairs]
            rows.extend(["", b] for b in extra if b)
            page = dict(slide)
            page["layout"] = "axis-table"
            page["content"] = {"headers": ["項目", "内容"], "rows": rows[:8]}
            log.info("pptx repair: %s → axis-table (%s)", slide.get("title"), reason)
            return [page]
    log.info("pptx repair: %s → fullwidth (%s)", slide.get("title"), reason)
    return _fullwidth(slide, points)


def repair_deck(deck: dict[str, Any] | None) -> dict[str, Any] | None:
    """溢れる・空の content スライドを分割するか全幅に直す。"""
    if not isinstance(deck, dict) or not isinstance(deck.get("slides"), list):
        return deck
    out: list[dict[str, Any]] = []
    for raw in deck["slides"]:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "content")
        if kind in {"content", "case-study"}:
            title = str(raw.get("title") or "")
            content = raw.get("content") if isinstance(raw.get("content"), dict) else {}
            if content:
                raw = {**raw, "content": strip_title_echo(title, content)}
            out.extend(_repair_slide(raw))
        else:
            out.append(raw)
    fixed = validate_deck({"slides": out})
    return fixed or deck
