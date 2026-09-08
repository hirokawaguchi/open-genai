"""deck JSON を DADS トークンで描く決定論レンダラ（python-pptx）。"""

from __future__ import annotations

import io
from typing import Any, Callable

from app.dads import ACCENT, BODY, FONT, INK, MUTED, ON_ACCENT, PAPER, RULE, SURFACE
from app.pptx_catalog import DEFAULT_LAYOUT, LAYOUT_ID_SET, content_nonempty, normalize_layout

RenderFn = Callable[[Any, Any, dict[str, Any], dict[str, bytes]], None]
_REGISTRY: dict[str, RenderFn] = {}


def register(name: str) -> Callable[[RenderFn], RenderFn]:
    def deco(fn: RenderFn) -> RenderFn:
        _REGISTRY[name] = fn
        return fn

    return deco


def _rgb(rgb: tuple[int, int, int]) -> Any:
    from pptx.dml.color import RGBColor

    return RGBColor(*rgb)


def _set_run_font(
    run: Any,
    *,
    size: Any,
    color: tuple[int, int, int],
    bold: bool = False,
    name: str = FONT,
) -> None:
    from lxml import etree
    from pptx.oxml.ns import qn

    if size is not None:
        run.font.size = size
    run.font.bold = bold
    run.font.color.rgb = _rgb(color)
    run.font.name = name
    r_pr = run._r.get_or_add_rPr()
    for tag in ("a:latin", "a:ea", "a:cs"):
        el = r_pr.find(qn(tag))
        if el is None:
            el = etree.SubElement(r_pr, qn(tag))
        el.set("typeface", name)


def _fill_slide(slide: Any, rgb: tuple[int, int, int] = PAPER) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(rgb)


def _no_line(shape: Any) -> None:
    shape.line.fill.background()


def _solid(shape: Any, rgb: tuple[int, int, int]) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(rgb)
    _no_line(shape)


def _rect(slide: Any, left: Any, top: Any, width: Any, height: Any, rgb: tuple[int, int, int]) -> Any:
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    _solid(shape, rgb)
    return shape


def _oval(slide: Any, left: Any, top: Any, width: Any, height: Any, rgb: tuple[int, int, int]) -> Any:
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, left, top, width, height)
    _solid(shape, rgb)
    return shape


def _style_p(
    paragraph: Any,
    text: str,
    *,
    size: Any,
    color: tuple[int, int, int],
    bold: bool = False,
    align: Any = None,
    space_after: Any | None = None,
) -> None:
    from pptx.enum.text import PP_ALIGN

    paragraph.text = str(text or "")
    paragraph.alignment = align or PP_ALIGN.LEFT
    if space_after is not None:
        paragraph.space_after = space_after
    for run in paragraph.runs:
        _set_run_font(run, size=size, color=color, bold=bold)


def _textbox(
    slide: Any,
    left: Any,
    top: Any,
    width: Any,
    height: Any,
    text: str,
    *,
    size: Any,
    color: tuple[int, int, int] = BODY,
    bold: bool = False,
    align: Any = None,
) -> Any:
    box = slide.shapes.add_textbox(left, top, width, height)
    box.text_frame.word_wrap = True
    _style_p(box.text_frame.paragraphs[0], text, size=size, color=color, bold=bold, align=align)
    return box


def _lines(
    slide: Any,
    left: Any,
    top: Any,
    width: Any,
    height: Any,
    lines: list[str],
    *,
    size: Any,
    color: tuple[int, int, int] = BODY,
    bullet: bool = False,
) -> None:
    from pptx.util import Pt

    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        text = f"•  {line}" if bullet else line
        _style_p(p, text, size=size, color=color, space_after=Pt(8))


def _card(
    slide: Any,
    left: Any,
    top: Any,
    width: Any,
    height: Any,
    heading: str,
    body: str = "",
    *,
    index: int | None = None,
) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    _rect(slide, left, top, width, height, SURFACE)
    _rect(slide, left, top, Inches(0.08), height, ACCENT)
    title_left = left + Inches(0.22)
    title_width = width - Inches(0.35)
    if index is not None:
        _oval(slide, left + Inches(0.18), top + Inches(0.16), Inches(0.32), Inches(0.32), ACCENT)
        _textbox(
            slide,
            left + Inches(0.18),
            top + Inches(0.16),
            Inches(0.32),
            Inches(0.32),
            str(index),
            size=Pt(11),
            color=ON_ACCENT,
            bold=True,
            align=PP_ALIGN.CENTER,
        )
        title_left = left + Inches(0.58)
        title_width = width - Inches(0.72)
    _textbox(slide, title_left, top + Inches(0.14), title_width, Inches(0.4), heading, size=Pt(14), color=INK, bold=True)
    if body:
        _textbox(
            slide,
            title_left,
            top + Inches(0.52),
            title_width,
            height - Inches(0.65),
            body,
            size=Pt(12),
            color=BODY,
        )


