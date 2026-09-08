"""文書生成・合成サービス（公開の汎用リファレンス実装 / 既定の合成バックエンド）。

Open GENAI の `procuretech-editor` から呼ばれる pluggable な生成/合成 API の
「そのまま動く」実装。`/generate` はナビゲーションシート（Markdown 表＋生成指示）
を読み、設問ごとの材料ファイルと、生成指示に基づく成果物 Markdown を作る。
成果物は LLM（未設定・失敗時はスキップして README に注記）で書く。
`/compose` の pptx は任意で OpenAI 互換 LLM がレイアウトを選び、失敗時は決定論変換へ落とす。
テーマ固有の非公開サービス（例: 調達仕様書=spec-app）を差し替える際の雛形であり、
テーマ無しの「素の文書」の合成の既定バックエンドでもある。

契約:
- POST /generate            multipart: 任意キーの Excel / form: username, doc_type, options
                            -> {"request_id": "..."}
- GET  /status/{id}         -> {"status": processing|success|error, "progress": int, "waiting_ready": bool}
- GET  /waiting/{id}        -> image/png（ジョブの待ち画像）
- POST /waiting-picture     -> image/png（書き出し待ち用。フォールバック落書き）
- GET  /result/{id}         -> application/zip（section*.md, README.md, sections.json）
- POST /compose             JSON {"outputs":[{"name","format?","sections":[{"filename","content"}]}],
                                   "assets": {"images/x.png": "<base64>"}}
                            -> application/zip（<name>.<format>。format 省略時は docx）。
                               format: docx / html / pptx / txt / md。
                               assets の画像は視覚形式（docx / html / pptx）へ埋め込む。
- GET  /template/{key}      -> 同梱のヒアリングシート様式（xlsx）をダウンロード

`GENERATE_API_KEY` が設定されていれば `X-API-Key` を検証する。
ジョブ状態はメモリ保持（プロセス再起動で消える）。
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import time
import uuid
import zipfile
from pathlib import Path
import sys
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response


def _ensure_shared() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "shared" / "navsheet.py").exists():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return


_ensure_shared()
from shared.navsheet import NavSheet, empty_workbook, parse_workbook, slug_for  # noqa: E402

from app.compose_formats import (
    SUPPORTED_FORMATS,
    markdown_to_html,
    markdown_to_md,
    markdown_to_pptx,
    markdown_to_txt,
    normalize_format,
)
from app.dads import BODY, FONT_MONO, MUTED, apply_docx_theme, shade_paragraph, style_run
from app.pptx_layouts import render_deck
from app.pptx_plan import plan_deck
from app.waiting import make_fallback_waiting_png

# API キー（旧名 GENERATE_SAMPLE_API_KEY も後方互換で参照）。
API_KEY = os.environ.get("GENERATE_API_KEY") or os.environ.get("GENERATE_SAMPLE_API_KEY", "")
# success になるまでの擬似処理時間（polling UI を確認できるように少し待たせる）。
PROCESS_SECONDS = float(
    os.environ.get("GENERATE_PROCESS_SECONDS")
    or os.environ.get("GENERATE_SAMPLE_PROCESS_SECONDS", "2")
)

TEMPLATE_KEYS = {"hearing", "navigation"}
TEMPLATE_FILENAME = "hearing-sheet.xlsx"

app = FastAPI(title="ProcureTech Generate", version="1.0.0")

# request_id -> {"created": float, "zip": bytes, "doc_type": str}
_JOBS: dict[str, dict[str, Any]] = {}


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _read_nav_sheet(files: dict[str, bytes]) -> NavSheet:
    for data in files.values():
        try:
            return parse_workbook(data)
        except Exception:  # noqa: BLE001
            continue
    return NavSheet()


GENERATED_FILENAME = "生成文書.md"
GENERATED_SECTION_KEY = "generated"
README_FILENAME = "README.md"
README_SECTION_KEY = "readme"
_RESERVED_KEYS = {README_SECTION_KEY, GENERATED_SECTION_KEY}
_UNSAFE_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


def _bullets_or_paragraph(value: str) -> str:
    """複数行の値は箇条書き、単一行はそのまま段落にする。"""
    lines = [ln.strip() for ln in value.splitlines() if ln.strip()]
    if len(lines) > 1:
        return "\n".join(f"- {ln}" for ln in lines)
    return value or "（未記入）"


def _safe_stem(label: str, index: int) -> str:
    raw = _UNSAFE_NAME.sub("", (label or "").strip()) or f"項目{index}"
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:80] or f"項目{index}"


def _unique_name(name: str, used: set[str]) -> str:
    if name not in used:
        return name
    stem, ext = (name.rsplit(".", 1) + [""])[:2] if "." in name else (name, "")
    suffix = f".{ext}" if ext else ""
    n = 2
    while True:
        cand = f"{stem}-{n}{suffix}"
        if cand not in used:
            return cand
        n += 1


def _section_key(label: str, index: int, used: set[str]) -> str:
    key = slug_for(label, index)
    if key in _RESERVED_KEYS:
        key = f"item-{index}"
    n = 2
    base = key
    while key in used:
        key = f"{base}-{n}"
        n += 1
    return key


def _materials_markdown(rows: list[Any]) -> str:
    parts: list[str] = []
    for i, row in enumerate(rows, start=1):
        heading = (row.label or "").strip() or f"項目{i}"
        parts.append(f"## {heading}\n")
        parts.append(_bullets_or_paragraph(row.value))
        parts.append("")
    return "\n".join(parts).strip()


def _unwrap_md(text: str) -> str:
    """モデルが全体をフェンスで包んだ場合は外す。"""
    raw = (text or "").strip()
    m = re.match(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$", raw, re.IGNORECASE)
    return (m.group(1) if m else raw).strip()


def _write_generated_document(instruction: str, rows: list[Any]) -> tuple[str | None, str | None]:
    """生成指示から成果物 Markdown を書く。(本文, スキップ理由) を返す。"""
    from app.llm import chat, instruction_llm_enabled

    if not instruction.strip():
        return None, "生成指示が空のため、成果物は作っていません。"
    if not instruction_llm_enabled():
        return None, "LLM が無効のため、生成指示に基づく成果物は作っていません。"
    materials = _materials_markdown(rows) or "（設問の回答はありません）"
    try:
        text = chat(
            [
                {
                    "role": "system",
                    "content": (
                        "あなたは文書作成アシスタントです。"
                        "利用者の「生成指示」に従い、提供された設問と回答だけを材料にして、"
                        "完成した Markdown 文書を 1 本書いてください。"
                        "前置き・説明・注意書きは書かず、本文の Markdown だけを出力してください。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"# 生成指示\n\n{instruction.strip()}\n\n"
                        f"# 材料（ナビゲーションシートの設問と回答）\n\n{materials}\n"
                    ),
                },
            ]
        )
    except Exception as e:  # noqa: BLE001
        return None, f"生成指示に基づく成果物の作成に失敗したため、スキップしました（{e}）。"
    body = _unwrap_md(text)
    if not body:
        return None, "モデルの応答が空のため、生成指示に基づく成果物は作っていません。"
    return body + "\n", None


def _readme_body(
    *,
    title: str,
    doc_type: str,
    ts: str,
    inventory: list[tuple[str, str]],
    note: str | None,
) -> str:
    lines = [
        f"# {title}",
        "",
        "このプロジェクトは、参考資料を読み込んで作成した"
        "ヒアリングシートを、"
        "Markdown エディタから読み込んで生成したものです。",
        "",
        f"- 生成日時: {ts}",
        f"- 文書種別: `{doc_type}`",
        "",
        "## 同梱ファイル",
        "",
    ]
    for name, desc in inventory:
        lines.append(f"- `{name}` — {desc}")
    if note:
        lines.extend(["", "## 注記", "", note])
    lines.append("")
    return "\n".join(lines)


def _build_zip(
    files: dict[str, bytes],
    doc_type: str,
    *,
    waiting_png: bytes | None = None,
    request_id: str = "",
) -> bytes:
    """ナビゲーションシートから材料ファイル＋生成指示の成果物 zip を作る。"""
    sheet = _read_nav_sheet(files)
    title = next((r.label for r in sheet.rows if r.label.strip()), "文書")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    instruction = sheet.instruction.strip()

    outputs: dict[str, str] = {}
    manifest: list[dict[str, Any]] = []
    inventory: list[tuple[str, str]] = []
    used_names: set[str] = {README_FILENAME, "sections.json"}
    used_keys: set[str] = {README_SECTION_KEY}

    generated, skip_note = _write_generated_document(instruction, sheet.rows)
    if generated:
        outputs[GENERATED_FILENAME] = generated
        used_names.add(GENERATED_FILENAME)
        used_keys.add(GENERATED_SECTION_KEY)
        manifest.append(
            {
                "file": GENERATED_FILENAME,
                "section_key": GENERATED_SECTION_KEY,
                "title": "生成文書",
                "order": 2,
                "role": "generated",
            }
        )
        inventory.append((GENERATED_FILENAME, "生成指示に基づく成果物"))

    for i, row in enumerate(sheet.rows, start=1):
        heading = (row.label or "").strip() or f"項目{i}"
        filename = _unique_name(f"{i:02d}_{_safe_stem(heading, i)}.md", used_names)
        used_names.add(filename)
        key = _section_key(heading, i, used_keys)
        used_keys.add(key)
        outputs[filename] = f"# {heading}\n\n{_bullets_or_paragraph(row.value)}\n"
        manifest.append(
            {
                "file": filename,
                "section_key": key,
                "title": heading,
                "order": i + 10,
                "role": "source",
            }
        )
        inventory.append((filename, f"設問「{heading}」の回答（材料）"))

    inventory.insert(0, (README_FILENAME, "このプロジェクトの概要と同梱ファイル一覧"))
    outputs[README_FILENAME] = _readme_body(
        title=title, doc_type=doc_type, ts=ts, inventory=inventory, note=skip_note
    )
    manifest.insert(
        0,
        {
            "file": README_FILENAME,
            "section_key": README_SECTION_KEY,
            "title": "README",
            "order": 1,
            "role": "readme",
        },
    )
    outputs["sections.json"] = json.dumps(
        {"theme": "sample", "sections": manifest}, ensure_ascii=False, indent=2
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, body in outputs.items():
            zf.writestr(name, body)
        if waiting_png:
            zf.writestr(f"images/{request_id or 'project'}_waiting.png", waiting_png)
    return buf.getvalue()


# 画像のみの行（ブロック画像として大きく埋め込む）。
_IMAGE_LINE_RE = re.compile(r"^!\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)$")
# 行内（インライン）画像。テキストと混在していても抽出できる。
_INLINE_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)>\s]+)>?(?:\s+\"[^\"]*\")?\s*\)")


def _rel_of(match_group: str) -> str:
    return match_group.replace("\\", "/").lstrip("/")


def _add_code_block(doc: Any, lang: str, lines: list[str]) -> None:
    """フェンス付きコードブロックを等幅段落で出力する。

    Mermaid はサーバ側では描画できない（本来はクライアントが合成前に PNG 化して画像へ差し替える）。
    未変換のまま届いた場合の保険として、注記＋ソースを崩さず出力する。
    """
    from docx.shared import Pt

    if lang == "mermaid":
        note = doc.add_paragraph()
        style_run(
            note.add_run("【Mermaid 図（画像未変換のためソースを表示）】"),
            size=Pt(10),
            color=MUTED,
            italic=True,
        )
    para = doc.add_paragraph()
    shade_paragraph(para)
    para.paragraph_format.line_spacing = 1.45
    style_run(
        para.add_run("\n".join(lines)),
        name=FONT_MONO,
        size=Pt(9),
        color=BODY,
    )


def _add_line_with_inline_images(doc: Any, line: str, assets: dict[str, bytes]) -> None:
    """テキストと行内画像が混在する行を、画像を埋め込みつつ 1 段落で出力する。"""
    from docx.shared import Cm

    matches = list(_INLINE_IMAGE_RE.finditer(line))
    if not matches:
        doc.add_paragraph(line)
        return
    para = doc.add_paragraph()
    last = 0
    for m in matches:
        pre = line[last : m.start()]
        if pre:
            para.add_run(pre)
        rel = _rel_of(m.group(1))
        data = assets.get(rel)
        if data:
            try:
                para.add_run().add_picture(io.BytesIO(data), width=Cm(12))
            except Exception:  # noqa: BLE001
                para.add_run(f"[画像: {rel}]")
        else:
            para.add_run(f"[画像: {rel}]")
        last = m.end()
    tail = line[last:]
    if tail:
        para.add_run(tail)


def _markdown_to_docx(
    name: str, sections: list[dict[str, Any]], assets: dict[str, bytes] | None = None
) -> bytes:
    """章（Markdown 文字列）を連結し、簡易パースで .docx を作る（python-docx）。

    spec-app（pandoc）と同等に、本文が参照する画像を assets（{相対パス: バイト列}）から
    埋め込む。画像のみの行はブロック画像、テキスト混在はインライン画像として配置する。
    Mermaid は合成前にクライアントが PNG 画像へ差し替える運用のため、ここでは通常画像として
    埋め込まれる（未変換で届いた場合はコードブロックとして安全に出力する）。
    """
    from docx import Document
    from docx.shared import Cm

    assets = assets or {}
    doc = Document()
    apply_docx_theme(doc)
    doc.add_heading(name, level=0)
    for sec in sections:
        content = str(sec.get("content") or "")
        in_code = False
        code_lang = ""
        code_lines: list[str] = []
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("```"):
                if in_code:
                    _add_code_block(doc, code_lang, code_lines)
                    in_code, code_lang, code_lines = False, "", []
                else:
                    in_code, code_lang, code_lines = True, stripped[3:].strip().lower(), []
                continue
            if in_code:
                code_lines.append(raw_line)
                continue
            line = raw_line.rstrip()
            if not line.strip():
                continue
            m = _IMAGE_LINE_RE.match(line.strip())
            if m:
                rel = _rel_of(m.group(1))
                data = assets.get(rel)
                if data:
                    try:
                        doc.add_picture(io.BytesIO(data), width=Cm(15))
                        continue
                    except Exception:  # noqa: BLE001
                        pass
                doc.add_paragraph(f"[画像: {rel}]")
                continue
            if line.startswith("### "):
                doc.add_heading(line[4:].strip(), level=3)
            elif line.startswith("## "):
                doc.add_heading(line[3:].strip(), level=2)
            elif line.startswith("# "):
                doc.add_heading(line[2:].strip(), level=1)
            elif line.lstrip().startswith(("- ", "* ")):
                doc.add_paragraph(line.lstrip()[2:].strip(), style="List Bullet")
            else:
                _add_line_with_inline_images(doc, line, assets)
        if in_code and code_lines:  # フェンス閉じ忘れの保険
            _add_code_block(doc, code_lang, code_lines)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()


def _decode_assets(raw: Any) -> dict[str, bytes]:
    """compose の assets（{相対パス: base64}）を {相対パス: バイト列} へ変換する。"""
    out: dict[str, bytes] = {}
    if not isinstance(raw, dict):
        return out
    for rel, b64 in raw.items():
        if not isinstance(rel, str) or not isinstance(b64, str):
            continue
        try:
            out[rel.replace("\\", "/").lstrip("/")] = base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            continue
    return out


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/template/{key}")
def template(key: str, x_api_key: str | None = Header(default=None)) -> Response:
    err = _check_key(x_api_key)
    if err:
        return err
    if key not in TEMPLATE_KEYS:
        return JSONResponse(status_code=404, content={"error": "template not found"})
    return Response(
        content=empty_workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_FILENAME}"'},
    )


@app.post("/generate")
async def generate(
    request: Request, x_api_key: str | None = Header(default=None)
) -> JSONResponse:
    """テーマ非依存: multipart 内の任意のアップロードファイルを受け付ける。"""
    err = _check_key(x_api_key)
    if err:
        return err
    form = await request.form()
    files: dict[str, bytes] = {}
    for key, value in form.multi_items():
        if hasattr(value, "read"):  # UploadFile
            files[key] = await value.read()
    doc_type = str(form.get("doc_type") or "sample")
    if not files:
        return JSONResponse(status_code=400, content={"error": "入力ファイルがありません"})
    request_id = uuid.uuid4().hex
    waiting_png = make_fallback_waiting_png()
    _JOBS[request_id] = {
        "created": time.time(),
        "zip": _build_zip(files, doc_type, waiting_png=waiting_png, request_id=request_id),
        "doc_type": doc_type,
        "waiting_png": waiting_png,
        "waiting_ready": True,
    }
    return JSONResponse(status_code=202, content={"request_id": request_id})


@app.get("/status/{request_id}")
def status(request_id: str, x_api_key: str | None = Header(default=None)) -> JSONResponse:
    err = _check_key(x_api_key)
    if err:
        return err
    job = _JOBS.get(request_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    elapsed = time.time() - job["created"]
    waiting_ready = bool(job.get("waiting_ready") or job.get("waiting_png"))
    if elapsed < PROCESS_SECONDS:
        pct = int(min(90, (elapsed / max(PROCESS_SECONDS, 0.001)) * 90))
        return JSONResponse(
            content={"status": "processing", "progress": pct, "waiting_ready": waiting_ready}
        )
    return JSONResponse(
        content={"status": "success", "progress": 100, "waiting_ready": waiting_ready}
    )


@app.get("/waiting/{request_id}")
def waiting_image(request_id: str, x_api_key: str | None = Header(default=None)) -> Response:
    err = _check_key(x_api_key)
    if err:
        return err
    job = _JOBS.get(request_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    png = job.get("waiting_png") or make_fallback_waiting_png()
    return Response(content=png, media_type="image/png")


@app.post("/waiting-picture")
async def waiting_picture(
    request: Request, x_api_key: str | None = Header(default=None)
) -> Response:
    err = _check_key(x_api_key)
    if err:
        return err
    return Response(content=make_fallback_waiting_png(), media_type="image/png")


@app.get("/result/{request_id}")
def result(request_id: str, x_api_key: str | None = Header(default=None)) -> Response:
    err = _check_key(x_api_key)
    if err:
        return err
    job = _JOBS.get(request_id)
    if job is None:
        return JSONResponse(status_code=404, content={"error": "not found"})
    return Response(
        content=job["zip"],
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{request_id}.zip"'},
    )


def _render_output(
    fmt: str, name: str, sections: list[dict[str, Any]], assets: dict[str, bytes]
) -> bytes:
    if fmt == "html":
        return markdown_to_html(name, sections, assets)
    if fmt == "pptx":
        deck = plan_deck(name, sections, assets)
        if deck:
            print(f"[generate] pptx: LLM deck ({len(deck.get('slides') or [])} slides)")
            return render_deck(deck, assets)
        print("[generate] pptx: fallback to heading split")
        return markdown_to_pptx(name, sections, assets)
    if fmt == "txt":
        return markdown_to_txt(sections)
    if fmt == "md":
        return markdown_to_md(sections)
    return _markdown_to_docx(name, sections, assets)


@app.post("/compose")
async def compose(
    request: Request, x_api_key: str | None = Header(default=None)
) -> Response:
    """順序付き Markdown（出力ファイル毎）を指定形式に合成して zip で返す。

    outputs[].format は docx（既定）/ html / pptx / txt / md。
    body.assets（{相対パス: base64}）に本文の `![](相対パス)` と一致する画像を渡すと、
    視覚形式（docx / html / pptx）へ埋め込む（Mermaid はクライアントが PNG 化して
    画像として渡す運用）。
    """
    err = _check_key(x_api_key)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=400, content={"error": "invalid json"})
    outputs = body.get("outputs") if isinstance(body, dict) else None
    if not isinstance(outputs, list) or not outputs:
        return JSONResponse(status_code=400, content={"error": "outputs がありません"})
    assets = _decode_assets(body.get("assets") if isinstance(body, dict) else None)

    unknown: list[str] = []
    rendered: list[tuple[str, bytes]] = []
    used: set[str] = set()
    for i, o in enumerate(outputs, 1):
        if not isinstance(o, dict):
            continue
        name = str(o.get("name") or f"output{i}")
        raw_fmt = str(o.get("format") or "docx").strip().lower().lstrip(".")
        if raw_fmt and raw_fmt not in SUPPORTED_FORMATS:
            unknown.append(raw_fmt)
            continue
        fmt = normalize_format(raw_fmt)
        sections = o.get("sections") or []
        if not isinstance(sections, list):
            sections = []
        data = _render_output(fmt, name, sections, assets)
        arc = f"{name}.{fmt}"
        n = 2
        while arc in used:
            arc = f"{name}({n}).{fmt}"
            n += 1
        used.add(arc)
        rendered.append((arc, data))

    if unknown and not rendered:
        return JSONResponse(
            status_code=422,
            content={"error": f"未対応の出力形式です: {', '.join(sorted(set(unknown)))}"},
        )
    if not rendered:
        return JSONResponse(status_code=400, content={"error": "合成対象の内容がありません"})

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for arc, data in rendered:
            zf.writestr(arc, data)
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="compose.zip"'},
    )


@app.get("/template/{input_key}")
def template(input_key: str, x_api_key: str | None = Header(default=None)) -> Response:
    err = _check_key(x_api_key)
    if err:
        return err
    key = (input_key or "").strip().lower()
    if key not in TEMPLATE_KEYS:
        return JSONResponse(status_code=404, content={"error": "template not found"})
    return Response(
        content=empty_workbook(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{TEMPLATE_FILENAME}"'},
    )
