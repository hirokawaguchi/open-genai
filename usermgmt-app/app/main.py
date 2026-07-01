"""利用者一括管理「AI アプリ」マイクロサービス（管理者限定）。

本サービス仕様書 6-(18)「管理者が利用者アカウントを発行/削除でき、CSV 等の
ファイルアップロードによる一括登録・更新・削除ができること」に対応する。
源内(genai-web)は無改修のまま「AI アプリ(exApp)」として提供する。

- 利用者アカウントは Keycloak(realm) で管理するため、Keycloak Admin REST API を叩く。
- exApp 同期プロトコル:
    リクエスト: { "inputs": { "operation": "dry_run|apply", "csv_text": "...",
                              "files": [ {files:[{filename,content(base64)}]} ] } }
    レスポンス: { "outputs": "<Markdown の処理レポート>" }
- 管理者判定: backend が付与する `x-user-groups` に SystemAdminGroup が必要。

CSV 見出し（別名可・大文字小文字問わず）:
    action(create/update/delete/upsert, 既定 upsert), username(必須), email,
    firstName, lastName, name, password, groups(; か , 区切り), enabled, temporary
"""

from __future__ import annotations

import base64
import os
from typing import Any

import httpx
from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from .kcadmin import parse_csv, plan_rows

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
ADMIN_GROUP = os.environ.get("AUDIT_ADMIN_GROUP", "SystemAdminGroup")

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://keycloak:8080").rstrip("/")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "open-genai")
KC_ADMIN = os.environ.get("KEYCLOAK_ADMIN", "admin")
KC_ADMIN_PASSWORD = os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "admin")
KC_ADMIN_CLIENT = os.environ.get("KEYCLOAK_ADMIN_CLIENT", "admin-cli")

app = FastAPI(title="Open GENAI User Management App", version="0.1.0")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _is_admin(x_user_groups: str | None) -> bool:
    groups = [g.strip() for g in (x_user_groups or "").split(",") if g.strip()]
    return ADMIN_GROUP in groups


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "keycloak": KEYCLOAK_URL, "realm": KEYCLOAK_REALM}


def _extract_csv(inputs: dict[str, Any]) -> str:
    """inputs.csv_text または添付ファイル(先頭)から CSV テキストを得る。"""
    text = (inputs.get("csv_text") or "").strip()
    if text:
        return text
    for entry in inputs.get("files") or []:
        for f in entry.get("files", []):
            content = f.get("content", "")
            if not content:
                continue
            try:
                return base64.b64decode(content).decode("utf-8", "ignore")
            except Exception:  # noqa: BLE001
                continue
    return ""


# ---------------------------------------------------------------------------
# Keycloak Admin API クライアント
# ---------------------------------------------------------------------------
async def _admin_token(client: httpx.AsyncClient) -> str:
    res = await client.post(
        f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": KC_ADMIN_CLIENT,
            "username": KC_ADMIN,
            "password": KC_ADMIN_PASSWORD,
        },
    )
    res.raise_for_status()
    return res.json()["access_token"]


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _find_user(client: httpx.AsyncClient, token: str, username: str) -> dict[str, Any] | None:
    res = await client.get(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
        params={"username": username, "exact": "true"},
        headers=_auth_headers(token),
    )
    res.raise_for_status()
    users = res.json()
    for u in users:
        if u.get("username") == username:
            return u
    return users[0] if users else None


async def _group_id(client: httpx.AsyncClient, token: str, name: str) -> str | None:
    res = await client.get(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/groups",
        params={"search": name},
        headers=_auth_headers(token),
    )
    res.raise_for_status()

    def _walk(groups: list[dict[str, Any]]) -> str | None:
        for g in groups:
            if g.get("name") == name:
                return g.get("id")
            sub = _walk(g.get("subGroups") or [])
            if sub:
                return sub
        return None

    return _walk(res.json())


