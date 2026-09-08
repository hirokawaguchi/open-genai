"""deck JSON（および任意の PPTX / HTML バイト）の機械検査。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_DESUMASU_RE = re.compile(r"(です|ます)[。．]?$")
_COUNT_TITLE_RE = re.compile(
    r"[0-9０-９]+つ(の理由|のポイント|の柱|の論点)|[0-9０-９]+(段階|フェーズ|ステップ|個の)"
)
_PLACEHOLDER_RE = re.compile(
    r"(Text\s*\d+|ラベル\s*\d+|タイトル\s*\d+|◯◯|YYYY年|Source\s*\d+)"
)


@dataclass(frozen=True)
class CheckIssue:
    level: str  # FAIL | WARN
    code: str
    message: str
    index: int | None = None


def _titles(deck: dict[str, Any]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for i, slide in enumerate(deck.get("slides") or []):
        if not isinstance(slide, dict):
            continue
        title = str(slide.get("title") or "").strip()
        out.append((i, title))
    return out


def check_deck(deck: dict[str, Any] | None) -> list[CheckIssue]:
    """形式の前に、同じ deck JSON を検査する。"""
    issues: list[CheckIssue] = []
    if not isinstance(deck, dict) or not isinstance(deck.get("slides"), list):
        return [CheckIssue("FAIL", "empty", "deck が空です")]
    for i, title in _titles(deck):
        if not title:
            issues.append(CheckIssue("FAIL", "empty-title", "タイトルが空です", i))
            continue
        if _DESUMASU_RE.search(title):
            issues.append(CheckIssue("FAIL", "desumasu", f"ですますで終わっている: {title}", i))
        if _COUNT_TITLE_RE.search(title):
            issues.append(CheckIssue("FAIL", "count-title", f"個数をタイトルに入れている: {title}", i))
        if _PLACEHOLDER_RE.search(title):
            issues.append(CheckIssue("FAIL", "placeholder", f"プレースホルダが残っている: {title}", i))
        if len(title) > 40:
            issues.append(CheckIssue("WARN", "long-title", f"40字超（2行想定）: {title}", i))
    return issues


def check_pptx_bytes(data: bytes) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    if not data.startswith(b"PK"):
        return [CheckIssue("FAIL", "not-pptx", "PPTX ではありません")]
    try:
        import zipfile
        from io import BytesIO

        with zipfile.ZipFile(BytesIO(data)) as zf:
            for name in zf.namelist():
                if not name.endswith(".xml"):
                    continue
                xml = zf.read(name).decode("utf-8", errors="replace")
                if "roundRect" in xml or "prst=\"roundRect\"" in xml:
                    issues.append(CheckIssue("FAIL", "round-rect", f"角丸図形があります: {name}"))
                    break
    except Exception as exc:  # noqa: BLE001
        issues.append(CheckIssue("WARN", "pptx-scan", f"PPTX 検査をスキップ: {exc}"))
    return issues


def check_html_bytes(data: bytes | str) -> list[CheckIssue]:
    text = data.decode("utf-8", errors="replace") if isinstance(data, bytes) else data
    issues: list[CheckIssue] = []
    if re.search(r"border-radius\s*:\s*([4-9]|\d{2,})\s*px", text, re.I):
        issues.append(CheckIssue("FAIL", "border-radius", "4px 以上の角丸があります"))
    return issues


def format_issues(issues: list[CheckIssue]) -> str:
    if not issues:
        return "pptx_check: ok"
    lines = [f"pptx_check: {len(issues)} issue(s)"]
    for item in issues:
        loc = f"[{item.index}] " if item.index is not None else ""
        lines.append(f"  {item.level} {item.code} {loc}{item.message}")
    return "\n".join(lines)
