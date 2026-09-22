"""deck JSON を DADS トークンで描く決定論レンダラ（python-pptx）。"""

from __future__ import annotations

import io
from typing import Any, Callable

from app.dads import (
    ACCENT,
    BODY,
    FONT,
    INK,
    ON_ACCENT,
    PAPER,
    PPTX_FRAME,
    PPTX_MUTED,
    PPTX_TYPE,
    PRIMARY_SURFACE,
    RULE,
    RULE_MEANINGFUL,
    SERIES,
    SURFACE,
    pptx_content_height,
    pptx_content_width,
)
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


def _inches_of(value: Any) -> float:
    if hasattr(value, "inches"):
        return float(value.inches)
    if hasattr(value, "pt"):
        return float(value.pt) / 72.0
    return float(value)


def _pt_of(value: Any) -> float:
    if hasattr(value, "pt"):
        return float(value.pt)
    return float(value)


def _char_capacity(width: Any, height: Any, size: Any, *, line_height: float = 1.5) -> int:
    """箱に収まるおおよその全角字数。溢れたときだけ自動縮小する判定に使う。"""
    pt = max(_pt_of(size), 8.0)
    chars = max(int(_inches_of(width) * 72 / pt), 4)
    lines = max(int(_inches_of(height) * 72 / (pt * line_height)), 1)
    return chars * lines