def _add_notes(slide: Any, notes: str) -> None:
    text = (notes or "").strip()
    if not text:
        return
    frame = slide.notes_slide.notes_text_frame
    frame.text = text
    for p in frame.paragraphs:
        for run in p.runs:
            _set_run_font(run, size=None, color=BODY)


def _add_title_slide(prs: Any, title: str, subtitle: str = "") -> Any:
    from pptx.util import Emu, Inches, Pt

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _fill_slide(slide)
    _rect(slide, Inches(0), Inches(0), prs.slide_width, Inches(1.05), ACCENT)
    _textbox(slide, Inches(0.7), Inches(0.32), Inches(12.0), Inches(0.45), "資料", size=Pt(14), color=ON_ACCENT, bold=True)
    box = slide.shapes.add_textbox(Inches(0.7), Inches(2.35), Inches(12.0), Inches(2.2))
    box.text_frame.word_wrap = True
    _style_p(box.text_frame.paragraphs[0], title, size=Pt(36), color=INK, bold=True)
    if subtitle:
        _textbox(slide, Inches(0.7), Inches(4.6), Inches(12.0), Inches(0.8), subtitle, size=Pt(16), color=MUTED)
    _rect(slide, Inches(0.7), Inches(5.5), Inches(3.2), Inches(0.04), ACCENT)
    _rect(slide, Inches(0), Emu(prs.slide_height - Inches(0.28)), prs.slide_width, Inches(0.28), SURFACE)
    return slide


def _add_section_slide(prs: Any, title: str) -> Any:
    from pptx.util import Inches, Pt

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _fill_slide(slide)
    _rect(slide, Inches(0), Inches(0), Inches(0.16), prs.slide_height, ACCENT)
    _textbox(slide, Inches(0.9), Inches(2.8), Inches(11.5), Inches(1.6), title, size=Pt(32), color=INK, bold=True)
    return slide


def _add_ending_slide(prs: Any, title: str, subtitle: str = "") -> Any:
    from pptx.util import Inches, Pt

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _fill_slide(slide)
    _rect(slide, Inches(0), Inches(0), prs.slide_width, Inches(0.16), ACCENT)
    _textbox(slide, Inches(0.7), Inches(2.6), Inches(12.0), Inches(1.4), title or "ご清聴ありがとうございました", size=Pt(28), color=INK, bold=True)
    if subtitle:
        _textbox(slide, Inches(0.7), Inches(4.2), Inches(12.0), Inches(0.7), subtitle, size=Pt(16), color=MUTED)
    return slide


def _add_content_chrome(slide: Any, prs: Any, title: str) -> None:
    from pptx.util import Inches, Pt

    _fill_slide(slide)
    _rect(slide, Inches(0), Inches(0), prs.slide_width, Inches(0.08), ACCENT)
    _textbox(slide, Inches(0.7), Inches(0.22), Inches(12.0), Inches(0.88), title, size=Pt(20), color=INK, bold=True)
    _rect(slide, Inches(0.7), Inches(1.12), Inches(11.9), Inches(0.012), RULE)


def _add_source(slide: Any, prs: Any, source: str) -> None:
    from pptx.util import Emu, Inches, Pt

    text = (source or "").strip()
    if not text:
        return
    _textbox(
        slide,
        Inches(0.7),
        Emu(prs.slide_height - Inches(0.38)),
        Inches(9.5),
        Inches(0.28),
        text,
        size=Pt(10),
        color=MUTED,
    )


def _add_footers(prs: Any) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    total = len(prs.slides)
    for i, slide in enumerate(prs.slides, start=1):
        if i == 1:
            continue
        _rect(
            slide,
            Inches(0.7),
            Emu(prs.slide_height - Inches(0.42)),
            Inches(11.9),
            Inches(0.01),
            RULE,
        )
        box = slide.shapes.add_textbox(
            Inches(11.4), Emu(prs.slide_height - Inches(0.38)), Inches(1.3), Inches(0.3)
        )
        p = box.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT
        run = p.add_run()
        run.text = f"{i} / {total}"
        _set_run_font(run, size=Pt(10), color=MUTED)


def _picture(slide: Any, rel: str, assets: dict[str, bytes], left: Any, top: Any, width: Any) -> bool:
    data = assets.get(rel)
    if not data:
        return False
    try:
        slide.shapes.add_picture(io.BytesIO(data), left, top, width=width)
        return True
    except Exception:  # noqa: BLE001
        return False


def _placeholder(slide: Any, left: Any, top: Any, width: Any, height: Any, label: str) -> None:
    from pptx.util import Pt

    _rect(slide, left, top, width, height, SURFACE)
    _textbox(slide, left, top + height / 3, width, height / 3, label or "画像", size=Pt(12), color=MUTED)


def _set_cell_border(cell: Any, *, bottom: tuple[int, int, int] | None, width_pt: float) -> None:
    from lxml import etree
    from pptx.oxml.ns import qn

    tc = cell._tc
    tc_pr = tc.get_or_add_tcPr()
    for child in list(tc_pr):
        if child.tag == qn("a:lnB"):
            tc_pr.remove(child)
    if bottom is None or width_pt <= 0:
        return
    ln = etree.SubElement(tc_pr, qn("a:lnB"))
    ln.set("w", str(int(width_pt * 12700)))
    sf = etree.SubElement(ln, qn("a:solidFill"))
    srgb = etree.SubElement(sf, qn("a:srgbClr"))
    srgb.set("val", f"{bottom[0]:02X}{bottom[1]:02X}{bottom[2]:02X}")


