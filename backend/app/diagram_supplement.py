"""チャット回答への補足図。

「図を見る」を押した時点で図は必要なので、要不要は判断しない。
項目の並びは回答の見出しからマインドマップにする。それ以外はモデルが種類を選ぶ。
ラベルは回答に書いてある言葉だけを認め、外れていれば項目の並びから描き直す。
"""

from __future__ import annotations

import re
from typing import Any

from . import llm

MAX_ANSWER_CHARS = 12000

_FENCE_RE = re.compile(r"```(?:mermaid)?\s*([\s\S]*?)```", re.IGNORECASE)
_NONE_RE = re.compile(r"NONE[.。]?", re.IGNORECASE)

# 先頭行で受け付ける図種。描画側が扱えるものに限る。
_DIAGRAM_HEAD_RE = re.compile(
    r"^(?:flowchart|graph|sequenceDiagram|timeline|stateDiagram(?:-v2)?"
    r"|mindmap|journey|gantt|pie|erDiagram|classDiagram|quadrantChart"
    r"|xychart-beta|sankey-beta|block-beta|gitGraph)\b",
    re.IGNORECASE,
)

_KEYWORDS = {
    "flowchart",
    "graph",
    "td",
    "tb",
    "lr",
    "rl",
    "bt",
    "dt",
    "sequencediagram",
    "participant",
    "actor",
    "autonumber",
    "timeline",
    "title",
    "section",
    "statediagram",
    "statediagram-v2",
    "state",
    "mindmap",
    "root",
    "end",
    "subgraph",
    "direction",
    "note",
    "over",
    "left",
    "right",
    "of",
    "loop",
    "alt",
    "else",
    "opt",
    "par",
    "and",
    "rect",
    "critical",
    "as",
    "activate",
    "deactivate",
    "journey",
    "gantt",
    "pie",
    "erdiagram",
    "classdiagram",
    "quadrantchart",
    "xychart-beta",
    "sankey-beta",
    "block-beta",
    "gitgraph",
    "dateformat",
    "axisformat",
    "section",
}

_SYSTEM = """あなたは Mermaid の説明図を書く編集者です。利用者はすでに図を求めています。要不要は判断せず、渡された回答を必ず1つの図にしてください。NONE は返さないでください。

図の種類は回答の形で1つだけ選びます。flowchart は、条件で道が分かれるときだけ使います。順番だけの手順を flowchart にしてはいけません。分類や列挙を timeline にしてはいけません。

- 分類、列挙、全体と部分、対比 → mindmap
- 順番だけの手順、期限や段階の並び → timeline
- 人や組織のやり取り → sequenceDiagram
- 状態が次の状態へ変わる → stateDiagram-v2
- 条件で行き先や手続きが分かれる説明 → flowchart TD

ラベルは回答本文の言葉だけを使います。本文に無い組織名、手続き、section、participant は足しません。ノードの文言に括弧やコロンは入れません。要素が多くなるときは骨組みだけにします。

mindmap はインデントで階層を表します。
mindmap
  root((全体))
    分類
      項目

timeline は時期を1つ、出来事を1つにします。読点で項目を1行に詰めません。
timeline
    title 回答にある題
    section 段階
    手順 : その内容

sequenceDiagram
    participant 回答にある人
    人->>相手: 回答にあるやり取り

stateDiagram-v2
    [*] --> 状態
    状態 --> 次の状態

flowchart TD
    A[条件] --> B[一方]
    A --> C[他方]

説明は付けず、mermaid のコードフェンスだけを返してください。
"""


def _norm(text: str) -> str:
    return re.sub(r"[\s　・、。,.，．/／:：]+", "", text).casefold()


def _strip_directives(code: str) -> str:
    lines = [
        line
        for line in code.splitlines()
        if not line.strip().startswith("%%")
    ]
    return "\n".join(lines).strip()


def existing_mermaid(answer: str) -> str | None:
    """回答にすでに含まれる最初の Mermaid ブロック。"""
    match = _FENCE_RE.search(answer or "")
    if not match:
        return None
    code = _strip_directives(match.group(1))
    if not code or not _DIAGRAM_HEAD_RE.match(code):
        return None
    return code


