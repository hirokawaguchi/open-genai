"""Dify 連携「AI アプリ」マイクロサービス。

外部 Dify の「ワークフロー」「チャットフロー」を、源内 の
「行政実務用 AI アプリ」プロトコル（同期形式）でラップして呼び出せるようにする。

- リクエスト: { "inputs": { ... } }（backend がプロキシ）
- レスポンス: { "outputs": "<Markdown テキスト>", "artifacts": [...] }
  artifacts にはファイル成果物に加え、Knowledge Retrieval の引用
  （mime_type=text/x.open-genai.citation）を含めることがある。

1 つの汎用プロキシで複数の Dify フローに対応する。Dify ごとの接続情報
（base_url / 種別 など）は、源内 の AI アプリ設定(config) に持たせ、
backend が `x-app-config`(JSON) ヘッダで本サービスへ転送する。

- Dify の API キー: `x-api-key`（= AI アプリの apiKey）→ Dify の `Bearer` に使用
- 会話継続(チャットフロー): `x-session-id` → Dify `conversation_id` を SQLite で対応付け

Dify の blocking モードには既知の不具合（1.4.1〜1.13 系で blocking 指定でも
`text/event-stream` を返す）があるため、本サービスは常に `response_mode=streaming`
で受信し、サーバ側で集約してから同期 `outputs` として返す。
"""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import sqlite3
import threading
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

# 既定の Dify 接続先（AI アプリの config で個別に上書きできる）
DEFAULT_DIFY_BASE_URL = os.environ.get("DIFY_BASE_URL", "").rstrip("/")

# session_id -> Dify conversation_id の対応を永続化する DB
SESSION_DB_PATH = os.environ.get("DIFY_SESSION_DB_PATH", "/data/dify-sessions.db")

REQUEST_TIMEOUT = float(os.environ.get("DIFY_TIMEOUT", "600"))

_lock = threading.Lock()

app = FastAPI(title="Open GENAI Dify App", version="0.1.0")