def _needs_autofit(text: str, width: Any, height: Any, size: Any) -> bool:
    compact = (text or "").replace("\n", "")
    return len(compact) > _char_capacity(width, height, size)


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
    from pptx.enum.text import MSO_AUTO_SIZE

    box = slide.shapes.add_textbox(left, top, width, height)
    box.text_frame.word_wrap = True
    # 収まるなら固定 pt。溢れた箱だけ TEXT_TO_FIT（本文を先に小さくしない）。
    box.text_frame.auto_size = (
        MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        if _needs_autofit(text, width, height, size)
        else MSO_AUTO_SIZE.NONE
    )
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
    from pptx.enum.text import MSO_AUTO_SIZE
    from pptx.util import Pt

    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame
    tf.word_wrap = True
    blob = "\n".join(f"•  {line}" if bullet else line for line in lines)
    tf.auto_size = (
        MSO_AUTO_SIZE.TEXT_TO_FIT_SHAPE
        if _needs_autofit(blob, width, height, size)
        else MSO_AUTO_SIZE.NONE
    )
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
    _textbox(slide, title_left, top + Inches(0.14), title_width, Inches(0.44), heading, size=Pt(PPTX_TYPE["card_head"]), color=INK, bold=True)
    if body:
        _textbox(
            slide,
            title_left,
            top + Inches(0.56),
            title_width,
            height - Inches(0.7),
            body,
            size=Pt(PPTX_TYPE["body"]),
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
    from pptx.util import Inches, Pt

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _fill_slide(slide)
    left = Inches(PPTX_FRAME["left"])
    width = Inches(pptx_content_width())
    # Web ヘッダー帯は置かない。大きな題名＋短い副題＋短い強調罫。
    box = slide.shapes.add_textbox(left, Inches(2.1), width, Inches(2.2))
    box.text_frame.word_wrap = True
    _style_p(box.text_frame.paragraphs[0], title, size=Pt(PPTX_TYPE["cover"]), color=INK, bold=True)
    if subtitle:
        _textbox(
            slide,
            left,
            Inches(4.5),
            width,
            Inches(0.8),
            subtitle,
            size=Pt(PPTX_TYPE["subhead"]),
            color=PPTX_MUTED,
        )
    _rect(slide, left, Inches(5.5), Inches(PPTX_FRAME["rule_width"]), Inches(PPTX_FRAME["rule_height"]), ACCENT)
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
    _textbox(
        slide,
        Inches(PPTX_FRAME["left"]),
        Inches(2.6),
        Inches(pptx_content_width()),
        Inches(1.4),
        title or "まとめ",
        size=Pt(PPTX_TYPE["title"]),
        color=INK,
        bold=True,
    )
    if subtitle:
        _textbox(
            slide,
            Inches(PPTX_FRAME["left"]),
            Inches(4.2),
            Inches(pptx_content_width()),
            Inches(0.7),
            subtitle,
            size=Pt(PPTX_TYPE["subhead"]),
            color=PPTX_MUTED,
        )
    return slide


def _add_content_chrome(slide: Any, prs: Any, title: str) -> None:
    from pptx.util import Inches, Pt

    _fill_slide(slide)
    left = Inches(PPTX_FRAME["left"])
    width = Inches(pptx_content_width())
    _textbox(
        slide,
        left,
        Inches(PPTX_FRAME["top"]),
        width,
        Inches(1.15),
        title,
        size=Pt(PPTX_TYPE["title"]),
        color=INK,
        bold=True,
    )
    rule_top = PPTX_FRAME["content_top"] - 0.28
    _rect(slide, left, Inches(rule_top), Inches(PPTX_FRAME["rule_width"]), Inches(PPTX_FRAME["rule_height"]), ACCENT)


def _add_source(slide: Any, prs: Any, source: str) -> None:
    from pptx.util import Inches, Pt

    text = (source or "").strip()
    if not text:
        return
    _textbox(
        slide,
        Inches(PPTX_FRAME["left"]),
        Inches(PPTX_FRAME["footer_top"]),
        Inches(pptx_content_width() - 1.6),
        Inches(0.28),
        text,
        size=Pt(PPTX_TYPE["caption"]),
        color=PPTX_MUTED,
    )


def _add_footers(prs: Any) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    total = len(prs.slides)
    page_left = PPTX_FRAME["left"] + pptx_content_width() - 1.3
    for i, slide in enumerate(prs.slides, start=1):
        if i == 1:
            continue
        _rect(
            slide,
            Inches(PPTX_FRAME["left"]),
            Inches(PPTX_FRAME["footer_top"] - 0.08),
            Inches(pptx_content_width()),
            Inches(0.01),
            RULE,
        )
        box = slide.shapes.add_textbox(
            Inches(page_left), Inches(PPTX_FRAME["footer_top"]), Inches(1.3), Inches(0.3)
        )
        p = box.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT
        run = p.add_run()
        run.text = f"{i} / {total}"
        _set_run_font(run, size=Pt(PPTX_TYPE["footer"]), color=PPTX_MUTED)


def _picture(slide: Any, rel: str, assets: dict[str, bytes], left: Any, top: Any, width: Any) -> bool:
    from app.pptx_figure import asset_png, is_png

    data = asset_png(rel, assets)
    if not is_png(data):
        raw = assets.get(rel) if rel else None
        if is_png(raw):
            data = raw
    if not is_png(data):
        return False
    try:
        slide.shapes.add_picture(io.BytesIO(data), left, top, width=width)
        return True
    except Exception as exc:  # noqa: BLE001
        log = __import__("logging").getLogger("procuretech-generate")
        log.info("pptx picture failed %s: %s", rel, exc)
        return False


def _placeholder(slide: Any, left: Any, top: Any, width: Any, height: Any, label: str) -> None:
    from pptx.util import Pt

    _rect(slide, left, top, width, height, SURFACE)
    _textbox(slide, left, top + height / 3, width, height / 3, label or "画像", size=Pt(PPTX_TYPE["caption"]), color=PPTX_MUTED)


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
            size = Pt(PPTX_TYPE["table"])
            for p in cell.text_frame.paragraphs:
                for run in p.runs:
                    _set_run_font(
                        run,
                        size=size,
                        color=INK,
                        bold=header or axis,
                    )
            fill = cell.fill
            fill.solid()
            fill.fore_color.rgb = _rgb(PRIMARY_SURFACE if header else PAPER)
            if header:
                _set_cell_border(cell, bottom=ACCENT, width_pt=1.5)
            elif r_i < last:
                _set_cell_border(cell, bottom=RULE_MEANINGFUL, width_pt=0.75)
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
    palette = SERIES
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


@register("fullwidth-points")
def _render_fullwidth(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    from app.pptx_repair import _echoes_title

    title = str(content.get("_slide_title") or "")
    points = [
        str(p)
        for p in _as_list(content.get("points"))
        if str(p).strip() and not _echoes_title(p, title)
    ]
    if not points:
        points = [
            x["heading"] or x["body"]
            for x in _items_from(content)
            if (x["heading"] or x["body"]) and not _echoes_title(x["heading"] or x["body"], title)
        ]
    if not points:
        narrative = str(content.get("narrative") or content.get("text") or "").strip()
        if narrative:
            points = [narrative]
    if not points:
        return
    _lines(
        slide,
        Inches(PPTX_FRAME["left"]),
        Inches(PPTX_FRAME["content_top"]),
        Inches(pptx_content_width()),
        Inches(pptx_content_height()),
        points[:8],
        size=Pt(PPTX_TYPE["body"]),
        bullet=len(points) > 1,
    )


@register("parallel-items")
@register("numbered-feature-cards")
@register("three-column")
@register("three-step-column")
@register("awards-parallel")
def _render_cards(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    from pptx.util import Inches, Pt

    from app.pptx_repair import _echoes_title

    title = str(content.get("_slide_title") or "")
    items = []
    for raw in _items_from(content)[:4]:
        heading = "" if _echoes_title(raw["heading"], title) else raw["heading"]
        body = raw["body"]
        if heading or body:
            items.append({"heading": heading or body, "body": body if heading else ""})
    if not items:
        return
    left0 = Inches(PPTX_FRAME["left"])
    top = Inches(PPTX_FRAME["content_top"])
    height = Inches(pptx_content_height())
    width = Inches(pptx_content_width())
    # 1件は全幅、2件は2列。囲みカードは並列が3件以上のときだけ。
    if len(items) == 1:
        heading = items[0]["heading"]
        body = items[0]["body"]
        lines = [x for x in (heading, body) if x]
        _lines(slide, left0, top, width, height, lines, size=Pt(PPTX_TYPE["body"]), bullet=len(lines) > 1)
        return
    if len(items) == 2:
        gap = Inches(PPTX_FRAME["column_gap"])
        col_w = (width - gap) / 2
        for i, item in enumerate(items):
            left = left0 + (col_w + gap) * i
            heading = item["heading"] or item["body"]
            body = item["body"] if item["heading"] else ""
            _textbox(slide, left, top, col_w, Inches(0.5), heading, size=Pt(PPTX_TYPE["subhead"]), color=INK, bold=True)
            if body:
                _textbox(slide, left, top + Inches(0.55), col_w, height - Inches(0.55), body, size=Pt(PPTX_TYPE["body"]))
        return
    n = max(len(items), 1)
    gap = Inches(0.2)
    w = (width - gap * (n - 1)) / n
    for i, item in enumerate(items):
        left = left0 + (w + gap) * i
        heading = item["heading"] or item["body"]
        body = item["body"] if item["heading"] else ""
        _card(slide, left, top, w, height, heading, body, index=i + 1)


def _flow_items(content: dict[str, Any]) -> list[dict[str, str]]:
    items = _items_from(content)
    if items:
        return items[:5]
    steps = _as_list(content.get("steps"))
    out: list[dict[str, str]] = []
    for i, step in enumerate(steps[:5]):
        if isinstance(step, dict):
            out.append(
                {
                    "heading": str(step.get("title") or step.get("heading") or step.get("label") or ""),
                    "body": str(step.get("text") or step.get("description") or step.get("body") or ""),
                }
            )
        else:
            out.append({"heading": str(step), "body": ""})
    return [x for x in out if x["heading"] or x["body"]]


def _render_process_row(slide: Any, items: list[dict[str, str]]) -> None:
    """DADS のプロセス型。一列に箱＋矢印。斜めには置かない。"""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    n = len(items)
    left0 = PPTX_FRAME["left"]
    width = pptx_content_width()
    arrow_w = 0.26 if n > 1 else 0.0
    box_w = (width - arrow_w * max(n - 1, 0)) / n
    top = PPTX_FRAME["content_top"] + 0.85
    h = 2.4
    for i, item in enumerate(items):
        x = left0 + i * (box_w + arrow_w)
        _rect(slide, Inches(x), Inches(top), Inches(box_w - 0.04), Inches(h), PRIMARY_SURFACE if i == 0 else SURFACE)
        heading = item["heading"] or item["body"]
        body = item["body"] if item["heading"] else ""
        _textbox(
            slide,
            Inches(x + 0.12),
            Inches(top + 0.16),
            Inches(box_w - 0.28),
            Inches(0.4),
            str(i + 1),
            size=Pt(PPTX_TYPE["caption"]),
            color=ACCENT,
            bold=True,
        )
        _textbox(
            slide,
            Inches(x + 0.12),
            Inches(top + 0.55),
            Inches(box_w - 0.28),
            Inches(0.9),
            heading,
            size=Pt(PPTX_TYPE["subhead"]),
            color=INK,
            bold=True,
        )
        if body:
            _textbox(
                slide,
                Inches(x + 0.12),
                Inches(top + 1.5),
                Inches(box_w - 0.28),
                Inches(0.7),
                body,
                size=Pt(PPTX_TYPE["body"]),
                color=BODY,
            )
        if i < n - 1:
            shape = slide.shapes.add_shape(
                MSO_SHAPE.RIGHT_ARROW,
                Inches(x + box_w - 0.02),
                Inches(top + h / 2 - 0.12),
                Inches(arrow_w),
                Inches(0.24),
            )
            _solid(shape, ACCENT)


def _render_branch_flow(slide: Any, root: dict[str, str], branches: list[dict[str, str]]) -> None:
    """上段に起点、下段に分岐を横並び。樹形を斜めにしない。"""
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    left0 = PPTX_FRAME["left"]
    width = pptx_content_width()
    top = PPTX_FRAME["content_top"]
    _rect(slide, Inches(left0), Inches(top), Inches(width), Inches(1.55), PRIMARY_SURFACE)
    _textbox(
        slide,
        Inches(left0 + 0.25),
        Inches(top + 0.2),
        Inches(width - 0.5),
        Inches(1.15),
        root.get("heading") or root.get("body") or "",
        size=Pt(PPTX_TYPE["subhead"]),
        color=INK,
        bold=True,
        align=PP_ALIGN.CENTER,
    )
    row = branches[:4]
    if not row:
        return
    gap = 0.2
    w = (width - gap * (len(row) - 1)) / len(row)
    y = top + 1.85
    h = pptx_content_height() - 1.95
    for i, item in enumerate(row):
        x = left0 + i * (w + gap)
        _rect(slide, Inches(x), Inches(y), Inches(w), Inches(h), SURFACE)
        _rect(slide, Inches(x), Inches(y), Inches(w), Inches(0.08), ACCENT)
        heading = item.get("heading") or item.get("body") or ""
        body = item.get("body") if item.get("heading") else ""
        _textbox(
            slide,
            Inches(x + 0.16),
            Inches(y + 0.22),
            Inches(w - 0.32),
            Inches(1.1),
            heading,
            size=Pt(PPTX_TYPE["card_head"]),
            color=INK,
            bold=True,
        )
        if body:
            _textbox(
                slide,
                Inches(x + 0.16),
                Inches(y + 1.35),
                Inches(w - 0.32),
                Inches(h - 1.55),
                body,
                size=Pt(PPTX_TYPE["body"]),
                color=BODY,
            )


@register("step-flow")
@register("step-up")
def _render_steps(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    items = _flow_items(content)
    if not items:
        return
    branches = _as_list(content.get("branches"))
    branch_items: list[dict[str, str]] = []
    for raw in branches:
        if isinstance(raw, dict):
            branch_items.append(
                {
                    "heading": str(raw.get("title") or raw.get("heading") or raw.get("label") or ""),
                    "body": str(raw.get("text") or raw.get("description") or raw.get("body") or ""),
                }
            )
        else:
            branch_items.append({"heading": str(raw), "body": ""})
    branch_items = [x for x in branch_items if x["heading"] or x["body"]]
    if content.get("mode") == "branch" and len(items) >= 2:
        _render_branch_flow(slide, items[0], branch_items or items[1:])
        return
    _render_process_row(slide, items)


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
        _textbox(slide, Inches(1.1), Inches(5.2), Inches(11.2), Inches(0.5), who, size=Pt(14), color=PPTX_MUTED)


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
        _textbox(slide, Inches(left + 0.2), Inches(top + 0.08), Inches(8.0), Inches(0.3), speaker, size=Pt(11), color=PPTX_MUTED, bold=True)
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
        _textbox(slide, Inches(x + 0.25), Inches(1.55), Inches(5.1), Inches(0.45), str(block.get("title") or key), size=Pt(PPTX_TYPE["subhead"]), color=INK, bold=True)
        points = [str(p) for p in _as_list(block.get("points"))]
        _lines(slide, Inches(x + 0.25), Inches(2.15), Inches(5.1), Inches(4.1), points, size=Pt(PPTX_TYPE["body"]), bullet=True)


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

    _textbox(slide, Inches(0.7), Inches(2.4), Inches(11.9), Inches(2.0), "図は本文の画像または Mermaid を参照", size=Pt(16), color=PPTX_MUTED)


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
    _textbox(slide, Inches(4.4), Inches(2.0), Inches(8.1), Inches(0.35), str(content.get("role") or ""), size=Pt(13), color=PPTX_MUTED)
    _textbox(slide, Inches(4.4), Inches(2.5), Inches(8.1), Inches(3.6), str(content.get("message") or content.get("bio") or ""), size=Pt(16), color=BODY)


@register("member-grid")
@register("member-three-col")
def _render_members(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    _render_cards(slide, prs, {"items": _as_list(content.get("members"))}, assets)


@register("figure-frame")
def _render_figure_frame(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    """図の枠。PNG があれば埋め、無ければ Mermaid フローを箱で描く。"""
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Inches, Pt

    from app.pptx_figure import mermaid_to_flow_items

    left = Inches(PPTX_FRAME["left"])
    top = Inches(PPTX_FRAME["content_top"])
    width = Inches(pptx_content_width())
    height = Inches(pptx_content_height())
    rel = str(content.get("image") or "").strip()
    pad = Inches(0.28)
    if _picture(slide, rel, assets, left + pad, top + Inches(0.28), width - pad * 2):
        return
    if rel:
        import logging

        logging.getLogger("procuretech-generate").info(
            "pptx figure: no png for %s (assets=%s)",
            rel,
            [k for k in (assets or {}) if str(k).endswith(".png")][:12],
        )
    items, mode = mermaid_to_flow_items(str(content.get("mermaid") or ""))
    if items:
        if mode == "branch" and len(items) >= 3:
            _render_branch_flow(slide, items[0], items[1:])
        else:
            _render_process_row(slide, items)
        return
    frame = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    frame.fill.solid()
    frame.fill.fore_color.rgb = _rgb(SURFACE)
    frame.line.color.rgb = _rgb(RULE_MEANINGFUL)
    frame.line.width = Pt(1.25)
    _rect(slide, left, top, Inches(PPTX_FRAME["rule_width"]), Inches(PPTX_FRAME["rule_height"]), ACCENT)
    alt = str(content.get("alt") or "").strip() or "ここに図を入れる"
    _textbox(
        slide,
        left + Inches(0.4),
        top + height / 3,
        width - Inches(0.8),
        Inches(1.4),
        alt,
        size=Pt(PPTX_TYPE["subhead"]),
        color=PPTX_MUTED,
        align=PP_ALIGN.CENTER,
    )


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
    data_rows = _as_list(content.get("rows"))
    if not data_rows:
        return
    rows: list[list[str]] = [headers]
    for row in data_rows:
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
        _textbox(
            slide,
            left + Inches(0.15),
            top + Inches(0.1),
            w - Inches(0.4),
            Inches(0.35),
            n_lab,
            size=Pt(PPTX_TYPE["caption"]),
            color=ink,
            bold=True,
            align=PP_ALIGN.LEFT,
        )
        _textbox(
            slide,
            left + Inches(0.15),
            top + Inches(0.42),
            w - Inches(0.4),
            Inches(0.5),
            title,
            size=Pt(PPTX_TYPE["card_head"]),
            color=ink,
            bold=True,
        )
        _textbox(
            slide,
            left + Inches(0.15),
            top + Inches(0.95),
            w - Inches(0.4),
            Inches(0.5),
            text,
            size=Pt(PPTX_TYPE["caption"]),
            color=ink,
        )


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
        _textbox(slide, Inches(0.7), Inches(1.25), Inches(6.3), Inches(0.3), unit, size=Pt(11), color=PPTX_MUTED)
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


# ---------------------------------------------------------------------------
# freeform（フェーズ B）: LLM がグリッド座標で要素を自由配置する。
# 座標はコンテンツ領域（タイトル帯の下）を 12 列 × 6 行に割ったグリッド。
# 重なり/はみ出しはサーバ側で必ずクランプする。配色・フォントは DADS のみ。
# ---------------------------------------------------------------------------
_GRID_COLS = 12
_GRID_ROWS = 6
_GRID_LEFT = PPTX_FRAME["left"]
_GRID_TOP = PPTX_FRAME["content_top"]
_GRID_WIDTH = pptx_content_width()
_GRID_HEIGHT = pptx_content_height()
_GRID_PAD = 0.08


def _clamp_int(value: Any, lo: int, hi: int, default: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _grid_span(el: dict[str, Any]) -> tuple[int, int, int, int]:
    """要素のグリッド指定を安全な (col,row,colspan,rowspan) に丸める。"""
    col = _clamp_int(el.get("col"), 0, _GRID_COLS - 1, 0)
    row = _clamp_int(el.get("row"), 0, _GRID_ROWS - 1, 0)
    colspan = _clamp_int(el.get("colspan"), 1, _GRID_COLS, 6)
    rowspan = _clamp_int(el.get("rowspan"), 1, _GRID_ROWS, 2)
    colspan = min(colspan, _GRID_COLS - col)
    rowspan = min(rowspan, _GRID_ROWS - row)
    return col, row, colspan, rowspan


def _grid_rect(prs: Any, col: int, row: int, colspan: int, rowspan: int) -> tuple[Any, Any, Any, Any]:
    """グリッドセルを EMU の (left, top, width, height) に変換する（内側パディング付き）。"""
    from pptx.util import Inches

    cell_w = _GRID_WIDTH / _GRID_COLS
    cell_h = _GRID_HEIGHT / _GRID_ROWS
    left = Inches(_GRID_LEFT + col * cell_w + _GRID_PAD)
    top = Inches(_GRID_TOP + row * cell_h + _GRID_PAD)
    width = Inches(max(colspan * cell_w - 2 * _GRID_PAD, 0.5))
    height = Inches(max(rowspan * cell_h - 2 * _GRID_PAD, 0.3))
    return left, top, width, height


_TONE = {"ink": INK, "body": BODY, "muted": PPTX_MUTED, "accent": ACCENT}


def _tone_color(tone: Any, default: tuple[int, int, int] = BODY) -> tuple[int, int, int]:
    return _TONE.get(str(tone or "").strip().lower(), default)


def _size_pt(size: Any, default_key: str) -> Any:
    from pptx.util import Pt

    # style.size と default_key はどちらもトークン（small/body/head/title）。
    table = {
        "small": PPTX_TYPE["caption"],
        "body": PPTX_TYPE["body"],
        "head": PPTX_TYPE["card_head"],
        "title": PPTX_TYPE["title"],
        "metric": PPTX_TYPE["metric"],
    }
    key = str(size or "").strip().lower()
    return Pt(table.get(key) or table.get(default_key, PPTX_TYPE["body"]))


def _align_of(value: Any) -> Any:
    from pptx.enum.text import PP_ALIGN

    return {
        "center": PP_ALIGN.CENTER,
        "right": PP_ALIGN.RIGHT,
        "left": PP_ALIGN.LEFT,
    }.get(str(value or "").strip().lower(), PP_ALIGN.LEFT)


@register("freeform")
def _render_freeform(slide: Any, prs: Any, content: dict[str, Any], assets: dict[str, bytes]) -> None:
    """LLM が指定したグリッド配置で要素を描く。未知/無効は無視し、必ず領域内に収める。"""
    elements = _as_list(content.get("elements"))
    seen: set[tuple[int, int, int, int, str]] = set()
    drawn = 0
    for el in elements:
        if not isinstance(el, dict):
            continue
        if drawn >= 14:
            break
        col, row, colspan, rowspan = _grid_span(el)
        kind = str(el.get("kind") or "text").strip().lower()
        key = (col, row, colspan, rowspan, kind)
        if key in seen:  # 完全に同じ矩形・種別の重複は後勝ちで間引く
            continue
        seen.add(key)
        left, top, width, height = _grid_rect(prs, col, row, colspan, rowspan)
        style = el.get("style") if isinstance(el.get("style"), dict) else {}
        fill = str(style.get("fill") or "none").strip().lower()
        if fill == "surface":
            _rect(slide, left, top, width, height, SURFACE)
        elif fill == "accent":
            _rect(slide, left, top, width, height, ACCENT)
        default_tone = "accent" if fill == "accent" else None
        color = ON_ACCENT if fill == "accent" else _tone_color(style.get("tone") or default_tone)
        align = _align_of(style.get("align"))
        bold = bool(style.get("bold"))
        if kind == "image":
            rel = str(el.get("image") or el.get("src") or "").replace("\\", "/").lstrip("/")
            if not _picture(slide, rel, assets, left, top, width):
                _placeholder(slide, left, top, width, height, "図")
        elif kind == "table":
            headers = [str(h) for h in _as_list(el.get("headers"))]
            rows = [[str(c) for c in _as_list(r)] for r in _as_list(el.get("rows"))]
            table_rows = ([headers] if headers else []) + rows
            if table_rows:
                _add_table(slide, left, top, width, height, table_rows)
        elif kind == "bullets":
            bullets = [str(b) for b in _as_list(el.get("bullets") or el.get("text")) if str(b).strip()]
            _lines(slide, left, top, width, height, bullets, size=_size_pt(style.get("size"), "body"), color=color, bullet=True)
        elif kind == "kpi":
            from pptx.util import Emu, Inches

            value = str(el.get("value") or el.get("text") or "")
            label = str(el.get("label") or "")
            box_h = _inches_of(height)
            value_h = min(1.05, max(box_h * 0.55, 0.5)) if label else box_h
            metric = PPTX_TYPE["metric"]
            size = _size_pt(style.get("size"), "metric")
            if _needs_autofit(value, width, Inches(value_h), metric):
                size = _size_pt("head", "head")
            _textbox(
                slide,
                left,
                top,
                width,
                Inches(value_h),
                value,
                size=size,
                color=ACCENT if fill != "accent" else ON_ACCENT,
                bold=True,
                align=align,
            )
            if label:
                _textbox(
                    slide,
                    left,
                    Emu(top + Inches(value_h)),
                    width,
                    Inches(max(box_h - value_h, 0.3)),
                    label,
                    size=_size_pt("body", "body"),
                    color=PPTX_MUTED if fill != "accent" else ON_ACCENT,
                    align=align,
                )
        elif kind == "heading":
            from app.pptx_repair import _echoes_title

            heading = str(el.get("text") or el.get("heading") or el.get("label") or "")
            if heading and not _echoes_title(heading, content.get("_slide_title")):
                _textbox(slide, left, top, width, height, heading, size=_size_pt(style.get("size"), "head"), color=(INK if fill != "accent" else ON_ACCENT), bold=True, align=align)
        elif kind == "box":
            text = str(el.get("text") or "")
            if text and fill == "none":
                _rect(slide, left, top, width, height, SURFACE)
            if text:
                _textbox(slide, left, top, width, height, text, size=_size_pt(style.get("size"), "body"), color=color, bold=bold, align=align)
        else:  # text
            text = str(el.get("text") or "")
            if text:
                _textbox(slide, left, top, width, height, text, size=_size_pt(style.get("size"), "body"), color=color, bold=bold, align=align)
        drawn += 1


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
        from app.pptx_repair import strip_title_echo

        title = str(slide_def.get("title") or "")
        content = {**strip_title_echo(title, content), "_slide_title": title}
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
