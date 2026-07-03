"""監査ログ参照「AI アプリ」マイクロサービス（管理者限定）。

本サービス仕様書 8-(1)「管理者は利用者単位の利用状況/内容ログを確認できること」を、
源内(genai-web)を無改修のまま「AI アプリ(exApp)」として提供する。

- backend が書き込む監査DB(audit.db)を、backend と同じボリューム(backend_data)を
  共有して **読み取り専用接続(mode=ro)** で参照する。
- exApp 同期プロトコルに準拠:
    リクエスト: { "inputs": { "action": "search", "userId": ..., ... } }
    レスポンス: { "outputs": "<Markdown の検索結果>" }
- 管理者判定: backend が付与する `x-user-groups`(カンマ区切り)に SystemAdminGroup が
  含まれる場合のみ結果を返す。含まれない場合は権限エラーメッセージを返す。

このサービスは SELECT のみを行う（DB は mode=ro で開く）。
"""

from __future__ import annotations

import datetime as _dt
import os
import sqlite3
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from . import intauth

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
AUDIT_DB_PATH = os.environ.get("AUDIT_DB_PATH", "/data/audit.db")
ADMIN_GROUP = os.environ.get("AUDIT_ADMIN_GROUP", "SystemAdminGroup")

app = FastAPI(title="Open GENAI Audit Viewer App", version="0.1.0")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _is_admin(x_user_groups: str | None) -> bool:
    groups = [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]
    return ADMIN_GROUP in groups


@app.get("/health")
async def health() -> dict[str, Any]:
    exists = os.path.exists(AUDIT_DB_PATH)
    return {"status": "ok", "db": AUDIT_DB_PATH, "dbExists": exists}


def _connect_ro() -> sqlite3.Connection:
    """監査DBを読み取り専用で開く（WAL の -shm 参照のためボリュームは rw マウント）。"""
    uri = f"file:{AUDIT_DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _date_to_ms(value: str | None, *, end_of_day: bool = False) -> int | None:
    """YYYY-MM-DD を UTC epoch(ms) に変換する。不正/空なら None。"""
    if not value:
        return None
    value = value.strip()
    try:
        d = _dt.datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None
    if end_of_day:
        d = d + _dt.timedelta(days=1) - _dt.timedelta(milliseconds=1)
    return int(d.timestamp() * 1000)


def _cell(text: Any, limit: int = 80) -> str:
    """Markdown テーブルのセル用にエスケープ・短縮する。

    利用者入力（inputText/outputText 等）が管理者 UI でリンク・画像・生 HTML として
    描画されないよう、Markdown/HTML の特殊文字を無害化する（フィッシング対策）。
    """
    s = "" if text is None else str(text)
    s = s.replace("\r", " ").replace("\n", " ")
    # まず長さを制限（エスケープでバックスラッシュが増える前に）
    if len(s) > limit:
        s = s[:limit] + "…"
    # HTML を無効化
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Markdown のリンク/画像/強調/コード等を無効化（バックスラッシュエスケープ）
    for ch in ("\\", "`", "*", "_", "[", "]", "(", ")", "!", "|"):
        s = s.replace(ch, "\\" + ch)
    return s


def _fmt_ts(ts: Any) -> str:
    try:
        return (
            _dt.datetime.fromtimestamp(int(ts) / 1000, tz=_dt.timezone.utc)
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except (TypeError, ValueError):
        return str(ts)


def _query(inputs: dict[str, Any]) -> str:
    if not os.path.exists(AUDIT_DB_PATH):
        return "監査ログDBがまだ作成されていません（利用が記録されると生成されます）。"

    user_id = (inputs.get("userId") or "").strip()
    # 操作(action)は search/help、絞り込み対象は action_filter
    action = (inputs.get("action_filter") or "").strip()
    keyword = (inputs.get("q") or "").strip()
    ts_from = _date_to_ms(inputs.get("from_date"))
    ts_to = _date_to_ms(inputs.get("to_date"), end_of_day=True)
    try:
        limit = int(inputs.get("limit") or 50)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(limit, 500))

    where: list[str] = []
    params: list[Any] = []
    if user_id:
        where.append("userId = ?")
        params.append(user_id)
    if action and action != "all":
        where.append("action = ?")
        params.append(action)
    if ts_from is not None:
        where.append("ts >= ?")
        params.append(ts_from)
    if ts_to is not None:
        where.append("ts <= ?")
        params.append(ts_to)
    if keyword:
        where.append("(inputText LIKE ? OR outputText LIKE ?)")
        params.extend([f"%{keyword}%", f"%{keyword}%"])
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    with _connect_ro() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) AS c FROM audit_logs{clause}", params
        ).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM audit_logs{clause} ORDER BY ts DESC LIMIT ?",
            (*params, limit),
        ).fetchall()

    header = (
        f"## 監査ログ検索結果\n\n"
        f"- 一致 **{total}** 件（表示 {len(rows)} 件 / 上限 {limit}）\n"
    )
    if not rows:
        return header + "\n該当するログはありません。"

    lines = [
        header,
        "",
        "| 日時(UTC) | ユーザー | アクション | モデル | 入力(文字) | 出力(文字) | 内容(抜粋) |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        snippet = r["inputText"] or r["outputText"] or ""
        lines.append(
            "| {ts} | {user} | {action} | {model} | {ic} | {oc} | {snip} |".format(
                ts=_cell(_fmt_ts(r["ts"]), 20),
                user=_cell(r["userEmail"] or r["userId"], 32),
                action=_cell(r["action"], 20),
                model=_cell(r["model"], 20),
                ic=r["inputChars"] if r["inputChars"] is not None else "",
                oc=r["outputChars"] if r["outputChars"] is not None else "",
                snip=_cell(snippet, 60),
            )
        )
    lines.append("")
    lines.append(
        "> 内容の全文は管理API `GET /admin/audit-logs`（およびエクスポート）で取得できます。"
    )
    return "\n".join(lines)


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

    # backend 署名の検証（x-user-*/x-scope の偽装＝管理者機能バイパス対策）
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
    action = (inputs.get("action") or "search").strip()
    if action == "help":
        return {
            "outputs": (
                "## 監査ログ参照の使い方\n\n"
                "- **ユーザーID**: 特定ユーザー(sub/email)で絞り込み\n"
                "- **アクション**: `chat.message` `predict.stream` `exapp.invoke` "
                "`auth.login` `api.access` など\n"
                "- **キーワード**: 入力/出力内容の部分一致\n"
                "- **開始日/終了日**: `YYYY-MM-DD`（UTC）\n"
                "- **表示件数**: 1〜500\n"
            )
        }

    try:
        outputs = _query(inputs)
    except Exception as e:  # noqa: BLE001
        outputs = f"[監査ログの検索でエラーが発生しました] {e}"
    return {"outputs": outputs}
