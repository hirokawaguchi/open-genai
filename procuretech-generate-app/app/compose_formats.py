"""Markdown 章を html / pptx / txt / md へ変換する（/compose の新形式）。"""

from __future__ import annotations

import base64
import html
import io
import re
from typing import Any

from app.dads import (
    ACCENT,
    BODY,
    FONT,
    FONT_MONO,
    INK,
    MUTED,
    ON_ACCENT,
    PAPER,
    RULE,
    SURFACE,
    hex_of,
)

# 画像のみの行（ブロック画像）。
_IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)$")
_INLINE_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_BOLD_RE = re.compile(r"(\*\*|__)(.+?)\1")
_ITALIC_RE = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^(\s*)[-*]\s+(.*)$")
_TABLE_LINE_RE = re.compile(r"^\s*\|.+\|\s*$")
_TABLE_SEP_CELL_RE = re.compile(r"^:?-+:?$")

SUPPORTED_FORMATS = ("docx", "html", "pptx", "txt", "md")

def _css_hex(rgb: tuple[int, int, int]) -> str:
    return f"#{hex_of(rgb)}"


# デジタル庁デザインシステム（DADS）。docx / pptx と同じトークン。
_HTML_CSS = f"""
:root {{
  --ink: {_css_hex(INK)};
  --body: {_css_hex(BODY)};
  --muted: {_css_hex(MUTED)};
  --rule: {_css_hex(RULE)};
  --paper: {_css_hex(PAPER)};
  --surface: {_css_hex(SURFACE)};
  --accent: {_css_hex(ACCENT)};
}}
@page {{ margin: 20mm 18mm; }}
html {{ background: {_css_hex(SURFACE)}; }}
body {{
  box-sizing: border-box;
  max-width: 46rem;
  margin: 2rem auto 3rem;
  padding: 2.2rem 2.4rem 2.8rem;
  background: var(--paper);
  color: var(--body);
  font-family: "{FONT}", "Hiragino Sans", "Yu Gothic Medium", "Yu Gothic", sans-serif;
  font-size: 16px;
  line-height: 1.7;
  letter-spacing: 0.02em;
}}
h1, h2, h3, h4 {{
  font-family: "{FONT}", "Hiragino Sans", "Yu Gothic", sans-serif;
  font-weight: 700;
  line-height: 1.5;
  color: var(--ink);
  letter-spacing: 0.01em;
}}
h1 {{
  font-size: 1.5rem;
  margin: 0 0 1.25rem;
  padding-bottom: 0.55rem;
  border-bottom: 2px solid var(--accent);
}}
h2 {{
  font-size: 1.25rem;
  margin: 1.75rem 0 0.6rem;
  padding-bottom: 0.35rem;
  border-bottom: 1px solid var(--rule);
}}
h3 {{ font-size: 1.1rem; margin: 1.4rem 0 0.45rem; }}
p {{ margin: 0 0 0.9rem; }}
ul {{ margin: 0 0 1rem 1.2rem; padding: 0; }}
li {{ margin: 0.2rem 0; }}
img {{ max-width: 100%; height: auto; display: block; margin: 1rem 0; }}
code, pre {{
  font-family: "{FONT_MONO}", ui-monospace, "SFMono-Regular", Menlo, monospace;
  font-size: 0.88em;
}}
code {{ background: var(--surface); padding: 0.1em 0.35em; }}
pre {{
  background: var(--surface);
  padding: 0.85rem 1rem;
  overflow: auto;
  line-height: 1.55;
  border: 1px solid var(--rule);
}}
pre code {{ background: none; padding: 0; }}
blockquote {{
  margin: 0 0 1rem;
  padding: 0.15rem 0 0.15rem 1rem;
  border-left: 3px solid var(--accent);
  color: var(--muted);
}}
table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 1.2rem; font-size: 0.95em; }}
th, td {{ border: 1px solid var(--rule); padding: 0.4rem 0.65rem; text-align: left; }}
th {{ background: var(--surface); font-weight: 700; }}
.figure-missing {{ color: var(--muted); font-style: italic; }}
footer.meta {{ margin-top: 2.5rem; color: var(--muted); font-size: 0.8rem; }}
@media print {{
  html {{ background: #fff; }}
  body {{ margin: 0; max-width: none; }}
}}
""".strip()