# ---------------------------------------------------------------------------
# session_id <-> conversation_id 永続化（チャットフローの会話継続用）
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SESSION_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(SESSION_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _lock, _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                sessionId TEXT PRIMARY KEY,
                conversationId TEXT NOT NULL
            )
            """
        )


def _get_conversation_id(session_id: str) -> str:
    if not session_id:
        return ""
    with _lock, _connect() as conn:
        r = conn.execute(
            "SELECT conversationId FROM sessions WHERE sessionId = ?", (session_id,)
        ).fetchone()
    return r["conversationId"] if r else ""


def _save_conversation_id(session_id: str, conversation_id: str) -> None:
    if not session_id or not conversation_id:
        return
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO sessions (sessionId, conversationId) VALUES (?, ?)",
            (session_id, conversation_id),
        )


@app.on_event("startup")
def _startup() -> None:
    try:
        _init_db()
    except Exception as e:  # noqa: BLE001 - 起動は止めない
        print(f"[dify-app] セッション DB の初期化に失敗: {e}")


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------
def _check_key(x_api_key: str | None) -> JSONResponse | None:
    # backend からの呼び出し時、x-api-key には「Dify の API キー」が入る。
    # ローカルでは固定キー(RAG_API_KEY)による前段認証は行わず、Dify 側に委ねる。
    return None


def _parse_config(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        cfg = json.loads(raw)
        return cfg if isinstance(cfg, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _file_type(mime: str) -> str:
    """Dify のファイル種別（image/audio/video/document）を MIME から推定する。"""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    if mime.startswith("video/"):
        return "video"
    return "document"


def _iter_input_files(inputs: dict[str, Any]) -> list[tuple[str, str, str]]:
    """inputs.files から (key, filename, content_b64) を取り出す。

    源内 の files 形式: [ { "key": str, "files": [ { "filename", "content" } ] } ]
    """
    out: list[tuple[str, str, str]] = []
    for entry in inputs.get("files") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("key") or "file"
        for f in entry.get("files", []):
            filename = f.get("filename", "uploaded")
            content_b64 = f.get("content", "")
            if content_b64:
                out.append((key, filename, content_b64))
    return out


async def _upload_file(
    client: httpx.AsyncClient,
    base: str,
    api_key: str,
    filename: str,
    content_b64: str,
    user: str,
) -> dict[str, Any]:
    """Dify の /files/upload にアップロードし、ファイル参照オブジェクトを返す。"""
    raw = base64.b64decode(content_b64)
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    res = await client.post(
        f"{base}/files/upload",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": (filename, raw, mime)},
        data={"user": user},
    )
    res.raise_for_status()
    file_id = res.json().get("id")
    return {
        "type": _file_type(mime),
        "transfer_method": "local_file",
        "upload_file_id": file_id,
    }


def _strip_meta(inputs: dict[str, Any], *extra: str) -> dict[str, Any]:
    """Dify の inputs として送らない源内 固有キーを除外する。"""
    drop = {"files", "conversation_histories", "action", *extra}
    return {k: v for k, v in inputs.items() if k not in drop}


def _coerce_dify_input_values(inputs: dict[str, Any]) -> dict[str, Any]:
    """源内フォーム由来の値を Dify inputs 向けに整える。

    Dify の text-input は string 必須。源内の number フィールドや JSON 数値化で
    int/float が渡ると `(type 'text-input') X in input form must be a string` になる。
    ファイル参照オブジェクト等の dict/list はそのまま残す。
    """
    out: dict[str, Any] = {}
    for key, value in inputs.items():
        if isinstance(value, bool):
            # bool は int のサブクラスなので先に扱う
            out[key] = "true" if value else "false"
        elif isinstance(value, (int, float)):
            out[key] = str(value)
        else:
            out[key] = value
    return out


# ---------------------------------------------------------------------------
# Dify のファイル出力（__dify__file__）の抽出・整形
# ---------------------------------------------------------------------------
# mime_type からの拡張子補正（Dify は tool_file 取得で .bin を付けることがある）
_MIME_EXT = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/msword": ".doc",
    "application/vnd.ms-powerpoint": ".ppt",
    "application/vnd.ms-excel": ".xls",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/markdown": ".md",
    "text/html": ".html",
    "application/json": ".json",
    "application/zip": ".zip",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def _is_dify_file(o: Any) -> bool:
    if not isinstance(o, dict):
        return False
    if o.get("dify_model_identity") == "__dify__file__":
        return True
    return bool(o.get("url")) and o.get("type") in (
        "document", "image", "audio", "video", "custom",
    )


def _extract_dify_files(obj: Any) -> list[dict[str, Any]]:
    """outputs（dict/list ネスト可）から Dify のファイルオブジェクトを収集する。"""
    found: list[dict[str, Any]] = []

    def walk(o: Any) -> None:
        if _is_dify_file(o):
            found.append(o)
            return
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(obj)
    return found


def _contains_file(v: Any) -> bool:
    return bool(_extract_dify_files(v))


def _clean_mime(mime: Any) -> str:
    return str(mime or "").split(";")[0].strip()


def _looks_opaque(stem: str) -> bool:
    """uuid/ハッシュ様（人間に無意味）な名前か。"""
    s = stem.replace("-", "")
    return len(s) >= 16 and all(c in "0123456789abcdefABCDEF" for c in s)


def _human_size(size: Any) -> str:
    try:
        n = float(size)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def _friendly_name(f: dict[str, Any], idx: int) -> str:
    name = str(f.get("filename") or "").strip()
    mime = _clean_mime(f.get("mime_type"))
    ext = _MIME_EXT.get(mime)
    stem, _, cur = name.rpartition(".")
    stem = stem or name
    if ext and (not cur or cur.lower() == "bin" or f".{cur.lower()}" != ext):
        base = stem if (stem and not _looks_opaque(stem)) else f"output_{idx + 1}"
        return base + ext
    return name or f"output_{idx + 1}{ext or ''}"


def _resolve_url(base: str, url: str) -> str:
    """相対 URL（/files/...）を Dify ホストの絶対 URL に解決する。"""
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    from urllib.parse import urlsplit

    parts = urlsplit(base)
    origin = f"{parts.scheme}://{parts.netloc}"
    if not url.startswith("/"):
        url = "/" + url
    return origin + url


def _files_to_artifacts(base: str, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dify のファイルオブジェクトを、backend へ渡す artifact 参照へ変換する。

    実体取得・再ホストは backend 側で行うため、ここでは参照(file_url)＋メタのみ返す。
    """
    arts: list[dict[str, Any]] = []
    for i, f in enumerate(files):
        url = _resolve_url(base, f.get("url") or f.get("remote_url") or "")
        if not url:
            continue
        arts.append(
            {
                "file_url": url,
                "display_name": _friendly_name(f, i),
                "mime_type": _clean_mime(f.get("mime_type")),
                "size": f.get("size"),
                "type": f.get("type"),
            }
        )
    return arts