def _extract_labels(code: str) -> list[str]:
    labels: list[str] = []
    for match in re.finditer(r"[\[\(\{]+([^\[\]\(\)\{\}]+)[\]\)\}]+", code):
        labels.append(match.group(1))
    for match in re.finditer(r'"([^"]+)"', code):
        labels.append(match.group(1))
    for raw_line in code.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("%%"):
            continue
        section = re.match(r"section\s+(.+)$", line, re.IGNORECASE)
        if section:
            labels.append(section.group(1))
        who = re.match(r"(?:participant|actor)\s+(.+)$", line, re.IGNORECASE)
        if who:
            name = who.group(1)
            if re.search(r"\bas\b", name, re.IGNORECASE):
                name = re.split(r"\bas\b", name, maxsplit=1, flags=re.IGNORECASE)[1]
            labels.append(name)
        if ":" in line and not line.lower().startswith(("title", "section")):
            lhs, rhs = line.split(":", 1)
            if rhs.strip():
                labels.append(rhs.strip())
            if lhs.strip() and not re.search(r"[>\-]", lhs):
                labels.append(lhs.strip())
    lines = [ln.strip() for ln in code.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith("mindmap"):
        for line in lines[1:]:
            if re.search(r"[()\[\]{}]", line):
                continue
            if line:
                labels.append(line)
    if lines and lines[0].lower().startswith("statediagram"):
        for line in lines[1:]:
            if "-->" not in line:
                continue
            for part in line.split("-->"):
                part = re.sub(r"\[\*\]", "", part).strip().strip('"').strip("'")
                if part:
                    labels.append(part)
    return labels


def _label_fit(label: str, answer_n: str) -> str:
    """ok は本文どおり。soft は言い換え。hard は本文に無い言葉。"""
    folded = _norm(label)
    if not folded or folded in _KEYWORDS or len(folded) < 2:
        return "skip"
    if folded in answer_n:
        return "ok"
    kanji = re.findall(r"[一-龯]", folded)
    if kanji and all(ch in answer_n for ch in kanji):
        return "ok"
    pieces = kanji or [folded]
    if any(piece and piece in answer_n for piece in pieces):
        return "soft"
    return "hard"


def _labels_in_answer(code: str, answer: str) -> bool:
    answer_n = _norm(answer)
    saw = False
    for raw in _extract_labels(code):
        fit = _label_fit(raw, answer_n)
        if fit == "hard":
            return False
        if fit in ("ok", "soft"):
            saw = True
    return saw


def parse_diagram_response(raw: str, answer: str) -> dict[str, str]:
    """モデル出力を {status: none} または {status: ready, mermaid} にする。"""
    text = (raw or "").strip()
    if not text or _NONE_RE.fullmatch(text):
        return {"status": "none"}
    fence = _FENCE_RE.search(text)
    code = _strip_directives(fence.group(1) if fence else text)
    if not code or _NONE_RE.fullmatch(code) or not _DIAGRAM_HEAD_RE.match(code):
        return {"status": "none"}
    if not _labels_in_answer(code, answer):
        return {"status": "none"}
    return {"status": "ready", "mermaid": code}


def _user_prompt(answer: str, question: str) -> str:
    body = answer.strip()
    if len(body) > MAX_ANSWER_CHARS:
        body = body[:MAX_ANSWER_CHARS]
    question = (question or "").strip()
    if len(question) > 2000:
        question = question[:2000]
    parts = [
        "次の回答を1つの Mermaid 図にしてください。",
    ]
    if question:
        parts.append(f"\n質問:\n{question}")
    parts.append(f"\n回答:\n{body}")
    return "\n".join(parts)


_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$")
_BOLD_LINE_RE = re.compile(r"^\*\*(.+?)\*\*\s*$")
_BULLET_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.+)$")


def _mindmap_label(text: str) -> str:
    """マインドマップのノードに入れられる短いラベル。"""
    label = re.sub(r"[*_`#]+", "", text or "")
    label = re.split(r"[:：]", label, maxsplit=1)[0]
    label = re.sub(r"（[^）]*）", "", label)
    label = re.sub(r"\([^)]*\)", "", label)
    label = re.sub(r"^\d+[.)]\s*", "", label)
    label = re.sub(r"[\[\]{}<>\"']", "", label)
    label = re.sub(r"\s+", " ", label).strip(" ・、。．！？? ")
    if len(label) > 24:
        label = label[:24].rstrip()
    if not label or _norm(label) in _KEYWORDS:
        return ""
    return label


