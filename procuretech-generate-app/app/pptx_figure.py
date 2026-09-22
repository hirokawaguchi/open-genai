"""整理ノートから図スライドを決める。枠を置き、可能なら Mermaid→PNG を埋める。"""

from __future__ import annotations

import hashlib
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("procuretech-generate")

FIGURE_KINDS = frozenset({"flowchart", "sequence"})
_FIGURE_HEADING = ("フロー", "完成イメージ", "関係図", "構成図", "分岐", "経路")
_SAFE_LABEL_RE = re.compile(r'["\[\]]')


def _normalize_figure(raw: Any) -> str:
    name = str(raw or "").strip().lower()
    aliases = {
        "flow": "flowchart",
        "graph": "flowchart",
        "diagram": "flowchart",
        "seq": "sequence",
        "true": "flowchart",
        "yes": "flowchart",
        "1": "flowchart",
        "図": "flowchart",
        "あり": "flowchart",
    }
    name = aliases.get(name, name)
    return name if name in FIGURE_KINDS else ""


def _is_mermaid_image(rel: str) -> bool:
    name = (rel or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name.startswith("mermaid-") or name.startswith("mermaid_")


def mermaid_images(paths: list[str] | None) -> list[str]:
    return [p for p in (paths or []) if p and _is_mermaid_image(p)]


def _has_diagram_marks(block: Any) -> bool:
    """樹形や連続する矢印。『経路』という語だけでは図にしない。"""
    blob = f"{getattr(block, 'text', '')}\n{' '.join(getattr(block, 'bullets', []) or [])}"
    if re.search(r"[├└]", blob):
        return True
    return blob.count("→") >= 2 or blob.count("↓") >= 2


def guess_figure(block: Any, llm_figure: str = "") -> str:
    """図にするか。写真がある枚は図化しない。エディタの Mermaid PNG は図にする。"""
    from app.pptx_plan import _content_images

    mmd_imgs = mermaid_images(getattr(block, "images", None))
    photos = [p for p in _content_images(block.images) if p not in mmd_imgs]
    if photos and not mmd_imgs:
        return ""
    kind = _normalize_figure(llm_figure)
    if mmd_imgs or getattr(block, "mermaid_blocks", None):
        return kind or "flowchart"
    if kind:
        return kind
    heading = block.heading or ""
    if any(k in heading for k in _FIGURE_HEADING) or _has_diagram_marks(block):
        return "flowchart"
    return ""


def _mmd_label(text: str) -> str:
    from app.pptx_plan import _clip, _plain_source

    s = _plain_source(text).replace("\n", "").strip()
    s = s.replace('"', "”").replace("[", "［").replace("]", "］")
    s = _SAFE_LABEL_RE.sub("", s)
    return _clip(s, 36) or "項目"


_NODE_DECL_RE = re.compile(r'^\s*([A-Za-z][\w-]*)\s*\[\s*"?([^"\]]+)"?\s*\]\s*$')
_EDGE_RE = re.compile(
    r'([A-Za-z][\w-]*)(?:\s*\[\s*"?([^"\]]+)"?\s*\])?\s*(?:-->|---)\s*(?:\|[^|]*\|\s*)?'
    r'([A-Za-z][\w-]*)(?:\s*\[\s*"?([^"\]]+)"?\s*\])?'
)
_HEADER_RE = re.compile(r"^(?:flowchart|graph)\b", re.I)
_FLOW_DIR_RE = re.compile(
    r"^(\s*)(flowchart|graph)(?:\s+(TD|TB|BT|DT|LR|RL))?(\b.*)?$",
    re.I,
)
_OTHER_DIAGRAM_RE = re.compile(
    r"^\s*(sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|"
    r"mindmap|timeline|gitGraph|journey|quadrantChart|xychart|sankey|"
    r"block-beta|requirementDiagram|C4Context|architecture-beta)\b",
    re.I,
)


def parse_mermaid_flowchart(code: str) -> dict[str, Any] | None:
    """flowchart / graph のノードと辺だけを取る。他の図種は None。"""
    text = (code or "").strip()
    if not text:
        return None
    nodes: dict[str, str] = {}
    order: list[str] = []
    edges: list[tuple[str, str]] = []

    def add_node(nid: str, label: str = "") -> None:
        if nid not in nodes:
            nodes[nid] = label or nid
            order.append(nid)
        elif label:
            nodes[nid] = label

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("%%") or _HEADER_RE.match(line):
            continue
        decl = _NODE_DECL_RE.match(line)
        if decl:
            add_node(decl.group(1), decl.group(2).strip())
            continue
        for em in _EDGE_RE.finditer(line):
            add_node(em.group(1), (em.group(2) or "").strip())
            add_node(em.group(3), (em.group(4) or "").strip())
            edges.append((em.group(1), em.group(3)))
    if len(order) < 2:
        return None
    return {"nodes": [(nid, nodes[nid]) for nid in order], "edges": edges}


def mermaid_to_flow_items(code: str) -> tuple[list[dict[str, str]], str]:
    """図枠に描く箱。分岐なら branch、一列なら linear。"""
    parsed = parse_mermaid_flowchart(code)
    if not parsed:
        return [], ""
    nodes: list[tuple[str, str]] = parsed["nodes"]
    labels = {nid: lab for nid, lab in nodes}
    incoming = {nid: 0 for nid, _ in nodes}
    outgoing: dict[str, list[str]] = {nid: [] for nid, _ in nodes}
    for src, dst in parsed["edges"]:
        if src in outgoing:
            outgoing[src].append(dst)
        if dst in incoming:
            incoming[dst] += 1
    roots = [nid for nid, n in incoming.items() if n == 0]
    hubs = [nid for nid, dests in outgoing.items() if len(dests) >= 2]
    if roots and hubs:
        root, hub = roots[0], hubs[0]
        items = [{"heading": labels[root], "body": ""}]
        if hub != root:
            items.append({"heading": labels.get(hub, hub), "body": ""})
        for dest in outgoing[hub]:
            items.append({"heading": labels.get(dest, dest), "body": ""})
        return items[:6], "branch"
    return [{"heading": lab, "body": ""} for _, lab in nodes][:5], "linear"


def mermaid_landscape(code: str) -> str:
    """flowchart / graph を LR（横書き）にする。他の図種はそのまま。"""
    text = (code or "").strip()
    if not text or _OTHER_DIAGRAM_RE.match(text):
        return text
    lines = text.splitlines()
    for i, line in enumerate(lines):
        match = _FLOW_DIR_RE.match(line)
        if not match:
            continue
        indent, kind, _direction, rest = match.groups()
        lines[i] = f"{indent}{kind} LR{rest or ''}"
        return "\n".join(lines)
    return text


def mermaid_flowchart(nodes: list[str], *, branch: bool) -> str:
    labels = [_mmd_label(n) for n in nodes if _mmd_label(n)]
    if not labels:
        return ""
    ids = [f"N{i}" for i in range(len(labels))]
    lines = ["flowchart LR"]
    for i, label in enumerate(labels):
        lines.append(f'  {ids[i]}["{label}"]')
    if branch and len(ids) >= 3:
        lines.append(f"  {ids[0]} --> {ids[1]}")
        for dest in ids[2:]:
            lines.append(f"  {ids[1]} --> {dest}")
    else:
        for i in range(len(ids) - 1):
            lines.append(f"  {ids[i]} --> {ids[i + 1]}")
    return "\n".join(lines)


def source_mermaid(block: Any) -> str:
    """原稿の ```mermaid。無ければ空。"""
    existing = getattr(block, "mermaid_blocks", None) or []
    return str(existing[0]).strip() if existing else ""


def mermaid_from_notes(block: Any, points: list[str] | None) -> str:
    """ノートが図にすると判断したときの新規 Mermaid。原稿のフェンスは使わない。"""
    from app.pptx_plan import _flow_nodes, _looks_like_branch

    nodes = _flow_nodes(block, points or list(block.bullets))
    if len(nodes) < 2:
        nodes = [p for p in (points or []) if p][:5]
    if len(nodes) < 2:
        return ""
    return mermaid_flowchart(nodes, branch=_looks_like_branch(block) or len(nodes) >= 3)


def mermaid_from_block(block: Any, points: list[str] | None) -> str:
    return source_mermaid(block) or mermaid_from_notes(block, points)


def render_mermaid_png(code: str) -> bytes | None:
    """mmdc があれば PNG にする。無ければ None（枠＋代替テキストのまま）。"""
    text = (code or "").strip()
    if not text:
        return None
    mmdc = shutil.which("mmdc")
    if not mmdc:
        return None
    try:
        with tempfile.TemporaryDirectory() as td:
            src = Path(td) / "diagram.mmd"
            dst = Path(td) / "diagram.png"
            src.write_text(text, encoding="utf-8")
            subprocess.run(
                [mmdc, "-i", str(src), "-o", str(dst), "-b", "white"],
                check=True,
                timeout=45,
                capture_output=True,
            )
            if dst.is_file():
                data = dst.read_bytes()
                return data if data[:8] == b"\x89PNG\r\n\x1a\n" else None
    except Exception as exc:  # noqa: BLE001
        log.info("mermaid png skipped: %s", exc)
    return None


def figure_asset_name(block: Any) -> str:
    digest = hashlib.sha1(f"{block.filename}:{block.heading}".encode()).hexdigest()[:10]
    return f"images/pptx-fig-{digest}.png"


def mermaid_pending_path(code: str, index: int) -> str:
    digest = hashlib.sha1(f"{index}:{code}".encode()).hexdigest()[:10]
    return f"images/pptx-mmd-{digest}.png"


def is_png(data: bytes | None) -> bool:
    return bool(data) and data[:8] == b"\x89PNG\r\n\x1a\n"


def png_size(data: bytes | None) -> tuple[int, int] | None:
    """PNG の IHDR から幅・高さ（px）。"""
    import struct

    if not is_png(data) or data is None or len(data) < 24:
        return None
    width, height = struct.unpack(">II", data[16:24])
    if width < 1 or height < 1:
        return None
    return width, height


def asset_png(rel: str, assets: dict[str, bytes] | None) -> bytes | None:
    """相対パス、なければ同じファイル名の PNG を探す。"""
    if not rel or not assets:
        return None
    key = rel.replace("\\", "/").lstrip("./")
    data = assets.get(key) or assets.get(rel)
    if is_png(data):
        return data
    name = key.rsplit("/", 1)[-1].lower()
    if not name:
        return None
    for path, raw in assets.items():
        if path.replace("\\", "/").rsplit("/", 1)[-1].lower() == name and is_png(raw):
            return raw
    return None


def pending_mermaid(
    deck: dict[str, Any] | None, assets: dict[str, bytes] | None
) -> list[dict[str, str]]:
    """PNG がまだ無い figure-frame の Mermaid。書き出し側で画像化する。"""
    assets = assets or {}
    out: list[dict[str, str]] = []
    if not isinstance(deck, dict):
        return out
    for i, slide in enumerate(deck.get("slides") or []):
        if not isinstance(slide, dict) or str(slide.get("layout") or "") != "figure-frame":
            continue
        content = slide.get("content") if isinstance(slide.get("content"), dict) else {}
        code = str(content.get("mermaid") or "").strip()
        if not code:
            continue
        rel = str(content.get("image") or "").strip()
        if asset_png(rel, assets):
            continue
        path = rel or mermaid_pending_path(code, i)
        content["image"] = path
        slide["content"] = content
        out.append({"id": str(i), "path": path, "code": mermaid_landscape(code)})
    return out


def figure_content(
    block: Any,
    notes: Any,
    assets: dict[str, bytes] | None,
) -> dict[str, Any] | None:
    """図スライド。原稿の Mermaid/PNG を優先し、無ければノートから新規に作る。"""
    mmd_imgs = mermaid_images(getattr(block, "images", None))
    source = source_mermaid(block)
    kind = guess_figure(block, notes.figure if notes else "")
    if mmd_imgs or source:
        kind = kind or "flowchart"
    if not kind:
        return None
    caption = str((notes.figure_caption if notes else "") or block.heading or "図").strip()
    rel = ""
    mermaid = ""
    if mmd_imgs:
        for cand in mmd_imgs:
            if assets is None or asset_png(cand, assets) or cand in (assets or {}):
                rel = cand
                break
        rel = rel or mmd_imgs[0]
        log.info("pptx figure: source image %s", rel)
    elif source:
        mermaid = mermaid_landscape(source)
        log.info("pptx figure: source mermaid")
    else:
        mermaid = mermaid_landscape(mermaid_from_notes(block, notes.points if notes else None))
        if mermaid:
            png = render_mermaid_png(mermaid)
            if png and assets is not None:
                rel = figure_asset_name(block)
                assets[rel] = png
                log.info("pptx figure: notes mermaid %s", rel)
            else:
                log.info("pptx figure: notes mermaid pending (%s)", caption)
    return {
        "caption": caption,
        "alt": f"ここに{caption}の図を入れる",
        "image": rel,
        "mermaid": mermaid,
        "kind": kind,
    }
