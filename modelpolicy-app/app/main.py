"""モデル利用制御「AI アプリ」マイクロサービス（管理者限定）。

本サービス仕様書 6-(5)「複数の LLM を提供する場合、利用者によって使用できる LLM を
管理者で自由に設定できること」に対応。源内(genai-web)無改修の管理者限定 exApp。

- ポリシーは `POLICY_DB_PATH`(既定 /data/policy.db, backend_data 共有) に保存。
- 本サービスが**唯一のライター**。backend は同ファイルを読み取り専用で参照して
  predict 系の利用可否を強制する（単一ライターでロック競合を回避）。
- exApp 同期プロトコル:
    リクエスト: { "inputs": { "operation": "view|set", "policy_json": "..." } }
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

from .policystore import parse_and_validate, render_policy

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
ADMIN_GROUP = os.environ.get("AUDIT_ADMIN_GROUP", "SystemAdminGroup")
POLICY_DB_PATH = os.environ.get("POLICY_DB_PATH", "/data/policy.db")

app = FastAPI(title="Open GENAI Model Policy App", version="0.1.0")

_DEFAULT_POLICY: dict[str, Any] = {"enabled": False, "default": [], "groups": {}}


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _is_admin(x_user_groups: str | None) -> bool:
    groups = [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]
    return ADMIN_GROUP in groups


def _connect():
    import sqlite3

    os.makedirs(os.path.dirname(POLICY_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(POLICY_DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def _init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS model_policy ("
            " id INTEGER PRIMARY KEY CHECK (id = 1),"
            " policy TEXT NOT NULL,"
            " updatedDate TEXT NOT NULL)"
        )


def _read_policy() -> dict[str, Any]:
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT policy FROM model_policy WHERE id = 1"
            ).fetchone()
        if row and row[0]:
            data = json.loads(row[0])
            if isinstance(data, dict):
                return data
    except Exception:  # noqa: BLE001
        pass
    return dict(_DEFAULT_POLICY)


def _write_policy(policy: dict[str, Any]) -> None:
    now = str(int(time.time() * 1000))
    with _connect() as conn:
        conn.execute(
            "INSERT INTO model_policy (id, policy, updatedDate) VALUES (1, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET policy = excluded.policy,"
            " updatedDate = excluded.updatedDate",
            (json.dumps(policy, ensure_ascii=False), now),
        )


@app.on_event("startup")
def _startup() -> None:
    try:
        _init_db()
    except Exception as e:  # noqa: BLE001
        print(f"[modelpolicy] init 失敗: {e}")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "db": POLICY_DB_PATH}


_EXAMPLE = (
    '{\n'
    '  "enabled": true,\n'
    '  "default": ["gpt-oss:20b"],\n'
    '  "groups": {"PowerUsers": ["gemma3:27b"]}\n'
    '}'
)


@app.post("/invoke")
async def invoke(
    request: Request,
    x_api_key: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err
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
        policy, verr = parse_and_validate(inputs.get("policy_json") or "")
        if verr:
            return {"outputs": f"設定エラー: {verr}\n\n記入例:\n```json\n{_EXAMPLE}\n```"}
        try:
            _write_policy(policy)
        except Exception as e:  # noqa: BLE001
            return {"outputs": f"[ポリシーの保存に失敗しました] {e}"}
        return {
            "outputs": "ポリシーを更新しました。\n\n" + render_policy(policy)
        }

    # view（既定）
    policy = _read_policy()
    return {
        "outputs": (
            render_policy(policy)
            + "\n\n---\n設定するには「操作」で **設定** を選び、`ポリシーJSON` に記入例の形式で入力してください:\n"
            + f"```json\n{_EXAMPLE}\n```"
        )
    }