def _add_table(slide: Any, left: Any, top: Any, width: Any, height: Any, rows: list[list[str]]) -> None:
    from pptx.util import Pt

    if not rows:
        return
    cols = max(len(r) for r in rows)
    table_shape = slide.shapes.add_table(len(rows), cols, left, top, width, height)
    table = table_shape.table
    last = len(rows) - 1
    for r_i, row in enumerate(rows):
        for c_i in range(cols):
            cell = table.cell(r_i, c_i)
            cell.text = row[c_i] if c_i < len(row) else ""
            header = r_i == 0
            axis = c_i == 0
            size = Pt(13) if header else (Pt(15) if axis else Pt(12))
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    _set_run_font(
                        run,
                        size=size,
                        color=ACCENT if header else INK,
                        bold=header or axis,
                    )
            fill = cell.fill
            fill.solid()
            fill.fore_color.rgb = _rgb(PAPER)
            if header:
                _set_cell_border(cell, bottom=ACCENT, width_pt=1.8)
            elif r_i < last:
                _set_cell_border(cell, bottom=RULE, width_pt=0.75)
            else:
                _set_cell_border(cell, bottom=None, width_pt=0)


def _chart(
    slide: Any,
    left: Any,
    top: Any,
    width: Any,
    height: Any,
    labels: list[str],
    series: list[tuple[str, list[float]]],
    kind: str = "bar",
) -> None:
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE

    data = CategoryChartData()
    data.categories = labels or ["A"]
    if not series:
        data.add_series("値", (1,))
    else:
        for name, values in series:
            data.add_series(name or "値", tuple(values or [0]))
    chart_type = {
        "bar": XL_CHART_TYPE.BAR_CLUSTERED,
        "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
        "stacked": XL_CHART_TYPE.COLUMN_STACKED,
        "pie": XL_CHART_TYPE.PIE,
        "doughnut": XL_CHART_TYPE.DOUGHNUT,
    }.get(kind, XL_CHART_TYPE.BAR_CLUSTERED)
    frame = slide.shapes.add_chart(chart_type, left, top, width, height, data)
    palette = (ACCENT, MUTED, BODY, RULE)
    try:
        chart = frame.chart
        for i, ser in enumerate(chart.series):
            fill = ser.format.fill
            fill.solid()
            fill.fore_color.rgb = _rgb(palette[i % len(palette)])
    except Exception:  # noqa: BLE001
        pass
    return frame


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _item_heading(item: Any) -> str:
    if isinstance(item, str):
        return item
    if not isinstance(item, dict):
        return str(item)
    for key in ("heading", "title", "label", "name", "q", "year", "date", "phase"):
        if item.get(key):
            return str(item[key])
    return ""


