"""ノートブックへ上げた資料の個人情報警告。本文は置き換えない。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

for parent in Path(__file__).resolve().parents:
    if (parent / "shared" / "pii_scan.py").exists():
        if str(parent) not in sys.path:
            sys.path.insert(0, str(parent))
        break

from shared.pii_scan import (  # noqa: E402
    NOTEBOOK_SCAN_MAX_CHARS,
    format_warning_message,
    load_pii_settings,
    scan,
)


def file_text(nodes: list[dict[str, Any]] | None) -> str:
    parts: list[str] = []
    for node in nodes or []:
        if isinstance(node, dict):
            text = str(node.get("text") or "").strip()
            if text:
                parts.append(text)
    return "\n".join(parts)


def annotate_briefing(
    briefing: dict[str, Any] | None,
    nodes: list[dict[str, Any]] | None,
    tenant_id: str | None,
) -> dict[str, Any]:
    """検知結果を briefing.pii に載せる。ヒットが無ければ briefing はそのまま。"""
    base = dict(briefing or {})
    settings = load_pii_settings(tenant_id)
    if not settings.get("warn_attachments", True):
        return base
    text = file_text(nodes)[:NOTEBOOK_SCAN_MAX_CHARS]
    if not text.strip():
        return base
    result = scan(
        text,
        enable_ner=bool(settings.get("check_pii_ner", True)),
        check_mynumber=bool(settings.get("check_mynumber", True)),
    )
    if not result.get("categories"):
        return base
    base["pii"] = {
        "warned": True,
        "categories": result["categories"],
        "message": format_warning_message(result),
        "hits": list(result.get("hits") or [])[:6],
    }
    return base
