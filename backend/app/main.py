"""Open GENAI ローカルバックエンド (FastAPI)。

デジタル庁 源内 Web (genai-web) が呼び出すクラウド API
(genU API / Team Access Control API / Lambda ストリーム) を、
ローカル LLM (Ollama) 向けに最小実装で代替する。

- 認証は行わない（ローカル前提。フロント側でダミー化済み）。
- チャット履歴は SQLite に保存。
- チーム / AI アプリ (exApp) 系はローカルでは未対応のため空応答を返す。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import FastAPI, Header, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from . import audit, auth, llm, policy, storage, teams_store

# ファイル添付の保存先と、ブラウザから見たバックエンドの公開 URL
FILES_DIR = os.environ.get("FILES_DIR", "/data/files")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")

# ログイン後に戻るフロントエンド URL
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# 認証不要のパス（プレフィックス一致）
PUBLIC_PATH_PREFIXES = (
    "/health",
    "/auth/",
    "/files/",  # 添付ファイルの PUT/GET（img タグ等が Authorization を付けられないため）
    "/docs",
    "/openapi.json",
    "/redoc",
)

# RAG「AI アプリ」連携先（外部マイクロサービス）
RAG_APP_URL = os.environ.get("RAG_APP_URL", "http://rag-app:8001/invoke")
RAG_API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")

# 監査ログ参照「AI アプリ」連携先（管理者限定）
AUDIT_APP_URL = os.environ.get("AUDIT_APP_URL", "http://audit-app:8005/invoke")

# 利用者一括管理「AI アプリ」連携先（管理者限定）
USERMGMT_APP_URL = os.environ.get("USERMGMT_APP_URL", "http://usermgmt-app:8006/invoke")

# モデル利用制御「AI アプリ」連携先（管理者限定）
MODELPOLICY_APP_URL = os.environ.get(
    "MODELPOLICY_APP_URL", "http://modelpolicy-app:8007/invoke"
)

# 管理者(SystemAdminGroup)のみに一覧表示・実行を許可する exApp
ADMIN_ONLY_EXAPP_IDS = {"audit", "usermgmt", "modelpolicy"}

COMMON_TEAM_ID = teams_store.COMMON_TEAM_ID

_RAG_FORM = (
    '{'
    '"question":{"type":"text","title":"質問",'
    '"desc":"知識ベースへの質問を入力（管理操作のときは空でも可）。"},'
    '"files":{"type":"file","title":"参照ドキュメント（任意）",'
    '"desc":"PDF/Word/Excel/テキスト等。下の「添付ファイルの扱い」で保存方法を選べます。",'
    '"accept":".pdf,.docx,.xlsx,.txt,.md,.csv,.html,.json","multiple":true},'
    '"folder":{"type":"text","title":"フォルダ（任意）",'
    '"desc":"階層はスラッシュ区切り（例 総務/例規）。指定すると配下のみを対象にします。"},'
    '"store_mode":{"type":"radio","title":"添付ファイルの扱い",'
    '"items":[{"title":"知識ベースに登録（永続）","value":"permanent"},'
    '{"title":"この質問だけで使う（一時）","value":"ephemeral"}],'
    '"default_value":"permanent"},'
    '"top_k":{"type":"number","title":"参照件数","desc":"検索する関連箇所の数",'
    '"default_value":4,"min":1,"max":10},'
    '"action":{"type":"select","title":"操作",'
    '"desc":"通常は「質問する」。フォルダ/知識ベースの管理も行えます。",'
    '"items":[{"title":"質問する","value":"ask"},'
    '{"title":"登録済みの出典を一覧","value":"list_sources"},'
    '{"title":"フォルダ一覧","value":"list_folders"},'
    '{"title":"フォルダ作成（管理者）","value":"create_folder"},'
    '{"title":"フォルダ権限設定（管理者）","value":"set_folder_acl"},'
    '{"title":"フォルダ削除（管理者）","value":"delete_folder"},'
    '{"title":"指定した出典を削除（管理者）","value":"delete_source"},'
    '{"title":"知識ベースを全消去（管理者）","value":"clear"}],'
    '"default_value":"ask"},'
    '"groups":{"type":"text","title":"アクセス許可グループ",'
    '"desc":"フォルダ作成/権限設定時に、; か , 区切りで許可グループを指定（空=制限なし）。"},'
    '"source":{"type":"text","title":"削除する出典名",'
    '"desc":"「指定した出典を削除」を選んだ場合に、一覧に出る出典名を入力してください。"}'
    '}'
)

# 共通チームに既定で登録する RAG アプリ
RAG_SEED: dict[str, Any] = {
    "exAppId": "rag",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "ローカル RAG（ナレッジ検索）",
    "endpoint": RAG_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _RAG_FORM,
    "description": "添付・登録したドキュメントを根拠に、出典付きで回答するローカル RAG アプリです。",
    "howToUse": (
        "## 使い方\n\n"
        "質問を入力して実行すると、知識ベースを検索し、関連箇所を根拠に回答します。\n\n"
        "- 「参照ドキュメント」に PDF/Word/Excel/テキスト等を添付できます。\n"
        "- 「添付ファイルの扱い」で **知識ベースに登録（永続）** か **この質問だけで使う（一時）** を選べます。\n"
        "- 「操作」で知識ベースの管理ができます: 出典の一覧 / 出典の削除（管理者）/ 全消去（管理者）。\n"
        "- 同一内容のチャンクは重複登録されません（重複排除）。\n"
        "- 回答には出典番号が付きます。埋め込みは `mxbai-embed-large`、検索は Qdrant です。"
    ),
    "copyable": False,
    "status": "published",
}

# 文字起こし(Whisper) AI アプリ
WHISPER_APP_URL = os.environ.get("WHISPER_APP_URL", "http://whisper-app:8002/invoke")
_WHISPER_FORM = (
    '{'
    '"audio":{"type":"file","title":"音声ファイル",'
    '"desc":"文字起こしする音声を添付してください。",'
    '"accept":"audio/*,.mp3,.wav,.m4a,.aac,.flac,.ogg","multiple":false,"required":true},'
    '"language":{"type":"select","title":"言語",'
    '"items":[{"title":"自動判定","value":"auto"},{"title":"日本語","value":"ja"},'
    '{"title":"英語","value":"en"}],"default_value":"auto"}'
    '}'
)
WHISPER_SEED: dict[str, Any] = {
    "exAppId": "whisper",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "文字起こし（ローカル Whisper）",
    "endpoint": WHISPER_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _WHISPER_FORM,
    "description": "音声ファイルをローカルの Whisper で文字起こしします（タイムスタンプ付き）。",
    "howToUse": (
        "## 使い方\n\n"
        "音声ファイルを添付して実行すると、文字起こし結果を返します。\n\n"
        "- 実行環境はローカルの faster-whisper（クラウド非依存）です。\n"
        "- 言語は自動判定できます（日本語/英語の明示指定も可）。"
    ),
    "copyable": False,
    "status": "published",
}

# 画像生成(Stable Diffusion) AI アプリ
SD_APP_URL = os.environ.get("SD_APP_URL", "http://sd-app:8003/invoke")
_SD_FORM = (
    '{'
    '"prompt":{"type":"textarea","title":"プロンプト",'
    '"desc":"生成したい画像の説明（英語推奨）","required":true},'
    '"negative_prompt":{"type":"textarea","title":"ネガティブプロンプト",'
    '"desc":"避けたい要素（任意）"},'
    '"steps":{"type":"number","title":"ステップ数","default_value":20,"min":1,"max":50},'
    '"size":{"type":"select","title":"画像サイズ",'
    '"items":[{"title":"512x512","value":"512"},{"title":"768x768","value":"768"}],'
    '"default_value":"512"}'
    '}'
)
SD_SEED: dict[str, Any] = {
    "exAppId": "sd",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "画像生成（Stable Diffusion）",
    "endpoint": SD_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _SD_FORM,
    "description": "プロンプトから画像を生成します（ホストの Stable Diffusion サーバを利用）。",
    "howToUse": (
        "## 使い方\n\n"
        "プロンプトを入力して実行すると画像を生成します。\n\n"
        "- ホストで AUTOMATIC1111 互換 API(`/sdapi/v1/txt2img`) を起動しておく必要があります。\n"
        "- 既定の接続先はホストの `:7860` です（`SD_API_URL` で変更可）。\n"
        "- 生成は GPU のあるホスト側（または Linux+NVIDIA のコンテナ）で実行します。"
    ),
    "copyable": False,
    "status": "published",
}

# 監査ログ参照(Audit) AI アプリ（管理者限定）
_AUDIT_FORM = (
    '{'
    '"action":{"type":"select","title":"操作",'
    '"items":[{"title":"検索","value":"search"},{"title":"使い方","value":"help"}],'
    '"default_value":"search"},'
    '"userId":{"type":"text","title":"ユーザーID（任意）",'
    '"desc":"特定ユーザー(sub または email)で絞り込み。"},'
    '"action_filter":{"type":"select","title":"アクション種別（任意）",'
    '"items":[{"title":"すべて","value":"all"},'
    '{"title":"チャットメッセージ","value":"chat.message"},'
    '{"title":"推論ストリーム","value":"predict.stream"},'
    '{"title":"AIアプリ実行","value":"exapp.invoke"},'
    '{"title":"ログイン","value":"auth.login"},'
    '{"title":"APIアクセス","value":"api.access"}],'
    '"default_value":"all"},'
    '"q":{"type":"text","title":"キーワード（任意）",'
    '"desc":"入力/出力内容の部分一致。"},'
    '"from_date":{"type":"text","title":"開始日（任意）","desc":"YYYY-MM-DD（UTC）"},'
    '"to_date":{"type":"text","title":"終了日（任意）","desc":"YYYY-MM-DD（UTC）"},'
    '"limit":{"type":"number","title":"表示件数","default_value":50,"min":1,"max":500}'
    '}'
)
AUDIT_SEED: dict[str, Any] = {
    "exAppId": "audit",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "監査ログ参照（管理者限定）",
    "endpoint": AUDIT_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _AUDIT_FORM,
    "description": "利用状況/内容の監査ログを検索します（システム管理者のみ）。",
    "howToUse": (
        "## 使い方\n\n"
        "システム管理者向けの監査ログ参照アプリです。\n\n"
        "- ユーザーID・アクション種別・キーワード・期間で絞り込めます。\n"
        "- 内容の全文取得やエクスポートは管理API `GET /admin/audit-logs` を利用します。\n"
        "- 本アプリは監査ログDBを読み取り専用で参照します（改変しません）。"
    ),
    "copyable": False,
    "status": "published",
}

# 利用者一括管理(User Management) AI アプリ（管理者限定）
_USERMGMT_FORM = (
    '{'
    '"operation":{"type":"select","title":"操作",'
    '"desc":"まずドライランで内容を確認し、問題なければ適用してください。",'
    '"items":[{"title":"ドライラン（変更しない）","value":"dry_run"},'
    '{"title":"適用（Keycloakに反映）","value":"apply"}],'
    '"default_value":"dry_run"},'
    '"files":{"type":"file","title":"CSVファイル",'
    '"desc":"見出し: action,username,email,firstName,lastName,name,password,groups,enabled",'
    '"accept":".csv,.txt","multiple":false},'
    '"csv_text":{"type":"textarea","title":"CSV（貼り付け・任意）",'
    '"desc":"ファイルの代わりにCSVを直接貼り付けても可。"}'
    '}'
)
USERMGMT_SEED: dict[str, Any] = {
    "exAppId": "usermgmt",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "利用者一括管理（管理者限定）",
    "endpoint": USERMGMT_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _USERMGMT_FORM,
    "description": "CSV で利用者アカウントを一括登録/更新/削除します（システム管理者のみ）。",
    "howToUse": (
        "## 使い方\n\n"
        "システム管理者向けの利用者一括管理アプリです（Keycloak と連携）。\n\n"
        "1. CSV を用意します。見出し例:\n"
        "   `action,username,email,name,password,groups,enabled`\n"
        "   - action: `create`/`update`/`delete`/`upsert`（既定 upsert）\n"
        "   - groups: `;` か `,` 区切り（例 `UserGroup;SystemAdminGroup`）\n"
        "2. まず「ドライラン」で対象と操作内容を確認します（変更されません）。\n"
        "3. 問題なければ「適用」で Keycloak に反映します。\n\n"
        "> パスワード列を含む CSV の取り扱いに注意してください。"
    ),
    "copyable": False,
    "status": "published",
}

# モデル利用制御(Model Policy) AI アプリ（管理者限定）
_MODELPOLICY_FORM = (
    '{'
    '"operation":{"type":"select","title":"操作",'
    '"items":[{"title":"現在の設定を表示","value":"view"},'
    '{"title":"設定を更新","value":"set"}],"default_value":"view"},'
    '"policy_json":{"type":"textarea","title":"ポリシーJSON（更新時のみ）",'
    '"desc":"例: {\\"enabled\\":true,\\"default\\":[\\"gpt-oss:20b\\"],'
    '\\"groups\\":{\\"PowerUsers\\":[\\"gemma3:27b\\"]}}"}'
    '}'
)
MODELPOLICY_SEED: dict[str, Any] = {
    "exAppId": "modelpolicy",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "モデル利用制御（管理者限定）",
    "endpoint": MODELPOLICY_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _MODELPOLICY_FORM,
    "description": "利用者/グループごとに使用可能な LLM を管理者が設定します（システム管理者のみ）。",
    "howToUse": (
        "## 使い方\n\n"
        "利用可能な LLM をグループ単位で制御します（backend が推論時に強制）。\n\n"
        "- 「現在の設定を表示」で有効/無効・許可モデルを確認できます。\n"
        "- 「設定を更新」で `ポリシーJSON` を保存します。\n"
        "  - `enabled`: 制御の有効/無効（無効時は全モデル利用可）\n"
        "  - `default`: 全ユーザー共通で許可するモデルID\n"
        "  - `groups`: グループ名→許可モデルID配列\n"
        "- システム管理者は常に全モデル利用可能です。\n"
    ),
    "copyable": False,
    "status": "published",
}

EXAPP_SEEDS = [RAG_SEED, WHISPER_SEED, SD_SEED, AUDIT_SEED, USERMGMT_SEED, MODELPOLICY_SEED]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 認可ヘルパ（JWT クレームから現在ユーザーを取得）
# ---------------------------------------------------------------------------
def _claims_from_request(request: Request) -> dict[str, Any]:
    authz = request.headers.get("authorization", "")
    if authz.startswith("Bearer "):
        try:
            return auth.verify_token(authz[7:])
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _user_id(claims: dict[str, Any]) -> str:
    return claims.get("sub") or claims.get("email") or ""


def _is_system_admin(claims: dict[str, Any]) -> bool:
    return "SystemAdminGroup" in (claims.get("groups") or [])


def _forbidden(msg: str = "この操作を行う権限がありません") -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": msg})


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    """監査ログ用に、メッセージ列から最後のユーザー発話のテキストを取り出す。"""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            content = m.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _model_denied(claims: dict[str, Any], model: Any) -> str | None:
    """利用ポリシー上、指定モデルが不許可なら理由メッセージを返す（許可なら None）。"""
    model_id = llm.resolve_model(model if isinstance(model, dict) else None)
    groups = claims.get("groups") or []
    if policy.is_model_allowed(groups, _is_system_admin(claims), model_id):
        return None
    return f"モデル「{model_id}」の利用は許可されていません（管理者にお問い合わせください）。"

app = FastAPI(title="Open GENAI Local Backend", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    storage.init_db()
    teams_store.init_db(seed_exapps=EXAPP_SEEDS)
    audit.start()
    os.makedirs(FILES_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 認証ミドルウェア（ブラウザ向け API を JWT で保護）
# ---------------------------------------------------------------------------
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or any(
        path.startswith(p) for p in PUBLIC_PATH_PREFIXES
    ):
        return await call_next(request)

    authz = request.headers.get("authorization", "")
    if authz.startswith("Bearer "):
        try:
            auth.verify_token(authz[7:])
            return await call_next(request)
        except Exception:  # noqa: BLE001 - トークン不正は 401 に集約
            pass

    return JSONResponse(
        status_code=401,
        content={"error": "unauthorized"},
        headers={"Access-Control-Allow-Origin": "*"},
    )


# ---------------------------------------------------------------------------
# 監査アクセスログ（全 API 共通）。auth_middleware より後に登録 = 外側で動作。
# ---------------------------------------------------------------------------
@app.middleware("http")
async def audit_access_middleware(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
    started = time.monotonic()
    response = await call_next(request)
    try:
        audit.record_access(
            request,
            status=response.status_code,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception:  # noqa: BLE001 - ログ失敗は本処理に影響させない
        pass
    return response


# ---------------------------------------------------------------------------
# SAML 認証 (backend = SAML SP)
# ---------------------------------------------------------------------------
async def _prepare_saml_request(request: Request) -> dict[str, Any]:
    form: dict[str, Any] = {}
    if request.method == "POST":
        raw = await request.form()
        form = {k: v for k, v in raw.items()}
    host = request.headers.get("host", "localhost:8000")
    server_port = host.split(":")[1] if ":" in host else (
        "443" if request.url.scheme == "https" else "80"
    )
    return {
        "https": "on" if request.url.scheme == "https" else "off",
        "http_host": host,
        "server_port": server_port,
        "script_name": request.url.path,
        "get_data": dict(request.query_params),
        "post_data": form,
    }


@app.get("/auth/login")
async def auth_login(request: Request) -> Response:
    relay = request.query_params.get("redirect") or FRONTEND_URL
    try:
        req = await _prepare_saml_request(request)
        saml_auth = auth.build_saml_auth(req)
        sso_url = saml_auth.login(return_to=relay)
    except Exception as e:  # noqa: BLE001
        auth.reset_settings_cache()
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "IdP(Keycloak) に接続できません。起動直後の可能性があります。"
                    f"少し待って再試行してください: {e}"
                )
            },
        )
    return RedirectResponse(sso_url, status_code=303)


@app.post("/auth/saml/acs")
async def auth_acs(request: Request) -> Response:
    req = await _prepare_saml_request(request)
    saml_auth = auth.build_saml_auth(req)
    saml_auth.process_response()
    errors = saml_auth.get_errors()
    relay = req["post_data"].get("RelayState") or FRONTEND_URL
    target = relay if str(relay).startswith("http") else FRONTEND_URL

    if errors or not saml_auth.is_authenticated():
        reason = saml_auth.get_last_error_reason() or ",".join(errors)
        print(f"[auth] SAML 検証失敗: {reason}")
        audit.record(
            request, action="auth.login", status=401, output_text=f"SAML検証失敗: {reason}"
        )
        return RedirectResponse(f"{FRONTEND_URL}/auth-error", status_code=303)

    attrs = saml_auth.get_attributes()
    nameid = saml_auth.get_nameid()
    email = (attrs.get("email") or [nameid])[0]
    name = (attrs.get("name") or [email])[0]
    groups = list(attrs.get("groups") or [])
    session_index = saml_auth.get_session_index()

    audit.record(
        request,
        action="auth.login",
        status=200,
        user_id=nameid,
        user_email=email,
        user_name=name,
        groups=groups,
    )

    # ローカル DB 上でいずれかのチームの管理者なら TeamAdminGroup を付与
    # （Keycloak 側でグループを手動設定しなくてもチーム管理 UI が使えるようにする）
    if teams_store.user_admins_any_team(nameid) and "TeamAdminGroup" not in groups:
        groups.append("TeamAdminGroup")

    token = auth.mint_token(
        sub=nameid,
        email=email,
        name=name,
        groups=groups,
        session_index=session_index,
    )
    return RedirectResponse(f"{target.rstrip('/')}/#token={token}", status_code=303)


@app.get("/auth/saml/metadata")
async def auth_metadata() -> Response:
    try:
        metadata = auth.get_sp_metadata()
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"error": str(e)})
    return Response(content=metadata, media_type="text/xml")


@app.get("/auth/me")
async def auth_me(authorization: str | None = Header(default=None)) -> JSONResponse:
    if not authorization or not authorization.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    try:
        claims = auth.verify_token(authorization[7:])
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return JSONResponse(content=claims)


@app.get("/auth/logout")
async def auth_logout(
    request: Request, token: str | None = Query(default=None)
) -> Response:
    """SAML シングルログアウト(SLO) を開始し、Keycloak のセッションも終了させる。

    token(JWT) から nameid / session_index を取り出して LogoutRequest を組み立てる。
    失敗時はローカルのみのログアウト（/signed-out）にフォールバックする。
    """
    return_to = f"{FRONTEND_URL}/signed-out"
    if token:
        try:
            claims = auth.verify_token(token)
            req = await _prepare_saml_request(request)
            saml_auth = auth.build_saml_auth(req)
            slo_url = saml_auth.logout(
                return_to=return_to,
                name_id=claims.get("sub"),
                session_index=claims.get("sidx"),
                name_id_format="urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
            )
            return RedirectResponse(slo_url, status_code=303)
        except Exception as e:  # noqa: BLE001
            print(f"[auth] SLO 開始に失敗、ローカルログアウトにフォールバック: {e}")
    return RedirectResponse(return_to, status_code=303)


@app.get("/auth/saml/sls")
async def auth_sls(request: Request) -> Response:
    """IdP からの SLO 応答/要求を処理し、サインアウト完了画面へ戻す。"""
    req = await _prepare_saml_request(request)
    saml_auth = auth.build_saml_auth(req)
    try:
        saml_auth.process_slo(delete_session_cb=lambda: None)
    except Exception as e:  # noqa: BLE001
        print(f"[auth] SLO 応答処理エラー: {e}")
    return RedirectResponse(f"{FRONTEND_URL}/signed-out", status_code=303)


# ---------------------------------------------------------------------------
# ヘルス / メタ
# ---------------------------------------------------------------------------
@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "models": await llm.list_models()}


# ---------------------------------------------------------------------------
# チャット履歴 (genU API)
# ---------------------------------------------------------------------------
@app.post("/chats")
async def create_chat(request: Request) -> dict[str, Any]:
    user_id = _user_id(_claims_from_request(request))
    return {"chat": storage.create_chat(user_id)}


@app.get("/chats")
async def list_chats(request: Request) -> dict[str, Any]:
    user_id = _user_id(_claims_from_request(request))
    return {"data": storage.list_chats(user_id), "lastEvaluatedKey": None}


@app.get("/chats/{chat_id}")
async def find_chat(chat_id: str, request: Request) -> JSONResponse:
    user_id = _user_id(_claims_from_request(request))
    chat = storage.find_chat(chat_id, user_id)
    if not chat:
        return JSONResponse(status_code=404, content={"message": "chat not found"})
    return JSONResponse(content={"chat": chat})


@app.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request) -> JSONResponse:
    user_id = _user_id(_claims_from_request(request))
    ok = storage.delete_chat(chat_id, user_id)
    if not ok:
        return JSONResponse(status_code=404, content={"message": "chat not found"})
    return JSONResponse(content={})


@app.put("/chats/{chat_id}/title")
async def update_title(chat_id: str, request: Request) -> JSONResponse:
    user_id = _user_id(_claims_from_request(request))
    body = await request.json()
    chat = storage.update_title(chat_id, user_id, body.get("title", ""))
    if not chat:
        return JSONResponse(status_code=404, content={"message": "chat not found"})
    return JSONResponse(content={"chat": chat})


@app.get("/chats/{chat_id}/messages")
async def list_messages(chat_id: str, request: Request) -> dict[str, Any]:
    user_id = _user_id(_claims_from_request(request))
    return {"messages": storage.list_messages(chat_id, user_id)}


@app.post("/chats/{chat_id}/messages")
async def create_messages(chat_id: str, request: Request) -> JSONResponse:
    user_id = _user_id(_claims_from_request(request))
    body = await request.json()
    messages = body.get("messages", [])
    recorded = storage.create_messages(chat_id, user_id, messages)
    if recorded is None:
        return JSONResponse(status_code=404, content={"message": "chat not found"})
    # 監査ログ（内容ログ）: 確定メッセージを証跡として記録（messages テーブルとは独立）
    for m in messages:
        audit.record(
            request,
            action="chat.message",
            usecase=m.get("usecase") or "/chat",
            chatId=chat_id,
            input_text=m.get("content", "") if m.get("role") == "user" else "",
            output_text=m.get("content", "") if m.get("role") == "assistant" else "",
            model=m.get("llmType"),
        )
    return JSONResponse(content={"messages": recorded})


# ---------------------------------------------------------------------------
# 推論 (genU API / Lambda ストリーム代替)
# ---------------------------------------------------------------------------
@app.post("/predict")
async def predict(request: Request) -> Response:
    body = await request.json()
    denied = _model_denied(_claims_from_request(request), body.get("model"))
    if denied:
        return JSONResponse(status_code=403, content={"error": denied})
    text = await llm.chat_once(body.get("messages", []), body.get("model"))
    return JSONResponse(content=text)


def _clean_title(text: str) -> str:
    if not text or not text.strip():
        return ""
    # <output> 等の XML/HTML タグを除去
    cleaned = re.sub(r"<[^>]+>", "", text)
    # 1 行目だけ採用し、前後の引用符・空白を除去
    first_line = cleaned.strip().splitlines()[0] if cleaned.strip() else ""
    first_line = first_line.strip().strip('"').strip("'").strip("「」").strip()
    return first_line[:50]


@app.post("/predict/title")
async def predict_title(request: Request) -> str:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    body = await request.json()
    # 許可外モデルではタイトル生成もしない（空タイトルを返す）
    if _model_denied(claims, body.get("model")):
        return ""
    prompt = body.get("prompt", "")
    messages = [{"role": "user", "content": prompt}]
    raw = await llm.chat_once(messages, body.get("model"))
    title = _clean_title(raw)

    # クラウド版同様、生成したタイトルをサーバ側でチャットに保存する
    # （所有者のチャットのみ。update_title が所有者一致を強制する）
    chat = body.get("chat") or {}
    chat_id_raw = chat.get("chatId", "")
    chat_id = chat_id_raw.split("#")[1] if "#" in chat_id_raw else chat_id_raw
    if chat_id and title:
        storage.update_title(chat_id, user_id, title)

    return title


# ---------------------------------------------------------------------------
# システムプロンプト保存 (systemcontexts) — DynamoDB を SQLite で代替
# ---------------------------------------------------------------------------
@app.get("/systemcontexts")
async def list_system_contexts(request: Request) -> list[Any]:
    claims = _claims_from_request(request)
    return storage.list_system_contexts(_user_id(claims))


@app.post("/systemcontexts")
async def create_system_context(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    sc = storage.create_system_context(
        _user_id(claims),
        body.get("systemContextTitle", ""),
        body.get("systemContext", ""),
    )
    return JSONResponse(content={"systemContext": sc})


@app.put("/systemcontexts/{sc_id}/title")
async def update_system_context_title(sc_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    sc = storage.update_system_context_title(
        _user_id(claims), sc_id, body.get("title", "")
    )
    if not sc:
        return JSONResponse(status_code=404, content={"error": "見つかりません"})
    return JSONResponse(content={"systemContext": sc})


@app.delete("/systemcontexts/{sc_id}")
async def delete_system_context(sc_id: str, request: Request) -> dict[str, Any]:
    claims = _claims_from_request(request)
    storage.delete_system_context(_user_id(claims), sc_id)
    return {}


@app.post("/predict/stream")
async def predict_stream(request: Request) -> StreamingResponse:
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model")

    # 利用ポリシーで許可されていないモデルはブロック（エラー行を1件流して終了）
    denied = _model_denied(_claims_from_request(request), model)
    if denied:
        async def _blocked():
            yield json.dumps({"text": denied, "stopReason": "error"}, ensure_ascii=False) + "\n"

        return StreamingResponse(_blocked(), media_type="application/x-ndjson")

    generator = llm.chat_stream(messages, model)
    # 監査ログ（内容ログ）: 入力（最終ユーザー発話）と集約した出力を1件記録
    audited = audit.wrap_stream(
        generator,
        request,
        action="predict.stream",
        usecase="/chat",
        input_text=_last_user_text(messages),
        model=(model or {}).get("modelId") if isinstance(model, dict) else None,
    )
    return StreamingResponse(audited, media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# 監査ログ参照（システム管理者限定） — 8-(1) 管理者による利用状況/内容の確認
# ---------------------------------------------------------------------------
def _parse_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


@app.get("/admin/audit-logs")
async def list_audit_logs(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("監査ログの閲覧には管理者権限が必要です")
    qp = request.query_params
    result = audit.query(
        user_id=qp.get("userId") or None,
        action=qp.get("action") or None,
        ts_from=_parse_int(qp.get("from")),
        ts_to=_parse_int(qp.get("to")),
        q=qp.get("q") or None,
        limit=_parse_int(qp.get("limit")) or 100,
        offset=_parse_int(qp.get("offset")) or 0,
    )
    return JSONResponse(content=result)


@app.get("/models/allowed")
async def list_allowed_models(request: Request) -> JSONResponse:
    """現在のユーザーが利用可能なモデル ID を返す（unrestricted=true は無制限）。"""
    claims = _claims_from_request(request)
    allowed = policy.allowed_models(claims.get("groups") or [], _is_system_admin(claims))
    if allowed is None:
        return JSONResponse(content={"unrestricted": True, "models": []})
    return JSONResponse(content={"unrestricted": False, "models": sorted(allowed)})


@app.get("/admin/model-policy")
async def get_model_policy(request: Request) -> JSONResponse:
    """モデル利用ポリシーの現在値を返す（システム管理者限定・参照のみ）。

    設定変更は管理者限定 exApp「モデル利用制御」（modelpolicy-app）から行う。
    """
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("モデル利用ポリシーの閲覧には管理者権限が必要です")
    return JSONResponse(content=policy.get_policy())


@app.get("/admin/audit-logs/export")
async def export_audit_logs(request: Request) -> Response:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("監査ログのエクスポートには管理者権限が必要です")
    qp = request.query_params
    ts_from = _parse_int(qp.get("from"))
    ts_to = _parse_int(qp.get("to"))

    def _gen():
        yield from audit.iter_export(ts_from, ts_to)

    return StreamingResponse(
        _gen(),
        media_type="application/x-ndjson",
        headers={"Content-Disposition": "attachment; filename=audit-logs.jsonl"},
    )


# ---------------------------------------------------------------------------
# ファイル添付（クラウド版は S3 署名付き URL。ローカルではバックエンドに保存）
# ---------------------------------------------------------------------------
def _safe_path(key: str) -> str:
    """FILES_DIR 配下に収まる安全な絶対パスへ解決する（パストラバーサル防止）。"""
    full = os.path.normpath(os.path.join(FILES_DIR, key))
    if not full.startswith(os.path.abspath(FILES_DIR) + os.sep) and full != os.path.abspath(
        FILES_DIR
    ):
        raise ValueError("invalid path")
    return full


@app.post("/file/url")
async def get_upload_url(request: Request) -> str:
    """アップロード先 URL を発行する（源内 Web の署名付き URL 取得を代替）。"""
    body = await request.json()
    filename = body.get("filename") or f"file.{body.get('mediaFormat', 'bin')}"
    # ファイル名はそのまま使うとパス衝突するため UUID ディレクトリに格納する
    safe_name = os.path.basename(filename)
    key = f"{uuid.uuid4()}/{safe_name}"
    return f"{PUBLIC_BASE_URL}/files/{key}"


@app.put("/files/{key:path}")
async def put_file(key: str, request: Request) -> dict[str, Any]:
    full = _safe_path(key)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    data = await request.body()
    with open(full, "wb") as f:
        f.write(data)
    return {}


@app.get("/files/{key:path}")
async def get_file(key: str) -> FileResponse:
    full = _safe_path(key)
    if not os.path.isfile(full):
        return JSONResponse(status_code=404, content={"message": "file not found"})
    return FileResponse(full)


@app.delete("/file/{file_name:path}")
async def delete_file(file_name: str) -> dict[str, Any]:
    # file_name は "files/<uuid>/<name>" 形式（フロントが pathname から生成）
    key = file_name[len("files/") :] if file_name.startswith("files/") else file_name
    try:
        full = _safe_path(key)
        if os.path.isfile(full):
            os.remove(full)
    except ValueError:
        pass
    return None


# ---------------------------------------------------------------------------
# AI アプリ一覧 / 実行（横断, Team Access Control API）
# ---------------------------------------------------------------------------
def _health_url(endpoint: str) -> str:
    """AI アプリの endpoint(.../invoke) から /health の URL を導出する。"""
    if endpoint.endswith("/invoke"):
        return endpoint[: -len("/invoke")] + "/health"
    return endpoint.rstrip("/") + "/health"


async def _is_app_up(endpoint: str) -> bool:
    """AI アプリのマイクロサービスが起動・到達可能かを確認する。"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(_health_url(endpoint))
        return res.status_code == 200
    except httpx.HTTPError:
        return False