# フロントの出典アコーディオン用（rag-app と同一定義）
CITATION_MIME = "text/x.open-genai.citation"


def _citations_to_artifacts(resources: list[Any]) -> list[dict[str, Any]]:
    """Dify の引用情報を citation artifacts へ変換する。

    受け付ける入力:
    - 通常チャットの retriever_resources
      {document_name, score, content, position}
    - Chatflow の knowledge-retrieval ノード outputs.result
      {title, content, metadata: {document_name, score, position, ...}}

    Dify Studio の「引用」と同じ情報を、源内の ExAppCitations が
    アコーディオン表示できる形式にする。
    """
    arts: list[dict[str, Any]] = []
    for r in resources or []:
        if not isinstance(r, dict):
            continue
        meta = r.get("metadata") if isinstance(r.get("metadata"), dict) else {}
        name = (
            str(
                r.get("document_name")
                or meta.get("document_name")
                or r.get("title")
                or r.get("document_id")
                or meta.get("document_id")
                or "unknown"
            ).strip()
            or "unknown"
        )
        position = r.get("position") or meta.get("position") or (len(arts) + 1)
        score = r.get("score")
        if score is None:
            score = meta.get("score")
        try:
            score_f = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_f = None
        if score_f is not None:
            display = f"[{position}] {name}（類似度: {score_f:.3f}）"
        else:
            display = f"[{position}] {name}"
        content = r.get("content")
        arts.append(
            {
                "display_name": display,
                "mime_type": CITATION_MIME,
                "text": content if isinstance(content, str) else "",
            }
        )
    return arts


def _normalize_citation_list(raw: Any) -> list[dict[str, Any]]:
    """citation_artifacts 配列（または JSON 文字列）を artifact 化する。"""
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        try:
            raw = json.loads(s)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    arts: list[dict[str, Any]] = []
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            text = item.get("content") if isinstance(item.get("content"), str) else ""
        text = (text or "").strip()
        if not text:
            continue
        display = str(item.get("display_name") or "").strip()
        if not display:
            source = str(item.get("source") or item.get("title") or "unknown").strip()
            display = f"[{i}] {source or 'unknown'}"
        arts.append(
            {
                "display_name": display,
                "mime_type": CITATION_MIME,
                "text": text,
            }
        )
    return arts


def _citation_artifacts_from_workflow_outputs(
    outputs: Any,
) -> list[dict[str, Any]]:
    """workflow outputs の citation_artifacts（JSON 文字列 or 配列）を artifact 化する。

    OpenGENAI Retrieval を HTTP で呼ぶワークフロー向け。各要素は
    {display_name?, source?, text|content, mime_type?} を想定。
    """
    if not isinstance(outputs, dict):
        return []
    raw = outputs.get("citation_artifacts")
    if raw is None:
        raw = outputs.get("citations_json")
    return _normalize_citation_list(raw)


def _extract_first_json_value(s: str) -> Any | None:
    """文字列中の最初の JSON 値を取り出す。

    Dify Agent の tool_response は
    `tool response: {...}', stream=False).` のように後続ゴミが付くことがあるため、
    JSONDecoder.raw_decode で先頭オブジェクトだけ読む。
    """
    if not s:
        return None
    decoder = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch not in "{[":
            continue
        try:
            obj, _end = decoder.raw_decode(s, i)
            return obj
        except json.JSONDecodeError:
            continue
    return None