def normalize_format(raw: Any) -> str:
    fmt = str(raw or "docx").strip().lower().lstrip(".")
    return fmt if fmt in SUPPORTED_FORMATS else "docx"


def _rel_of(path: str) -> str:
    return path.replace("\\", "/").lstrip("/")


def _join_sections(sections: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for sec in sections:
        content = str(sec.get("content") or "").strip()
        if content:
            parts.append(content)
    return "\n\n".join(parts)


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


def markdown_to_md(sections: list[dict[str, Any]]) -> bytes:
    """章本文を空行区切りで連結する（ソースそのもの）。"""
    body = _join_sections(sections)
    if body and not body.endswith("\n"):
        body += "\n"
    return body.encode("utf-8")


def markdown_to_txt(sections: list[dict[str, Any]]) -> bytes:
    """Markdown 記法を除いたプレーンテキスト。画像・Mermaid はプレースホルダ。"""
    lines_out: list[str] = []
    in_code = False
    code_lang = ""
    for raw in _join_sections(sections).splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            if in_code:
                if code_lang == "mermaid":
                    lines_out.append("[図]")
                in_code = False
                code_lang = ""
            else:
                in_code = True
                code_lang = stripped[3:].strip().lower()
            continue
        if in_code:
            if code_lang != "mermaid":
                lines_out.append(raw)
            continue
        m = _IMAGE_LINE_RE.match(stripped)
        if m:
            lines_out.append(f"[画像: {_rel_of(m.group(1))}]")
            continue
        line = _INLINE_IMAGE_RE.sub(lambda mm: f"[画像: {_rel_of(mm.group(2))}]", raw)
        line = _LINK_RE.sub(r"\1", line)
        line = _BOLD_RE.sub(r"\2", line)
        line = _ITALIC_RE.sub(r"\1", line)
        hm = _HEADING_RE.match(line)
        if hm:
            line = hm.group(2).strip()
        bm = _BULLET_RE.match(line)
        if bm:
            line = f"{bm.group(1)}・ {bm.group(2)}"
        lines_out.append(line.rstrip())
    text = "\n".join(lines_out).strip() + "\n"
    return text.encode("utf-8")


def _inline_html(text: str, assets: dict[str, bytes]) -> str:
    def img(m: re.Match[str]) -> str:
        rel = _rel_of(m.group(2))
        data = assets.get(rel)
        alt = html.escape(m.group(1) or "")
        if data:
            return f'<img src="{_data_uri(rel, data)}" alt="{alt}">'
        return f'<span class="figure-missing">[画像: {html.escape(rel)}]</span>'

    escaped = html.escape(text)
    # エスケープ後に画像記法を戻すため、元テキストで置換してから残りを escape する。
    parts: list[str] = []
    last = 0
    for m in _INLINE_IMAGE_RE.finditer(text):
        parts.append(html.escape(text[last : m.start()]))
        parts.append(img(m))
        last = m.end()
    parts.append(html.escape(text[last:]))
    s = "".join(parts)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    return s


def _table_cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_table_sep(cells: list[str]) -> bool:
    return bool(cells) and all(
        _TABLE_SEP_CELL_RE.match(c.replace(" ", "")) for c in cells
    )


def parse_gfm_table(lines: list[str]) -> dict[str, list[list[str]] | list[str]] | None:
    """GFM 表を headers / rows に分解する。区切り行は捨てる。"""
    raw = [ln for ln in lines if ln.strip()]
    if len(raw) < 2:
        return None
    parsed = [_table_cells(ln) for ln in raw]
    header = parsed[0]
    if not header or not any(header):
        return None
    width = len(header)
    rows: list[list[str]] = []
    for cells in parsed[1:]:
        if _is_table_sep(cells):
            continue
        padded = cells + [""] * width
        rows.append(padded[:width])
    if not rows:
        return None
    return {"headers": header, "rows": rows}


def _table_html(block: list[str], assets: dict[str, bytes]) -> str:
    rows = [_table_cells(ln) for ln in block]
    header = rows[0]
    body = [r for r in rows[1:] if not _is_table_sep(r)]
    width = len(header)
    parts = ["<table>", "<thead>", "<tr>"]
    for cell in header:
        parts.append(f"<th>{_inline_html(cell, assets)}</th>")
    parts.extend(["</tr>", "</thead>", "<tbody>"])
    for row in body:
        padded = row + [""] * width
        parts.append("<tr>")
        for cell in padded[:width]:
            parts.append(f"<td>{_inline_html(cell, assets)}</td>")
        parts.append("</tr>")
    parts.extend(["</tbody>", "</table>"])
    return "".join(parts)


def markdown_to_html(
    name: str, sections: list[dict[str, Any]], assets: dict[str, bytes] | None = None
) -> bytes:
    """タイポグラフィ用 CSS を埋め込んだ単一 HTML。画像は data URI。"""
    assets = assets or {}
    chunks: list[str] = [f"<h1>{html.escape(name)}</h1>"]
    in_code = False
    code_lang = ""
    code_lines: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            chunks.append("</ul>")
            in_list = False

    def flush_code() -> None:
        nonlocal in_code, code_lang, code_lines
        body = html.escape("\n".join(code_lines))
        chunks.append(f"<pre><code>{body}</code></pre>")
        in_code, code_lang, code_lines = False, "", []

    lines = _join_sections(sections).splitlines()
    i = 0
    while i < len(lines):
        raw_line = lines[i]
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            if in_code:
                flush_code()
            else:
                close_list()
                in_code, code_lang, code_lines = True, stripped[3:].strip().lower(), []
            i += 1
            continue
        if in_code:
            code_lines.append(raw_line)
            i += 1
            continue
        if _TABLE_LINE_RE.match(stripped):
            block = [raw_line]
            j = i + 1
            while j < len(lines) and _TABLE_LINE_RE.match(lines[j].strip()):
                block.append(lines[j])
                j += 1
            if len(block) >= 2 and _is_table_sep(_table_cells(block[1])):
                close_list()
                chunks.append(_table_html(block, assets))
                i = j
                continue
        if not stripped:
            close_list()
            i += 1
            continue
        hm = _HEADING_RE.match(stripped)
        if hm:
            close_list()
            level = min(len(hm.group(1)) + 1, 4)
            chunks.append(f"<h{level}>{html.escape(hm.group(2).strip())}</h{level}>")
            i += 1
            continue
        m = _IMAGE_LINE_RE.match(stripped)
        if m:
            close_list()
            rel = _rel_of(m.group(1))
            data = assets.get(rel)
            if data:
                chunks.append(f'<p><img src="{_data_uri(rel, data)}" alt=""></p>')
            else:
                chunks.append(f'<p class="figure-missing">[画像: {html.escape(rel)}]</p>')
            i += 1
            continue
        bm = _BULLET_RE.match(raw_line)
        if bm:
            if not in_list:
                chunks.append("<ul>")
                in_list = True
            chunks.append(f"<li>{_inline_html(bm.group(2), assets)}</li>")
            i += 1
            continue
        close_list()
        if stripped.startswith("> "):
            chunks.append(f"<blockquote><p>{_inline_html(stripped[2:], assets)}</p></blockquote>")
            i += 1
            continue
        chunks.append(f"<p>{_inline_html(stripped, assets)}</p>")
        i += 1
    if in_code:
        flush_code()
    close_list()

    doc = (
        "<!DOCTYPE html>\n"
        '<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{html.escape(name)}</title>\n"
        f"<style>\n{_HTML_CSS}\n</style>\n</head>\n<body>\n"
        + "\n".join(chunks)
        + "\n</body>\n</html>\n"
    )
    return doc.encode("utf-8")


# PPTX は dads のトークンをそのまま使う（docx / html と揃える）。
_PPTX_INK = INK
_PPTX_BODY = BODY
_PPTX_MUTED = MUTED
_PPTX_RULE = RULE
_PPTX_PAPER = PAPER
_PPTX_SURFACE = SURFACE
_PPTX_ACCENT = ACCENT
_PPTX_ON_ACCENT = ON_ACCENT
_PPTX_FONT = FONT


def _rgb(rgb: tuple[int, int, int]) -> Any:
    from pptx.dml.color import RGBColor

    return RGBColor(*rgb)


def _no_line(shape: Any) -> None:
    shape.line.fill.background()


def _solid(shape: Any, rgb: tuple[int, int, int]) -> None:
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(rgb)
    _no_line(shape)


def _set_run_font(
    run: Any,
    *,
    size: Any,
    color: tuple[int, int, int],
    bold: bool = False,
    name: str = _PPTX_FONT,
) -> None:
    from lxml import etree
    from pptx.oxml.ns import qn

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


def _fill_slide(slide: Any, rgb: tuple[int, int, int]) -> None:
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = _rgb(rgb)


def _add_rect(slide: Any, left: Any, top: Any, width: Any, height: Any, rgb: tuple[int, int, int]) -> Any:
    from pptx.enum.shapes import MSO_SHAPE

    shape = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left, top, width, height)
    _solid(shape, rgb)
    return shape