def _root_label(question: str) -> str:
    title = re.sub(
        r"(を|について)?(分類|説明|教え|まとめ|整理|挙げ|列挙).*$",
        "",
        (question or "").strip(),
    )
    label = _mindmap_label(title)
    if 2 <= len(label) <= 18:
        return label
    return "概要"


def _list_nodes(answer: str) -> list[tuple[str, list[str]]]:
    """見出しと箇条書きだけを拾う。地の文は含めない。"""
    sections: list[tuple[str, list[str]]] = []
    loose: list[str] = []
    current: tuple[str, list[str]] | None = None

    def flush() -> None:
        nonlocal current
        if current and (current[0] or current[1]):
            sections.append((current[0], current[1][:8]))
        current = None

    for raw in (answer or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("```"):
            continue
        heading = _HEADING_RE.match(line) or _BOLD_LINE_RE.match(line)
        bullet = _BULLET_RE.match(line)
        if heading and not bullet:
            flush()
            title = _mindmap_label(heading.group(1))
            current = (title, [])
            continue
        if not bullet:
            continue
        label = _mindmap_label(bullet.group(1))
        if not label:
            continue
        if current is None:
            loose.append(label)
            continue
        if len(current[1]) < 8:
            current[1].append(label)
    flush()

    nodes = [(title, kids) for title, kids in sections if title or kids]
    if nodes:
        return nodes[:8]
    if len(loose) >= 2:
        return [("", loose[:8])]
    return []


def list_mindmap(answer: str, question: str = "") -> str | None:
    """分類や列挙を、回答に書いてある項目だけのマインドマップにする。"""
    nodes = _list_nodes(answer)
    count = sum((1 if title else 0) + len(kids) for title, kids in nodes)
    if count < 2:
        return None
    return _render_mindmap(_root_label(question), nodes)


def _clause_nodes(answer: str) -> list[tuple[str, list[str]]]:
    text = re.sub(r"```[\s\S]*?```", " ", answer or "")
    text = re.sub(r"[#*`>]", "", text)
    labels: list[str] = []
    seen: set[str] = set()
    for part in re.split(r"[。！？\n]+", text):
        label = _mindmap_label(part)
        if len(label) < 4 or label in seen:
            continue
        seen.add(label)
        labels.append(label)
        if len(labels) >= 6:
            break
    if len(labels) < 2:
        return []
    return [("", labels)]


def _render_mindmap(root: str, nodes: list[tuple[str, list[str]]]) -> str:
    lines = ["mindmap", f"  root(({root}))"]
    for title, kids in nodes:
        if title:
            lines.append(f"    {title}")
            for kid in kids:
                lines.append(f"      {kid}")
            continue
        for kid in kids:
            lines.append(f"    {kid}")
    return "\n".join(lines)


def finalize_diagram(
    parsed: dict[str, str],
    answer: str,
    question: str = "",
) -> dict[str, str]:
    """モデルの図を優先し、捨てたときは回答の項目から描く。"""
    if parsed.get("status") == "ready" and parsed.get("mermaid"):
        return {"status": "ready", "mermaid": parsed["mermaid"]}
    fallback = list_mindmap(answer, question)
    if not fallback:
        nodes = _clause_nodes(answer)
        if nodes:
            fallback = _render_mindmap(_root_label(question), nodes)
    if fallback:
        return {"status": "ready", "mermaid": fallback}
    return {"status": "none"}


async def build_diagram(
    answer: str,
    question: str = "",
    model: dict[str, Any] | None = None,
) -> dict[str, str]:
    """回答から補足図を作る。空の回答は図なし。"""
    text = (answer or "").strip()
    if not text:
        return {"status": "none"}
    found = existing_mermaid(text)
    if found:
        return {"status": "ready", "mermaid": found}
    listed = list_mindmap(text, question)
    if listed:
        return {"status": "ready", "mermaid": listed}
    raw = await llm.chat_once(
        [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": _user_prompt(text, question)},
        ],
        model,
    )
    return finalize_diagram(parse_diagram_response(raw, text), text, question)
