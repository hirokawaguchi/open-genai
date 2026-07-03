"""禁止ワード/機密情報 入力制限「AI アプリ」マイクロサービス（管理者限定）。

本サービス仕様書 8-(8)「禁止ワードや機密情報の入力制限機能を有し、管理者は自由に
設定できること」に対応。源内(genai-web)無改修の管理者限定 exApp。

- ルールは `NGWORD_DB_PATH`(既定 /data/ngwords.db, backend_data 共有) に保存。
- 本サービスが**唯一のライター**。backend は同ファイルを読み取り専用で参照し、
  推論前段（/predict 系・AIアプリ）で入力を検査してブロックする。
- exApp 同期プロトコル:
    リクエスト: { "inputs": { "operation": "view|set", "rules_json": "..." } }
    レスポンス: { "outputs": "<Markdown>" }
- 管理者判定: backend が付与する `x-user-groups` に SystemAdminGroup が必要。
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from . import intauth
from .ngrules import parse_and_validate, render_rules

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
ADMIN_GROUP = os.environ.get("AUDIT_ADMIN_GROUP", "SystemAdminGroup")
NGWORD_DB_PATH = os.environ.get("NGWORD_DB_PATH", "/data/ngwords.db")

app = FastAPI(title="Open GENAI NG-Word App", version="0.1.0")

_DEFAULT: dict[str, Any] = {
    "enabled": False,
    "case_sensitive": False,
    "words": [],
    "patterns": [],
}


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _is_admin(x_user_groups: str | None) -> bool:
    groups = [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]
    return ADMIN_GROUP in groups


def _connect():
    import sqlite3

    os.makedirs(os.path.dirname(NGWORD_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(NGWORD_DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS ngword_rules ("
            " id INTEGER PRIMARY KEY CHECK (id = 1),"
            " rules TEXT NOT NULL,"
            " updatedDate TEXT NOT NULL)"
        )


def _read_rules() -> dict[str, Any]:
    try:
        with _connect() as conn:
            row = conn.execute("SELECT rules FROM ngword_rules WHERE id = 1").fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return dict(_DEFAULT)


def _write_rules(rules: dict[str, Any]) -> None:
    now = str(int(time.time() * 1000))
    with _connect() as conn:
        conn.execute(
            "INSERT INTO ngword_rules (id, rules, updatedDate) VALUES (1, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET rules = excluded.rules,"
            " updatedDate = excluded.updatedDate",
            (json.dumps(rules, ensure_ascii=False), now),
        )


@app.on_event("startup")
def _startup() -> None:
    try:
        _init_db()
    except Exception as e:  # noqa: BLE001
        print(f"[ngword] init 失敗: {e}")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "db": NGWORD_DB_PATH}


_EXAMPLE = (
    '{\n'
    '  "enabled": true,\n'
    '  "case_sensitive": false,\n'
    '  "words": ["禁止語の例"],\n'
    '  "patterns": ["\\\\d{12}"]\n'
    '}'
)


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "on", "有効", "する")


def _build_schema(rules: dict[str, Any]) -> dict[str, Any]:
    """OpenGENAI Form Spec v1: 現在ルールをプレフィルした構造化フォームを返す。"""
    set_vw = {"field": "operation", "in": ["set"]}
    return {
        "$version": "opengenai-form/1",
        "operation": {
            "type": "select",
            "title": "操作",
            "items": [
                {"title": "現在の設定を表示", "value": "view"},
                {
                    "title": "設定を保存",
                    "value": "set",
                    "confirm": "入力制限ルールを上書き保存します。よろしいですか？",
                },
            ],
            "default_value": "view",
        },
        "enabled": {
            "type": "select",
            "title": "入力制限",
            "items": [
                {"title": "有効（制限する）", "value": "true"},
                {"title": "無効（制限しない）", "value": "false"},
            ],
            "default_value": "true" if rules.get("enabled") else "false",
            "visibleWhen": set_vw,
        },
        "case_sensitive": {
            "type": "select",
            "title": "大文字小文字の区別",
            "items": [
                {"title": "区別しない", "value": "false"},
                {"title": "区別する", "value": "true"},
            ],
            "default_value": "true" if rules.get("case_sensitive") else "false",
            "visibleWhen": set_vw,
        },
        "words": {
            "type": "textarea",
            "title": "禁止ワード（1行に1語）",
            "desc": "入力に含まれるとブロックする語を改行区切りで指定します。",
            "default_value": "\n".join(rules.get("words") or []),
            "visibleWhen": set_vw,
        },
        "patterns": {
            "type": "textarea",
            "title": "機密情報パターン（1行に1正規表現）",
            "desc": "例: \\d{12}（12桁の数字）。改行区切りで複数指定できます。",
            "default_value": "\n".join(rules.get("patterns") or []),
            "visibleWhen": set_vw,
        },
    }


@app.get("/schema")
async def schema(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Any:
    """現在ルールをプレフィルした構造化フォーム定義を返す。"""
    err = _check_key(x_api_key)
    if err:
        return err
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    if not _is_admin(x_user_groups):
        return {"placeholder": {}}
    return {"placeholder": _build_schema(_read_rules())}


@app.post("/invoke")
async def invoke(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    if not _is_admin(x_user_groups):
        return {
            "outputs": (
                "この機能は**システム管理者のみ**が利用できます"
                "（SystemAdminGroup 所属が必要です）。"
            )
        }

    body = await request.json()
    inputs = body.get("inputs", body)
    operation = (inputs.get("operation") or "view").strip().lower()

    if operation == "set":
        raw_json = (inputs.get("rules_json") or "").strip()
        if raw_json:
            # 後方互換: 生JSON入力も引き続き受理
            rules, verr = parse_and_validate(raw_json)
        else:
            # 構造化フォーム入力（enabled/case_sensitive/words/patterns）から組み立て
            built = {
                "enabled": _as_bool(inputs.get("enabled")),
                "case_sensitive": _as_bool(inputs.get("case_sensitive")),
                "words": [w.strip() for w in (inputs.get("words") or "").splitlines() if w.strip()],
                "patterns": [
                    p.strip() for p in (inputs.get("patterns") or "").splitlines() if p.strip()
                ],
            }
            rules, verr = parse_and_validate(json.dumps(built, ensure_ascii=False))
        if verr:
            return {"outputs": f"設定エラー: {verr}\n\n記入例:\n```json\n{_EXAMPLE}\n```"}
        try:
            _write_rules(rules)
        except Exception as e:  # noqa: BLE001
            return {"outputs": f"[ルールの保存に失敗しました] {e}"}
        return {"outputs": "入力制限ルールを更新しました。\n\n" + render_rules(rules)}

    rules = _read_rules()
    return {
        "outputs": (
            render_rules(rules)
            + "\n\n---\n変更するには「操作」で **設定を保存** を選ぶと、"
            "現在の設定が入力欄にプレフィルされます。編集して実行すると保存されます。"
        )
    }
