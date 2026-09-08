"""deck JSON を 16:9 HTML スライドにする（PPTX と同じスロット）。"""

from __future__ import annotations

import base64
import html
from typing import Any

from app.dads import ACCENT, BODY, FONT, INK, MUTED, PAPER, RULE, SURFACE, hex_of
from app.pptx_catalog import DEFAULT_LAYOUT, LAYOUT_ID_SET, normalize_layout
from app.pptx_layouts import validate_deck


def _h(rgb: tuple[int, int, int]) -> str:
    return f"#{hex_of(rgb)}"


def _esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=True)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _data_uri(rel: str, data: bytes) -> str:
    ext = rel.rsplit(".", 1)[-1].lower() if "." in rel else ""
    mime = {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(ext, "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"


_CSS = f"""
:root {{
  --ink: {_h(INK)};
  --body: {_h(BODY)};
  --muted: {_h(MUTED)};
  --rule: {_h(RULE)};
  --paper: {_h(PAPER)};
  --surface: {_h(SURFACE)};
  --accent: {_h(ACCENT)};
}}
@page {{ size: 338.67mm 190.5mm; margin: 0; }}
html, body {{ margin: 0; padding: 0; background: #ddd; }}
body {{
  font-family: "{FONT}", "Hiragino Sans", "Yu Gothic", sans-serif;
  color: var(--body);
}}
.slide {{
  position: relative;
  width: 338.67mm;
  height: 190.5mm;
  background: var(--paper);
  box-sizing: border-box;
  page-break-after: always;
  overflow: hidden;
}}
.slide:last-child {{ page-break-after: auto; }}
.bar {{ position: absolute; left: 0; top: 0; width: 100%; height: 3.2mm; background: var(--accent); }}
.cover-bar {{ height: 26.6mm; }}
.title {{
  position: absolute; left: 17.8mm; top: 8mm; width: 304mm;
  font-size: 20pt; font-weight: 700; color: var(--ink); line-height: 1.35;
}}
.rule {{ position: absolute; left: 17.8mm; top: 28.5mm; width: 302mm; height: 0.3mm; background: var(--rule); }}
.body {{ position: absolute; left: 17.8mm; top: 32mm; width: 302mm; height: 142mm; }}
.page {{ position: absolute; right: 17.8mm; bottom: 6mm; font-size: 10pt; color: var(--muted); }}
.source {{ position: absolute; left: 17.8mm; bottom: 6mm; font-size: 10pt; color: var(--muted); width: 240mm; }}
.cover-label {{ position: absolute; left: 17.8mm; top: 8mm; color: #fff; font-size: 14pt; font-weight: 700; }}
.cover-title {{
  position: absolute; left: 17.8mm; top: 60mm; width: 304mm;
  font-size: 36pt; font-weight: 700; color: var(--ink); line-height: 1.3;
}}
.cover-sub {{ position: absolute; left: 17.8mm; top: 118mm; font-size: 16pt; color: var(--muted); }}
.cover-accent {{ position: absolute; left: 17.8mm; top: 140mm; width: 81mm; height: 1mm; background: var(--accent); }}
.section-rail {{ position: absolute; left: 0; top: 0; width: 4mm; height: 100%; background: var(--accent); }}
.section-title {{
  position: absolute; left: 23mm; top: 71mm; width: 292mm;
  font-size: 32pt; font-weight: 700; color: var(--ink);
}}
.grid {{ display: grid; gap: 5mm; height: 100%; }}
.card {{ background: var(--surface); padding: 4mm 5mm; box-sizing: border-box; }}
.card h3 {{ margin: 0 0 2mm; font-size: 14pt; color: var(--ink); }}
.card p, .col p {{ margin: 0; font-size: 12pt; line-height: 1.45; }}
.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6mm; height: 100%; }}
.two-chart {{ display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 6mm; height: 100%; }}
.col h3 {{ margin: 0 0 2mm; font-size: 14pt; color: var(--ink); border-bottom: 1.8px solid var(--accent); padding-bottom: 1.5mm; }}
ul {{ margin: 2mm 0 0 5mm; padding: 0; font-size: 13pt; line-height: 1.5; }}
table.axis {{ width: 100%; border-collapse: collapse; font-size: 12pt; }}
table.axis th {{
  text-align: left; font-weight: 700; color: var(--accent); font-size: 13.5pt;
  border-bottom: 1.8px solid var(--accent); padding: 2mm 3mm; background: none;
}}
table.axis td {{ border-bottom: 1px solid var(--rule); padding: 2.2mm 3mm; vertical-align: top; }}
table.axis tr:last-child td {{ border-bottom: 0; }}
table.axis td:first-child, table.axis th:first-child {{ font-weight: 700; font-size: 14pt; color: var(--ink); }}
.chevrons {{ display: flex; gap: 3mm; height: 42mm; align-items: stretch; }}
.chevron {{
  flex: 1; background: var(--surface); color: var(--ink);
  clip-path: polygon(0 0, calc(100% - 8mm) 0, 100% 50%, calc(100% - 8mm) 100%, 0 100%, 8mm 50%);
  padding: 4mm 10mm 4mm 12mm; box-sizing: border-box;
}}
.chevron.first {{ background: var(--accent); color: #fff; }}
.chevron .n {{ font-size: 11pt; font-weight: 700; }}
.chevron .t {{ font-size: 13pt; font-weight: 700; margin-top: 1mm; }}
.chevron .d {{ font-size: 11pt; margin-top: 2mm; }}
.kpi {{ display: grid; gap: 5mm; height: 90mm; }}
.kpi .card {{ text-align: center; padding-top: 12mm; }}
.kpi .v {{ font-size: 36pt; font-weight: 700; color: var(--accent); }}
.photo {{ width: 100%; height: 118mm; object-fit: contain; background: var(--surface); }}
@media print {{
  html, body {{ background: #fff; }}
}}
""".strip()


def _heading(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return str(item)
    for key in ("heading", "title", "label", "name", "q", "year", "date", "phase"):
        if item.get(key):
            return str(item[key])
    return ""


def _body(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("description", "body", "detail", "text", "a", "note", "message", "bio"):
        if item.get(key):
            return str(item[key])
    return ""


def _items(content: dict[str, Any]) -> list[tuple[str, str]]:
    raw = (
        content.get("items")
        or content.get("steps")
        or content.get("members")
        or content.get("columns")
        or content.get("painPoints")
    )
    out: list[tuple[str, str]] = []
    for item in _as_list(raw):
        if isinstance(item, str):
            out.append((item, ""))
        else:
            out.append((_heading(item), _body(item)))
    return [x for x in out if x[0] or x[1]]


def _bullets(lines: list[str]) -> str:
    if not lines:
        return ""
    return "<ul>" + "".join(f"<li>{_esc(x)}</li>" for x in lines if x) + "</ul>"


def _table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = rows[0]
    body = rows[1:]
    th = "".join(f"<th>{_esc(c)}</th>" for c in head)
    trs = []
    for row in body:
        tds = "".join(f"<td>{_esc(c)}</td>" for c in row)
        trs.append(f"<tr>{tds}</tr>")
    return f'<table class="axis"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def _bar_svg(labels: list[str], values: list[float]) -> str:
    if not labels:
        return ""
    width, height = 520, 280
    n = len(labels)
    mx = max(values) if values else 1
    mx = mx or 1
    gap = 16
    bar_w = max((width - 40 - gap * n) / n, 8)
    parts = [f'<svg viewBox="0 0 {width} {height}" width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">']
    for i, label in enumerate(labels):
        val = values[i] if i < len(values) else 0
        h = (val / mx) * 200
        x = 30 + i * (bar_w + gap)
        y = 230 - h
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{h:.1f}" fill="{_h(ACCENT)}"/>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="255" text-anchor="middle" font-size="12" fill="{_h(INK)}">{_esc(label)}</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


def _cards(items: list[tuple[str, str]]) -> str:
    n = max(len(items), 1)
    inner = []
    for i, (h, b) in enumerate(items[:4], 1):
        inner.append(f'<div class="card"><h3>{i}. {_esc(h)}</h3><p>{_esc(b)}</p></div>')
    return f'<div class="grid" style="grid-template-columns:repeat({min(n, 4)},1fr)">{"".join(inner)}</div>'


def _content_html(layout: str, content: dict[str, Any], assets: dict[str, bytes]) -> str:
    if layout == "axis-table":
        headers = [str(h) for h in _as_list(content.get("headers") or ["項目", "内容"])]
        rows = [headers]
        for row in _as_list(content.get("rows")):
            if isinstance(row, list):
                rows.append([str(c) for c in row])
            elif isinstance(row, dict):
                rows.append([str(v) for v in row.values()])
            else:
                rows.append([str(row)])
        return _table(rows)
    if layout == "premise-conclusion":
        left = content.get("left") if isinstance(content.get("left"), dict) else {}
        right = content.get("right") if isinstance(content.get("right"), dict) else {}
        table_rows: list[list[str]] = []
        for row in _as_list(left.get("rows")):
            if isinstance(row, list):
                table_rows.append([str(c) for c in row[:2]])
            else:
                table_rows.append([str(row), ""])
        bullets = [str(b) for b in _as_list(right.get("bullets") or right.get("points"))]
        return (
            '<div class="two">'
            f'<div class="col"><h3>{_esc(left.get("header") or "前提")}</h3>{_table(table_rows)}</div>'
            f'<div class="col"><h3>{_esc(right.get("header") or "意味合い")}</h3>{_bullets(bullets)}</div>'
            "</div>"
        )
    if layout == "before-after-split":
        cols = []
        for key in ("before", "after"):
            block = content.get(key) if isinstance(content.get(key), dict) else {}
            pts = [str(p) for p in _as_list(block.get("points"))]
            cols.append(f'<div class="col card"><h3>{_esc(block.get("title") or key)}</h3>{_bullets(pts)}</div>')
        return f'<div class="two">{"".join(cols)}</div>'
    if layout == "chevron-steps":
        chips = []
        for i, step in enumerate(_as_list(content.get("steps") or content.get("items"))[:6]):
            if isinstance(step, dict):
                n = str(step.get("n") or i + 1)
                title = str(step.get("title") or step.get("heading") or step.get("label") or "")
                text = str(step.get("text") or step.get("description") or "")
            else:
                n, title, text = str(i + 1), str(step), ""
            cls = "chevron first" if i == 0 else "chevron"
            chips.append(
                f'<div class="{cls}"><div class="n">{_esc(n)}</div>'
                f'<div class="t">{_esc(title)}</div><div class="d">{_esc(text)}</div></div>'
            )
        return f'<div class="chevrons">{"".join(chips)}</div>'
    if layout == "chart-insight":
        labels = [str(x) for x in _as_list(content.get("labels"))]
        values: list[float] = []
        for v in _as_list(content.get("values")):
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                values.append(0)
        insight = content.get("insight") if isinstance(content.get("insight"), dict) else {}
        bullets = [str(b) for b in _as_list(insight.get("bullets") or content.get("bullets"))]
        return (
            '<div class="two-chart">'
            f"<div>{_bar_svg(labels, values)}</div>"
            f'<div class="col"><h3>{_esc(insight.get("header") or "意味合い")}</h3>{_bullets(bullets)}</div>'
            "</div>"
        )
    if layout in {"kpi-three-col", "tam-parallel"}:
        items = _as_list(content.get("items"))[:3]
        cards = []
        for item in items:
            if isinstance(item, dict):
                v, lab = str(item.get("value") or ""), str(item.get("label") or "")
            else:
                v, lab = str(item), ""
            cards.append(f'<div class="card"><div class="v">{_esc(v)}</div><p>{_esc(lab)}</p></div>')
        return f'<div class="kpi" style="grid-template-columns:repeat({max(len(cards), 1)},1fr)">{"".join(cards)}</div>'
    if layout == "fullscreen-photo":
        rel = str(content.get("image") or content.get("backgroundPath") or "")
        data = assets.get(rel)
        img = f'<img class="photo" src="{_data_uri(rel, data)}" alt=""/>' if data else '<div class="card">図</div>'
        cap = str(content.get("headline") or "")
        return img + (f"<p>{_esc(cap)}</p>" if cap else "")
    if layout in {"comparison-table", "checklist-table", "pricing-table"}:
        rows: list[list[str]] = []
        raw_rows = content.get("rows") or []
        if raw_rows and isinstance(raw_rows[0], dict) and "category" in raw_rows[0]:
            rows = [["項目", str(content.get("beforeTitle") or "前"), str(content.get("afterTitle") or "後")]]
            for row in raw_rows:
                rows.append([str(row.get("category") or ""), str(row.get("before") or ""), str(row.get("after") or "")])
        elif content.get("items"):
            rows.append([str(h) for h in _as_list(content.get("headers") or ["項目", "状態", "備考"])])
            for item in content["items"]:
                if isinstance(item, dict):
                    rows.append([str(item.get("label") or ""), "済" if item.get("checked") else "—", str(item.get("note") or "")])
        return _table(rows)
    if content.get("labels") and content.get("values"):
        insight = content.get("insight") if isinstance(content.get("insight"), dict) else {}
        labels = [str(x) for x in _as_list(content.get("labels"))]
        values = []
        for v in _as_list(content.get("values")):
            try:
                values.append(float(v))
            except (TypeError, ValueError):
                values.append(0)
        return (
            '<div class="two-chart">'
            f"<div>{_bar_svg(labels, values)}</div>"
            f'<div class="col">{_bullets([str(b) for b in _as_list(insight.get("bullets"))])}</div>'
            "</div>"
        )
    items = _items(content)
    if items:
        return _cards(items)
    if content.get("text"):
        return f"<p>{_esc(content.get('text'))}</p>"
    if content.get("narrative"):
        return (
            '<div class="two">'
            f"<p>{_esc(content.get('narrative'))}</p>"
            f'<div class="card" style="text-align:center"><div class="v">{_esc(content.get("bigNumber"))}</div>'
            f'<p>{_esc(content.get("bigNumberLabel"))}</p></div></div>'
        )
    return ""


def render_deck_html(deck: dict[str, Any], assets: dict[str, bytes] | None = None) -> bytes:
    """検証済み deck を単一 HTML にする。"""
    assets = assets or {}
    valid = validate_deck(deck) or deck
    slides = valid.get("slides") or []
    total = len(slides)
    parts = [
        "<!DOCTYPE html><html lang=\"ja\"><head><meta charset=\"utf-8\">",
        "<title>資料</title>",
        f"<style>{_CSS}</style></head><body>",
    ]
    for i, slide in enumerate(slides, 1):
        kind = slide.get("type")
        title = str(slide.get("title") or "")
        source = str(slide.get("source") or "")
        if isinstance(slide.get("content"), dict) and not source:
            source = str(slide["content"].get("source") or "")
        inner = []
        if kind == "cover":
            inner.append('<div class="bar cover-bar"></div>')
            inner.append('<div class="cover-label">資料</div>')
            inner.append(f'<div class="cover-title">{_esc(title)}</div>')
            if slide.get("subtitle"):
                inner.append(f'<div class="cover-sub">{_esc(slide.get("subtitle"))}</div>')
            inner.append('<div class="cover-accent"></div>')
        elif kind == "section":
            inner.append('<div class="section-rail"></div>')
            inner.append(f'<div class="section-title">{_esc(title)}</div>')
        else:
            layout = slide.get("layout") if slide.get("layout") in LAYOUT_ID_SET else normalize_layout(slide.get("layout"))
            if layout not in LAYOUT_ID_SET:
                layout = DEFAULT_LAYOUT
            content = slide.get("content") if isinstance(slide.get("content"), dict) else {}
            inner.append('<div class="bar"></div>')
            inner.append(f'<div class="title">{_esc(title)}</div>')
            inner.append('<div class="rule"></div>')
            inner.append(f'<div class="body">{_content_html(layout, content, assets)}</div>')
            if source:
                inner.append(f'<div class="source">{_esc(source)}</div>')
        if kind != "cover":
            inner.append(f'<div class="page">{i} / {total}</div>')
        parts.append(f'<section class="slide">{"".join(inner)}</section>')
    parts.append("</body></html>")
    return "".join(parts).encode("utf-8")