def _citations_from_knowledge_search_payload(
    data: Any,
) -> list[dict[str, Any]]:
    """knowledge_search / MCP ツール応答から citation artifacts を取り出す。"""
    if isinstance(data, str):
        s = data.strip()
        if not s:
            return []
        parsed = _extract_first_json_value(s)
        if parsed is None:
            return []
        data = parsed
    if not isinstance(data, dict):
        return []

    arts = _normalize_citation_list(
        data.get("citation_artifacts") or data.get("citations_json")
    )
    if arts:
        return arts

    # citation_artifacts が無い場合は nodes から組み立てる
    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        return []
    out: list[dict[str, Any]] = []
    for i, n in enumerate(nodes, start=1):
        if not isinstance(n, dict):
            continue
        text = n.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        ref = n.get("ref") or i
        source = str(n.get("source") or "").strip() or "unknown"
        title = str(n.get("title") or "").strip()
        parts = [source]
        if title and title != source and title.lower() != "chunk":
            parts.append(title)
        ps, pe = n.get("page_start"), n.get("page_end")
        if ps is not None:
            try:
                ps_i = int(ps)
                pe_i = int(pe) if pe is not None else ps_i
                parts.append(
                    f"p.{ps_i}-{pe_i}" if pe_i != ps_i else f"p.{ps_i}"
                )
            except (TypeError, ValueError):
                pass
        label = " / ".join(parts)
        out.append(
            {
                "display_name": f"[{ref}] {label}",
                "mime_type": CITATION_MIME,
                "text": text.strip(),
            }
        )
    return out


def _merge_citation_arts(
    dst: list[dict[str, Any]], src: list[dict[str, Any]]
) -> None:
    """display_name+text で重複を除きながら追加する。"""
    seen = {(a.get("display_name"), a.get("text")) for a in dst}
    for a in src:
        key = (a.get("display_name"), a.get("text"))
        if key in seen:
            continue
        seen.add(key)
        dst.append(a)


_ANSWER_REF_RE = re.compile(r"\[(\d+)\]")
_CITATION_REF_RE = re.compile(r"^\[(\d+)\]")