@app.get("/exapps")
async def list_exapps(request: Request) -> list[Any]:
    # ListExAppsResponse = Array<ExApp & { teamName }>
    # 起動していない(ヘルスチェック不通の) AI アプリは一覧から隠す。
    claims = _claims_from_request(request)
    is_admin = _is_system_admin(claims)
    candidates = teams_store.list_visible_exapps(_user_id(claims), is_admin)
    # 管理者限定 exApp（監査ログ参照 等）は非管理者の一覧から隠す
    if not is_admin:
        candidates = [
            a for a in candidates if a.get("exAppId") not in ADMIN_ONLY_EXAPP_IDS
        ]
    checks = await asyncio.gather(
        *[_is_app_up(a["endpoint"]) for a in candidates], return_exceptions=True
    )
    return [a for a, ok in zip(candidates, checks) if ok is True]


@app.post("/exapps/invoke")
async def invoke_exapp(request: Request) -> JSONResponse:
    """実行要求を、登録された AI アプリの endpoint へプロキシする。"""
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    body = await request.json()
    team_id = body.get("teamId", "")
    ex_app_id = body.get("exAppId", "")
    inputs = body.get("inputs", {})
    session_id = body.get("sessionId", "")

    app_def = teams_store.get_exapp(team_id, ex_app_id)
    if not app_def:
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})

    # 管理者限定 exApp（監査ログ参照 等）は非管理者の実行を拒否
    if ex_app_id in ADMIN_ONLY_EXAPP_IDS and not _is_system_admin(claims):
        return _forbidden("このアプリの実行には管理者権限が必要です")

    # 認可: 共通チーム or システム管理者 or 所属メンバー
    if (
        team_id != COMMON_TEAM_ID
        and not _is_system_admin(claims)
        and not teams_store.is_team_member(team_id, user_id)
    ):
        return _forbidden("このアプリを実行する権限がありません")

    started = _now_iso()
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            res = await client.post(
                app_def["endpoint"],
                json={"inputs": inputs},
                headers={
                    "x-api-key": app_def.get("apiKey", ""),
                    "x-user-id": user_id,
                    # AI アプリ側で管理操作の権限判定に使う
                    "x-user-groups": ",".join(claims.get("groups") or []),
                    # ナレッジのスコープ = AI アプリを所有するチーム(teamId)
                    "x-scope": team_id,
                    # AI アプリ固有の設定(JSON)。Dify 連携等で接続先の判別に使う
                    "x-app-config": app_def.get("config", "") or "",
                    # 会話継続(疑似チャット)用のセッション ID
                    "x-session-id": session_id,
                    "Content-Type": "application/json",
                },
            )
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502, content={"error": f"AI アプリに接続できませんでした: {e}"}
        )
    ended = _now_iso()

    if res.status_code != 200:
        return JSONResponse(
            status_code=502,
            content={"error": f"AI アプリの呼び出しに失敗しました (status: {res.status_code})"},
        )

    data = res.json()
    outputs = data.get("outputs", "")
    artifacts = data.get("artifacts")

    # 実行履歴を保存（会話継続「会話を続ける」や履歴表示で参照される）
    team = teams_store.get_team(team_id)
    try:
        teams_store.create_exapp_history(
            {
                "teamId": team_id,
                "teamName": team["teamName"] if team else "",
                "exAppId": ex_app_id,
                "exAppName": app_def.get("exAppName", ""),
                "userId": user_id,
                "inputs": inputs,
                "outputs": outputs,
                "status": "COMPLETED",
                "progress": "",
                "artifacts": artifacts,
                "sessionId": session_id or None,
            }
        )
    except Exception as e:  # noqa: BLE001 - 履歴保存失敗で実行結果は返す
        print(f"[exapps] 履歴の保存に失敗: {e}")

    # 監査ログ（内容ログ）: AI アプリ実行を証跡として記録
    try:
        audit.record(
            request,
            action="exapp.invoke",
            teamId=team_id,
            exAppId=ex_app_id,
            session_id=session_id or None,
            status=200,
            input_text=json.dumps(inputs, ensure_ascii=False) if inputs else "",
            output_text=outputs if isinstance(outputs, str) else json.dumps(
                outputs, ensure_ascii=False
            ),
        )
    except Exception as e:  # noqa: BLE001
        print(f"[exapps] 監査ログの記録に失敗: {e}")

    return JSONResponse(
        content={
            "outputs": outputs,
            "artifacts": artifacts,
            "timestamps": {"processingStartedAt": started, "processingEndedAt": ended},
        }
    )


