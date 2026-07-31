"""利用者一括管理「AI アプリ」マイクロサービス（管理者限定）。

本サービス仕様書 6-(18)「管理者が利用者アカウントを発行/削除でき、CSV 等の
ファイルアップロードによる一括登録・更新・削除ができること」に対応する。
源内(genai-web)は無改修のまま「AI アプリ(exApp)」として提供する。

- 利用者アカウントは Keycloak(realm) で管理するため、Keycloak Admin REST API を叩く。
- exApp 同期プロトコル:
    リクエスト: { "inputs": { "operation": "list|dry_run|apply", "csv_text": "...",
                              "search": "...",
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

from . import intauth
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


def _md_cell(value: Any) -> str:
    """Markdown 表セル用にパイプ・改行を無害化する。"""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ").replace("\r", "").strip()


async def _user_groups(
    client: httpx.AsyncClient, token: str, user_id: str
) -> list[str]:
    res = await client.get(
        f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users/{user_id}/groups",
        headers=_auth_headers(token),
    )
    res.raise_for_status()
    names: list[str] = []
    for g in res.json() or []:
        name = (g.get("name") or "").strip()
        if name:
            names.append(name)
    return names


def _coerce_limit(value: Any, default: int = 200) -> int:
    try:
        limit = int(value or default)
    except (TypeError, ValueError):
        limit = default
    return max(1, min(limit, 1000))


async def _collect_users(search: str, limit: int) -> tuple[list[dict[str, Any]], bool]:
    """Keycloak から利用者を集めて構造化リストで返す。

    戻り値: (利用者リスト, 上限に達したか)。各要素は
    {id, username, email, name, groups[], enabled} を持つ。専用ページ(REST)と
    従来の Markdown 一覧(/invoke) の共通ソースとして使う。
    """
    limit = _coerce_limit(limit)
    page_size = 100
    raw: list[dict[str, Any]] = []
    users: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=60) as client:
        token = await _admin_token(client)
        first = 0
        while len(raw) < limit:
            params: dict[str, Any] = {
                "first": first,
                "max": min(page_size, limit - len(raw)),
            }
            if search:
                params["search"] = search
            res = await client.get(
                f"{KEYCLOAK_URL}/admin/realms/{KEYCLOAK_REALM}/users",
                params=params,
                headers=_auth_headers(token),
            )
            res.raise_for_status()
            batch = res.json() or []
            if not batch:
                break
            raw.extend(batch)
            if len(batch) < params["max"]:
                break
            first += len(batch)

        for u in raw:
            uid = u.get("id") or ""
            groups = await _user_groups(client, token, uid) if uid else []
            name = " ".join(
                x
                for x in [
                    (u.get("lastName") or "").strip(),
                    (u.get("firstName") or "").strip(),
                ]
                if x
            )
            users.append(
                {
                    "id": uid,
                    "username": u.get("username") or "",
                    "email": u.get("email") or "",
                    "name": name,
                    "groups": groups,
                    "enabled": bool(u.get("enabled", True)),
                }
            )
    return users, len(users) >= limit


async def _list_users(inputs: dict[str, Any]) -> str:
    """Keycloak の利用者一覧を Markdown 表で返す（読み取り専用・/invoke 後方互換）。"""
    search = (inputs.get("search") or "").strip()
    limit = _coerce_limit(inputs.get("limit"))
    try:
        users, limit_reached = await _collect_users(search, limit)
    except Exception as e:  # noqa: BLE001
        return f"[Keycloak への接続/認証に失敗しました] {e}"

    title = "## 利用者一覧"
    if search:
        title += f"（検索: `{_md_cell(search)}`）"
    lines = [
        title,
        "",
        f"件数: **{len(users)}**" + ("（上限に達しています）" if limit_reached else ""),
        "",
        "| # | username | email | 氏名 | groups | 状態 | id |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not users:
        lines.append("| - | （該当なし） |  |  |  |  |  |")
    else:
        for i, u in enumerate(users, 1):
            uid = u["id"]
            lines.append(
                f"| {i} | "
                + " | ".join(
                    [
                        _md_cell(u["username"]),
                        _md_cell(u["email"]),
                        _md_cell(u["name"]),
                        _md_cell(",".join(u["groups"]) if u["groups"] else "-"),
                        "有効" if u["enabled"] else "無効",
                        _md_cell(uid[:8] + "…" if len(uid) > 8 else uid),
                    ]
                )
                + " |"
            )
    lines.append("")
    lines.append("> 読み取り専用です。作成・更新・削除は CSV のドライラン／適用を使ってください。")
    return "\n".join(lines)


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
    operation = (inputs.get("operation") or "list").strip().lower()
    if operation == "list":
        return await _list_users(inputs)

    csv_text = _extract_csv(inputs)
    if not csv_text:
        return "CSV が指定されていません（`csv_text` に貼り付けるか、CSV ファイルを添付してください）。"

    rows = parse_csv(csv_text)
    if not rows:
        return "CSV から有効な行を読み取れませんでした。見出し行（username 等）を確認してください。"

    plans = plan_rows(rows)
    apply = operation == "apply"

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
        results = await _apply_plans(plans)
    except Exception as e:  # noqa: BLE001
        return f"[Keycloak への接続/認証に失敗しました] {e}"
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r['username']} | {r['action']} | {r['result']} | {r['note']} |"
        )
    return "\n".join(lines)


async def _apply_plans(plans: list[dict[str, Any]]) -> list[dict[str, str]]:
    """計画を Keycloak へ反映し、行ごとの結果を構造化して返す。

    Markdown レポート(/invoke) と REST(/users/apply) の共通ソース。
    """
    results: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=120) as client:
        token = await _admin_token(client)
        for p in plans:
            username = p["username"]
            action = p["action"]
            if p["error"]:
                results.append(
                    {"username": username, "action": action, "result": "スキップ", "note": p["error"]}
                )
                continue
            try:
                existing = await _find_user(client, token, username)
                result, note = await _apply_one(client, token, p, existing)
            except httpx.HTTPStatusError as e:
                result, note = "エラー", f"HTTP {e.response.status_code}"
            except Exception as e:  # noqa: BLE001
                result, note = "エラー", str(e)
            results.append(
                {"username": username, "action": action, "result": result, "note": note}
            )
    return results


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


# ---------------------------------------------------------------------------
# 専用ページ(REST) 用エンドポイント
#
# 源内の汎用 exApp フォーム（Markdown 出力）では一覧・ドライラン・適用の往復が
# 直感的でないため、backend 経由の専用ページ(/admin/users)から叩く構造化 REST を提供する。
# 認証は /invoke と同じ（api-key + 内部署名 + SystemAdminGroup）。
# ---------------------------------------------------------------------------
def _verify_admin(request: Request) -> JSONResponse | None:
    h = request.headers
    err = _check_key(h.get("x-api-key"))
    if err:
        return err
    if not intauth.verify(
        h.get("x-user-id"),
        h.get("x-user-groups"),
        h.get("x-scope"),
        h.get("x-user-ts"),
        h.get("x-user-sig"),
        h.get("x-user-tags"),
    ):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    if not _is_admin(h.get("x-user-groups")):
        return JSONResponse(
            status_code=403,
            content={"error": "この機能はシステム管理者のみが利用できます（SystemAdminGroup 所属が必要です）"},
        )
    return None


def _plans_from_body(body: dict[str, Any]) -> tuple[JSONResponse | None, list[dict[str, Any]]]:
    csv_text = (body.get("csv_text") or "").strip()
    if not csv_text:
        return (
            JSONResponse(status_code=400, content={"error": "CSV が指定されていません（csv_text が空です）"}),
            [],
        )
    rows = parse_csv(csv_text)
    if not rows:
        return (
            JSONResponse(
                status_code=400,
                content={"error": "CSV から有効な行を読み取れませんでした。見出し行（username 等）を確認してください。"},
            ),
            [],
        )
    return None, plan_rows(rows)


def _plan_public(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "username": p["username"],
            "action": p["action"],
            "groups": p["groups"],
            "error": p["error"],
        }
        for p in plans
    ]


@app.get("/users")
async def list_users_api(request: Request) -> Any:
    err = _verify_admin(request)
    if err:
        return err
    qp = request.query_params
    search = (qp.get("search") or "").strip()
    limit = _coerce_limit(qp.get("limit"))
    try:
        users, limit_reached = await _collect_users(search, limit)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"error": f"Keycloak への接続/認証に失敗しました: {e}"}
        )
    return {"users": users, "count": len(users), "limitReached": limit_reached}


@app.post("/users/plan")
async def plan_users_api(request: Request) -> Any:
    err = _verify_admin(request)
    if err:
        return err
    body = await request.json()
    perr, plans = _plans_from_body(body)
    if perr:
        return perr
    rows = _plan_public(plans)
    return {"rows": rows, "count": len(rows)}


@app.post("/users/apply")
async def apply_users_api(request: Request) -> Any:
    err = _verify_admin(request)
    if err:
        return err
    body = await request.json()
    perr, plans = _plans_from_body(body)
    if perr:
        return perr
    try:
        results = await _apply_plans(plans)
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"error": f"Keycloak への接続/認証に失敗しました: {e}"}
        )
    return {"results": results, "count": len(results)}


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
    try:
        outputs = await _process(inputs)
    except Exception as e:  # noqa: BLE001
        outputs = f"[一括処理でエラーが発生しました] {e}"
    return {"outputs": outputs}