def _style_paragraph(
    paragraph: Any,
    text: str,
    *,
    size: Any,
    color: tuple[int, int, int],
    bold: bool = False,
    space_after: Any | None = None,
    space_before: Any | None = None,
) -> None:
    from pptx.enum.text import PP_ALIGN

    paragraph.text = text
    paragraph.alignment = PP_ALIGN.LEFT
    if space_after is not None:
        paragraph.space_after = space_after
    if space_before is not None:
        paragraph.space_before = space_before
    for run in paragraph.runs:
        _set_run_font(run, size=size, color=color, bold=bold)


def _add_title_slide(prs: Any, title: str) -> None:
    """表紙。DADS の Blue 900 ヘッダー＋白地。装飾色は使わない。"""
    from pptx.util import Emu, Inches, Pt

    blank = prs.slide_layouts[6]
    slide = prs.slides.add_slide(blank)
    _fill_slide(slide, _PPTX_PAPER)
    _add_rect(slide, Inches(0), Inches(0), prs.slide_width, Inches(1.05), _PPTX_ACCENT)
    label = slide.shapes.add_textbox(Inches(0.7), Inches(0.32), Inches(12.0), Inches(0.45))
    _style_paragraph(label.text_frame.paragraphs[0], "資料", size=Pt(14), color=_PPTX_ON_ACCENT, bold=True)

    box = slide.shapes.add_textbox(Inches(0.7), Inches(2.35), Inches(12.0), Inches(2.4))
    box.text_frame.word_wrap = True
    _style_paragraph(box.text_frame.paragraphs[0], title, size=Pt(36), color=_PPTX_INK, bold=True)
    _add_rect(slide, Inches(0.7), Inches(5.0), Inches(3.2), Inches(0.04), _PPTX_ACCENT)
    _add_rect(
        slide, Inches(0), Emu(prs.slide_height - Inches(0.28)), prs.slide_width, Inches(0.28), _PPTX_SURFACE
    )