@app.post("/exapps/schema")
async def get_exapp_schema(request: Request) -> JSONResponse:
    """AI アプリの入力フォーム定義(placeholder)を取得する。

    Dify 連携アプリ等で、endpoint の `/schema` から入力スキーマを動的取得する。
    """
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    body = await request.json()
    team_id = body.get("teamId", "")
    ex_app_id = body.get("exAppId", "")

    app_def = teams_store.get_exapp(team_id, ex_app_id)
    if not app_def:
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})

    if (
        team_id != COMMON_TEAM_ID
        and not _is_system_admin(claims)
        and not teams_store.is_team_member(team_id, user_id)
    ):
        return _forbidden("このアプリを参照する権限がありません")

    endpoint = app_def.get("endpoint", "")
    if endpoint.endswith("/invoke"):
        schema_url = endpoint[: -len("/invoke")] + "/schema"
    else:
        schema_url = endpoint.rstrip("/") + "/schema"

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(
                schema_url,
                headers={
                    "x-api-key": app_def.get("apiKey", ""),
                    "x-app-config": app_def.get("config", "") or "",
                },
            )
        if res.status_code != 200:
            return JSONResponse(content={"placeholder": {}})
        return JSONResponse(content=res.json())
    except httpx.HTTPError:
        return JSONResponse(content={"placeholder": {}})