def _filter_citations_cited_in_answer(
    answer: str, citations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """回答本文で参照された [n] に対応する出典だけ残す。

    タグ検索の全ヒットをアコーディオンに載せると、本文未使用の別文書まで
    並んでしまうため。本文に [n] が無い場合はフィルタしない（従来どおり）。
    """
    if not citations:
        return citations
    refs = {m.group(1) for m in _ANSWER_REF_RE.finditer(answer or "")}
    if not refs:
        return citations
    kept: list[dict[str, Any]] = []
    for a in citations:
        name = str(a.get("display_name") or "")
        m = _CITATION_REF_RE.match(name.strip())
        if m and m.group(1) in refs:
            kept.append(a)
    # 参照番号はあるが display_name 形式が合わない場合は落とさない
    return kept if kept else citations


def _scavenge_citations(value: Any, dst: list[dict[str, Any]], *, depth: int = 0) -> None:
    """agent_log / node outputs を再帰的に歩き knowledge_search 由来の出典を集める。

    Chatflow の Agent ノードは agent_thought ではなく agent_log を流す。
    ツール結果は data.output.tool_response や outputs.json[*].data などに入る。
    """
    if depth > 8 or value is None:
        return
    if isinstance(value, str):
        if "citation_artifacts" in value or '"nodes"' in value or "'nodes'" in value:
            _merge_citation_arts(dst, _citations_from_knowledge_search_payload(value))
        return
    if isinstance(value, dict):
        if "citation_artifacts" in value or (
            isinstance(value.get("nodes"), list) and value.get("nodes")
        ):
            _merge_citation_arts(dst, _citations_from_knowledge_search_payload(value))
        # 優先キーを先に見る
        for key in (
            "tool_response",
            "output",
            "observation",
            "text",
            "result",
            "json",
            "data",
            "citation_artifacts",
            "nodes",
        ):
            if key in value:
                _scavenge_citations(value.get(key), dst, depth=depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _scavenge_citations(item, dst, depth=depth + 1)


def _extract_knowledge_results(node_data: dict[str, Any]) -> list[Any]:
    """node_finished(data) から knowledge-retrieval のヒット一覧を取り出す。"""
    if not isinstance(node_data, dict):
        return []
    ntype = str(node_data.get("node_type") or "")
    if ntype not in ("knowledge-retrieval", "knowledge_retrieval"):
        return []
    outputs = node_data.get("outputs") or {}
    if not isinstance(outputs, dict):
        return []
    result = outputs.get("result")
    return result if isinstance(result, list) else []


def _normalize_field_names(value: Any) -> list[str]:
    """config の response_field / query_field を文字列リストへ正規化する。

    文字列・配列の両方を受け付ける（配列をそのまま `in dict` すると
    unhashable type: 'list' になるため）。
    """
    if value is None or value == "":
        return []
    if isinstance(value, str):
        s = value.strip()
        return [s] if s else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    s = str(value).strip()
    return [s] if s else []


def _outputs_to_text(outputs: Any, response_field: Any) -> str:
    """ワークフローの outputs(dict) を表示用テキストに整形する。

    Dify のファイル出力（`__dify__file__`）は、配列 JSON をそのまま出さず、
    ダウンロードリンク（[ファイル名](url)）として整形する。

    response_field は文字列または配列（例: ["report","citations"]）を受け付ける。
    """
    if outputs is None:
        return ""
    if isinstance(outputs, str):
        return outputs

    def _val_text(v: Any) -> str:
        return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)

    if not isinstance(outputs, dict):
        return json.dumps(outputs, ensure_ascii=False, indent=2)

    fields = _normalize_field_names(response_field)
    if fields:
        parts: list[str] = []
        for key in fields:
            if key not in outputs:
                continue
            val = outputs[key]
            if _contains_file(val):
                continue
            text = _val_text(val).strip()
            if not text:
                continue
            # 複数キー指定時は見出し付き、単一なら本文のみ
            if len(fields) == 1:
                parts.append(text)
            else:
                parts.append(f"**{key}**\n\n{text}")
        if parts:
            return "\n\n".join(parts)

    # ファイル／出典 JSON は artifacts 側で扱うため、テキストからは除外
    skip_keys = {"citation_artifacts", "citations_json"}
    non_file = [
        (k, v)
        for k, v in outputs.items()
        if k not in skip_keys and not _contains_file(v)
    ]
    if not non_file:
        return ""
    if len(non_file) == 1:
        return _val_text(non_file[0][1])  # 単一キーは値をそのまま
    # response_field 未指定時はよく使う本文キーを優先（複数キーの **report** 羅列を避ける）
    preferred = ("report", "result", "text", "answer", "output", "response")
    by_key = {k: v for k, v in non_file}
    for key in preferred:
        if key in by_key and isinstance(by_key[key], str) and by_key[key].strip():
            return by_key[key]
    return "\n\n".join(f"**{k}**\n\n{_val_text(v)}" for k, v in non_file)


async def _detect_file_input(base: str, api_key: str) -> tuple[str | None, bool]:
    """Dify の /parameters からファイル入力変数(file / file-list)を自動検出する。

    フローごとに入力変数名は異なるため、源内側に変数名を固定せず、
    Dify の入力スキーマ(user_input_form)から動的に解決する。
    戻り値: (変数名 or None, file-list なら True / file なら False)
    """
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(
                f"{base}/parameters",
                headers={"Authorization": f"Bearer {api_key}"},
            )
        if res.status_code != 200:
            return None, False
        for item in res.json().get("user_input_form", []) or []:
            if not isinstance(item, dict):
                continue
            for spec in item.values():
                if isinstance(spec, dict) and spec.get("type") in ("file", "file-list"):
                    return spec.get("variable"), spec.get("type") == "file-list"
    except (httpx.HTTPError, ValueError):
        return None, False
    return None, False


# ---------------------------------------------------------------------------
# Dify 呼び出し（streaming で受信して集約）
# ---------------------------------------------------------------------------
async def _run_workflow(
    base: str,
    api_key: str,
    inputs: dict[str, Any],
    user: str,
    response_field: str | None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """戻り値: (表示テキスト, ファイルobjs, citation artifacts)。"""
    payload = {"inputs": inputs, "response_mode": "streaming", "user": user}
    text_parts: list[str] = []
    final_outputs: Any = None
    error: str | None = None

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{base}/workflows/run",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as res:
            if res.status_code != 200:
                body = (await res.aread()).decode("utf-8", "replace")
                return (
                    f"Dify ワークフローの呼び出しに失敗しました (status: {res.status_code}).\n\n```\n{body[:1000]}\n```",
                    [],
                    [],
                )
            async for line in res.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload_str = line[len("data:") :].strip()
                if not payload_str or payload_str == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                event = obj.get("event")
                data = obj.get("data") or {}
                if event == "text_chunk":
                    text_parts.append(data.get("text", ""))
                elif event == "workflow_finished":
                    final_outputs = data.get("outputs")
                    if data.get("error"):
                        error = str(data.get("error"))
                elif event == "error":
                    error = obj.get("message") or data.get("message") or "unknown error"

    if error:
        return (f"Dify ワークフローでエラーが発生しました: {error}", [], [])
    if final_outputs is not None:
        text = _outputs_to_text(final_outputs, response_field)
        files = _extract_dify_files(final_outputs)
        citations = _citation_artifacts_from_workflow_outputs(final_outputs)
        return (text, files, citations)
    # workflow_finished が無い場合はストリームされたテキストを返す
    return ("".join(text_parts), [], [])


async def _run_chat(
    base: str,
    api_key: str,
    query: str,
    inputs: dict[str, Any],
    user: str,
    conversation_id: str,
    files: list[dict[str, Any]],
) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    """チャットフローを実行する。

    戻り値: (answer, conversation_id, file_objs, citation_artifacts)
    """
    payload: dict[str, Any] = {
        "query": query,
        "inputs": inputs,
        "response_mode": "streaming",
        "user": user,
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    if files:
        payload["files"] = files

    answer_parts: list[str] = []
    file_objs: list[dict[str, Any]] = []
    retriever_resources: list[Any] = []
    tool_citations: list[dict[str, Any]] = []
    new_conv_id = conversation_id
    error: str | None = None

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async with client.stream(
            "POST",
            f"{base}/chat-messages",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as res:
            if res.status_code != 200:
                body = (await res.aread()).decode("utf-8", "replace")
                return (
                    f"Dify チャットフローの呼び出しに失敗しました (status: {res.status_code}).\n\n```\n{body[:1000]}\n```",
                    new_conv_id,
                    [],
                    [],
                )
            async for line in res.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                payload_str = line[len("data:") :].strip()
                if not payload_str or payload_str == "[DONE]":
                    continue
                try:
                    obj = json.loads(payload_str)
                except json.JSONDecodeError:
                    continue
                if obj.get("conversation_id"):
                    new_conv_id = obj["conversation_id"]
                event = obj.get("event")
                if event in ("message", "agent_message"):
                    answer_parts.append(obj.get("answer", ""))
                elif event == "message_file":
                    # ツール等が生成したファイル（画像/文書）
                    file_objs.append(obj)
                elif event == "agent_thought":
                    # 旧 Agent チャット: observation にツール結果が入る
                    obs = obj.get("observation")
                    if obs:
                        _scavenge_citations(obs, tool_citations)
                elif event == "agent_log":
                    # Chatflow の Agent ノード: ツール結果は agent_log.data 配下
                    # 例: data.data.output.tool_response = knowledge_search の JSON
                    _scavenge_citations(obj.get("data"), tool_citations)
                elif event == "node_finished":
                    # Chatflow: message_end.retriever_resources が空でも
                    # knowledge-retrieval ノードの outputs.result に出典がある
                    data = obj.get("data") or {}
                    hits = _extract_knowledge_results(data)
                    if hits:
                        retriever_resources.extend(hits)
                    # Agent / Tool / Code ノード outputs（json / text 等）を走査
                    if isinstance(data, dict):
                        _scavenge_citations(data.get("outputs"), tool_citations)
                        _scavenge_citations(data.get("process_data"), tool_citations)
                elif event == "message_end":
                    # message_end に files 配列が入る版がある
                    for f in obj.get("files") or []:
                        if isinstance(f, dict):
                            file_objs.append(f)
                    # 通常チャットアプリの引用（Chatflow では空配列のことがある）
                    meta = obj.get("metadata") or {}
                    resources = meta.get("retriever_resources") or []
                    if isinstance(resources, list) and resources:
                        retriever_resources = list(resources)
                elif event == "error":
                    error = obj.get("message") or "unknown error"

    if error:
        return (
            f"Dify チャットフローでエラーが発生しました: {error}",
            new_conv_id,
            [],
            [],
        )
    answer = "".join(answer_parts)
    # 生成ファイルは backend で再ホストするため、参照(file_obj)を返す
    out_files = _extract_dify_files(file_objs)
    citations = _citations_to_artifacts(retriever_resources)
    _merge_citation_arts(citations, tool_citations)
    citations = _filter_citations_cited_in_answer(answer, citations)
    return (answer, new_conv_id, out_files, citations)


# 源内フォームには出さず、invoke 時に自動注入する Dify 入力変数
_HIDDEN_FORM_VARS = frozenset({"top_k", "scope", "rag_scope"})


def _inject_hidden_inputs(
    inputs: dict[str, Any],
    *,
    scope: str | None,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """非表示項目へ適切な値を入れる（チーム scope・参照件数）。"""
    out = dict(inputs)
    team_scope = (scope or "").strip()
    if team_scope:
        out["scope"] = team_scope
    elif not str(out.get("scope") or "").strip():
        default_scope = str(cfg.get("default_scope") or "").strip()
        if default_scope:
            out["scope"] = default_scope
    if not str(out.get("top_k") or "").strip():
        out["top_k"] = str(cfg.get("default_top_k") or "8")
    return out


# ---------------------------------------------------------------------------
# Dify の入力スキーマ(/parameters) を 源内のフォーム定義(placeholder) に変換
# ---------------------------------------------------------------------------
def _convert_user_input_form(form: list[Any]) -> dict[str, Any]:
    """Dify の user_input_form を 源内 の placeholder(uiJson) 形式へ変換する。

    Dify のコンポーネント型 → 源内の type:
      text-input -> text, paragraph -> textarea, number -> number,
      select -> select(items), file / file-list -> file

    top_k / scope は源内では非表示（実行時に自動注入）。
    """
    ui: dict[str, Any] = {}
    for item in form or []:
        if not isinstance(item, dict):
            continue
        for comp_type, spec in item.items():
            if not isinstance(spec, dict):
                continue
            variable = spec.get("variable")
            if not variable:
                continue
            if variable in _HIDDEN_FORM_VARS:
                continue
            field: dict[str, Any] = {
                "title": spec.get("label") or variable,
                "required": bool(spec.get("required")),
            }
            if comp_type == "text-input":
                field["type"] = "text"
                if spec.get("max_length"):
                    field["max_length"] = spec["max_length"]
            elif comp_type == "paragraph":
                field["type"] = "textarea"
                if spec.get("max_length"):
                    field["max_length"] = spec["max_length"]
            elif comp_type == "number":
                field["type"] = "number"
            elif comp_type == "select":
                field["type"] = "select"
                field["items"] = [
                    {"title": str(o), "value": str(o)} for o in (spec.get("options") or [])
                ]
            elif comp_type in ("file", "file-list"):
                field["type"] = "file"
                field["multiple"] = comp_type == "file-list"
            else:
                # 未知のコンポーネントはスキップ
                continue
            if spec.get("default") not in (None, ""):
                field["default_value"] = spec["default"]
            ui[variable] = field
    return ui


# ---------------------------------------------------------------------------
# エンドポイント
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.get("/schema")
async def schema(
    x_api_key: str | None = Header(default=None),
    x_app_config: str | None = Header(default=None),
) -> Any:
    """Dify の /parameters を取得し、源内のフォーム定義(placeholder) に変換して返す。"""
    cfg = _parse_config(x_app_config)
    base = (cfg.get("dify_base_url") or DEFAULT_DIFY_BASE_URL).rstrip("/")
    if not base:
        return {"placeholder": {}}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.get(
                f"{base}/parameters",
                headers={"Authorization": f"Bearer {x_api_key or ''}"},
            )
        if res.status_code != 200:
            return {"placeholder": {}}
        form = res.json().get("user_input_form", [])
    except (httpx.HTTPError, ValueError):
        return {"placeholder": {}}
    return {"placeholder": _convert_user_input_form(form)}


@app.post("/invoke")
async def invoke(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_app_config: str | None = Header(default=None),
    x_session_id: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err

    # x-app-config 例:
    #   {"dify_base_url":"https://<dify>/v1","dify_app_type":"chat",
    #    "query_field":"query","file_var":"upload_files"}
    cfg = _parse_config(x_app_config)
    base = (cfg.get("dify_base_url") or DEFAULT_DIFY_BASE_URL).rstrip("/")
    if not base:
        return {
            "outputs": (
                "Dify の接続先(dify_base_url)が設定されていません。"
                "AI アプリの「設定(config)」に "
                '`{"dify_base_url": "https://<dify>/v1", "dify_app_type": "chat"}` '
                "の形式で指定してください。"
            )
        }

    app_type = (cfg.get("dify_app_type") or "chat").strip().lower()
    query_fields = _normalize_field_names(cfg.get("query_field")) or ["query"]
    query_field = query_fields[0]
    # response_field または response_fields を受理（文字列 / 配列）
    response_field = cfg.get("response_field")
    if response_field in (None, "", []):
        response_field = cfg.get("response_fields")
    api_key = x_api_key or ""
    user = x_user_id or "open-genai"

    body = await request.json()
    inputs = _inject_hidden_inputs(
        body.get("inputs", body) or {},
        scope=x_scope,
        cfg=cfg,
    )

    # ファイルを Dify にアップロードして参照オブジェクト化
    file_refs_by_key: dict[str, list[dict[str, Any]]] = {}
    all_file_refs: list[dict[str, Any]] = []
    files_meta = _iter_input_files(inputs)
    if files_meta:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                for key, filename, content_b64 in files_meta:
                    ref = await _upload_file(
                        client, base, api_key, filename, content_b64, user
                    )
                    file_refs_by_key.setdefault(key, []).append(ref)
                    all_file_refs.append(ref)
        except httpx.HTTPError as e:
            return {"outputs": f"Dify へのファイルアップロードに失敗しました: {e}"}
        except Exception as e:  # noqa: BLE001
            return {"outputs": f"ファイルの処理に失敗しました: {e}"}

    try:
        # ファイル入力変数の解決（chat / workflow 共通。源内側に変数名を固定しない）:
        #  1. config.file_var で明示指定があればそれを使う（画面から設定・任意の上書き）
        #  2. なければ Dify の /parameters から file 入力変数を自動検出
        # 解決した変数があれば、その型(file-list/file)に応じて inputs へ割り当てる。
        async def _resolve_file_var() -> tuple[str | None, bool]:
            if cfg.get("file_var"):
                return cfg.get("file_var"), True
            if all_file_refs:
                return await _detect_file_input(base, api_key)
            return None, False

        if app_type == "workflow":
            dify_inputs = _coerce_dify_input_values(_strip_meta(inputs))
            if all_file_refs:
                file_var, is_list = await _resolve_file_var()
                if file_var:
                    dify_inputs[file_var] = (
                        all_file_refs if is_list else all_file_refs[0]
                    )
                else:
                    # フォールバック: 源内フォームのキー名を Dify 変数名として割り当て
                    for key, refs in file_refs_by_key.items():
                        dify_inputs[key] = refs if len(refs) > 1 else refs[0]
            outputs, out_files, citations = await _run_workflow(
                base, api_key, dify_inputs, user, response_field
            )
            resp: dict[str, Any] = {"outputs": outputs}
            arts = _files_to_artifacts(base, out_files) + citations
            if arts:
                resp["artifacts"] = arts
            return resp

        # ---- チャットフロー ----
        query = str(inputs.get(query_field) or inputs.get("question") or "").strip()
        if not query:
            return {"outputs": "メッセージ(query)が空です。入力してください。"}
        dify_inputs = _coerce_dify_input_values(
            _strip_meta(inputs, query_field, "question")
        )
        conversation_id = _get_conversation_id(x_session_id or "")
        # 解決した入力変数へ。解決できなければメッセージ添付(sys.files)として送る。
        chat_files = all_file_refs
        if all_file_refs:
            file_var, is_list = await _resolve_file_var()
            if file_var:
                dify_inputs[file_var] = all_file_refs if is_list else all_file_refs[0]
                chat_files = []
        answer, new_conv_id, out_files, citations = await _run_chat(
            base, api_key, query, dify_inputs, user, conversation_id, chat_files
        )
        if new_conv_id and x_session_id:
            _save_conversation_id(x_session_id, new_conv_id)
        resp = {"outputs": answer}
        arts = _files_to_artifacts(base, out_files) + citations
        if arts:
            resp["artifacts"] = arts
        return resp
    except httpx.HTTPError as e:
        return {"outputs": f"Dify への接続でエラーが発生しました: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"outputs": f"処理中にエラーが発生しました: {e}"}