def _add_content_chrome(slide: Any, prs: Any, title: str) -> None:
    from pptx.util import Inches, Pt

    _fill_slide(slide, _PPTX_PAPER)
    _add_rect(slide, Inches(0), Inches(0), prs.slide_width, Inches(0.08), _PPTX_ACCENT)
    box = slide.shapes.add_textbox(Inches(0.7), Inches(0.28), Inches(12.0), Inches(0.85))
    box.text_frame.word_wrap = True
    _style_paragraph(box.text_frame.paragraphs[0], title, size=Pt(24), color=_PPTX_INK, bold=True)
    _add_rect(slide, Inches(0.7), Inches(1.16), Inches(11.9), Inches(0.012), _PPTX_RULE)


def _add_slide_footers(prs: Any) -> None:
    from pptx.enum.text import PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    total = len(prs.slides)
    for i, slide in enumerate(prs.slides, start=1):
        if i == 1:
            continue
        _add_rect(
            slide,
            Inches(0.7),
            Emu(prs.slide_height - Inches(0.42)),
            Inches(11.9),
            Inches(0.01),
            _PPTX_RULE,
        )
        box = slide.shapes.add_textbox(
            Inches(11.4), Emu(prs.slide_height - Inches(0.38)), Inches(1.3), Inches(0.3)
        )
        p = box.text_frame.paragraphs[0]
        p.alignment = PP_ALIGN.RIGHT
        run = p.add_run()
        run.text = f"{i} / {total}"
        _set_run_font(run, size=Pt(10), color=_PPTX_MUTED)


