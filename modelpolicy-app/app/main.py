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

import base64
import binascii
import json
import os
import time
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from . import intauth
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
    '  "teams": {"<teamId>": ["gemma3:27b"]}\n'
    '}'
)


def _as_bool(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "1", "yes", "on", "有効")


def _team_maps(x_teams: str | None) -> tuple[dict[str, str], dict[str, str]]:
    """backend が渡す全チーム(Base64化JSON [{id,name}]) から id→name, name→id を作る。"""
    id2name: dict[str, str] = {}
    name2id: dict[str, str] = {}
    if not x_teams:
        return id2name, name2id
    try:
        data = json.loads(base64.b64decode(x_teams).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
        return id2name, name2id
    if isinstance(data, list):
        for t in data:
            if isinstance(t, dict) and t.get("id"):
                tid = str(t["id"])
                name = str(t.get("name") or tid)
                id2name[tid] = name
                name2id[name] = tid
    return id2name, name2id


def _build_schema(
    policy: dict[str, Any],
    available_models: list[str],
    id2name: dict[str, str],
) -> dict[str, Any]:
    """OpenGENAI Form Spec v1: 現在ポリシーをプレフィルした構造化フォームを返す。

    利用可能モデルID一覧は backend が `x-available-models`、全チームは `x-teams` で渡す。
    チーム別許可は「チーム名: モデルID,...」で入出力する（内部は teamId で保持）。
    """
    set_vw = {"field": "operation", "in": ["set"]}
    avail = (
        "利用可能なモデルID: " + ", ".join(available_models)
        if available_models
        else "（利用可能なモデル一覧を取得できませんでした。IDを直接入力してください）"
    )
    team_lines = [
        f"{id2name.get(tid, tid)}: {','.join(models or [])}"
        for tid, models in (policy.get("teams") or {}).items()
    ]
    team_names = [n for n in id2name.values()]
    team_desc = (
        "1行に「チーム名: モデルID,モデルID」。対象チーム: " + ", ".join(team_names)
        if team_names
        else "チームがまだありません。先に「チーム管理」でチームを作成してください。"
    )
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
                    "confirm": "モデル利用ポリシーを上書き保存します。よろしいですか？",
                },
            ],
            "default_value": "view",
        },
        "enabled": {
            "type": "select",
            "title": "モデル利用制御",
            "items": [
                {"title": "有効（許可モデルのみ使用可）", "value": "true"},
                {"title": "無効（全モデル使用可）", "value": "false"},
            ],
            "default_value": "true" if policy.get("enabled") else "false",
            "visibleWhen": set_vw,
        },
        "default_models": {
            "type": "textarea",
            "title": "全ユーザー共通で許可するモデル（1行に1ID）",
            "desc": avail,
            "default_value": "\n".join(policy.get("default") or []),
            "visibleWhen": set_vw,
        },
        "team_rules": {
            "type": "textarea",
            "title": "チーム別の追加許可（1行に「チーム名: モデルID,モデルID」）",
            "desc": team_desc,
            "default_value": "\n".join(team_lines),
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
    x_available_models: str | None = Header(default=None),
    x_teams: str | None = Header(default=None),
) -> Any:
    """現在ポリシーをプレフィルした構造化フォーム定義を返す。"""
    err = _check_key(x_api_key)
    if err:
        return err
    if not intauth.verify(x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    if not _is_admin(x_user_groups):
        return {"placeholder": {}}
    models = [m.strip() for m in (x_available_models or "").split(",") if m.strip()]
    id2name, _ = _team_maps(x_teams)
    return {"placeholder": _build_schema(_read_policy(), models, id2name)}


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
    x_teams: str | None = Header(default=None),
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

    id2name, name2id = _team_maps(x_teams)
    body = await request.json()
    inputs = body.get("inputs", body)
    operation = (inputs.get("operation") or "view").strip().lower()

    if operation == "set":
        raw_json = (inputs.get("policy_json") or "").strip()
        unknown_teams: list[str] = []
        if raw_json:
            # 後方互換: 生JSON入力も引き続き受理
            policy, verr = parse_and_validate(raw_json)
        else:
            # 構造化フォーム入力（enabled/default_models/team_rules）から組み立て
            teams: dict[str, list[str]] = {}
            for line in (inputs.get("team_rules") or "").splitlines():
                line = line.strip()
                if not line or ":" not in line:
                    continue
                name, models = line.split(":", 1)
                name = name.strip()
                if not name:
                    continue
                # チーム名→ID解決（既に teamId が入力された場合はそのまま採用）
                tid = name2id.get(name) or (name if name in id2name else "")
                if not tid:
                    unknown_teams.append(name)
                    continue
                teams[tid] = [m.strip() for m in models.split(",") if m.strip()]
            built = {
                "enabled": _as_bool(inputs.get("enabled")),
                "default": [
                    m.strip()
                    for m in (inputs.get("default_models") or "").splitlines()
                    if m.strip()
                ],
                "teams": teams,
            }
            policy, verr = parse_and_validate(json.dumps(built, ensure_ascii=False))
        if verr:
            return {"outputs": f"設定エラー: {verr}\n\n記入例:\n```json\n{_EXAMPLE}\n```"}
        try:
            _write_policy(policy)
        except Exception as e:  # noqa: BLE001
            return {"outputs": f"[ポリシーの保存に失敗しました] {e}"}
        note = ""
        if unknown_teams:
            note = (
                "\n\n> 次のチーム名は見つからず無視しました: "
                + ", ".join(unknown_teams)
                + "（チーム管理のチーム名と一致させてください）。"
            )
        return {
            "outputs": "ポリシーを更新しました。\n\n" + render_policy(policy, id2name) + note
        }

    # view（既定）
    policy = _read_policy()
    return {
        "outputs": (
            render_policy(policy, id2name)
            + "\n\n---\n変更するには「操作」で **設定を保存** を選ぶと、"
            "現在の設定が入力欄にプレフィルされます。編集して実行すると保存されます。"
        )
    }