@app.get("/exapps/histories")
async def list_exapp_histories(
    request: Request,
    teamId: str = Query(default=""),
    exAppId: str = Query(default=""),
) -> dict[str, Any]:
    # ListInvokeExAppHistoriesResponse（ログインユーザー自身の履歴のみ）
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if not teamId or not exAppId:
        return {"history": [], "lastEvaluatedKey": None}
    history = teams_store.list_exapp_histories(teamId, exAppId, user_id)
    return {"history": history, "lastEvaluatedKey": None}


@app.get("/exapps/history")
async def get_exapp_history(
    teamId: str = Query(default=""),
    exAppId: str = Query(default=""),
    createdDate: str = Query(default=""),
) -> dict[str, Any]:
    # GetInvokeExAppHistoryResponse
    if not teamId or not exAppId or not createdDate:
        return {"history": None}
    return {"history": teams_store.get_exapp_history(teamId, exAppId, createdDate)}


# ---------------------------------------------------------------------------
# チーム管理 (Team Access Control API)
# ---------------------------------------------------------------------------
@app.get("/teams")
async def list_teams(request: Request) -> dict[str, Any]:
    claims = _claims_from_request(request)
    if _is_system_admin(claims):
        teams = teams_store.list_teams()
    else:
        teams = teams_store.list_teams_for_admin(_user_id(claims))
    # 共通チームは管理対象から除外して表示
    teams = [t for t in teams if t["teamId"] != COMMON_TEAM_ID]
    return {"teams": teams, "lastEvaluatedKey": None}