def markdown_to_pptx(
    name: str, sections: list[dict[str, Any]], assets: dict[str, bytes] | None = None
) -> bytes:
    """`#` / `##` 見出しでスライドを分け、本文と画像を配置する。"""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    assets = assets or {}
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    _add_title_slide(prs, name)

    slide = None
    body_lines: list[tuple[str, bool]] = []
    table_buf: list[str] = []
    text_flushed = False
    in_code = False
    code_lang = ""

    def flush_table() -> None:
        nonlocal table_buf, text_flushed
        parsed = parse_gfm_table(table_buf)
        table_buf = []
        if not parsed or slide is None:
            return
        from pptx.util import Inches

        from app.pptx_layouts import _add_table

        rows = [list(parsed["headers"]), *[list(r) for r in parsed["rows"]]]
        top = Inches(4.55) if text_flushed else Inches(1.4)
        height = Inches(2.15) if text_flushed else Inches(5.1)
        _add_table(slide, Inches(0.7), top, Inches(11.9), height, rows)
        text_flushed = True

    def flush_text(*, narrow: bool = False) -> None:
        nonlocal body_lines, text_flushed
        if slide is None or not body_lines:
            body_lines = []
            return
        # 同じ座標に重ねない（本文のあと画像、そのあとまた本文、で文字が重なっていた）。
        top = Inches(4.55) if text_flushed else Inches(1.4)
        height = Inches(2.15) if text_flushed else Inches(5.3)
        width = Inches(6.6) if narrow else Inches(11.9)
        box = slide.shapes.add_textbox(Inches(0.7), top, width, height)
        tf = box.text_frame
        tf.word_wrap = True
        for i, (line, is_bullet) in enumerate(body_lines):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            text = f"•   {line}" if is_bullet else line
            _style_paragraph(p, text, size=Pt(16), color=_PPTX_BODY, space_after=Pt(8), space_before=Pt(0))
            p.line_spacing = 1.35
        body_lines = []
        text_flushed = True

    def new_slide(title: str) -> None:
        nonlocal slide, text_flushed
        flush_text()
        flush_table()
        slide = prs.slides.add_slide(blank)
        _add_content_chrome(slide, prs, title)
        text_flushed = False

    def add_image(rel: str) -> None:
        data = assets.get(rel)
        if slide is None:
            new_slide(name)
        if not data:
            body_lines.append((f"[画像: {rel}]", False))
            return
        narrow = bool(body_lines)
        flush_text(narrow=narrow)
        stream = io.BytesIO(data)
        try:
            if narrow:
                slide.shapes.add_picture(stream, Inches(7.6), Inches(1.45), width=Inches(5.0))
            else:
                slide.shapes.add_picture(stream, Inches(1.8), Inches(1.5), width=Inches(9.6))
        except Exception:  # noqa: BLE001
            body_lines.append((f"[画像: {rel}]", False))

    for raw_line in _join_sections(sections).splitlines():
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            if in_code:
                in_code = False
                code_lang = ""
            else:
                in_code = True
                code_lang = stripped[3:].strip().lower()
            continue
        if in_code:
            if code_lang != "mermaid":
                body_lines.append((raw_line, False))
            continue
        if not stripped:
            flush_table()
            continue
        hm = _HEADING_RE.match(stripped)
        if hm and len(hm.group(1)) <= 2:
            new_slide(hm.group(2).strip())
            continue
        if hm:
            if slide is None:
                new_slide(name)
            flush_table()
            body_lines.append((hm.group(2).strip(), False))
            continue
        if _TABLE_LINE_RE.match(stripped):
            if slide is None:
                new_slide(name)
            table_buf.append(stripped)
            continue
        flush_table()
        m = _IMAGE_LINE_RE.match(stripped)
        if m:
            add_image(_rel_of(m.group(1)))
            continue
        if slide is None:
            new_slide(name)
        bm = _BULLET_RE.match(raw_line)
        text = bm.group(2) if bm else stripped
        text = _INLINE_IMAGE_RE.sub("", text).strip()
        text = _BOLD_RE.sub(r"\2", text)
        if text:
            body_lines.append((text, bool(bm)))
    flush_text()
    flush_table()
    _add_slide_footers(prs)

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()

