"""Dify 連携「AI アプリ」マイクロサービス。

外部 Dify の「ワークフロー」「チャットフロー」を、源内 の
「行政実務用 AI アプリ」プロトコル（同期形式）でラップして呼び出せるようにする。

- リクエスト: { "inputs": { ... } }（backend がプロキシ）
- レスポンス: { "outputs": "<Markdown テキスト>" }

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


def _outputs_to_text(outputs: Any, response_field: str | None) -> str:
    """ワークフローの outputs(dict) を表示用テキストに整形する。"""
    if outputs is None:
        return ""
    if isinstance(outputs, str):
        return outputs
    if isinstance(outputs, dict):
        if response_field and response_field in outputs:
            val = outputs[response_field]
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False, indent=2)
        # 単一キーならその値を、複数キーなら全体を見やすく整形
        if len(outputs) == 1:
            val = next(iter(outputs.values()))
            return val if isinstance(val, str) else json.dumps(val, ensure_ascii=False, indent=2)
        parts = []
        for k, v in outputs.items():
            v_text = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False, indent=2)
            parts.append(f"**{k}**\n\n{v_text}")
        return "\n\n".join(parts)
    return json.dumps(outputs, ensure_ascii=False, indent=2)


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
) -> str:
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
                return f"Dify ワークフローの呼び出しに失敗しました (status: {res.status_code}).\n\n```\n{body[:1000]}\n```"
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
        return f"Dify ワークフローでエラーが発生しました: {error}"
    if final_outputs is not None:
        return _outputs_to_text(final_outputs, response_field)
    # workflow_finished が無い場合はストリームされたテキストを返す
    return "".join(text_parts)


async def _run_chat(
    base: str,
    api_key: str,
    query: str,
    inputs: dict[str, Any],
    user: str,
    conversation_id: str,
    files: list[dict[str, Any]],
) -> tuple[str, str]:
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
                elif event == "error":
                    error = obj.get("message") or "unknown error"

    if error:
        return (f"Dify チャットフローでエラーが発生しました: {error}", new_conv_id)
    return ("".join(answer_parts), new_conv_id)


# ---------------------------------------------------------------------------
# Dify の入力スキーマ(/parameters) を 源内のフォーム定義(placeholder) に変換
# ---------------------------------------------------------------------------
def _convert_user_input_form(form: list[Any]) -> dict[str, Any]:
    """Dify の user_input_form を 源内 の placeholder(uiJson) 形式へ変換する。

    Dify のコンポーネント型 → 源内の type:
      text-input -> text, paragraph -> textarea, number -> number,
      select -> select(items), file / file-list -> file
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
    query_field = cfg.get("query_field") or "query"
    response_field = cfg.get("response_field")
    api_key = x_api_key or ""
    user = x_user_id or "open-genai"

    body = await request.json()
    inputs = body.get("inputs", body) or {}

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
            dify_inputs = _strip_meta(inputs)
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
            outputs = await _run_workflow(
                base, api_key, dify_inputs, user, response_field
            )
            return {"outputs": outputs}

        # ---- チャットフロー ----
        query = str(inputs.get(query_field) or inputs.get("question") or "").strip()
        if not query:
            return {"outputs": "メッセージ(query)が空です。入力してください。"}
        dify_inputs = _strip_meta(inputs, query_field, "question")
        conversation_id = _get_conversation_id(x_session_id or "")
        # 解決した入力変数へ。解決できなければメッセージ添付(sys.files)として送る。
        chat_files = all_file_refs
        if all_file_refs:
            file_var, is_list = await _resolve_file_var()
            if file_var:
                dify_inputs[file_var] = all_file_refs if is_list else all_file_refs[0]
                chat_files = []
        answer, new_conv_id = await _run_chat(
            base, api_key, query, dify_inputs, user, conversation_id, chat_files
        )
        if new_conv_id and x_session_id:
            _save_conversation_id(x_session_id, new_conv_id)
        return {"outputs": answer}
    except httpx.HTTPError as e:
        return {"outputs": f"Dify への接続でエラーが発生しました: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"outputs": f"処理中にエラーが発生しました: {e}"}