def _item_body(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    for key in ("description", "body", "detail", "text", "a", "note", "message", "bio"):
        if item.get(key):
            return str(item[key])
    return ""


def _items_from(content: dict[str, Any]) -> list[dict[str, str]]:
    raw = (
        content.get("items")
        or content.get("steps")
        or content.get("members")
        or content.get("columns")
        or content.get("painPoints")
        or content.get("levels")
        or content.get("logos")
    )
    out: list[dict[str, str]] = []
    for item in _as_list(raw):
        if isinstance(item, str):
            out.append({"heading": item, "body": ""})
        elif isinstance(item, dict):
            out.append({"heading": _item_heading(item), "body": _item_body(item)})
    return [x for x in out if x["heading"] or x["body"]]


# --- layouts ---


@register("parallel-items")
@register("numbered-feature-cards")
@register("three-column")
@register("three-step-column")
@register("awards-parallel")
def _render_cards(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches

    items = _items_from(content)[:4]
    if not items:
        return
    n = max(len(items), 1)
    gap = Inches(0.2)
    total_w = Inches(11.9)
    w = (total_w - gap * (n - 1)) / n
    top = Inches(1.4)
    h = Inches(5.0)
    for i, item in enumerate(items):
        left = Inches(0.7) + (w + gap) * i
        heading = item["heading"] or item["body"]
        body = item["body"] if item["heading"] else ""
        _card(slide, left, top, w, h, heading, body, index=i + 1)


@register("step-flow")
@register("step-up")
def _render_steps(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    _render_cards(slide, prs, content, assets)


@register("user-pain-points")
def _render_pains(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    points = [str(p) for p in _as_list(content.get("painPoints") or content.get("items"))][:6]
    _lines(slide, Inches(0.7), Inches(1.45), Inches(11.9), Inches(5.2), points, size=Pt(18), bullet=True)


@register("quote")
def _render_quote(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    _rect(slide, Inches(0.7), Inches(1.5), Inches(0.1), Inches(4.6), ACCENT)
    _textbox(slide, Inches(1.1), Inches(1.7), Inches(11.2), Inches(3.2), str(content.get("text") or ""), size=Pt(20), color=INK)
    who = " / ".join(x for x in (content.get("author"), content.get("role"), content.get("company")) if x)
    if who:
        _textbox(slide, Inches(1.1), Inches(5.2), Inches(11.2), Inches(0.5), who, size=Pt(14), color=MUTED)


@register("chat-dialogue")
def _render_chat(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    messages = _as_list(content.get("messages"))[:4]
    top = 1.4
    for i, msg in enumerate(messages):
        if isinstance(msg, dict):
            speaker = str(msg.get("speaker") or "")
            text = str(msg.get("text") or "")
        else:
            speaker, text = "", str(msg)
        left = 0.7 if i % 2 == 0 else 4.0
        _rect(slide, Inches(left), Inches(top), Inches(8.4), Inches(1.15), SURFACE)
        _textbox(slide, Inches(left + 0.2), Inches(top + 0.08), Inches(8.0), Inches(0.3), speaker, size=Pt(11), color=MUTED, bold=True)
        _textbox(slide, Inches(left + 0.2), Inches(top + 0.4), Inches(8.0), Inches(0.65), text, size=Pt(14), color=BODY)
        top += 1.3


@register("qa-grid")
def _render_qa(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches

    items = _as_list(content.get("items"))[:4]
    positions = [(0.7, 1.4), (7.0, 1.4), (0.7, 4.15), (7.0, 4.15)]
    for item, (x, y) in zip(items, positions):
        q = _item_heading(item) if not isinstance(item, dict) else str(item.get("q") or _item_heading(item))
        a = _item_body(item) if not isinstance(item, dict) else str(item.get("a") or _item_body(item))
        _card(slide, Inches(x), Inches(y), Inches(5.6), Inches(2.5), q, a)


@register("year-list")
@register("timeline")
def _render_timeline(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    items = _as_list(content.get("items") or content.get("steps"))[:6]
    if not items:
        return
    n = len(items)
    y = Inches(3.4)
    _rect(slide, Inches(0.8), y, Inches(11.6), Inches(0.04), ACCENT)
    for i, item in enumerate(items):
        x = Inches(0.8) + Inches(11.6) * (i / max(n - 1, 1))
        _oval(slide, x - Inches(0.1), y - Inches(0.08), Inches(0.2), Inches(0.2), ACCENT)
        heading = _item_heading(item)
        body = _item_body(item)
        _textbox(slide, x - Inches(0.85), Inches(1.4), Inches(1.8), Inches(1.7), heading, size=Pt(12), color=INK, bold=True, align=PP_ALIGN.CENTER)
        _textbox(slide, x - Inches(0.85), Inches(3.7), Inches(1.8), Inches(2.2), body, size=Pt(11), color=BODY, align=PP_ALIGN.CENTER)


@register("vertical-timeline")
@register("schedule-list")
def _render_vtimeline(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    items = _as_list(content.get("items") or content.get("phases") or content.get("steps"))[:6]
    _rect(slide, Inches(2.15), Inches(1.4), Inches(0.04), Inches(5.2), ACCENT)
    top = 1.4
    for item in items:
        if isinstance(item, dict):
            heading = str(item.get("date") or item.get("phase") or item.get("period") or _item_heading(item))
            body = " ".join(
                str(item.get(k) or "")
                for k in ("title", "description", "details", "owner", "period")
                if item.get(k) and str(item.get(k)) != heading
            )
        else:
            heading, body = str(item), ""
        _oval(slide, Inches(2.02), Inches(top + 0.08), Inches(0.3), Inches(0.3), ACCENT)
        _textbox(slide, Inches(2.55), Inches(top), Inches(9.8), Inches(0.35), heading, size=Pt(14), color=INK, bold=True)
        if body:
            _textbox(slide, Inches(2.55), Inches(top + 0.32), Inches(9.8), Inches(0.45), body, size=Pt(12), color=BODY)
        top += 0.9


@register("comparison-table")
@register("checklist-table")
@register("pricing-table")
def _render_tables(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches

    rows: list[list[str]] = []
    raw_rows = content.get("rows") or []
    if raw_rows and isinstance(raw_rows[0], dict) and "category" in raw_rows[0]:
        rows = [["項目", str(content.get("beforeTitle") or "前"), str(content.get("afterTitle") or "後")]]
        for row in raw_rows:
            rows.append([str(row.get("category") or ""), str(row.get("before") or ""), str(row.get("after") or "")])
    elif content.get("items"):
        headers = [str(h) for h in _as_list(content.get("headers") or ["項目", "状態", "備考"])]
        rows.append(headers)
        for item in content["items"]:
            if isinstance(item, dict):
                checked = "済" if item.get("checked") else "—"
                rows.append([str(item.get("label") or ""), checked, str(item.get("note") or "")])
    elif content.get("headers") and content.get("rows"):
        headers = content["headers"]
        if headers and isinstance(headers[0], dict):
            rows.append([str(h.get("text") or "") for h in headers])
        else:
            rows.append([str(h) for h in headers])
        for row in content["rows"]:
            if row and isinstance(row[0], dict):
                rows.append([str(c.get("text") or "") for c in row])
            else:
                rows.append([str(c) for c in row])
    _add_table(slide, Inches(0.7), Inches(1.4), Inches(11.9), Inches(5.1), rows)


@register("before-after-split")
def _render_ba(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    for x, key in ((0.7, "before"), (7.05, "after")):
        block = content.get(key) if isinstance(content.get(key), dict) else {}
        _rect(slide, Inches(x), Inches(1.4), Inches(5.55), Inches(5.1), SURFACE)
        _textbox(slide, Inches(x + 0.25), Inches(1.55), Inches(5.1), Inches(0.45), str(block.get("title") or key), size=Pt(16), color=INK, bold=True)
        points = [str(p) for p in _as_list(block.get("points"))]
        _lines(slide, Inches(x + 0.25), Inches(2.15), Inches(5.1), Inches(4.1), points, size=Pt(14), bullet=True)


@register("kpi-three-col")
@register("tam-parallel")
def _render_kpis(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    items = _as_list(content.get("items"))[:3]
    n = max(len(items), 1)
    w = Inches(11.9) / n - Inches(0.15)
    for i, item in enumerate(items):
        left = Inches(0.7) + (w + Inches(0.2)) * i
        if isinstance(item, dict):
            value = str(item.get("value") or "")
            label = str(item.get("label") or "")
        else:
            value, label = str(item), ""
        _rect(slide, left, Inches(2.0), w, Inches(3.4), SURFACE)
        _textbox(slide, left, Inches(2.4), w, Inches(1.4), value, size=Pt(36), color=ACCENT, bold=True, align=PP_ALIGN.CENTER)
        _textbox(slide, left, Inches(4.0), w, Inches(0.8), label, size=Pt(14), color=INK, align=PP_ALIGN.CENTER)


@register("text-data-emphasis")
def _render_emphasis(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    _textbox(slide, Inches(0.7), Inches(1.5), Inches(7.0), Inches(4.8), str(content.get("narrative") or ""), size=Pt(18), color=BODY)
    _rect(slide, Inches(8.1), Inches(2.0), Inches(4.4), Inches(3.6), SURFACE)
    _textbox(slide, Inches(8.1), Inches(2.4), Inches(4.4), Inches(1.6), str(content.get("bigNumber") or ""), size=Pt(40), color=ACCENT, bold=True, align=PP_ALIGN.CENTER)
    _textbox(slide, Inches(8.1), Inches(4.2), Inches(4.4), Inches(0.7), str(content.get("bigNumberLabel") or ""), size=Pt(14), color=INK, align=PP_ALIGN.CENTER)


@register("kpi-formula")
def _render_formula(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    _textbox(slide, Inches(0.7), Inches(2.0), Inches(11.9), Inches(0.6), str(content.get("kpiName") or "指標"), size=Pt(18), color=INK, bold=True, align=PP_ALIGN.CENTER)
    _textbox(
        slide,
        Inches(0.7),
        Inches(3.0),
        Inches(11.9),
        Inches(1.2),
        f"{content.get('numerator') or ''}  /  {content.get('denominator') or ''}",
        size=Pt(28),
        color=ACCENT,
        bold=True,
        align=PP_ALIGN.CENTER,
    )
    notes = [str(a) for a in _as_list(content.get("annotations"))]
    if notes:
        _lines(slide, Inches(0.7), Inches(4.6), Inches(11.9), Inches(1.6), notes, size=Pt(12))


@register("kpi-logic-tree")
@register("radial-spread")
@register("convergence")
@register("containment")
@register("venn-diagram")
@register("three-way-relation")
@register("funnel")
@register("pyramid")
@register("cycle")
@register("tam-concentric")
@register("matrix-quadrant")
@register("channel-mapping")
@register("business-concept")
def _render_diagram_fallback(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    """関係図系は簡易カード列。本図は Mermaid PNG 側を優先する。"""
    items = _items_from(content)
    if not items:
        extra = []
        for key in ("center", "root", "target", "outer", "a", "b"):
            block = content.get(key)
            if isinstance(block, dict) and (block.get("label") or block.get("title")):
                extra.append({"heading": str(block.get("label") or block.get("title")), "body": str(block.get("description") or "")})
        items = extra
    if items:
        _render_cards(slide, prs, {"items": items}, assets)
        return
    from pptx.util import Inches, Pt

    _textbox(slide, Inches(0.7), Inches(2.4), Inches(11.9), Inches(2.0), "図は本文の画像または Mermaid を参照", size=Pt(16), color=MUTED)


@register("doughnut-three-col")
@register("pie-chart-highlight")
@register("two-col-text-chart")
@register("stacked-bar-chart")
@register("horizontal-bar-ranking")
def _render_charts(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    if content.get("charts"):
        charts = _as_list(content["charts"])[:3]
        n = max(len(charts), 1)
        w = Inches(11.9) / n - Inches(0.1)
        for i, ch in enumerate(charts):
            left = Inches(0.7) + (w + Inches(0.15)) * i
            labels = [str(x) for x in _as_list(ch.get("labels"))]
            values = [float(v) for v in _as_list(ch.get("values"))]
            _textbox(slide, left, Inches(1.35), w, Inches(0.35), str(ch.get("title") or ""), size=Pt(12), color=INK, bold=True)
            _chart(slide, left, Inches(1.8), w, Inches(4.6), labels, [("値", values)], "doughnut")
        return
    if content.get("left") or content.get("right"):
        left = content.get("left") if isinstance(content.get("left"), dict) else {}
        right = content.get("right") if isinstance(content.get("right"), dict) else {}
        _textbox(slide, Inches(0.7), Inches(1.4), Inches(5.8), Inches(0.5), str(left.get("heading") or ""), size=Pt(16), color=INK, bold=True)
        _textbox(slide, Inches(0.7), Inches(2.0), Inches(5.8), Inches(4.4), str(left.get("body") or ""), size=Pt(14), color=BODY)
        data = right.get("data") if isinstance(right.get("data"), dict) else {}
        labels = [str(x) for x in _as_list(data.get("labels"))]
        values = [float(v) for v in _as_list(data.get("values"))]
        kind = "doughnut" if str(right.get("chartType") or "") == "doughnut" else "column"
        _chart(slide, Inches(6.8), Inches(1.5), Inches(5.7), Inches(5.0), labels, [("値", values)], kind)
        return
    if content.get("data"):
        data = content["data"] if isinstance(content["data"], dict) else {}
        labels = [str(x) for x in _as_list(data.get("labels"))]
        values = [float(v) for v in _as_list(data.get("values"))]
        _chart(slide, Inches(0.7), Inches(1.4), Inches(7.4), Inches(5.1), labels, [("値", values)], "pie")
        hi = content.get("highlight") if isinstance(content.get("highlight"), dict) else {}
        _rect(slide, Inches(8.4), Inches(2.2), Inches(4.1), Inches(3.2), SURFACE)
        _textbox(slide, Inches(8.5), Inches(2.5), Inches(3.9), Inches(1.2), str(hi.get("value") or ""), size=Pt(28), color=ACCENT, bold=True)
        _textbox(slide, Inches(8.5), Inches(3.8), Inches(3.9), Inches(1.2), str(hi.get("message") or ""), size=Pt(13), color=BODY)
        return
    if content.get("categories") and content.get("series"):
        labels = [str(x) for x in content["categories"]]
        series = [(str(s.get("name") or "値"), [float(v) for v in _as_list(s.get("values"))]) for s in content["series"] if isinstance(s, dict)]
        _chart(slide, Inches(0.7), Inches(1.4), Inches(11.9), Inches(5.1), labels, series, "stacked")
        return
    items = _as_list(content.get("items"))
    labels = [_item_heading(it) for it in items]
    values = []
    for it in items:
        try:
            values.append(float(it.get("value") if isinstance(it, dict) else 0))
        except (TypeError, ValueError):
            values.append(0)
    _chart(slide, Inches(0.7), Inches(1.4), Inches(11.9), Inches(5.1), labels, [("値", values)], "bar")


@register("ceo-message")
def _render_ceo(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    photo = str(content.get("photo") or content.get("path") or "")
    if not _picture(slide, photo, assets, Inches(0.7), Inches(1.5), Inches(3.4)):
        _placeholder(slide, Inches(0.7), Inches(1.5), Inches(3.4), Inches(4.6), str(content.get("name") or ""))
    _textbox(slide, Inches(4.4), Inches(1.5), Inches(8.1), Inches(0.45), str(content.get("name") or ""), size=Pt(20), color=INK, bold=True)
    _textbox(slide, Inches(4.4), Inches(2.0), Inches(8.1), Inches(0.35), str(content.get("role") or ""), size=Pt(13), color=MUTED)
    _textbox(slide, Inches(4.4), Inches(2.5), Inches(8.1), Inches(3.6), str(content.get("message") or content.get("bio") or ""), size=Pt(16), color=BODY)


@register("member-grid")
@register("member-three-col")
def _render_members(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    _render_cards(slide, prs, {"items": _as_list(content.get("members"))}, assets)


@register("fullscreen-photo")
def _render_photo(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    rel = str(content.get("backgroundPath") or content.get("image") or "")
    if not _picture(slide, rel, assets, Inches(0.7), Inches(1.35), Inches(11.9)):
        _placeholder(slide, Inches(0.7), Inches(1.35), Inches(11.9), Inches(4.0), "図")
    caption = str(content.get("headline") or "").strip()
    if caption:
        _textbox(slide, Inches(0.7), Inches(6.05), Inches(11.9), Inches(0.4), caption, size=Pt(14), color=INK, bold=True)


@register("logo-wall")
def _render_logos(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    logos = _as_list(content.get("logos"))[:8]
    for i, logo in enumerate(logos):
        col, row = i % 4, i // 4
        left = Inches(0.7) + Inches(3.05) * col
        top = Inches(1.5) + Inches(2.5) * row
        name = str(logo.get("name") if isinstance(logo, dict) else logo)
        path = str(logo.get("path") if isinstance(logo, dict) else "")
        if not _picture(slide, path, assets, left, top, Inches(2.8)):
            _rect(slide, left, top, Inches(2.8), Inches(2.1), SURFACE)
            _textbox(slide, left, top + Inches(0.8), Inches(2.8), Inches(0.5), name, size=Pt(14), color=INK, align=PP_ALIGN.CENTER)


@register("location-map")
def _render_map(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    _rect(slide, Inches(0.7), Inches(1.4), Inches(11.9), Inches(5.1), SURFACE)
    for loc in _as_list(content.get("locations")):
        if not isinstance(loc, dict):
            continue
        x = 0.7 + 11.9 * (float(loc.get("posX") or 50) / 100.0)
        y = 1.4 + 5.1 * (float(loc.get("posY") or 50) / 100.0)
        color = ACCENT if loc.get("isHQ") else BODY
        _oval(slide, Inches(x), Inches(y), Inches(0.22), Inches(0.22), color)
        _textbox(slide, Inches(x + 0.25), Inches(y - 0.08), Inches(2.4), Inches(0.35), str(loc.get("name") or ""), size=Pt(12), color=INK)


@register("case-two-col")
def _render_case(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    _textbox(slide, Inches(0.7), Inches(1.35), Inches(11.9), Inches(0.45), str(content.get("companyName") or ""), size=Pt(18), color=INK, bold=True)
    info = [f"{i.get('key')}: {i.get('value')}" for i in _as_list(content.get("info")) if isinstance(i, dict)]
    metrics = [f"{i.get('key')}: {i.get('value')}" for i in _as_list(content.get("metrics")) if isinstance(i, dict)]
    _lines(slide, Inches(0.7), Inches(2.0), Inches(5.8), Inches(4.4), info, size=Pt(14), bullet=True)
    _lines(slide, Inches(6.8), Inches(2.0), Inches(5.8), Inches(4.4), metrics, size=Pt(14), bullet=True)


@register("axis-table")
def _render_axis_table(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches

    headers = [str(h) for h in _as_list(content.get("headers") or ["項目", "内容"])]
    rows: list[list[str]] = [headers]
    for row in _as_list(content.get("rows")):
        if isinstance(row, dict):
            vals = [str(v) for v in row.values()]
            rows.append((vals + [""] * len(headers))[: len(headers)])
        elif isinstance(row, list):
            rows.append([str(c) for c in row])
        else:
            rows.append([str(row)])
    _add_table(slide, Inches(0.7), Inches(1.4), Inches(11.9), Inches(4.9), rows)


@register("premise-conclusion")
def _render_premise(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    left = content.get("left") if isinstance(content.get("left"), dict) else {}
    right = content.get("right") if isinstance(content.get("right"), dict) else {}
    _textbox(slide, Inches(0.7), Inches(1.3), Inches(5.4), Inches(0.4), str(left.get("header") or "前提"), size=Pt(14), color=INK, bold=True)
    _rect(slide, Inches(0.7), Inches(1.72), Inches(5.4), Inches(0.02), ACCENT)
    left_rows = _as_list(left.get("rows"))
    table_rows: list[list[str]] = []
    for row in left_rows:
        if isinstance(row, list):
            table_rows.append([str(c) for c in row[:2]])
        elif isinstance(row, dict):
            table_rows.append([str(row.get("axis") or row.get("label") or ""), str(row.get("text") or row.get("body") or "")])
        else:
            table_rows.append([str(row), ""])
    if table_rows:
        _add_table(slide, Inches(0.7), Inches(1.9), Inches(5.4), Inches(4.4), table_rows)
    arrow = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, Inches(6.25), Inches(3.7), Inches(0.7), Inches(0.35))
    _solid(arrow, ACCENT)
    _textbox(slide, Inches(7.15), Inches(1.3), Inches(5.4), Inches(0.4), str(right.get("header") or "意味合い"), size=Pt(14), color=INK, bold=True)
    _rect(slide, Inches(7.15), Inches(1.72), Inches(5.4), Inches(0.02), ACCENT)
    bullets = [str(b) for b in _as_list(right.get("bullets") or right.get("points"))]
    _lines(slide, Inches(7.15), Inches(1.95), Inches(5.4), Inches(4.3), bullets, size=Pt(14), bullet=True)


@register("chevron-steps")
def _render_chevron(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    steps = _as_list(content.get("steps") or content.get("items"))[:6]
    if not steps:
        return
    n = len(steps)
    gap = Inches(0.12)
    total = Inches(11.9)
    w = (total - gap * (n - 1)) / n
    top = Inches(2.2)
    h = Inches(1.6)
    for i, step in enumerate(steps):
        left = Inches(0.7) + (w + gap) * i
        shape = slide.shapes.add_shape(MSO_SHAPE.CHEVRON, left, top, w, h)
        _solid(shape, ACCENT if i == 0 else SURFACE)
        if isinstance(step, dict):
            n_lab = str(step.get("n") or i + 1)
            title = str(step.get("title") or step.get("heading") or step.get("label") or "")
            text = str(step.get("text") or step.get("description") or step.get("body") or "")
        else:
            n_lab, title, text = str(i + 1), str(step), ""
        ink = ON_ACCENT if i == 0 else INK
        _textbox(slide, left + Inches(0.15), top + Inches(0.12), w - Inches(0.4), Inches(0.35), n_lab, size=Pt(11), color=ink, bold=True, align=PP_ALIGN.LEFT)
        _textbox(slide, left + Inches(0.15), top + Inches(0.45), w - Inches(0.4), Inches(0.45), title, size=Pt(13), color=ink, bold=True)
        _textbox(slide, left + Inches(0.15), top + Inches(0.95), w - Inches(0.4), Inches(0.5), text, size=Pt(11), color=ink)


@register("chart-insight")
def _render_chart_insight(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    labels = [str(x) for x in _as_list(content.get("labels"))]
    values: list[float] = []
    for v in _as_list(content.get("values")):
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            values.append(0)
    if content.get("data") and isinstance(content["data"], dict):
        labels = labels or [str(x) for x in _as_list(content["data"].get("labels"))]
        if not values:
            for v in _as_list(content["data"].get("values")):
                try:
                    values.append(float(v))
                except (TypeError, ValueError):
                    values.append(0)
    unit = str(content.get("unit") or "")
    if unit:
        _textbox(slide, Inches(0.7), Inches(1.25), Inches(6.3), Inches(0.3), unit, size=Pt(11), color=MUTED)
    _chart(slide, Inches(0.7), Inches(1.55), Inches(6.4), Inches(4.9), labels, [("値", values)], str(content.get("kind") or "bar"))
    insight = content.get("insight") if isinstance(content.get("insight"), dict) else {}
    header = str(insight.get("header") or content.get("insightHeader") or "意味合い")
    bullets = [str(b) for b in _as_list(insight.get("bullets") or content.get("bullets"))]
    _textbox(slide, Inches(7.35), Inches(1.3), Inches(5.25), Inches(0.4), header, size=Pt(14), color=INK, bold=True)
    _rect(slide, Inches(7.35), Inches(1.72), Inches(5.25), Inches(0.02), ACCENT)
    _lines(slide, Inches(7.35), Inches(1.95), Inches(5.25), Inches(4.4), bullets, size=Pt(14), bullet=True)


def validate_deck(deck: Any) -> dict[str, Any] | None:
    if not isinstance(deck, dict):
        return None
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        return None
    out: list[dict[str, Any]] = []
    for raw in slides:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("type") or "content")
        if kind not in {"cover", "section", "content", "case-study", "ending"}:
            kind = "content"
        slide = dict(raw)
        slide["type"] = kind
        if kind in {"content", "case-study"}:
            slide["layout"] = normalize_layout(slide.get("layout"))
            if not content_nonempty(slide.get("content")):
                continue
        elif not str(slide.get("title") or "").strip():
            continue
        out.append(slide)
    if not out:
        return None
    return {"slides": out}


def render_deck(deck: dict[str, Any], assets: dict[str, bytes] | None = None) -> bytes:
    """検証済み deck を PPTX バイト列にする。"""
    from pptx import Presentation
    from pptx.util import Inches

    assets = assets or {}
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    for slide_def in deck.get("slides") or []:
        kind = slide_def.get("type")
        notes = str(slide_def.get("notes") or "")
        if kind == "cover":
            slide = _add_title_slide(prs, str(slide_def.get("title") or ""), str(slide_def.get("subtitle") or ""))
            _add_notes(slide, notes)
            continue
        if kind == "section":
            slide = _add_section_slide(prs, str(slide_def.get("title") or ""))
            _add_notes(slide, notes)
            continue
        if kind == "ending":
            slide = _add_ending_slide(prs, str(slide_def.get("title") or ""), str(slide_def.get("subtitle") or ""))
            _add_notes(slide, notes)
            continue
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        layout = slide_def.get("layout") if slide_def.get("layout") in LAYOUT_ID_SET else DEFAULT_LAYOUT
        if layout != "fullscreen-photo":
            _add_content_chrome(slide, prs, str(slide_def.get("title") or ""))
        else:
            _fill_slide(slide)
            _add_content_chrome(slide, prs, str(slide_def.get("title") or ""))
        content = slide_def.get("content") if isinstance(slide_def.get("content"), dict) else {}
        renderer = _REGISTRY.get(layout) or _REGISTRY[DEFAULT_LAYOUT]
        renderer(slide, prs, content, assets)
        _add_source(slide, prs, str(slide_def.get("source") or content.get("source") or ""))
        _add_notes(slide, notes)
    _add_footers(prs)
    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()


def registered_layouts() -> tuple[str, ...]:
    return tuple(sorted(_REGISTRY))