async def _apply_groups(
    client: httpx.AsyncClient, token: str, user_id: str, groups: list[str]
) -> list[str]:
    notes: list[str] = []
    for name in groups:
        gid = await _group_id(client, token, name)
        if not gid:
            notes.append(f"グループ未検出:{name}")
            continue
        r = await client.put(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/groups/{gid}",
            headers=_auth_headers(token),
        )
        if r.status_code not in (204, 201):
            notes.append(f"グループ付与失敗:{name}({r.status_code})")
    return notes


async def _process(inputs: dict[str, Any]) -> str:
    csv_text = _extract_csv(inputs)
    if not csv_text:
        return "CSV が指定されていません（`csv_text` に貼り付けるか、CSV ファイルを添付してください）。"

    rows = parse_csv(csv_text)
    if not rows:
        return "CSV から有効な行を読み取れませんでした。見出し行（username 等）を確認してください。"

    plans = plan_rows(rows)
    apply = (inputs.get("operation") or "dry_run").strip().lower() == "apply"

    lines = [
        f"## 利用者一括管理 {'（適用）' if apply else '（ドライラン：変更なし）'}",
        "",
        "| # | username | action | 結果 | 備考 |",
        "| --- | --- | --- | --- | --- |",
    ]

    if not apply:
        for i, p in enumerate(plans, 1):
            result = "エラー" if p["error"] else "実行予定"
            note = p["error"] or f"groups={','.join(p['groups']) or '-'}"
            lines.append(f"| {i} | {p['username']} | {p['action']} | {result} | {note} |")
        lines.append("")
        lines.append("> ドライランです。実際に反映するには「操作」で **適用** を選んで再実行してください。")
        return "\n".join(lines)

    # apply: Keycloak へ反映
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            token = await _admin_token(client)
            for i, p in enumerate(plans, 1):
                username = p["username"]
                action = p["action"]
                if p["error"]:
                    lines.append(f"| {i} | {username} | {action} | スキップ | {p['error']} |")
                    continue
                try:
                    existing = await _find_user(client, token, username)
                    result, note = await _apply_one(client, token, p, existing)
                except httpx.HTTPStatusError as e:
                    result, note = "エラー", f"HTTP {e.response.status_code}"
                except Exception as e:  # noqa: BLE001
                    result, note = "エラー", str(e)
                lines.append(f"| {i} | {username} | {action} | {result} | {note} |")
    except Exception as e:  # noqa: BLE001
        return f"[Keycloak への接続/認証に失敗しました] {e}"

    return "\n".join(lines)


async def _apply_one(
    client: httpx.AsyncClient,
    token: str,
    plan: dict[str, Any],
    existing: dict[str, Any] | None,
) -> tuple[str, str]:
    action = plan["action"]
    rep = plan["rep"]
    groups = plan["groups"]

    if action == "delete":
        if not existing:
            return "スキップ", "対象なし"
        r = await client.delete(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{existing['id']}",
            headers=_auth_headers(token),
        )
        return ("削除", "") if r.status_code in (204, 200) else ("エラー", f"HTTP {r.status_code}")

    if action == "update" or (action == "upsert" and existing):
        if not existing:
            return "スキップ", "対象なし（update）"
        r = await client.put(
            f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{existing['id']}",
            json=rep,
            headers=_auth_headers(token),
        )
        if r.status_code not in (204, 200):
            return "エラー", f"更新失敗 HTTP {r.status_code}"
        notes = await _apply_groups(client, token, existing["id"], groups)
        return "更新", "; ".join(notes)

    # create または upsert(新規)
    if action == "update":
        return "スキップ", "対象なし"
    if existing:
        return "スキップ", "既に存在（create）"
    r = await client.post(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
        json=rep,
        headers=_auth_headers(token),
    )
    if r.status_code not in (201, 204):
        return "エラー", f"作成失敗 HTTP {r.status_code}"
    created = await _find_user(client, token, plan["username"])
    notes = await _apply_groups(client, token, created["id"], groups) if created else ["作成後IDの取得に失敗"]
    return "作成", "; ".join(notes)


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
    try:
        outputs = await _process(inputs)
    except Exception as e:  # noqa: BLE001
        outputs = f"[一括処理でエラーが発生しました] {e}"
    return {"outputs": outputs}