@app.post("/teams")
async def create_team(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("チーム作成はシステム管理者のみ可能です")
    body = await request.json()
    team_name = body.get("teamName", "")
    admin_email = body.get("teamAdminEmail", "")
    if not team_name or not admin_email:
        return JSONResponse(
            status_code=400, content={"error": "teamName と teamAdminEmail は必須です"}
        )
    team = teams_store.create_team(team_name, admin_email)
    # 新規チームに「チーム専用ローカル RAG」を自動登録（ナレッジはこのチームに閉じる）
    rag_template = {
        k: RAG_SEED[k]
        for k in (
            "exAppName",
            "endpoint",
            "apiKey",
            "config",
            "placeholder",
            "description",
            "howToUse",
            "copyable",
            "status",
        )
    }
    rag_template["exAppName"] = f"ローカル RAG（{team_name}）"
    rag_template["description"] = (
        f"「{team_name}」チーム専用のナレッジ検索です（他チームと分離）。"
    )
    teams_store.create_exapp(team["teamId"], rag_template)
    return JSONResponse(content=team)


@app.get("/teams/{team_id}")
async def get_team(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    team = teams_store.get_team(team_id)
    if not team:
        return JSONResponse(status_code=404, content={"error": "チームが見つかりません"})
    if not _is_system_admin(claims) and not teams_store.is_team_admin(
        team_id, _user_id(claims)
    ):
        return _forbidden()
    return JSONResponse(content=team)


@app.get("/teams/{team_id}/raw")
async def get_team_raw(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims) and not teams_store.is_team_admin(
        team_id, _user_id(claims)
    ):
        return _forbidden()
    team = teams_store.get_team(team_id)
    if not team:
        return JSONResponse(status_code=404, content={"error": "チームが見つかりません"})
    team["users"] = teams_store.list_team_users(team_id)
    team["exApps"] = teams_store.list_team_exapps(team_id)
    # raw はフロントで文字列として扱われるため JSON 文字列で返す
    return JSONResponse(content=json.dumps(team, ensure_ascii=False))


@app.put("/teams/{team_id}")
async def update_team(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims) and not teams_store.is_team_admin(
        team_id, _user_id(claims)
    ):
        return _forbidden()
    body = await request.json()
    team = teams_store.update_team(team_id, body.get("teamName", ""))
    if not team:
        return JSONResponse(status_code=404, content={"error": "チームが見つかりません"})
    return JSONResponse(content=team)


@app.delete("/teams/{team_id}")
async def delete_team(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("チーム削除はシステム管理者のみ可能です")
    teams_store.delete_team(team_id)
    # このチームの RAG ナレッジ(Qdrant スコープ)も消去する（ベストエフォート）
    try:
        base = RAG_APP_URL.rsplit("/invoke", 1)[0]
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(
                f"{base}/clear_scope",
                json={"scope": team_id},
                headers={"x-api-key": RAG_API_KEY},
            )
    except httpx.HTTPError as e:
        print(f"[teams] チームのナレッジ消去に失敗（残存の可能性）: {e}")
    return JSONResponse(content={})


# ---- メンバー管理 ----
def _can_manage_team(claims: dict[str, Any], team_id: str) -> bool:
    return _is_system_admin(claims) or teams_store.is_team_admin(
        team_id, _user_id(claims)
    )


@app.get("/teams/{team_id}/users")
async def list_team_users(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    return JSONResponse(
        content={"teamUsers": teams_store.list_team_users(team_id), "lastEvaluatedKey": None}
    )


@app.get("/teams/{team_id}/users/{user_id}")
async def get_team_user(team_id: str, user_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    user = teams_store.get_team_user(team_id, user_id)
    if not user:
        return JSONResponse(status_code=404, content={"error": "メンバーが見つかりません"})
    return JSONResponse(content=user)


@app.post("/teams/{team_id}/users")
async def create_team_user(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    body = await request.json()
    email = body.get("email", "")
    if not email:
        return JSONResponse(status_code=400, content={"error": "email は必須です"})
    user = teams_store.create_team_user(team_id, email, bool(body.get("isAdmin")))
    return JSONResponse(content=user)


@app.put("/teams/{team_id}/users/{user_id}")
async def update_team_user(team_id: str, user_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    body = await request.json()
    is_admin = bool(body.get("isAdmin"))
    # 最後の管理者を一般化しようとした場合はエラー
    if not is_admin and teams_store.is_team_admin(team_id, user_id):
        if teams_store.count_team_admins(team_id) <= 1:
            return JSONResponse(
                status_code=400,
                content={"error": "チーム管理者が0人になるため変更できません"},
            )
    user = teams_store.update_team_user(team_id, user_id, is_admin)
    if not user:
        return JSONResponse(status_code=404, content={"error": "メンバーが見つかりません"})
    return JSONResponse(content=user)


@app.delete("/teams/{team_id}/users/{user_id}")
async def delete_team_user(team_id: str, user_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    if teams_store.is_team_admin(team_id, user_id) and teams_store.count_team_admins(
        team_id
    ) <= 1:
        return JSONResponse(
            status_code=400,
            content={"error": "チーム管理者が0人になるため削除できません"},
        )
    teams_store.delete_team_user(team_id, user_id)
    return JSONResponse(content={})


# ---- AI アプリ管理（チーム単位）----
@app.get("/teams/{team_id}/exapps")
async def list_team_exapps(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    return JSONResponse(
        content={
            "teamExApps": teams_store.list_team_exapps(team_id),
            "lastEvaluatedKey": None,
        }
    )


@app.get("/teams/{team_id}/exapps/{ex_app_id}")
async def find_exapp(team_id: str, ex_app_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    app_def = teams_store.get_exapp(team_id, ex_app_id)
    if not app_def:
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})
    # 実行ページからの詳細取得: 共通 / システム管理者 / 所属メンバー が閲覧可
    if (
        team_id != COMMON_TEAM_ID
        and not _is_system_admin(claims)
        and not teams_store.is_team_member(team_id, user_id)
    ):
        return _forbidden()
    return JSONResponse(content=app_def)


@app.get("/teams/{team_id}/exapps/{ex_app_id}/raw")
async def get_exapp_raw(team_id: str, ex_app_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    app_def = teams_store.get_exapp(team_id, ex_app_id)
    if not app_def:
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})
    # raw はフロントで文字列として扱われるため JSON 文字列で返す
    return JSONResponse(content=json.dumps(app_def, ensure_ascii=False))


@app.post("/teams/{team_id}/exapps")
async def create_exapp(team_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    body = await request.json()
    return JSONResponse(content=teams_store.create_exapp(team_id, body))


@app.put("/teams/{team_id}/exapps/{ex_app_id}")
async def update_exapp(team_id: str, ex_app_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    body = await request.json()
    app_def = teams_store.update_exapp(team_id, ex_app_id, body)
    if not app_def:
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})
    return JSONResponse(content=app_def)


@app.delete("/teams/{team_id}/exapps/{ex_app_id}")
async def delete_exapp(team_id: str, ex_app_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    teams_store.delete_exapp(team_id, ex_app_id)
    return JSONResponse(content={})


@app.post("/teams/{team_id}/exapps/{ex_app_id}/copy")
async def copy_exapp(team_id: str, ex_app_id: str, request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    if not _can_manage_team(claims, team_id):
        return _forbidden()
    body = await request.json()
    app_def = teams_store.copy_exapp(team_id, ex_app_id, body)
    if not app_def:
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})
    return JSONResponse(content=app_def)


@app.delete("/teams/{team_id}/exapps/{ex_app_id}/history")
async def delete_exapp_history(
    team_id: str,
    ex_app_id: str,
    request: Request,
    createdDate: str = Query(default=""),
) -> JSONResponse:
    """AI アプリの実行履歴を 1 件削除する（共通 / システム管理者 / 所属メンバー）。"""
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if (
        team_id != COMMON_TEAM_ID
        and not _is_system_admin(claims)
        and not teams_store.is_team_member(team_id, user_id)
    ):
        return _forbidden()
    if createdDate:
        teams_store.delete_exapp_history(team_id, ex_app_id, createdDate)
    return JSONResponse(content={})
