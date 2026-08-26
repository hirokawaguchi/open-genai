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
import base64
import hmac
import html
import json
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)

from shared import ssrfguard

from . import (
    audit,
    auth,
    filesig,
    image_gen,
    intauth,
    llm,
    ngwords,
    objstore,
    policy,
    security_warn,
    storage,
    teams_store,
    titlegen,
)

# ファイル添付の保存先と、ブラウザから見たバックエンドの公開 URL
FILES_DIR = os.environ.get("FILES_DIR", "/data/files")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")

# チャットタイトル生成方式: "heuristic"（既定・LLM 不使用）/ "llm"
TITLE_MODE = os.environ.get("TITLE_MODE", "heuristic").strip().lower()

# リバースプロキシが /api を除去して転送する場合の公開 API パス prefix（SAML Recipient 検証用）
PUBLIC_API_PATH_PREFIX = os.environ.get("PUBLIC_API_PATH_PREFIX", "/api").rstrip("/")

# ログイン後に戻るフロントエンド URL
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:5173").rstrip("/")

# 認証不要のパス
# /health は完全一致のみ（/health/details は JWT 必須）。
# /files/ は Authorization を付けられない img/PUT 用。認可は HMAC クエリで行う。
PUBLIC_EXACT_PATHS = frozenset({"/health"})
PUBLIC_PATH_PREFIXES = (
    "/auth/",
    "/files/",
    "/docs",
    "/openapi.json",
    "/redoc",
)


def _is_public_path(path: str) -> bool:
    if path in PUBLIC_EXACT_PATHS:
        return True
    return any(path.startswith(p) for p in PUBLIC_PATH_PREFIXES)

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

# 禁止ワード/機密情報 入力制限「AI アプリ」連携先（管理者限定）
NGWORD_APP_URL = os.environ.get("NGWORD_APP_URL", "http://ngword-app:8008/invoke")

# プロンプトテンプレート「AI アプリ」連携先（全ユーザー利用可）
PROMPT_APP_URL = os.environ.get("PROMPT_APP_URL", "http://prompt-app:8009/invoke")

# 日程調整（Compose profiles: ["chosei"] でオプション起動。未起動時は専用ページが案内を出す）
# 実 API は /chosei/* プロキシ。endpoint 末尾の /invoke はヘルスチェック導出用（実体なし可）。
CHOSEI_APP_URL = os.environ.get("CHOSEI_APP_URL", "http://chosei-app:8010/invoke")
CHOSEI_PUBLIC_ENDPOINT = (os.environ.get("CHOSEI_PUBLIC_ENDPOINT") or "").rstrip("/")
# 書類領域分割チェック（Compose profiles: ["doccheck"]）
DOCCHECK_APP_URL = os.environ.get("DOCCHECK_APP_URL", "http://doccheck-app:8011/invoke")
DOCCHECK_PUBLIC_ENDPOINT = (os.environ.get("DOCCHECK_PUBLIC_ENDPOINT") or "").rstrip("/")
# フォーム（Compose profiles: ["patchform"]）。実 API は /patchform/* プロキシ。
PATCHFORM_APP_URL = os.environ.get("PATCHFORM_APP_URL", "http://patchform-app:8012/invoke")
PATCHFORM_PUBLIC_ENDPOINT = (os.environ.get("PATCHFORM_PUBLIC_ENDPOINT") or "").rstrip("/")
PATCHFORM_SERVICE_USER = "service"
_PATCHFORM_SERVICE_PATHS = re.compile(
    r"^/patchform/(?:procedures(?:/[^/]+(?:/(?:applications|export))?)?|applications/[^/]+(?:/export)?)$"
)

# 管理者(SystemAdminGroup)のみに一覧表示・実行を許可する exApp
# （共有ナレッジの管理系は共通チーム上だが管理者限定）
ADMIN_ONLY_EXAPP_IDS = {
    "audit",
    "usermgmt",
    "modelpolicy",
    "ngword",
    "rag-manage",  # 旧統合管理（移行後も残っていれば制限）
    "rag-tags",
    "rag-register",
    "rag-maintain",
}

COMMON_TEAM_ID = teams_store.COMMON_TEAM_ID
# 管理者向けアプリ（監査/利用者一括/モデル制御/入力制限/RAGナレッジ管理）専用チーム
ADMIN_TEAM_ID = teams_store.ADMIN_TEAM_ID

# RAG の検索/管理フォームは rag-app の /schema で動的生成する（タグ/ドキュメントを
# 選択式に）。そのため exApp の placeholder は空、config に dynamic_schema/rag_role を持たせる。


# 共通チームに既定で登録する RAG「検索」アプリ（全員向け・検索専用）
RAG_SEED: dict[str, Any] = {
    "exAppId": "rag",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "ナレッジ検索",
    "endpoint": RAG_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": '{"dynamic_schema": true, "rag_role": "search"}',
    "placeholder": "",
    "description": "共有ナレッジを検索し、根拠となるドキュメントとともに回答します（検索専用）。",
    "howToUse": (
        "## このアプリでできること\n\n"
        "組織で共有しているナレッジ（登録済みの資料・URL）を検索し、"
        "根拠となる該当箇所を引用しながら回答します。一般的なチャットと違い、"
        "**登録済みの資料に基づいた回答**が得られます。\n\n"
        "## 操作手順\n\n"
        "1. 「質問」に知りたいことを入力します（例:「育児休業の申請期限は？」）。\n"
        "2. 必要に応じて「タグ」で対象を絞り込みます（後述）。\n"
        "3. 「参照件数」で根拠として参照する件数を調整します（既定4件）。\n"
        "4. 「実行」を押すと、回答と根拠ドキュメントが表示されます。\n\n"
        "## 各項目\n\n"
        "- **質問**: 自然文で入力できます。具体的に書くほど精度が上がります。\n"
        "- **タグ**: 指定するとそのタグの資料だけを検索します"
        "（複数選択可・未指定なら**タグ付き資料全体**。タグ未付与は対象外）。\n"
        "- **検索方式**: 手動選択はありません。"
        "対象資料の全文がコンテキストに収まる場合は全文、"
        "すべて構造化済みならハイブリッド、非構造化を含む場合はベクトルを自動選択します。\n"
        "- **参照件数**: 多いほど広く探します（1〜10。全文モードでは文書単位）。\n\n"
        "## こんなときは\n\n"
        "- ヒットしない: タグ付きで登録されているか、「ナレッジ管理」で確認。\n"
        "- 資料の追加・分類・一覧・削除・タグ付け替え: アカウントメニューの"
        "**「ナレッジ管理」**（専用ページ）で行います。\n"
    ),
    "copyable": False,
    "status": "published",
}

# 注: 共有ナレッジのタグ管理・ドキュメント登録・ドキュメント管理は、汎用 exApp を廃止し
# 専用ページ /knowledge に統合済み（旧 rag-tags / rag-register / rag-maintain）。


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
    "exAppName": "文字起こし",
    "endpoint": WHISPER_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _WHISPER_FORM,
    "description": "音声ファイルをテキストに書き起こします（タイムスタンプ付き）。",
    "howToUse": (
        "## このアプリでできること\n\n"
        "会議やインタビューの録音などの音声ファイルを、テキストに書き起こします。"
        "音声はクラウドに送信されないため、機微な内容も扱えます。\n\n"
        "## 操作手順\n\n"
        "1. 「音声ファイル」に録音データを添付します"
        "（mp3 / wav / m4a / aac / flac / ogg）。\n"
        "2. 「言語」を選びます（迷ったら「自動判定」でOK。日本語/英語は明示指定も可）。\n"
        "3. 「実行」を押すと、タイムスタンプ付きの文字起こし結果が表示されます。\n\n"
        "## コツ・注意\n\n"
        "- 長い音声は処理に時間がかかります。区切って投入すると安定します。\n"
        "- 雑音が少なくクリアな音声ほど精度が上がります。\n"
        "- 固有名詞や専門用語は誤変換されることがあります。結果は必ず確認してください。\n"
        "- 文字起こし結果はコピーして、そのままチャットで要約・議事録化に使えます。"
    ),
    "copyable": False,
    "status": "published",
}

# 監査ログ参照(Audit) AI アプリ（管理者限定）
# 「使い方」はページ上部の howToUse に統一（操作プルダウンには含めない）。検索専用フォーム。
_AUDIT_FORM = (
    '{'
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
    "teamId": ADMIN_TEAM_ID,
    "exAppName": "監査ログ参照（管理者限定）",
    "endpoint": AUDIT_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _AUDIT_FORM,
    "description": "利用状況/内容の監査ログを検索します（システム管理者のみ）。",
    "howToUse": (
        "## このアプリでできること（管理者）\n\n"
        "誰が・いつ・どの機能を使ったか（チャット送信、推論、AIアプリ実行、ログイン、"
        "APIアクセス等）の監査ログを検索します。読み取り専用で、ログは改変されません。\n\n"
        "## 操作手順\n\n"
        "1. 必要な条件を入力します（すべて任意。未入力なら直近の全件を新しい順に表示）。\n"
        "2. 「実行」を押すと、条件に一致するログが一覧表示されます。\n\n"
        "## 絞り込み条件\n\n"
        "- **ユーザーID**: 特定利用者（メール または sub）で絞り込み。\n"
        "- **アクション種別**: チャットメッセージ／推論ストリーム／AIアプリ実行／ログイン／APIアクセス。\n"
        "- **キーワード**: 入力・出力内容の部分一致。\n"
        "- **開始日／終了日**: `YYYY-MM-DD`（UTC）で期間を指定。\n"
        "- **表示件数**: 1〜500件（既定50）。\n\n"
        "## 注意\n\n"
        "- 監査ログには入力・出力の本文が含まれる場合があります。取り扱いに注意してください。\n"
        "- 全文取得やCSVエクスポートは管理API `GET /admin/audit-logs`(/export) を利用します。"
    ),
    "copyable": False,
    "status": "published",
}

# 利用者一括管理(User Management) AI アプリ（管理者限定）
_USERMGMT_FORM = (
    "{\"operation\":{\"type\":\"select\",\"title\":\"操作\",\"desc\":\"一覧表示、または CSV のドライラン／適用。まずドライランで内容を確認してく"
    "ださい。\",\"items\":[{\"title\":\"ユーザ一覧（表示のみ）\",\"value\":\"list\"},{\"title\":\"ドライラン（変更しない）\",\"value\":\"dry"
    "_run\"},{\"title\":\"適用（Keycloakに反映）\",\"value\":\"apply\",\"confirm\":\"CSVの内容をKeycloakに反映します（利用者の作成・"
    "更新・削除を含む）。削除は元に戻せません。ドライランで確認済みですか？\"}],\"default_value\":\"list\"},\"search\":{\"type\":\"text\",\"ti"
    "tle\":\"検索（一覧用・任意）\",\"desc\":\"ユーザ一覧時のみ有効。username / email / 氏名の部分一致。\"},\"limit\":{\"type\":\"number"
    "\",\"title\":\"表示件数（一覧用）\",\"default_value\":200,\"min\":1,\"max\":1000},\"files\":{\"type\":\"file\",\"titl"
    "e\":\"CSVファイル\",\"desc\":\"見出し: action,username,email,firstName,lastName,name,password,groups,en"
    "abled（一覧表示時は不要）\",\"accept\":\".csv,.txt\",\"multiple\":false},\"csv_text\":{\"type\":\"textarea\",\"tit"
    "le\":\"CSV（貼り付け・任意）\",\"desc\":\"ファイルの代わりにCSVを直接貼り付けても可（一覧表示時は不要）。\"}}"
)
USERMGMT_SEED: dict[str, Any] = {
    "exAppId": "usermgmt",
    "teamId": ADMIN_TEAM_ID,
    "exAppName": "利用者一括管理（管理者限定）",
    "endpoint": USERMGMT_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _USERMGMT_FORM,
    "description": "利用者一覧の表示、および CSV による一括登録/更新/削除（システム管理者のみ）。",
    "howToUse": "## このアプリでできること（管理者）\n\nKeycloak 上の利用者アカウントを一覧表示し、CSV で一括作成・更新・削除できます。\n\n## ユーザ一覧\n\n1. 「操作」で「ユーザ一覧（表示のみ）」を選びます（既定）。\n2. 必要なら「検索」と「表示件数」を指定して「実行」します。\n3. username / email / 氏名 / 所属グループ / 有効状態が一覧表示されます（変更はされません）。\n\n## CSV の準備\n\n1行目に見出し、2行目以降に利用者を記載します。見出し例:\n\n```\naction,username,email,name,password,groups,enabled\nupsert,yamada,yamada@example.com,山田太郎,Passw0rd!,UserGroup,true\n```\n\n- **action**: `create`（新規）/`update`（更新）/`delete`（削除）/`upsert`（無ければ作成・あれば更新／既定）。\n- **username**: 必須。ログインID。\n- **email / name**: メールアドレス・氏名。\n- **password**: 新規作成時の初期パスワード（更新時は変更したい場合のみ）。\n- **groups**: 権限グループ（例 `SystemAdminGroup`＝システム管理者）。`;` か `,` 区切り。\n- **enabled**: 有効/無効（`true`/`false`）。\n\n## CSV 操作手順\n\n1. CSV ファイルを添付するか、「CSV（貼り付け）」に直接貼り付けます。\n2. 「操作」で「ドライラン」を選んで実行し、**対象と操作内容を必ず確認**します（この時点では変更されません）。\n3. 問題なければ「操作」を「適用」にして実行します（確認ダイアログが表示されます）。\n\n## 注意\n\n- 「適用」は作成・更新・**削除**を伴い、削除は元に戻せません。必ずドライランで確認してください。\n- パスワード列を含む CSV の保管・共有には十分注意してください。",
    "copyable": False,
    "status": "published",
}

# モデル利用制御(Model Policy) AI アプリ（管理者限定）
# 構造化フォームは modelpolicy-app の /schema が現在ポリシーをプレフィルして生成する。
# 利用可能モデルID一覧は backend が x-available-models で渡す。placeholder は空・dynamic_schema。
MODELPOLICY_SEED: dict[str, Any] = {
    "exAppId": "modelpolicy",
    "teamId": ADMIN_TEAM_ID,
    "exAppName": "モデル利用制御（管理者限定）",
    "endpoint": MODELPOLICY_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": '{"dynamic_schema": true}',
    "placeholder": "",
    "description": "チームごとに使用可能な LLM を管理者が設定します（システム管理者のみ）。",
    "howToUse": (
        "## 使い方\n\n"
        "利用可能な LLM をチーム単位で制御します（backend が推論時に、利用者の所属チームで強制）。\n\n"
        "- 「操作」で「設定を保存」を選ぶと、現在の設定が入力欄にプレフィルされます。\n"
        "- 「全ユーザー共通で許可するモデル」は1行に1つのモデルIDで入力します。\n"
        "- 「チーム別の追加許可」は「チーム名: モデルID,モデルID」を1行に1チームで入力します。\n"
        "- 利用者は所属する各チームの許可モデルの和集合を使えます。\n"
        "- 保存時に確認ダイアログが表示されます。システム管理者は常に全モデル利用可能です。\n"
    ),
    "copyable": False,
    "status": "published",
}

# 禁止ワード/機密情報 入力制限(NG-Word) AI アプリ（管理者限定）
# 構造化フォームは ngword-app の /schema が現在ルールをプレフィルして生成する。
# そのため placeholder は空、config で動的スキーマを有効化する。
NGWORD_SEED: dict[str, Any] = {
    "exAppId": "ngword",
    "teamId": ADMIN_TEAM_ID,
    "exAppName": "入力制限（禁止ワード・機密情報／管理者限定）",
    "endpoint": NGWORD_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": '{"dynamic_schema": true}',
    "placeholder": "",
    "description": "禁止ワード・機密情報の入力制限ルールを管理者が設定します（システム管理者のみ）。",
    "howToUse": (
        "## 使い方\n\n"
        "入力（チャット/AIアプリ）に対する禁止ワード・機密情報の制限を設定します。\n"
        "backend が推論前段で入力を検査し、該当時はブロックします。\n\n"
        "- 「操作」で「設定を保存」を選ぶと、現在の設定が入力欄にプレフィルされます。\n"
        "- **マイナンバー検査**: 検査用数字が一致する12桁のみブロック"
        "（単なる12桁数字や UUID では止めません）。\n"
        "- 禁止ワード・その他の機密パターンは1行に1件で入力します。\n"
        "- 保存時に確認ダイアログが表示されます。\n\n"
        "> 管理系アプリ（本アプリ等）の実行は制限対象外です。\n"
    ),
    "copyable": False,
    "status": "published",
}

# プロンプトテンプレート(Prompt) AI アプリ（全ユーザー利用可）
# OpenGENAI exApp Form Spec v1 に対応。フォームは prompt-app の /schema・/resolve が
# リアクティブに生成する（操作に応じた項目の出し分け・テンプレの選択式・変数入力欄の
# 自動生成・組み上がりプレビュー）。そのため placeholder は空、config で動的スキーマを有効化。
PROMPT_SEED: dict[str, Any] = {
    "exAppId": "prompt",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "プロンプトテンプレート",
    "endpoint": PROMPT_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": '{"dynamic_schema": true}',
    "placeholder": "",
    "description": "標準テンプレートの利用や、個人/チーム共有テンプレートの作成ができます。選ぶとチャットへ流し込めます。",
    "howToUse": (
        "## 使い方\n\n"
        "- 「操作」で「使う／一覧／作成／削除」を選ぶと、それに応じた項目だけが表示されます。\n"
        "- 「使う」ではテンプレートを一覧から選ぶと、本文の `{{変数}}` に応じた入力欄が自動で出ます。"
        "入力するとプレビューに組み上がったプロンプトが表示され、そのまま**チャットで開く**ことができます。\n"
        "- 「作成」で個人／チーム共有／全体公開のテンプレートを追加できます（標準は管理者のみ）。\n"
        "- 「共有範囲」の「チーム共有」は自分の所属チームから選べます。全体公開は全利用者に見えます。\n"
    ),
    "copyable": False,
    "status": "published",
}

# 日程調整（共通アプリ）。UI は専用ページ /chosei。Compose profile `chosei` 未起動時は
# /health 失敗で一覧非表示。endpoint はヘルスチェック用（実 API は /chosei/* プロキシ）。
CHOSEI_SEED: dict[str, Any] = {
    "exAppId": "chosei",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "日程調整",
    "endpoint": (
        CHOSEI_APP_URL
        if CHOSEI_APP_URL.endswith("/invoke")
        else CHOSEI_APP_URL.rstrip("/") + "/invoke"
    ),
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": "",
    "description": "庁内・外部参加者向けの日程調整。専用画面で作成・回答・集計できます。",
    "howToUse": (
        "## 使い方\n\n"
        "- 専用ページ「日程調整」からイベントを作成し、共有 URL を配布します。\n"
        "- 庁内利用者はログインしたまま回答できます。外部は公開 URL から回答します。\n"
        "- 有効化: `docker compose --profile chosei up -d` または `COMPOSE_PROFILES=chosei`。\n"
    ),
    "copyable": False,
    "status": "published",
}

# 書類領域分割チェック（共通アプリ）。UI は専用ページ /doccheck。
DOCCHECK_SEED: dict[str, Any] = {
    "exAppId": "doccheck",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "書類読取とチェック",
    "endpoint": (
        DOCCHECK_APP_URL
        if DOCCHECK_APP_URL.endswith("/invoke")
        else DOCCHECK_APP_URL.rstrip("/") + "/invoke"
    ),
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": "",
    "description": "申請書類の領域分割 OCR と分散チェック。専用画面で投入・配信・合意形成できます。",
    "howToUse": (
        "## 使い方\n\n"
        "- 専用ページ「書類読取とチェック」から帳票テンプレートとスキャンを登録します。\n"
        "- 領域ごとに OCR 候補を出し、庁内・外部へチェックを配信します。\n"
        "- 有効化: `docker compose --profile doccheck up -d` または `COMPOSE_PROFILES=doccheck`。\n"
    ),
    "copyable": False,
    "status": "published",
}

# フォーム（共通アプリ）。UI は専用ページ /patchform。Compose profile `patchform` 未起動時は
# /health 失敗で一覧非表示。endpoint はヘルスチェック用（実 API は /patchform/* プロキシ）。
PATCHFORM_SEED: dict[str, Any] = {
    "exAppId": "patchform",
    "teamId": COMMON_TEAM_ID,
    "exAppName": "フォーム",
    "endpoint": (
        PATCHFORM_APP_URL
        if PATCHFORM_APP_URL.endswith("/invoke")
        else PATCHFORM_APP_URL.rstrip("/") + "/invoke"
    ),
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": "",
    "description": "庁内・外部向けのオンラインフォーム。専用画面で作成・回答・集計できます。",
    "howToUse": (
        "## 使い方\n\n"
        "- 専用ページ「フォーム」から定義を作成し、共有 URL を配布します。\n"
        "- 庁内利用者はログインしたまま回答できます。外部は公開 URL から回答します。\n"
        "- 有効化: `docker compose --profile patchform up -d` または `COMPOSE_PROFILES=patchform`。\n"
    ),
    "copyable": False,
    "status": "published",
}


def _team_rag_search_app(team_name: str) -> dict[str, Any]:
    return {
        "exAppName": f"{team_name}のナレッジ検索",
        "endpoint": RAG_APP_URL,
        "apiKey": RAG_API_KEY,
        "config": '{"dynamic_schema": true, "rag_role": "search"}',
        "placeholder": "",
        "description": f"「{team_name}」チームのナレッジ検索です（他チームと分離）。",
        "howToUse": RAG_SEED["howToUse"],
        "copyable": False,
        "status": "published",
    }


def _rag_role_of(app: dict[str, Any]) -> str | None:
    try:
        cfg = json.loads(app.get("config") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    return cfg.get("rag_role")


# 専用ページ /knowledge へ統合したため削除する旧管理系 RAG ロール。
# 独自 exApp（未知ロール・rag_role なし）は誤削除しない。
_RETIRED_RAG_ROLES = frozenset({"tags", "register", "maintain", "manage"})


def _ensure_team_rag_search() -> None:
    """各チームに「ナレッジ検索」を1つだけ用意する（冪等）。

    タグ管理・ドキュメント登録・ドキュメント管理は専用ページ /knowledge に統合したため、
    既知の旧管理系ロール（tags/register/maintain/旧 manage）のみ削除する。
    同じ RAG endpoint を指す独自 exApp は残す。
    """
    for team in teams_store.list_teams():
        team_id = team["teamId"]
        if team_id in (COMMON_TEAM_ID, ADMIN_TEAM_ID):
            continue
        tname = team["teamName"]
        apps = [
            a
            for a in teams_store.list_team_exapps(team_id)
            if a.get("endpoint") == RAG_APP_URL
        ]

        search_apps = [a for a in apps if _rag_role_of(a) == "search"]
        retired = [a for a in apps if _rag_role_of(a) in _RETIRED_RAG_ROLES]

        if search_apps:
            # 検索アプリを最新化し、重複のみ削除
            teams_store.update_exapp(
                team_id, search_apps[0]["exAppId"], _team_rag_search_app(tname)
            )
            for extra in search_apps[1:]:
                teams_store.delete_exapp(team_id, extra["exAppId"])
        else:
            # 検索が無ければ新規作成（独自/旧管理アプリを転用しない）
            teams_store.create_exapp(team_id, _team_rag_search_app(tname))

        for a in retired:
            teams_store.delete_exapp(team_id, a["exAppId"])


EXAPP_SEEDS = [
    RAG_SEED,
    WHISPER_SEED,
    AUDIT_SEED,
    USERMGMT_SEED,
    MODELPOLICY_SEED,
    NGWORD_SEED,
    PROMPT_SEED,
    CHOSEI_SEED,
    DOCCHECK_SEED,
    PATCHFORM_SEED,
]

# 源内 Web の汎用ページ／専用ページに統合したため exApp 登録を廃止した ID。
# ナレッジのタグ管理・登録・管理は専用ページ /knowledge に統合済み（検索 rag は維持）。
RETIRED_SEED_EXAPP_IDS = [
    "sd",
    "rag-manage",
    "rag-tags",
    "rag-register",
    "rag-maintain",
]


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


def _is_team_or_system_admin(claims: dict[str, Any]) -> bool:
    groups = claims.get("groups") or []
    return "SystemAdminGroup" in groups or "TeamAdminGroup" in groups


_MODELS_CACHE: dict[str, Any] = {"ts": 0.0, "models": []}


async def _available_models_cached(ttl: float = 60.0) -> list[str]:
    """利用可能モデルID一覧（短時間キャッシュ）。modelpolicy の /schema 用。"""
    now = time.time()
    if _MODELS_CACHE["models"] and (now - _MODELS_CACHE["ts"] < ttl):
        return _MODELS_CACHE["models"]
    try:
        models = await llm.list_models()
    except Exception:  # noqa: BLE001
        models = _MODELS_CACHE["models"]
    _MODELS_CACHE["ts"] = now
    _MODELS_CACHE["models"] = models
    return models


def _all_teams_header() -> str:
    """全チーム(id+name)を Base64 化した JSON。modelpolicy のチーム別設定 UI 用。

    固定チーム(共通/管理者ツール)は設定対象外のため除外。日本語チーム名を含むため
    HTTP ヘッダに載せられるよう Base64 する。
    """
    try:
        teams = [
            t
            for t in teams_store.list_teams()
            if t["teamId"] not in (COMMON_TEAM_ID, ADMIN_TEAM_ID)
        ]
    except Exception:  # noqa: BLE001
        teams = []
    payload = json.dumps(
        [{"id": t["teamId"], "name": t["teamName"]} for t in teams], ensure_ascii=False
    )
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def _member_teams(user_id: str) -> list[dict[str, str]]:
    try:
        return teams_store.list_teams_for_member(user_id)
    except Exception:  # noqa: BLE001
        return []


def _user_team_ids_str(user_id: str) -> str:
    """所属チームID(カンマ区切り)。共有資産(プロンプト等)の可視判定に使う。

    backend が信頼の根として team_users を解決し、`x-user-tags`(署名スロット)として
    exApp へ署名付与する。x-user-* の偽装による他チーム資産の閲覧を防ぐ。
    """
    return ",".join(t["teamId"] for t in _member_teams(user_id))


def _user_teams_header(user_id: str) -> str:
    """表示用の所属チーム(JSON: [{id,name}])を Base64 化して返す。ラベル表示専用。

    チーム名は日本語を含むため、HTTP ヘッダ(latin-1 制約)に載せられるよう Base64 する。
    可視判定・作成検証は署名済みチームID(x-user-tags)で行うため本ヘッダは非署名でよい
    （改ざんしても表示ラベルが変わるだけでアクセスは得られない）。
    """
    payload = json.dumps(
        [{"id": t["teamId"], "name": t["teamName"]} for t in _member_teams(user_id)],
        ensure_ascii=False,
    )
    return base64.b64encode(payload.encode("utf-8")).decode("ascii")


def _forbidden(msg: str = "この操作を行う権限がありません") -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": msg})


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    """監査ログ用に、メッセージ列から最後のユーザー発話のテキストを取り出す。"""
    for m in reversed(messages or []):
        if m.get("role") == "user":
            content = m.get("content", "")
            return content if isinstance(content, str) else str(content)
    return ""


def _user_scope_ids(claims: dict[str, Any]) -> list[str]:
    """モデル利用ポリシー判定に使う利用者スコープ = 所属チームID。"""
    try:
        return teams_store.list_team_ids_for_user(_user_id(claims))
    except Exception:  # noqa: BLE001
        return []


def _model_denied(claims: dict[str, Any], model: Any) -> str | None:
    """利用ポリシー上、指定モデルが不許可なら理由メッセージを返す（許可なら None）。"""
    model_id = llm.resolve_model(model if isinstance(model, dict) else None)
    scopes = _user_scope_ids(claims)
    if policy.is_model_allowed(scopes, _is_system_admin(claims), model_id):
        return None
    return f"モデル「{model_id}」の利用は許可されていません（管理者にお問い合わせください）。"


def _ngword_denied(request: Request, text: str, *, usecase: str = "/chat") -> str | None:
    """入力が禁止ワード/機密情報に該当すればブロック理由を返し、監査ログに記録する。"""
    blocked, reason = ngwords.check(text or "")
    if not blocked:
        return None
    try:
        audit.record(
            request,
            action="input.blocked",
            usecase=usecase,
            status=403,
            input_text=text,
            output_text=reason or "",
        )
    except Exception:  # noqa: BLE001
        pass
    return reason or "入力に使用できない語句が含まれています。"


def _texts_from_inputs(inputs: dict[str, Any]) -> str:
    """AI アプリの inputs から文字列値を連結する（禁止ワード検査用）。"""
    parts: list[str] = []
    for v in (inputs or {}).values():
        if isinstance(v, str):
            parts.append(v)
    return "\n".join(parts)


# 監査ログに残してはいけない機微フィールド（部分一致・小文字比較）。
# 例: usermgmt の csv_text / password（利用者一括登録の資格情報）。
_AUDIT_SENSITIVE_KEYS = ("password", "csv_text", "secret", "token", "api_key", "apikey")


def _redact_for_audit(inputs: Any) -> Any:
    """監査ログ用に inputs から機微情報を除去する。

    - password/csv_text 等はマスク。
    - files(base64) は内容を保存せずファイル名のみに置換（資格情報混入・肥大化を防ぐ）。
    """
    if not isinstance(inputs, dict):
        return inputs
    out: dict[str, Any] = {}
    for k, v in inputs.items():
        kl = str(k).lower()
        if any(s in kl for s in _AUDIT_SENSITIVE_KEYS):
            out[k] = "***"
            continue
        if k == "files":
            names: list[str] = []
            try:
                for entry in v or []:
                    for f in entry.get("files", []):
                        names.append(f.get("filename", "file"))
            except (AttributeError, TypeError):
                pass
            out[k] = f"[files: {', '.join(names)}]" if names else "[files]"
            continue
        out[k] = v
    return out


def _is_http_url(url: Any) -> bool:
    return isinstance(url, str) and (
        url.startswith("http://") or url.startswith("https://")
    )


_MD_SPECIAL = ("\\", "`", "*", "_", "[", "]", "(", ")", "!", "<", ">", "|")


def _md_escape(text: Any) -> str:
    """Markdown/HTML の特殊文字を無効化する（リンク注入・フィッシング防止）。"""
    s = str(text or "").replace("\r", " ").replace("\n", " ")
    for ch in _MD_SPECIAL:
        s = s.replace(ch, "\\" + ch)
    return s


def _header_config_value(config: str | None) -> str:
    """AI アプリ config を HTTP ヘッダ(x-app-config)に載せられる1行文字列へ正規化する。

    UI で整形された JSON（改行入り）をそのままヘッダに入れると httpx が拒否し、
    /exapps/schema・/exapps/invoke が 502 相当で失敗する。
    """
    raw = (config or "").strip()
    if not raw:
        return ""
    try:
        return json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))
    except (json.JSONDecodeError, TypeError):
        return raw.replace("\r", " ").replace("\n", " ")


# 成果物取得（SSRF 対策）の設定
# - ARTIFACT_FETCH_ALLOWED_HOSTS が指定されていれば、そのホストのみ取得を許可（推奨）。
# - allowlist に載せたホストは、ローカル/セルフホスト Dify 向けに private/loopback
#   解決を許可する（未掲載ホストや allowlist 空の場合は公開アドレスのみ）。
# - リンクローカル（クラウドメタデータ等）は allowlist でも拒否。
# - 取得は shared.ssrfguard 経由（DNS リバインディング対策・リダイレクト都度検証つき）。
_ARTIFACT_ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.environ.get("ARTIFACT_FETCH_ALLOWED_HOSTS", "").split(",")
    if h.strip()
}
_ARTIFACT_MAX_BYTES = int(os.environ.get("ARTIFACT_MAX_BYTES", str(50 * 1024 * 1024)))

# 成果物の配信方式（LGWAN 対応）。
# - "open"    : 署名付き URL を outputs に直接リンクとして提示（開発・直接 DL 可能な環境向け）。
# - "carrier" : 署名付き URL を UI に出さず、別途「リンクファイル(.txt/.html)」として
#               持ち出させる（LGWAN 端末から成果物本体へ直接アクセスできない環境向け）。
ARTIFACT_DELIVERY_MODE = (os.environ.get("ARTIFACT_DELIVERY_MODE", "open").strip().lower())
if ARTIFACT_DELIVERY_MODE not in ("open", "carrier"):
    ARTIFACT_DELIVERY_MODE = "open"
# キャリアファイルの既定形式（"txt" / "html" / "both"）。"both" は UI からの format 指定で切替。
ARTIFACT_CARRIER_FORMAT = (os.environ.get("ARTIFACT_CARRIER_FORMAT", "txt").strip().lower())
if ARTIFACT_CARRIER_FORMAT not in ("txt", "html", "both"):
    ARTIFACT_CARRIER_FORMAT = "txt"


async def _fetch_artifact(file_url: str) -> tuple[bytes | None, str]:
    """SSRF 対策付きで成果物を取得する。(data, mime) を返す（失敗時 data=None）。"""
    try:
        return await ssrfguard.fetch(
            file_url,
            allowed_hosts=_ARTIFACT_ALLOWED_HOSTS or None,
            max_bytes=_ARTIFACT_MAX_BYTES,
            timeout=120.0,
        )
    except ssrfguard.SsrfBlocked as e:
        print(f"[exapps] 成果物 URL を拒否({e}): {file_url}")
        return None, ""
    except httpx.HTTPError as e:
        print(f"[exapps] 成果物の取得に失敗: {e}")
        return None, ""


async def _rehost_artifacts(
    request: Request,
    user_id: str,
    outputs: Any,
    artifacts: Any,
) -> tuple[Any, Any]:
    """AI アプリの成果物ファイルを自前オブジェクトストレージへ再ホストする。

    - `content`(base64) かつ画像（または mime 未設定の従来互換）はインラインのまま。
    - `content`(base64) かつ非画像（例: xlsx 書き戻し）はデコードして SeaweedFS へ再ホスト。
    - `file_url`(外部参照, 例: Dify 署名URL) は実体を取得し、S3 互換(SeaweedFS)へ
      アップロードして**自前の署名付き URL**へ差し替え、`outputs` に DL リンクを付す。
    - オブジェクトストレージ未設定時は、取得元 URL をそのままリンクとして提示（フォールバック）。
      content のみの非画像でストレージ未設定のときは content を残す（フロントは非対応のため非推奨）。
    """
    if not artifacts or not isinstance(artifacts, list):
        return outputs, artifacts

    links: list[tuple[str, str, str]] = []
    # carrier モードで UI に生 URL を出さず「リンクファイル」で持ち出させる成果物の表示名
    carrier_names: list[str] = []
    new_arts: list[Any] = []
    for a in artifacts:
        if not isinstance(a, dict):
            new_arts.append(a)
            continue

        name = a.get("display_name") or "file"
        mime = (a.get("mime_type") or "").split(";")[0].strip()
        content_b64 = a.get("content") or ""
        file_url = a.get("file_url") or ""

        # 画像（または mime 未設定の content）は従来どおりインライン
        if content_b64 and (not mime or mime.startswith("image/")):
            new_arts.append(a)
            continue

        data: bytes | None = None
        if content_b64 and mime and not mime.startswith("image/"):
            try:
                raw = content_b64
                if isinstance(raw, str) and raw.startswith("data:"):
                    comma = raw.find(",")
                    if comma != -1:
                        raw = raw[comma + 1 :]
                data = base64.b64decode(raw)
            except Exception:  # noqa: BLE001
                data = None
                new_arts.append(a)
                continue
        elif file_url.startswith("http://") or file_url.startswith("https://"):
            data, fetched_mime = await _fetch_artifact(file_url)
            if data is not None:
                mime = mime or fetched_mime
        elif not file_url:
            new_arts.append(a)
            continue

        if data is None and file_url:
            # 取得失敗時は元 URL を残す
            safe_url = file_url if _is_http_url(file_url) else ""
            art_out = {**a, "file_url": safe_url}
            if mime:
                art_out["mime_type"] = mime
            new_arts.append(art_out)
            if safe_url:
                links.append((name, safe_url, mime))
            continue

        if data is None:
            new_arts.append(a)
            continue

        presigned = None
        object_key = None
        if objstore.is_configured():
            presigned, object_key = objstore.put_and_presign(
                data, filename=name, content_type=mime, user_id=user_id
            )

        final_url = presigned or (file_url if _is_http_url(file_url) else "")
        # http(s) 以外(javascript:/data:/相対 等)はリンク化・成果物化しない（注入防止）
        safe_url = final_url if _is_http_url(final_url) else ""
        # carrier モードでは自前ストレージに保存できた成果物の署名 URL を UI から隠し、
        # object_key 経由で別途「リンクファイル」を発行させる（LGWAN 端末は本体へ直接届かない）。
        carrier = ARTIFACT_DELIVERY_MODE == "carrier" and bool(object_key)
        art_out = {
            **a,
            "file_url": "" if carrier else safe_url,
            # 再ホストできた非画像 content は UI を URL/carrier に寄せる
            "content": "" if (object_key or safe_url) else a.get("content"),
        }
        if object_key:
            art_out["object_key"] = object_key
        if mime:
            art_out["mime_type"] = mime
        new_arts.append(art_out)
        if carrier:
            carrier_names.append(name)
        elif safe_url:
            links.append((name, safe_url, mime))
        try:
            audit.record(
                request,
                action="file.output",
                usecase="exapp",
                output_text=(
                    f"{name} -> {'objstore' if presigned else 'source-url'}"
                ),
            )
        except Exception:  # noqa: BLE001
            pass

    if isinstance(outputs, str) and (links or carrier_names):
        lines = ["", "## 生成されたファイル", ""]
        for name, url, mime in links:
            # 表示名は Markdown/HTML を無効化（リンク注入・フィッシング防止）
            suffix = f"（{_md_escape(mime)}）" if mime else ""
            lines.append(f"- [{_md_escape(name)}]({url})" + suffix)
        if carrier_names:
            for name in carrier_names:
                lines.append(f"- {_md_escape(name)}")
            lines.append("")
            lines.append(
                "LGWAN 端末からは上記ファイルを直接ダウンロードできません。"
                "下の「リンクファイル」ボタンから取得し、"
                "データ持ち出し経路でインターネット接続端末へ移してから開いてください。"
            )
        outputs = outputs + "\n" + "\n".join(lines)
    return outputs, new_arts


# ---------------------------------------------------------------------------
# キャリアファイル（LGWAN 持ち出し用のダウンロード URL 記載ファイル）生成
# ---------------------------------------------------------------------------
_JST = timezone(timedelta(hours=9))


def _carrier_expiry_text() -> str:
    """キャリア内に記載する URL 有効期限（署名発行時点から S3_PRESIGN_EXPIRY 秒後）。"""
    dt = datetime.now(_JST) + timedelta(seconds=objstore.S3_PRESIGN_EXPIRY)
    return dt.strftime("%Y-%m-%d %H:%M (JST)")


def _carrier_txt(display_name: str, url: str, expiry: str) -> str:
    return (
        "成果物ダウンロード情報\n"
        "====================\n"
        f"ファイル名: {display_name}\n"
        f"有効期限: {expiry}\n"
        "ダウンロードURL:\n"
        f"{url}\n"
        "\n"
        "【手順】\n"
        "1. インターネット接続端末のブラウザで上記 URL を開く\n"
        "2. 表示されたファイルを保存する\n"
        "※ この URL を知っていれば期限内は誰でもダウンロードできます。第三者に共有しないでください。\n"
    )


def _carrier_html(display_name: str, url: str, expiry: str) -> str:
    """外部リソース・スクリプトを含まない単一の静的 HTML を返す。"""
    name = html.escape(display_name)
    href = html.escape(url, quote=True)
    text = html.escape(url)
    exp = html.escape(expiry)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="ja">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>成果物ダウンロード: {name}</title>\n"
        "<style>body{font-family:sans-serif;max-width:720px;margin:40px auto;padding:0 16px;"
        "line-height:1.7;color:#1a1a1a}h1{font-size:1.3rem}"
        ".url{width:100%;box-sizing:border-box;padding:8px;font-family:monospace;font-size:.9rem}"
        ".btn{display:inline-block;margin:12px 0;padding:10px 20px;background:#1a3aad;color:#fff;"
        "text-decoration:none;border-radius:6px}.note{color:#555;font-size:.9rem}</style>\n"
        "</head>\n<body>\n"
        "<h1>成果物ダウンロード情報</h1>\n"
        f"<p>ファイル名: <strong>{name}</strong><br>有効期限: {exp}</p>\n"
        f'<p><a class="btn" href="{href}">インターネット接続端末でダウンロード</a></p>\n'
        "<p>上のボタンが使えない場合は、次の URL をコピーしてブラウザで開いてください。</p>\n"
        f'<textarea class="url" rows="4" readonly>{text}</textarea>\n'
        '<p class="note">※ この URL を知っていれば期限内は誰でもダウンロードできます。'
        "第三者に共有しないでください。</p>\n"
        "</body>\n</html>\n"
    )


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
    security_warn.warn_insecure_defaults()
    storage.init_db()
    teams_store.init_db(seed_exapps=EXAPP_SEEDS)
    for ex_app_id in RETIRED_SEED_EXAPP_IDS:
        teams_store.delete_exapp(COMMON_TEAM_ID, ex_app_id)
    # 各チームに「ナレッジ検索」を1つだけ用意し、旧管理系 RAG アプリは削除（冪等）。
    # 管理は専用ページ /knowledge に統合済み。
    try:
        _ensure_team_rag_search()
    except Exception as e:  # noqa: BLE001
        print(f"[startup] チーム RAG の整理に失敗: {e}")
    audit.start()
    objstore.start_retention_scheduler()
    os.makedirs(FILES_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 認証ミドルウェア（ブラウザ向け API を JWT で保護）
# ---------------------------------------------------------------------------
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or _is_public_path(path):
        return await call_next(request)

    authz = request.headers.get("authorization", "")
    if authz.startswith("Bearer "):
        try:
            auth.verify_token(authz[7:])
            return await call_next(request)
        except Exception:  # noqa: BLE001 - トークン不正は 401 に集約
            pass

    if _patchform_service_request(request):
        return await call_next(request)

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
    # リバースプロキシ配下では request.url.scheme が http のままになるため、
    # X-Forwarded-* を優先して Recipient 検証用の公開 URL を組み立てる。
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("x-forwarded-host") or request.headers.get(
        "host", "localhost:8000"
    )
    forwarded_port = request.headers.get("x-forwarded-port")
    if forwarded_port:
        server_port = forwarded_port
    elif ":" in host:
        server_port = host.split(":", 1)[1]
    else:
        server_port = "443" if forwarded_proto == "https" else "80"
    return {
        "https": "on" if forwarded_proto == "https" else "off",
        "http_host": host,
        "server_port": server_port,
        "script_name": _saml_script_name(request),
        "get_data": dict(request.query_params),
        "post_data": form,
    }


def _saml_script_name(request: Request) -> str:
    """proxy 経由で /api が除去された path を、SAML 検証用に復元する。"""
    path = request.url.path
    prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    if not prefix:
        prefix = PUBLIC_API_PATH_PREFIX
    if prefix and not path.startswith(f"{prefix}/"):
        return f"{prefix}{path}"
    return path


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
    relay = req["post_data"].get("RelayState") or FRONTEND_URL
    target = relay if str(relay).startswith("http") else FRONTEND_URL

    try:
        saml_auth.process_response()
    except Exception as exc:  # noqa: BLE001 — IdP 応答の検証例外をログイン失敗へ落とす
        reason = str(exc) or type(exc).__name__
        print(f"[auth] SAML 検証例外: {reason}")
        audit.record(
            request, action="auth.login", status=401, output_text=f"SAML検証例外: {reason}"
        )
        # Keycloak 再構成後の古い IdP メタデータ/証明書キャッシュを次回で刷新する
        auth.reset_settings_cache()
        return RedirectResponse(f"{FRONTEND_URL}/auth-error", status_code=303)

    errors = saml_auth.get_errors()
    if errors or not saml_auth.is_authenticated():
        reason = saml_auth.get_last_error_reason() or ",".join(errors)
        print(f"[auth] SAML 検証失敗: {reason}")
        audit.record(
            request, action="auth.login", status=401, output_text=f"SAML検証失敗: {reason}"
        )
        # Keycloak 再構成後の古い IdP メタデータ/証明書キャッシュを次回で刷新する
        auth.reset_settings_cache()
        return RedirectResponse(f"{FRONTEND_URL}/auth-error", status_code=303)

    attrs = saml_auth.get_attributes()
    # 識別子(メール)は表記ゆれで別人物扱いにならないよう正規化して用いる
    nameid = teams_store.normalize_email(saml_auth.get_nameid())
    email = teams_store.normalize_email((attrs.get("email") or [nameid])[0])
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
    """無認証向け。モデル一覧など内部情報は含めない。"""
    return {"status": "ok"}


@app.get("/health/details")
async def health_details() -> dict[str, Any]:
    """認証必須。利用可能モデル一覧などを返す。"""
    return {"status": "ok", "models": await llm.list_models()}


# ---------------------------------------------------------------------------
# チャット履歴 (genU API)
# ---------------------------------------------------------------------------
@app.post("/chats")
async def create_chat(request: Request) -> dict[str, Any]:
    user_id = _user_id(_claims_from_request(request))
    body: dict[str, Any] = {}
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - body 省略時はデフォルト usecase
        body = {}
    usecase = body.get("usecase") or "/chat"
    return {"chat": storage.create_chat(user_id, usecase)}


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


IMAGE_RESULT_EXTRA_NAME = "open-genai-generated-image"


@app.put("/chats/{chat_id}/messages/{message_id}/image-result")
async def save_image_result(
    chat_id: str, message_id: str, request: Request
) -> JSONResponse:
    """画像生成結果を assistant メッセージの extraData に永続化する。"""
    user_id = _user_id(_claims_from_request(request))
    body = await request.json()
    images_b64 = body.get("images") or []
    meta = body.get("meta") or {}

    stored_images: list[dict[str, str]] = []
    for b64 in images_b64:
        if not b64:
            continue
        raw_str = b64.split(",", 1)[1] if isinstance(b64, str) and "," in b64 else b64
        try:
            raw = base64.b64decode(raw_str)
        except (ValueError, TypeError):
            continue
        key = f"image-gen/{chat_id}/{message_id}/{uuid.uuid4().hex}.png"
        full = _safe_path(key)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(raw)
        stored_images.append(
            {"fileUrl": filesig.build_signed_url(PUBLIC_BASE_URL, key, "GET")}
        )

    if not stored_images:
        return JSONResponse(status_code=400, content={"message": "images are empty"})

    payload = {"version": 1, **meta, "images": stored_images}
    extra_data = [
        {
            "type": "json",
            "name": IMAGE_RESULT_EXTRA_NAME,
            "source": {
                "type": "json",
                "mediaType": "application/json",
                "data": json.dumps(payload, ensure_ascii=False),
            },
        }
    ]
    updated = storage.update_message_extra_data(
        chat_id, user_id, message_id, extra_data
    )
    if not updated:
        return JSONResponse(status_code=404, content={"message": "message not found"})
    return JSONResponse(content={"message": updated})


# ---------------------------------------------------------------------------
# 推論 (genU API / Lambda ストリーム代替)
# ---------------------------------------------------------------------------
@app.get("/image/health")
async def image_health() -> JSONResponse:
    """画像生成(SD)サーバの稼働状況。フロントの表示出し分けに使う。"""
    ok = await image_gen.is_sd_up()
    return JSONResponse(content={"ok": ok})


@app.post("/image/generate")
async def generate_image(request: Request) -> Response:
    """源内 Web「画像を生成」ページ向け API（Bedrock Lambda 代替）。"""
    body = await request.json()
    params = body.get("params") or {}
    try:
        image_base64 = await image_gen.generate_image_base64(params)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"message": str(exc)})
    except RuntimeError as exc:
        return JSONResponse(status_code=502, content={"message": str(exc)})
    return Response(content=image_base64, media_type="text/plain")


@app.post("/predict")
async def predict(request: Request) -> Response:
    body = await request.json()
    messages = body.get("messages", [])
    denied = _model_denied(_claims_from_request(request), body.get("model"))
    if denied:
        return JSONResponse(status_code=403, content={"error": denied})
    ng = _ngword_denied(request, _last_user_text(messages))
    if ng:
        return JSONResponse(status_code=403, content={"error": ng})
    text = await llm.chat_once(messages, body.get("model"))
    return JSONResponse(content=text)


@app.post("/predict/title")
async def predict_title(request: Request) -> str:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    body = await request.json()
    prompt = body.get("prompt", "")

    if TITLE_MODE == "llm":
        # 許可外モデルではタイトル生成もしない（空タイトルを返す）
        if _model_denied(claims, body.get("model")):
            return ""
        messages = [{"role": "user", "content": prompt}]
        raw = await llm.chat_once(messages, body.get("model"))
        title = titlegen.clean_title(raw)
        # LLM が拒否・空応答のときはユーザー発話から題名を復元する
        if not title:
            title = titlegen.fallback_title_from_prompt(prompt)
    else:
        # 既定: LLM を使わずユーザー発話から決定的に題名を作る
        title = titlegen.fallback_title_from_prompt(prompt)

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
    user_id = _user_id(claims)
    # 本人 ＋ 全体公開 ＋ 所属チーム共有（チームは backend が信頼の根として解決）
    team_ids = [t["teamId"] for t in _member_teams(user_id)]
    return storage.list_system_contexts(user_id, team_ids)


@app.post("/systemcontexts")
async def create_system_context(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    body = await request.json()
    shared_teams, is_public = _resolve_share_teams(user_id, claims, body)
    sc = storage.create_system_context(
        user_id,
        body.get("systemContextTitle", ""),
        body.get("systemContext", ""),
        shared_tags=shared_teams,
        is_public=is_public,
    )
    return JSONResponse(content={"systemContext": sc})


def _resolve_share_teams(
    user_id: str, claims: dict[str, Any], body: dict[str, Any]
) -> tuple[list[str], bool]:
    """保存プロンプトの共有設定を検証して (共有先チームID, 全体公開) を返す。

    チーム共有は自分の所属チームのみ許可（システム管理者は例外）。
    """
    is_public = bool(body.get("isPublic", False))
    requested = body.get("sharedTeams") or []
    if not isinstance(requested, list):
        requested = []
    requested = [str(t).strip() for t in requested if str(t).strip()]
    if not requested:
        return [], is_public
    if _is_system_admin(claims):
        return requested, is_public
    owned = {t["teamId"] for t in _member_teams(user_id)}
    allowed = [t for t in requested if t in owned]
    return allowed, is_public


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


@app.put("/systemcontexts/{sc_id}")
async def update_system_context(sc_id: str, request: Request) -> JSONResponse:
    """保存プロンプトの本文・タイトル・共有設定を更新する（所有者のみ）。"""
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    body = await request.json()
    shared_teams = None
    is_public = None
    if "sharedTeams" in body or "isPublic" in body:
        shared_teams, is_public = _resolve_share_teams(user_id, claims, body)
    sc = storage.update_system_context(
        user_id,
        sc_id,
        title=body.get("systemContextTitle"),
        system_context=body.get("systemContext"),
        shared_tags=shared_teams,
        is_public=is_public,
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
    if not denied:
        denied = _ngword_denied(request, _last_user_text(messages))
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
    allowed = policy.allowed_models(_user_scope_ids(claims), _is_system_admin(claims))
    if allowed is None:
        return JSONResponse(content={"unrestricted": True, "models": []})
    return JSONResponse(content={"unrestricted": False, "models": sorted(allowed)})


# ---------------------------------------------------------------------------
# 管理者限定サービス（modelpolicy / ngword）への書き込みプロキシ共通ヘルパ
#
# 読み取りは backend が読み取り専用で直接参照する。書き込みは各サービスが単一ライター
# のため、管理者権限を検証（403）のうえ内部署名を付けて転送する。
# ---------------------------------------------------------------------------
def _admin_app_url(base_url: str, path: str) -> str:
    if base_url.endswith("/invoke"):
        base = base_url[: -len("/invoke")]
    else:
        base = base_url.rstrip("/")
    return base + path


def _admin_app_headers(
    request: Request, forbid_msg: str
) -> tuple[JSONResponse | None, dict[str, str]]:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden(forbid_msg), {}
    user_id = _user_id(claims)
    groups_str = ",".join(claims.get("groups") or [])
    team_ids = _user_team_ids_str(user_id)
    teams_hdr = _user_teams_header(user_id)
    headers = {
        "x-api-key": RAG_API_KEY,
        "x-user-id": user_id,
        "x-user-groups": groups_str,
        "x-user-tags": team_ids,
        "x-user-teams": teams_hdr,
        "x-scope": ADMIN_TEAM_ID,
        **intauth.signed_headers(user_id, groups_str, ADMIN_TEAM_ID, team_ids),
        "Content-Type": "application/json",
    }
    return None, headers


async def _proxy_admin_app(
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: Any | None,
    label: str,
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502, content={"error": f"{label}に接続できませんでした: {e}"}
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": f"{label}から不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


def _admin_teams_list() -> list[dict[str, str]]:
    """設定対象チーム(id+name)の一覧。固定チーム(共通/管理者ツール)は除外。"""
    try:
        teams = [
            t
            for t in teams_store.list_teams()
            if t["teamId"] not in (COMMON_TEAM_ID, ADMIN_TEAM_ID)
        ]
    except Exception:  # noqa: BLE001
        teams = []
    return [{"id": t["teamId"], "name": t["teamName"]} for t in teams]


@app.get("/admin/model-policy")
async def get_model_policy(request: Request) -> JSONResponse:
    """モデル利用ポリシーの現在値＋設定に必要な選択肢を返す（システム管理者限定）。

    書き込みは管理者限定サービス（modelpolicy-app）が担う。backend は読み取り専用で
    ポリシーを参照し、専用ページ用に利用可能モデルID一覧と設定対象チームも併せて返す。
    """
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("モデル利用ポリシーの閲覧には管理者権限が必要です")
    return JSONResponse(
        content={
            "policy": policy.get_policy(),
            "availableModels": await _available_models_cached(),
            "teams": _admin_teams_list(),
        }
    )


@app.post("/admin/model-policy")
async def set_model_policy(request: Request) -> JSONResponse:
    """モデル利用ポリシーを保存する（単一ライターの modelpolicy-app へプロキシ）。"""
    err, headers = _admin_app_headers(request, "モデル利用ポリシーの変更には管理者権限が必要です")
    if err:
        return err
    body = await request.json()
    return await _proxy_admin_app(
        "POST", _admin_app_url(MODELPOLICY_APP_URL, "/policy"), headers, body, "モデル利用制御サービス"
    )


@app.get("/admin/ngword")
async def get_ngword_rules(request: Request) -> JSONResponse:
    """入力制限ルールの現在値を返す（システム管理者限定・参照のみ）。"""
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("入力制限ルールの閲覧には管理者権限が必要です")
    return JSONResponse(content={"rules": ngwords.get_rules()})


@app.post("/admin/ngword")
async def set_ngword_rules(request: Request) -> JSONResponse:
    """入力制限ルールを保存する（単一ライターの ngword-app へプロキシ）。"""
    err, headers = _admin_app_headers(request, "入力制限ルールの変更には管理者権限が必要です")
    if err:
        return err
    body = await request.json()
    return await _proxy_admin_app(
        "POST", _admin_app_url(NGWORD_APP_URL, "/rules"), headers, body, "入力制限サービス"
    )


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
# ナレッジ管理 専用ページ（/knowledge）用プロキシ
# rag-app の構造化 REST へ、セッション認証 + スコープ別認可のうえプロキシする。
# 認可: 共有(common)スコープの書込は管理者のみ、チームスコープはメンバー(or 管理者)。
# refresh/clear は共有/チームとも管理者のみ（rag-app 側と整合）。
# ---------------------------------------------------------------------------
def _rag_base() -> str:
    return RAG_APP_URL.rsplit("/invoke", 1)[0]


def _knowledge_headers(claims: dict[str, Any], scope: str) -> dict[str, str]:
    user_id = _user_id(claims)
    groups_str = ",".join(claims.get("groups") or [])
    team_ids = _user_team_ids_str(user_id)
    return {
        "x-api-key": RAG_API_KEY,
        "x-user-id": user_id,
        "x-user-groups": groups_str,
        "x-user-tags": team_ids,
        "x-scope": scope,
        **intauth.signed_headers(user_id, groups_str, scope, team_ids),
        "Content-Type": "application/json",
    }


def _knowledge_authz(
    claims: dict[str, Any], scope: str, *, write: bool = False, admin_only: bool = False
) -> JSONResponse | None:
    """スコープ別の認可。None なら許可、JSONResponse ならエラー。"""
    user_id = _user_id(claims)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    scope = (scope or "").strip()
    if not scope:
        return JSONResponse(status_code=400, content={"error": "scope（teamId）が必要です"})
    is_admin = _is_system_admin(claims)
    if scope == COMMON_TEAM_ID:
        # 共有ナレッジ: 読取は全認証ユーザー、書込・管理操作は管理者のみ
        if (write or admin_only) and not is_admin:
            return _forbidden("共有ナレッジの管理には管理者権限が必要です")
        return None
    # チームスコープ: メンバー(or 管理者)。refresh/clear 等は管理者のみ
    if not is_admin and not teams_store.is_team_member(scope, user_id):
        return _forbidden("このチームのナレッジを操作する権限がありません")
    if admin_only and not is_admin:
        return _forbidden("この操作には管理者権限が必要です")
    return None


async def _knowledge_get(
    path: str, claims: dict[str, Any], scope: str, params: dict[str, str] | None = None
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            res = await client.get(
                f"{_rag_base()}{path}",
                params=params or {},
                headers=_knowledge_headers(claims, scope),
            )
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502, content={"error": f"ナレッジサービスに接続できませんでした: {e}"}
        )
    try:
        data = res.json()
    except Exception:  # noqa: BLE001
        data = {"error": "invalid response"}
    return JSONResponse(status_code=res.status_code, content=data)


async def _knowledge_post(
    path: str, claims: dict[str, Any], scope: str, json_body: dict[str, Any]
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            res = await client.post(
                f"{_rag_base()}{path}",
                json=json_body,
                headers=_knowledge_headers(claims, scope),
            )
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502, content={"error": f"ナレッジサービスに接続できませんでした: {e}"}
        )
    try:
        data = res.json()
    except Exception:  # noqa: BLE001
        data = {"error": "invalid response"}
    return JSONResponse(status_code=res.status_code, content=data)


@app.get("/knowledge/scopes")
async def knowledge_scopes(request: Request) -> JSONResponse:
    """操作可能なスコープ一覧（共有 + 所属チーム）。canManage で書込可否を示す。"""
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    is_admin = _is_system_admin(claims)
    scopes: list[dict[str, Any]] = [
        {
            "scope": COMMON_TEAM_ID,
            "name": "共有ナレッジ（共通）",
            "kind": "common",
            "canManage": is_admin,
        }
    ]
    for t in _member_teams(user_id):
        if t["teamId"] in (COMMON_TEAM_ID, ADMIN_TEAM_ID):
            continue
        scopes.append(
            {
                "scope": t["teamId"],
                "name": t.get("teamName") or t["teamId"],
                "kind": "team",
                "canManage": True,
            }
        )
    return JSONResponse(content={"scopes": scopes, "isSystemAdmin": is_admin})


@app.get("/knowledge/tags")
async def knowledge_list_tags(request: Request, scope: str = Query(default="")) -> JSONResponse:
    claims = _claims_from_request(request)
    err = _knowledge_authz(claims, scope)
    if err:
        return err
    return await _knowledge_get("/knowledge/tags", claims, scope, {"scope": scope})


@app.get("/knowledge/docs")
async def knowledge_list_docs(
    request: Request, scope: str = Query(default=""), tags: str = Query(default="")
) -> JSONResponse:
    claims = _claims_from_request(request)
    err = _knowledge_authz(claims, scope)
    if err:
        return err
    params = {"scope": scope}
    if tags:
        params["tags"] = tags
    return await _knowledge_get("/knowledge/docs", claims, scope, params)


def _knowledge_scope_from_body(body: dict[str, Any]) -> str:
    return (body.get("scope") or "").strip()


@app.post("/knowledge/tags")
async def knowledge_create_tag(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/tags", claims, scope, body)


@app.post("/knowledge/tags/rename")
async def knowledge_rename_tag(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/tags/rename", claims, scope, body)


@app.post("/knowledge/tags/delete")
async def knowledge_delete_tag(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/tags/delete", claims, scope, body)


@app.post("/knowledge/register")
async def knowledge_register(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/register", claims, scope, body)


@app.post("/knowledge/urls")
async def knowledge_add_url(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/urls", claims, scope, body)


@app.post("/knowledge/urls/delete")
async def knowledge_delete_url(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/urls/delete", claims, scope, body)


@app.post("/knowledge/urls/refresh")
async def knowledge_refresh_urls(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, admin_only=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/urls/refresh", claims, scope, body)


@app.post("/knowledge/docs/delete")
async def knowledge_delete_doc(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/docs/delete", claims, scope, body)


@app.post("/knowledge/docs/retag")
async def knowledge_retag_doc(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, write=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/docs/retag", claims, scope, body)


@app.post("/knowledge/clear")
async def knowledge_clear(request: Request) -> JSONResponse:
    claims = _claims_from_request(request)
    body = await request.json()
    scope = _knowledge_scope_from_body(body)
    err = _knowledge_authz(claims, scope, admin_only=True)
    if err:
        return err
    return await _knowledge_post("/knowledge/clear", claims, scope, body)


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


_FILE_OPS = {
    "upload": "PUT",
    "download": "GET",
    "delete": "DELETE",
}


def _normalize_file_key(key: str) -> str:
    """pathname 全体や先頭スラッシュをオブジェクトキーへ正規化する。"""
    key = (key or "").lstrip("/")
    for prefix in ("api/files/", "files/"):
        if key.startswith(prefix):
            key = key[len(prefix) :]
            break
    return key


def _require_file_sig(request: Request, key: str, method: str) -> JSONResponse | None:
    """HMAC が無効なら 403 レスポンスを返す。有効なら None。"""
    exp = request.query_params.get("exp")
    sig = request.query_params.get("sig")
    if not filesig.verify(method, key, exp, sig):
        return JSONResponse(
            status_code=403,
            content={"error": "invalid or missing file signature"},
        )
    return None


@app.post("/file/url")
async def get_upload_url(request: Request) -> str:
    """署名付きファイル URL を発行する（upload / download / delete）。

    body:
      - operation: upload（既定）| download | delete
      - filename / mediaFormat: upload 時のファイル名
      - key: download/delete 時のオブジェクトキー（`<uuid>/<name>`）
    """
    body = await request.json()
    operation = str(body.get("operation") or "upload").strip().lower()
    method = _FILE_OPS.get(operation)
    if not method:
        raise HTTPException(
            status_code=400, detail="operation must be upload|download|delete"
        )

    if operation == "upload":
        filename = body.get("filename") or f"file.{body.get('mediaFormat', 'bin')}"
        safe_name = os.path.basename(str(filename)) or "file.bin"
        key = f"{uuid.uuid4()}/{safe_name}"
    else:
        key = _normalize_file_key(str(body.get("key") or body.get("filename") or ""))
        if not key or key != os.path.normpath(key) or key.startswith(".."):
            raise HTTPException(status_code=400, detail="key is required")
        try:
            _safe_path(key)
        except ValueError as e:
            raise HTTPException(status_code=400, detail="invalid key") from e

    return filesig.build_signed_url(PUBLIC_BASE_URL, key, method)


def _guess_media_type(filename: str) -> str:
    """拡張子からおおまかな mediaType を推定する（添付検査用）。"""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "txt": "text/plain",
        "md": "text/markdown",
        "csv": "text/csv",
        "tsv": "text/tab-separated-values",
        "html": "text/html",
        "htm": "text/html",
        "json": "application/json",
        "log": "text/plain",
    }.get(ext, "")


@app.put("/files/{key:path}")
async def put_file(key: str, request: Request) -> dict[str, Any]:
    """添付を保存し、抽出可能な本文があれば個人情報を警告検知する（ブロックしない）。"""
    denied = _require_file_sig(request, key, "PUT")
    if denied:
        return denied  # type: ignore[return-value]

    full = _safe_path(key)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    data = await request.body()
    with open(full, "wb") as f:
        f.write(data)

    result: dict[str, Any] = {"warned": False, "categories": []}
    try:
        from shared.pii_scan import format_warning_message, load_pii_settings, scan
        from shared.docextract import extract_doc_text_full
        import base64 as _b64

        settings = load_pii_settings()
        if not settings.get("warn_attachments", True):
            return result
        filename = os.path.basename(key) or "file"
        media_type = _guess_media_type(filename)
        b64 = _b64.b64encode(data).decode("ascii")
        text = extract_doc_text_full(filename, media_type, b64)
        if not text or text.startswith("(添付ファイル"):
            return result
        scanned = scan(
            text,
            enable_ner=bool(settings.get("check_pii_ner", True)),
            ner_max_chars=int(os.environ.get("PII_NER_MAX_CHARS", "8000")),
            check_mynumber=bool(settings.get("check_mynumber", True)),
        )
        cats = list(scanned.get("categories") or [])
        hits = list(scanned.get("hits") or [])
        if cats:
            result = {
                "warned": True,
                "categories": cats,
                "hits": hits,
                "message": format_warning_message(scanned),
            }
    except Exception as e:  # noqa: BLE001 - 保存自体は成功させる
        print(f"[files] 個人情報検査をスキップ: {e}")
    return result


@app.get("/files/{key:path}")
async def get_file(key: str, request: Request) -> FileResponse:
    denied = _require_file_sig(request, key, "GET")
    if denied:
        return denied  # type: ignore[return-value]
    full = _safe_path(key)
    if not os.path.isfile(full):
        return JSONResponse(status_code=404, content={"message": "file not found"})
    return FileResponse(full)


def _delete_stored_file(key: str) -> None:
    """FILES_DIR 配下のオブジェクトを削除する（存在しなければ何もしない）。"""
    key = _normalize_file_key(key)
    try:
        full = _safe_path(key)
        if os.path.isfile(full):
            os.remove(full)
    except ValueError:
        pass


@app.delete("/files/{key:path}")
async def delete_file_public(key: str, request: Request) -> dict[str, Any]:
    """添付ファイル削除（署名付きクエリ必須。Authorization 不要）。"""
    denied = _require_file_sig(request, key, "DELETE")
    if denied:
        return denied  # type: ignore[return-value]
    _delete_stored_file(key)
    return {}


@app.delete("/file/{file_name:path}")
async def delete_file(file_name: str) -> dict[str, Any]:
    """互換: 旧フロントの /file/<pathname> 削除（JWT 必須。署名付き /files 削除を推奨）。"""
    _delete_stored_file(file_name)
    return {}


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
    # /knowledge へ集約済みの旧管理系は起動時削除するが、残存しても一覧に出さない
    candidates = [
        a for a in candidates if a.get("exAppId") not in RETIRED_SEED_EXAPP_IDS
    ]
    # 管理者限定 exApp（監査ログ参照 等）は非管理者の一覧から隠す
    if not is_admin:
        candidates = [
            a for a in candidates if a.get("exAppId") not in ADMIN_ONLY_EXAPP_IDS
        ]
    checks = await asyncio.gather(
        *[_is_app_up(a["endpoint"]) for a in candidates], return_exceptions=True
    )
    return [a for a, ok in zip(candidates, checks) if ok is True]


@app.get("/my/app-pins")
async def list_my_app_pins(request: Request) -> JSONResponse:
    """本人の AI アプリ ピン留め一覧。"""
    claims = _claims_from_request(request)
    if not _user_id(claims):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return JSONResponse(content={"pins": teams_store.list_user_app_pins(_user_id(claims))})


@app.post("/my/app-pins")
async def add_my_app_pin(request: Request) -> JSONResponse:
    """AI アプリをピン留めする（本人のみ・上限あり）。"""
    claims = _claims_from_request(request)
    if not _user_id(claims):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    body = await request.json()
    team_id = body.get("teamId", "")
    item_id = body.get("itemId", "")
    if not team_id or not item_id:
        return JSONResponse(
            status_code=400, content={"error": "teamId と itemId は必須です"}
        )
    pins, error = teams_store.add_user_app_pin(
        _user_id(claims), team_id, item_id, _is_system_admin(claims)
    )
    if error:
        return JSONResponse(status_code=400, content={"error": error})
    return JSONResponse(content={"pins": pins})


@app.delete("/my/app-pins/{team_id}/{item_id}")
async def remove_my_app_pin(team_id: str, item_id: str, request: Request) -> JSONResponse:
    """ピン留めを解除する（本人のみ）。"""
    claims = _claims_from_request(request)
    if not _user_id(claims):
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    pins = teams_store.remove_user_app_pin(_user_id(claims), team_id, item_id)
    return JSONResponse(content={"pins": pins})


# AI アプリ（dify-app 等）由来エラーのユーザ向け固定文言。
# 生のプロバイダ詳細（モデル名・リージョン等）はここへ載せない。
_EXAPP_ERROR_MESSAGES: dict[str, str] = {
    "RATE_LIMIT": (
        "現在リクエストが集中しています。"
        "しばらく時間をおいてから再度お試しください。"
    ),
    "UPLOAD_FAILED": (
        "ファイルのアップロードに失敗しました。"
        "形式・サイズを確認してから再度お試しください。"
    ),
    "CONNECTION": (
        "サービスに接続できませんでした。時間をおいて再度お試しください。"
    ),
    "INVALID_INPUT": "入力内容を確認してから再度お試しください。",
    "CONTEXT_TOO_LARGE": (
        "入力内容が大きすぎて処理できませんでした。"
        "指示を具体にするか、対象範囲を絞って再度お試しください。"
    ),
    "WORKFLOW_ERROR": (
        "処理中にエラーが発生しました。時間をおいて再度お試しください。"
        "解消しない場合は管理者にお問い合わせください。"
    ),
}
_EXAPP_ERROR_STATUS: dict[str, int] = {
    "RATE_LIMIT": 429,
    "UPLOAD_FAILED": 502,
    "CONNECTION": 502,
    "INVALID_INPUT": 400,
    "CONTEXT_TOO_LARGE": 413,
    "WORKFLOW_ERROR": 502,
}


def _normalize_exapp_error(
    error_code: Any,
    *,
    http_status: int | None = None,
) -> tuple[int, str, str]:
    """既知 error_code のみ信頼し、(status, message, code) を返す。"""
    code = str(error_code or "")
    if http_status == 429:
        code = "RATE_LIMIT"
    if code not in _EXAPP_ERROR_MESSAGES:
        code = "WORKFLOW_ERROR"
    return _EXAPP_ERROR_STATUS[code], _EXAPP_ERROR_MESSAGES[code], code


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

    # 禁止ワード/機密情報の入力制限（管理系 exApp はルール設定で語を含むため除外）
    if ex_app_id not in ADMIN_ONLY_EXAPP_IDS:
        ng = _ngword_denied(request, _texts_from_inputs(inputs), usecase=f"exapp:{ex_app_id}")
        if ng:
            return JSONResponse(status_code=403, content={"error": ng})

    started = _now_iso()
    _groups_str = ",".join(claims.get("groups") or [])
    _team_ids = _user_team_ids_str(user_id)
    _teams_hdr = _user_teams_header(user_id)
    _invoke_headers = {
        "x-api-key": app_def.get("apiKey", ""),
        "x-user-id": user_id,
        # AI アプリ側で管理操作の権限判定に使う
        "x-user-groups": _groups_str,
        # 所属チームID(署名対象)。チーム共有資産の可視判定に使う
        "x-user-tags": _team_ids,
        # 所属チーム(id+name, 表示専用・非署名)。共有先の選択肢ラベルに使う
        "x-user-teams": _teams_hdr,
        # ナレッジのスコープ = AI アプリを所有するチーム(teamId)
        "x-scope": team_id,
        # AI アプリ固有の設定(JSON)。Dify 連携等で接続先の判別に使う
        "x-app-config": _header_config_value(app_def.get("config")),
        # 会話継続(疑似チャット)用のセッション ID
        "x-session-id": session_id,
        # 内部サービス間の署名（x-user-*・x-scope の偽装を防ぐ）
        **intauth.signed_headers(user_id, _groups_str, team_id, _team_ids),
        "Content-Type": "application/json",
    }
    # モデル制御は保存時にチーム名→IDの解決・表示に全チーム(id+name)を使う
    if ex_app_id == "modelpolicy":
        _invoke_headers["x-teams"] = _all_teams_header()

    def _persist_invoke(
        *,
        outputs: str,
        status: str,
        artifacts: Any = None,
        audit_status: int,
    ) -> None:
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
                    "status": status,
                    "progress": "",
                    "artifacts": artifacts,
                    "sessionId": session_id or None,
                }
            )
        except Exception as e:  # noqa: BLE001 - 履歴保存失敗で実行結果は返す
            print(f"[exapps] 履歴の保存に失敗: {e}")
        try:
            audit.record(
                request,
                action="exapp.invoke",
                teamId=team_id,
                exAppId=ex_app_id,
                session_id=session_id or None,
                status=audit_status,
                input_text=(
                    json.dumps(_redact_for_audit(inputs), ensure_ascii=False)
                    if inputs
                    else ""
                ),
                output_text=outputs if isinstance(outputs, str) else json.dumps(
                    outputs, ensure_ascii=False
                ),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[exapps] 監査ログの記録に失敗: {e}")

    try:
        async with httpx.AsyncClient(timeout=600) as client:
            res = await client.post(
                app_def["endpoint"],
                json={"inputs": inputs},
                headers=_invoke_headers,
            )
    except httpx.HTTPError as e:
        print(f"[exapps] AI アプリ接続失敗: {e}")
        ended = _now_iso()
        status_code, message, error_code = _normalize_exapp_error("CONNECTION")
        _persist_invoke(outputs=message, status="ERROR", audit_status=status_code)
        return JSONResponse(
            status_code=status_code,
            content={
                "error": message,
                "error_code": error_code,
                "timestamps": {
                    "processingStartedAt": started,
                    "processingEndedAt": ended,
                },
            },
        )
    ended = _now_iso()

    if res.status_code != 200:
        raw_body = ""
        data: dict[str, Any] = {}
        try:
            data = res.json()
            if not isinstance(data, dict):
                data = {}
        except Exception:  # noqa: BLE001
            raw_body = (res.text or "")[:1000]
            data = {}
        print(
            f"[exapps] AI アプリ呼び出し失敗 status={res.status_code} "
            f"error_code={data.get('error_code')} body={raw_body or data}"
        )
        status_code, message, error_code = _normalize_exapp_error(
            data.get("error_code"),
            http_status=res.status_code,
        )
        _persist_invoke(outputs=message, status="ERROR", audit_status=status_code)
        return JSONResponse(
            status_code=status_code,
            content={
                "error": message,
                "error_code": error_code,
                "timestamps": {
                    "processingStartedAt": started,
                    "processingEndedAt": ended,
                },
            },
        )

    data = res.json()
    outputs = data.get("outputs", "")
    artifacts = data.get("artifacts")

    # 成果物ファイルを自前オブジェクトストレージへ再ホスト（署名付き URL 化）
    try:
        outputs, artifacts = await _rehost_artifacts(request, user_id, outputs, artifacts)
    except Exception as e:  # noqa: BLE001 - 失敗時は元の結果を返す
        print(f"[exapps] 成果物の再ホストに失敗: {e}")

    _persist_invoke(
        outputs=outputs if isinstance(outputs, str) else json.dumps(
            outputs, ensure_ascii=False
        ),
        status="COMPLETED",
        artifacts=artifacts,
        audit_status=200,
    )

    return JSONResponse(
        content={
            "outputs": outputs,
            "artifacts": artifacts,
            "timestamps": {"processingStartedAt": started, "processingEndedAt": ended},
        }
    )


def _derive_stream_endpoint(endpoint: str) -> str:
    """同期 invoke の endpoint URL から、ストリーミング用 URL を導出する。

    例: http://dify-app:8004/invoke -> http://dify-app:8004/invoke/stream
    """
    base = (endpoint or "").rstrip("/")
    if base.endswith("/invoke"):
        return base + "/stream"
    return base + "/invoke/stream"


@app.post("/exapps/invoke/stream")
async def invoke_exapp_stream(request: Request) -> Any:
    """AI アプリ実行を NDJSON でストリーミング中継する（Dify chat 種別専用）。

    dify-app の /invoke/stream からの NDJSON をそのままクライアントへ流し、
    `done` 到達時に成果物を自前ストレージへ再ホストして差し替える。履歴・監査は
    ストリーム完了時に 1 件記録する。chat 以外や未対応 endpoint は 400 を返す。
    """
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

    if ex_app_id in ADMIN_ONLY_EXAPP_IDS and not _is_system_admin(claims):
        return _forbidden("このアプリの実行には管理者権限が必要です")

    if (
        team_id != COMMON_TEAM_ID
        and not _is_system_admin(claims)
        and not teams_store.is_team_member(team_id, user_id)
    ):
        return _forbidden("このアプリを実行する権限がありません")

    if ex_app_id not in ADMIN_ONLY_EXAPP_IDS:
        ng = _ngword_denied(request, _texts_from_inputs(inputs), usecase=f"exapp:{ex_app_id}")
        if ng:
            return JSONResponse(status_code=403, content={"error": ng})

    # ストリーミングは Dify chat 種別のみ対応（フォーム型 workflow は同期 /exapps/invoke）
    try:
        _cfg = json.loads(app_def.get("config") or "{}")
    except (json.JSONDecodeError, TypeError):
        _cfg = {}
    if not isinstance(_cfg, dict) or (
        str(_cfg.get("dify_app_type") or "").strip().lower() != "chat"
    ):
        return JSONResponse(
            status_code=400,
            content={
                "error": "このアプリはストリーミングに対応していません。",
                "error_code": "INVALID_INPUT",
            },
        )

    stream_endpoint = _derive_stream_endpoint(app_def["endpoint"])

    started = _now_iso()
    _groups_str = ",".join(claims.get("groups") or [])
    _team_ids = _user_team_ids_str(user_id)
    _teams_hdr = _user_teams_header(user_id)
    _invoke_headers = {
        "x-api-key": app_def.get("apiKey", ""),
        "x-user-id": user_id,
        "x-user-groups": _groups_str,
        "x-user-tags": _team_ids,
        "x-user-teams": _teams_hdr,
        "x-scope": team_id,
        "x-app-config": _header_config_value(app_def.get("config")),
        "x-session-id": session_id,
        **intauth.signed_headers(user_id, _groups_str, team_id, _team_ids),
        "Content-Type": "application/json",
    }

    def _persist_invoke(
        *,
        outputs: str,
        status: str,
        artifacts: Any = None,
        audit_status: int,
    ) -> None:
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
                    "status": status,
                    "progress": "",
                    "artifacts": artifacts,
                    "sessionId": session_id or None,
                }
            )
        except Exception as e:  # noqa: BLE001 - 履歴保存失敗で実行結果は返す
            print(f"[exapps] 履歴の保存に失敗(stream): {e}")
        try:
            audit.record(
                request,
                action="exapp.invoke",
                teamId=team_id,
                exAppId=ex_app_id,
                session_id=session_id or None,
                status=audit_status,
                input_text=(
                    json.dumps(_redact_for_audit(inputs), ensure_ascii=False)
                    if inputs
                    else ""
                ),
                output_text=outputs if isinstance(outputs, str) else json.dumps(
                    outputs, ensure_ascii=False
                ),
            )
        except Exception as e:  # noqa: BLE001
            print(f"[exapps] 監査ログの記録に失敗(stream): {e}")

    async def _gen():
        def _line(obj: dict[str, Any]) -> str:
            return json.dumps(obj, ensure_ascii=False) + "\n"

        parts: list[str] = []
        final_outputs: Any = ""
        final_artifacts: Any = None
        status = "COMPLETED"
        audit_status = 200
        got_done = False
        terminal = False  # done または error を送出済み
        try:
            async with httpx.AsyncClient(timeout=600) as client:
                async with client.stream(
                    "POST",
                    stream_endpoint,
                    json={"inputs": inputs},
                    headers=_invoke_headers,
                ) as res:
                    if res.status_code != 200:
                        raw = (await res.aread()).decode("utf-8", "replace")
                        try:
                            data = json.loads(raw)
                            if not isinstance(data, dict):
                                data = {}
                        except (json.JSONDecodeError, TypeError):
                            data = {}
                        sc, message, code = _normalize_exapp_error(
                            data.get("error_code"), http_status=res.status_code
                        )
                        status = "ERROR"
                        audit_status = sc
                        final_outputs = message
                        terminal = True
                        yield _line(
                            {"event": "error", "error": message, "error_code": code}
                        )
                        return
                    async for line in res.aiter_lines():
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        event = obj.get("event")
                        if event == "delta":
                            parts.append(obj.get("text", ""))
                            yield line + "\n"
                        elif event == "done":
                            got_done = True
                            outputs = obj.get("outputs", "")
                            artifacts = obj.get("artifacts")
                            try:
                                outputs, artifacts = await _rehost_artifacts(
                                    request, user_id, outputs, artifacts
                                )
                            except Exception as e:  # noqa: BLE001
                                print(f"[exapps] 成果物の再ホストに失敗(stream): {e}")
                            final_outputs = outputs
                            final_artifacts = artifacts
                            done: dict[str, Any] = {"event": "done", "outputs": outputs}
                            if artifacts:
                                done["artifacts"] = artifacts
                            terminal = True
                            yield _line(done)
                        elif event == "error":
                            status = "ERROR"
                            audit_status = 502
                            final_outputs = obj.get("error", "")
                            terminal = True
                            yield line + "\n"
        except httpx.HTTPError as e:
            print(f"[exapps] AI アプリ接続失敗(stream): {e}")
            sc, message, code = _normalize_exapp_error("CONNECTION")
            status = "ERROR"
            audit_status = sc
            final_outputs = message
            if not terminal:
                terminal = True
                yield _line({"event": "error", "error": message, "error_code": code})
        except Exception as e:  # noqa: BLE001
            print(f"[exapps] ストリーム中継で予期せぬエラー: {e}")
            sc, message, code = _normalize_exapp_error("WORKFLOW_ERROR")
            status = "ERROR"
            audit_status = sc
            final_outputs = message
            if not terminal:
                terminal = True
                yield _line({"event": "error", "error": message, "error_code": code})
        finally:
            # done が来ずに接続が途切れた場合は、受信済みの断片を成果として残す
            if status == "COMPLETED" and not got_done:
                final_outputs = "".join(parts)
            _persist_invoke(
                outputs=(
                    final_outputs
                    if isinstance(final_outputs, str)
                    else json.dumps(final_outputs, ensure_ascii=False)
                ),
                status=status,
                artifacts=final_artifacts,
                audit_status=audit_status,
            )

    return StreamingResponse(_gen(), media_type="application/x-ndjson")


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

    # 管理者限定アプリのフォーム定義は非管理者に返さない
    if ex_app_id in ADMIN_ONLY_EXAPP_IDS and not _is_system_admin(claims):
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

    _groups_str = ",".join(claims.get("groups") or [])
    _team_ids = _user_team_ids_str(user_id)
    _teams_hdr = _user_teams_header(user_id)
    _headers = {
        "x-api-key": app_def.get("apiKey", ""),
        "x-app-config": _header_config_value(app_def.get("config")),
        # ローカル AI アプリがスコープ/権限に応じて動的フォームを作れるよう連携
        "x-scope": team_id,
        "x-user-id": user_id,
        "x-user-groups": _groups_str,
        "x-user-tags": _team_ids,
        "x-user-teams": _teams_hdr,
        # 内部サービス間の署名（x-user-*・x-scope の偽装を防ぐ）
        **intauth.signed_headers(user_id, _groups_str, team_id, _team_ids),
    }
    # モデル制御の構造化フォーム用に、利用可能モデルID一覧と全チーム(id+name)を渡す
    if ex_app_id == "modelpolicy":
        _headers["x-available-models"] = ",".join(await _available_models_cached())
        _headers["x-teams"] = _all_teams_header()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.get(schema_url, headers=_headers)
        if res.status_code != 200:
            return JSONResponse(content={"placeholder": {}})
        return JSONResponse(content=res.json())
    except httpx.HTTPError:
        return JSONResponse(content={"placeholder": {}})


@app.post("/exapps/resolve")
async def resolve_exapp_schema(request: Request) -> JSONResponse:
    """OpenGENAI exApp Form Spec v1: リアクティブなフォーム再計算。

    現在のフォーム入力値(inputs)を exApp の `/resolve` へ転送し、再計算された
    フォーム定義(placeholder)を返す。`/exapps/schema` と同じ認可・署名ヘッダを踏襲。
    """
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    body = await request.json()
    team_id = body.get("teamId", "")
    ex_app_id = body.get("exAppId", "")
    inputs = body.get("inputs", {})

    app_def = teams_store.get_exapp(team_id, ex_app_id)
    if not app_def:
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})

    if ex_app_id in ADMIN_ONLY_EXAPP_IDS and not _is_system_admin(claims):
        return JSONResponse(status_code=404, content={"error": "AI アプリが見つかりません"})

    if (
        team_id != COMMON_TEAM_ID
        and not _is_system_admin(claims)
        and not teams_store.is_team_member(team_id, user_id)
    ):
        return _forbidden("このアプリを参照する権限がありません")

    endpoint = app_def.get("endpoint", "")
    if endpoint.endswith("/invoke"):
        resolve_url = endpoint[: -len("/invoke")] + "/resolve"
    else:
        resolve_url = endpoint.rstrip("/") + "/resolve"

    _groups_str = ",".join(claims.get("groups") or [])
    _team_ids = _user_team_ids_str(user_id)
    _teams_hdr = _user_teams_header(user_id)
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            res = await client.post(
                resolve_url,
                json={"inputs": inputs},
                headers={
                    "x-api-key": app_def.get("apiKey", ""),
                    "x-app-config": _header_config_value(app_def.get("config")),
                    "x-scope": team_id,
                    "x-user-id": user_id,
                    "x-user-groups": _groups_str,
                    "x-user-tags": _team_ids,
                    "x-user-teams": _teams_hdr,
                    **intauth.signed_headers(user_id, _groups_str, team_id, _team_ids),
                    "Content-Type": "application/json",
                },
            )
        if res.status_code != 200:
            return JSONResponse(content={"placeholder": {}})
        return JSONResponse(content=res.json())
    except httpx.HTTPError:
        return JSONResponse(content={"placeholder": {}})


# ---------------------------------------------------------------------------
# プロンプトテンプレート専用ページ(/prompts) 用プロキシ
#
# 源内の汎用 exApp フォームでは操作が直感的でないため、専用ページを設ける。
# 認証済み利用者の JWT を検証し、prompt-app の構造化 REST へ HMAC 署名付きで転送する。
# スコープは共通チーム(COMMON_TEAM_ID)固定（プロンプトは全ユーザー利用可）。
# ---------------------------------------------------------------------------
def _prompt_app_url(path: str) -> str:
    if PROMPT_APP_URL.endswith("/invoke"):
        base = PROMPT_APP_URL[: -len("/invoke")]
    else:
        base = PROMPT_APP_URL.rstrip("/")
    return base + path


def _prompt_headers(request: Request) -> tuple[JSONResponse | None, dict[str, str]]:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), {}
    groups_str = ",".join(claims.get("groups") or [])
    team_ids = _user_team_ids_str(user_id)
    teams_hdr = _user_teams_header(user_id)
    headers = {
        "x-api-key": RAG_API_KEY,
        "x-user-id": user_id,
        "x-user-groups": groups_str,
        "x-user-tags": team_ids,
        "x-user-teams": teams_hdr,
        "x-scope": COMMON_TEAM_ID,
        **intauth.signed_headers(user_id, groups_str, COMMON_TEAM_ID, team_ids),
        "Content-Type": "application/json",
    }
    return None, headers


async def _proxy_prompt(
    method: str, url: str, headers: dict[str, str], json_body: Any | None = None
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"プロンプトテンプレートサービスに接続できませんでした: {e}"},
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "プロンプトテンプレートサービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.get("/prompts/templates")
async def list_prompt_templates(request: Request) -> JSONResponse:
    err, headers = _prompt_headers(request)
    if err:
        return err
    return await _proxy_prompt("GET", _prompt_app_url("/templates"), headers)


@app.post("/prompts/templates")
async def create_prompt_template(request: Request) -> JSONResponse:
    err, headers = _prompt_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_prompt("POST", _prompt_app_url("/templates"), headers, body)


@app.delete("/prompts/templates/{template_id}")
async def delete_prompt_template(template_id: str, request: Request) -> JSONResponse:
    err, headers = _prompt_headers(request)
    if err:
        return err
    return await _proxy_prompt(
        "DELETE", _prompt_app_url(f"/templates/{template_id}"), headers
    )


@app.post("/prompts/templates/{template_id}/render")
async def render_prompt_template(template_id: str, request: Request) -> JSONResponse:
    err, headers = _prompt_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_prompt(
        "POST", _prompt_app_url(f"/templates/{template_id}/render"), headers, body
    )


# ---------------------------------------------------------------------------
# 日程調整専用ページ(/chosei) 用プロキシ
#
# Compose profiles: ["chosei"] 未起動時は接続失敗 → 専用ページが有効化案内を表示する。
# スコープは共通チーム(COMMON_TEAM_ID)固定。
# ---------------------------------------------------------------------------
def _chosei_app_url(path: str) -> str:
    if CHOSEI_APP_URL.endswith("/invoke"):
        base = CHOSEI_APP_URL[: -len("/invoke")]
    else:
        base = CHOSEI_APP_URL.rstrip("/")
    return base + path


def _chosei_headers(request: Request) -> tuple[JSONResponse | None, dict[str, str]]:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), {}
    groups_str = ",".join(claims.get("groups") or [])
    team_ids = _user_team_ids_str(user_id)
    teams_hdr = _user_teams_header(user_id)
    headers = {
        "x-api-key": RAG_API_KEY,
        "x-user-id": user_id,
        "x-user-groups": groups_str,
        "x-user-tags": team_ids,
        "x-user-teams": teams_hdr,
        "x-scope": COMMON_TEAM_ID,
        **intauth.signed_headers(user_id, groups_str, COMMON_TEAM_ID, team_ids),
        "Content-Type": "application/json",
    }
    return None, headers


async def _proxy_chosei(
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: Any | None = None,
    *,
    timeout: float = 30,
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "日程調整サービスに接続できませんでした。"
                    "有効化するには `docker compose --profile chosei up -d` "
                    "または `COMPOSE_PROFILES=chosei` を設定してください。"
                    f"（詳細: {e}）"
                ),
                "enabled": False,
            },
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "日程調整サービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.get("/chosei/config")
async def chosei_config(request: Request) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    res = await _proxy_chosei("GET", _chosei_app_url("/config"), headers)
    # サービス側の public_endpoint が空でも、backend 側の env を補完して返す
    if res.status_code == 200:
        try:
            data = json.loads(res.body)
            if isinstance(data, dict) and CHOSEI_PUBLIC_ENDPOINT:
                data["public_endpoint"] = (
                    data.get("public_endpoint") or CHOSEI_PUBLIC_ENDPOINT
                )
            return JSONResponse(status_code=200, content=data)
        except Exception:  # noqa: BLE001
            pass
    return res


@app.get("/chosei/events")
async def chosei_list_events(request: Request) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    return await _proxy_chosei("GET", _chosei_app_url("/events"), headers)


@app.post("/chosei/events")
async def chosei_create_event(request: Request) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_chosei("POST", _chosei_app_url("/events"), headers, body)


@app.get("/chosei/events/{event_id}")
async def chosei_get_event(event_id: str, request: Request) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    return await _proxy_chosei(
        "GET", _chosei_app_url(f"/events/{event_id}"), headers
    )


@app.put("/chosei/events/{event_id}")
async def chosei_update_event(event_id: str, request: Request) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_chosei(
        "PUT", _chosei_app_url(f"/events/{event_id}"), headers, body
    )


@app.delete("/chosei/events/{event_id}")
async def chosei_delete_event(event_id: str, request: Request) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _proxy_chosei(
        "DELETE", _chosei_app_url(f"/events/{event_id}"), headers, body
    )


@app.post("/chosei/events/{event_id}/responses")
async def chosei_submit_response(event_id: str, request: Request) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_chosei(
        "POST", _chosei_app_url(f"/events/{event_id}/responses"), headers, body
    )


@app.delete("/chosei/events/{event_id}/participants/{participant_name}")
async def chosei_delete_participant(
    event_id: str, participant_name: str, request: Request
) -> JSONResponse:
    err, headers = _chosei_headers(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _proxy_chosei(
        "DELETE",
        _chosei_app_url(
            f"/events/{event_id}/participants/{quote(participant_name, safe='')}"
        ),
        headers,
        body,
    )


@app.post("/chosei/assist/parse-dates")
async def chosei_assist_parse_dates(request: Request) -> JSONResponse:
    """自然文から日程候補を抽出（LLM）。"""
    err, headers = _chosei_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_chosei(
        "POST",
        _chosei_app_url("/assist/parse-dates"),
        headers,
        body,
        timeout=120,
    )


@app.post("/chosei/events/{event_id}/assist/recommend")
async def chosei_assist_recommend(event_id: str, request: Request) -> JSONResponse:
    """回答マトリクスから最適日を提案（LLM、失敗時は簡易集計）。"""
    err, headers = _chosei_headers(request)
    if err:
        return err
    return await _proxy_chosei(
        "POST",
        _chosei_app_url(f"/events/{event_id}/assist/recommend"),
        headers,
        {},
        timeout=120,
    )


@app.post("/chosei/events/{event_id}/assist/invite")
async def chosei_assist_invite(event_id: str, request: Request) -> JSONResponse:
    """外部共有向けの案内文を下書き（LLM）。"""
    err, headers = _chosei_headers(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _proxy_chosei(
        "POST",
        _chosei_app_url(f"/events/{event_id}/assist/invite"),
        headers,
        body,
        timeout=120,
    )


@app.get("/chosei/events/{event_id}/carrier")
async def chosei_event_carrier(
    event_id: str, request: Request, format: str = Query(default="txt")
) -> Response:
    """外部共有 URL のリンクファイルをダウンロードさせる（LGWAN carrier）。"""
    err, headers = _chosei_headers(request)
    if err:
        return err
    res = await _proxy_chosei(
        "GET",
        _chosei_app_url(f"/events/{event_id}/carrier") + f"?format={quote(format)}",
        headers,
    )
    if res.status_code != 200:
        return res
    try:
        data = json.loads(res.body)
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": "不正な応答です"})
    content = data.get("content") or ""
    filename = data.get("filename") or "chosei_link.txt"
    fmt = (data.get("format") or format or "txt").lower()
    media = "text/html; charset=utf-8" if fmt == "html" else "text/plain; charset=utf-8"
    ascii_name = "".join(c if c.isascii() and c not in '"\\' else "_" for c in filename)
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=content.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": disposition},
    )


# ---------------------------------------------------------------------------
# 書類領域分割チェック専用ページ(/doccheck) 用プロキシ
#
# Compose profiles: ["doccheck"] 未起動時は接続失敗 → 専用ページが有効化案内を表示する。
# スコープは共通チーム(COMMON_TEAM_ID)固定。
# ---------------------------------------------------------------------------
def _doccheck_app_url(path: str) -> str:
    if DOCCHECK_APP_URL.endswith("/invoke"):
        base = DOCCHECK_APP_URL[: -len("/invoke")]
    else:
        base = DOCCHECK_APP_URL.rstrip("/")
    return base + path


def _doccheck_headers(request: Request) -> tuple[JSONResponse | None, dict[str, str]]:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"}), {}
    groups_str = ",".join(claims.get("groups") or [])
    team_ids = _user_team_ids_str(user_id)
    teams_hdr = _user_teams_header(user_id)
    headers = {
        "x-api-key": RAG_API_KEY,
        "x-user-id": user_id,
        "x-user-groups": groups_str,
        "x-user-tags": team_ids,
        "x-user-teams": teams_hdr,
        "x-scope": COMMON_TEAM_ID,
        **intauth.signed_headers(user_id, groups_str, COMMON_TEAM_ID, team_ids),
        "Content-Type": "application/json",
    }
    return None, headers


async def _proxy_doccheck(
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: Any | None = None,
    *,
    timeout: float = 120,
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "書類読取とチェックサービスに接続できませんでした。"
                    "有効化するには `docker compose --profile doccheck up -d` "
                    "または `COMPOSE_PROFILES=doccheck` を設定してください。"
                    f"（詳細: {e}）"
                ),
                "enabled": False,
            },
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "書類読取とチェックサービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.get("/doccheck/config")
async def doccheck_config(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    claims = _claims_from_request(request)
    res = await _proxy_doccheck("GET", _doccheck_app_url("/config"), headers)
    if res.status_code == 200:
        try:
            data = json.loads(res.body)
            if isinstance(data, dict):
                if DOCCHECK_PUBLIC_ENDPOINT:
                    data["public_endpoint"] = (
                        data.get("public_endpoint") or DOCCHECK_PUBLIC_ENDPOINT
                    )
                # JWT 側のグループ（チーム管理者付与含む）を優先
                data["can_arbitrate"] = _is_team_or_system_admin(claims)
            return JSONResponse(status_code=200, content=data)
        except Exception:  # noqa: BLE001
            pass
    return res


@app.post("/doccheck/demo/seed")
async def doccheck_demo_seed(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _proxy_doccheck(
        "POST", _doccheck_app_url("/demo/seed"), headers, body, timeout=300
    )


@app.get("/doccheck/templates")
async def doccheck_list_templates(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck("GET", _doccheck_app_url("/templates"), headers)


@app.post("/doccheck/templates")
async def doccheck_create_template(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_doccheck("POST", _doccheck_app_url("/templates"), headers, body)


@app.put("/doccheck/templates/{template_id}")
async def doccheck_update_template(template_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_doccheck(
        "PUT", _doccheck_app_url(f"/templates/{template_id}"), headers, body
    )


@app.get("/doccheck/templates/{template_id}")
async def doccheck_get_template(template_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    include = request.query_params.get("include_sample", "")
    q = "?include_sample=true" if include in ("1", "true", "yes") else ""
    return await _proxy_doccheck(
        "GET", _doccheck_app_url(f"/templates/{template_id}{q}"), headers, timeout=180
    )


@app.post("/doccheck/templates/{template_id}/sample")
async def doccheck_upload_sample(template_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_doccheck(
        "POST",
        _doccheck_app_url(f"/templates/{template_id}/sample"),
        headers,
        body,
        timeout=180,
    )


@app.put("/doccheck/templates/{template_id}/regions")
async def doccheck_put_regions(template_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_doccheck(
        "PUT",
        _doccheck_app_url(f"/templates/{template_id}/regions"),
        headers,
        body,
    )


@app.delete("/doccheck/templates/{template_id}")
async def doccheck_delete_template(template_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck(
        "DELETE", _doccheck_app_url(f"/templates/{template_id}"), headers
    )


@app.get("/doccheck/documents")
async def doccheck_list_documents(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    qs = request.url.query
    path = "/documents" + (f"?{qs}" if qs else "")
    return await _proxy_doccheck("GET", _doccheck_app_url(path), headers)


@app.get("/doccheck/batches")
async def doccheck_list_batches(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck("GET", _doccheck_app_url("/batches"), headers)


@app.post("/doccheck/batches")
async def doccheck_create_batch(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_doccheck(
        "POST", _doccheck_app_url("/batches"), headers, body, timeout=600
    )


@app.get("/doccheck/batches/{batch_id}")
async def doccheck_get_batch(batch_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck(
        "GET", _doccheck_app_url(f"/batches/{batch_id}"), headers
    )


@app.post("/doccheck/batches/{batch_id}/dispatch")
async def doccheck_dispatch_batch(batch_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _proxy_doccheck(
        "POST",
        _doccheck_app_url(f"/batches/{batch_id}/dispatch"),
        headers,
        body,
    )


@app.delete("/doccheck/batches/{batch_id}")
async def doccheck_delete_batch(batch_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck(
        "DELETE", _doccheck_app_url(f"/batches/{batch_id}"), headers, timeout=120
    )


@app.get("/doccheck/batches/{batch_id}/export")
async def doccheck_export_batch(
    batch_id: str,
    request: Request,
    format: str = Query(default="csv"),
    status: str = Query(default="completed"),
) -> Response:
    """バッチ確定データのダウンロード（CSV / JSONL / JSON）。"""
    err, headers = _doccheck_headers(request)
    if err:
        return err
    qs = f"?format={quote(format)}&status={quote(status)}"
    res = await _proxy_doccheck(
        "GET",
        _doccheck_app_url(f"/batches/{batch_id}/export") + qs,
        headers,
        timeout=120,
    )
    if res.status_code != 200:
        return res
    try:
        data = json.loads(res.body)
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=502, content={"error": "不正な応答です"})
    content = data.get("content") or ""
    filename = data.get("filename") or "doccheck_export.csv"
    media = data.get("media_type") or "text/csv; charset=utf-8"
    ascii_name = "".join(c if c.isascii() and c not in '"\\' else "_" for c in filename)
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename)}"
    )
    return Response(
        content=content.encode("utf-8"),
        media_type=media,
        headers={"Content-Disposition": disposition},
    )


@app.post("/doccheck/documents")
async def doccheck_create_document(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_doccheck(
        "POST", _doccheck_app_url("/documents"), headers, body, timeout=300
    )


@app.get("/doccheck/documents/{doc_id}")
async def doccheck_get_document(doc_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck(
        "GET", _doccheck_app_url(f"/documents/{doc_id}"), headers
    )


@app.post("/doccheck/documents/{doc_id}/dispatch")
async def doccheck_dispatch(doc_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _proxy_doccheck(
        "POST",
        _doccheck_app_url(f"/documents/{doc_id}/dispatch"),
        headers,
        body,
    )


@app.delete("/doccheck/documents/{doc_id}")
async def doccheck_delete_document(doc_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck(
        "DELETE", _doccheck_app_url(f"/documents/{doc_id}"), headers
    )


@app.get("/doccheck/documents/{doc_id}/export")
async def doccheck_export(doc_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck(
        "GET", _doccheck_app_url(f"/documents/{doc_id}/export"), headers
    )


@app.get("/doccheck/queue/next")
async def doccheck_queue_next(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck("GET", _doccheck_app_url("/queue/next"), headers)


@app.post("/doccheck/tasks/{token}/answer")
async def doccheck_answer(token: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_doccheck(
        "POST",
        _doccheck_app_url(f"/tasks/{token}/answer"),
        headers,
        body,
    )


@app.get("/doccheck/arbitration")
async def doccheck_arbitration_list(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    claims = _claims_from_request(request)
    if not _is_team_or_system_admin(claims):
        return JSONResponse(
            status_code=403,
            content={
                "error": "裁定はチーム管理者またはシステム管理者のみ実行できます",
                "can_arbitrate": False,
            },
        )
    return await _proxy_doccheck("GET", _doccheck_app_url("/arbitration"), headers)


@app.post("/doccheck/arbitration/{region_id}")
async def doccheck_arbitration_post(region_id: str, request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    claims = _claims_from_request(request)
    if not _is_team_or_system_admin(claims):
        return JSONResponse(
            status_code=403,
            content={
                "error": "裁定はチーム管理者またはシステム管理者のみ実行できます",
                "can_arbitrate": False,
            },
        )
    body = await request.json()
    return await _proxy_doccheck(
        "POST",
        _doccheck_app_url(f"/arbitration/{region_id}"),
        headers,
        body,
    )


@app.get("/doccheck/scores/me")
async def doccheck_score_me(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck("GET", _doccheck_app_url("/scores/me"), headers)


@app.get("/doccheck/scores/leaderboard")
async def doccheck_leaderboard(request: Request) -> JSONResponse:
    err, headers = _doccheck_headers(request)
    if err:
        return err
    return await _proxy_doccheck(
        "GET", _doccheck_app_url("/scores/leaderboard"), headers
    )


# ---------------------------------------------------------------------------
# フォーム専用ページ(/patchform) 用プロキシ
#
# Compose profiles: ["patchform"] 未起動時は接続失敗 → 専用ページが有効化案内を表示する。
# スコープは共通チーム(COMMON_TEAM_ID)固定。
# ---------------------------------------------------------------------------
def _patchform_app_url(path: str) -> str:
    if PATCHFORM_APP_URL.endswith("/invoke"):
        base = PATCHFORM_APP_URL[: -len("/invoke")]
    else:
        base = PATCHFORM_APP_URL.rstrip("/")
    return base + path


def _patchform_service_key() -> str:
    return (os.environ.get("PATCHFORM_SERVICE_KEY") or "").strip()


def _patchform_service_ok(request: Request) -> bool:
    expected = _patchform_service_key()
    offered = (request.headers.get("x-service-key") or "").strip()
    if not expected or not offered:
        return False
    return hmac.compare_digest(expected, offered)


def _patchform_service_request(request: Request) -> bool:
    if request.method != "GET":
        return False
    if not _PATCHFORM_SERVICE_PATHS.match(request.url.path):
        return False
    return _patchform_service_ok(request)


def _patchform_headers(request: Request) -> tuple[JSONResponse | None, dict[str, str]]:
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    groups_str = ",".join(claims.get("groups") or [])
    if not user_id:
        if not _patchform_service_request(request):
            return JSONResponse(status_code=401, content={"error": "認証が必要です"}), {}
        user_id = PATCHFORM_SERVICE_USER
        groups_str = "SystemAdminGroup"
    team_ids = _user_team_ids_str(user_id) if user_id != PATCHFORM_SERVICE_USER else ""
    teams_hdr = _user_teams_header(user_id) if user_id != PATCHFORM_SERVICE_USER else ""
    headers = {
        "x-api-key": RAG_API_KEY,
        "x-user-id": user_id,
        "x-user-groups": groups_str,
        "x-user-tags": team_ids,
        "x-user-teams": teams_hdr,
        "x-scope": COMMON_TEAM_ID,
        **intauth.signed_headers(user_id, groups_str, COMMON_TEAM_ID, team_ids),
        "Content-Type": "application/json",
    }
    return None, headers


async def _proxy_patchform(
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: Any | None = None,
    *,
    timeout: float = 30,
) -> JSONResponse:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            res = await client.request(method, url, headers=headers, json=json_body)
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": (
                    "フォームサービスに接続できませんでした。"
                    "有効化するには `docker compose --profile patchform up -d` "
                    "または `COMPOSE_PROFILES=patchform` を設定してください。"
                    f"（詳細: {e}）"
                ),
                "enabled": False,
            },
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "フォームサービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.get("/patchform/config")
async def patchform_config(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    res = await _proxy_patchform("GET", _patchform_app_url("/config"), headers)
    if res.status_code == 200:
        try:
            data = json.loads(res.body)
            if isinstance(data, dict) and PATCHFORM_PUBLIC_ENDPOINT:
                data["public_endpoint"] = (
                    data.get("public_endpoint") or PATCHFORM_PUBLIC_ENDPOINT
                )
            return JSONResponse(status_code=200, content=data)
        except Exception:  # noqa: BLE001
            pass
    return res


@app.get("/patchform/forms")
async def patchform_list_forms(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform("GET", _patchform_app_url("/forms"), headers)


@app.post("/patchform/forms")
async def patchform_create_form(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform("POST", _patchform_app_url("/forms"), headers, body)


@app.get("/patchform/forms/{form_id}")
async def patchform_get_form(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "GET", _patchform_app_url(f"/forms/{form_id}"), headers
    )


@app.put("/patchform/forms/{form_id}")
async def patchform_update_form(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "PUT", _patchform_app_url(f"/forms/{form_id}"), headers, body
    )


@app.delete("/patchform/forms/{form_id}")
async def patchform_delete_form(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "DELETE", _patchform_app_url(f"/forms/{form_id}"), headers
    )


@app.post("/patchform/forms/{form_id}/status")
async def patchform_set_status(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST", _patchform_app_url(f"/forms/{form_id}/status"), headers, body
    )


@app.post("/patchform/forms/{form_id}/submissions")
async def patchform_submit(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST", _patchform_app_url(f"/forms/{form_id}/submissions"), headers, body
    )


@app.get("/patchform/forms/{form_id}/submissions")
async def patchform_list_submissions(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "GET", _patchform_app_url(f"/forms/{form_id}/submissions"), headers
    )


@app.post("/patchform/forms/{form_id}/submissions/{submission_id}/withdraw")
async def patchform_withdraw_submission(
    form_id: str, submission_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url(f"/forms/{form_id}/submissions/{submission_id}/withdraw"),
        headers,
        body,
    )


@app.get("/patchform/forms/{form_id}/submissions/{submission_id}")
async def patchform_reveal_submission(
    form_id: str, submission_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "GET",
        _patchform_app_url(f"/forms/{form_id}/submissions/{submission_id}"),
        headers,
    )


@app.get("/patchform/forms/{form_id}/draft")
async def patchform_get_draft(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform("GET", _patchform_app_url(f"/forms/{form_id}/draft"), headers)


@app.get("/patchform/forms/{form_id}/audit")
async def patchform_list_audit(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform("GET", _patchform_app_url(f"/forms/{form_id}/audit"), headers)


@app.get("/patchform/forms/{form_id}/export")
async def patchform_export(form_id: str, request: Request) -> Response:
    err, headers = _patchform_headers(request)
    if err:
        return err
    fmt = (request.query_params.get("format") or "csv").strip() or "csv"
    reveal = (request.query_params.get("reveal") or "").strip()
    qs = f"?format={quote(fmt)}"
    if reveal:
        qs += f"&reveal={quote(reveal)}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(
                _patchform_app_url(f"/forms/{form_id}/export") + qs,
                headers=headers,
            )
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": f"フォームサービスに接続できませんでした: {e}",
                "enabled": False,
            },
        )
    ctype = res.headers.get("content-type", "")
    if ctype.startswith("text/csv") or "ndjson" in ctype:
        return Response(
            content=res.content,
            media_type=ctype or "text/csv",
            headers={
                "Content-Disposition": res.headers.get(
                    "content-disposition",
                    f'attachment; filename="patchform_{form_id}.{"jsonl" if fmt == "jsonl" else "csv"}"',
                )
            },
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "フォームサービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.post("/patchform/forms/{form_id}/files")
async def patchform_upload_file(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url(f"/forms/{form_id}/files"),
        headers,
        body,
        timeout=120,
    )


@app.get("/patchform/forms/{form_id}/files/{file_id}")
async def patchform_download_file(form_id: str, file_id: str, request: Request) -> Response:
    err, headers = _patchform_headers(request)
    if err:
        return err
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(
                _patchform_app_url(f"/forms/{form_id}/files/{file_id}"),
                headers=headers,
            )
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": f"フォームサービスに接続できませんでした: {e}",
                "enabled": False,
            },
        )
    ctype = res.headers.get("content-type", "")
    if res.status_code == 200 and ctype and not ctype.startswith("application/json"):
        return Response(
            content=res.content,
            media_type=ctype,
            headers={
                "Content-Disposition": res.headers.get(
                    "content-disposition",
                    f'attachment; filename="patchform_{file_id}"',
                )
            },
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "フォームサービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.get("/patchform/lookup/postal")
async def patchform_lookup_postal(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    zipcode = (request.query_params.get("zip") or "").strip()
    return await _proxy_patchform(
        "GET",
        _patchform_app_url("/lookup/postal") + f"?zip={quote(zipcode)}",
        headers,
        timeout=15,
    )


@app.get("/patchform/lookup/corporate")
async def patchform_lookup_corporate(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    number = (request.query_params.get("number") or "").strip()
    return await _proxy_patchform(
        "GET",
        _patchform_app_url("/lookup/corporate") + f"?number={quote(number)}",
        headers,
        timeout=15,
    )


@app.post("/patchform/assist/generate")
async def patchform_assist_generate(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url("/assist/generate"),
        headers,
        body,
        timeout=120,
    )


@app.post("/patchform/extract")
async def patchform_extract(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url("/extract"),
        headers,
        body,
        timeout=120,
    )


@app.post("/patchform/assist/procedure")
async def patchform_assist_procedure(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url("/assist/procedure"),
        headers,
        body,
        timeout=180,
    )


@app.post("/patchform/assist/procedure/apply")
async def patchform_assist_procedure_apply(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url("/assist/procedure/apply"),
        headers,
        body,
        timeout=180,
    )


@app.post("/patchform/assist/invite")
async def patchform_assist_invite(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    return await _proxy_patchform(
        "POST",
        _patchform_app_url("/assist/invite"),
        headers,
        body,
        timeout=120,
    )


@app.get("/patchform/forms/{form_id}/carrier")
async def patchform_carrier(form_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    fmt = request.query_params.get("format") or "txt"
    return await _proxy_patchform(
        "GET",
        _patchform_app_url(f"/forms/{form_id}/carrier") + f"?format={quote(fmt)}",
        headers,
    )


@app.get("/patchform/procedures")
async def patchform_list_procedures(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform("GET", _patchform_app_url("/procedures"), headers)


@app.post("/patchform/procedures")
async def patchform_create_procedure(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform("POST", _patchform_app_url("/procedures"), headers, body)


@app.get("/patchform/procedures/{procedure_id}")
async def patchform_get_procedure(procedure_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "GET", _patchform_app_url(f"/procedures/{procedure_id}"), headers
    )


@app.get("/patchform/procedures/{procedure_id}/share")
async def patchform_procedure_share(procedure_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    qs = request.url.query
    path = f"/procedures/{procedure_id}/share"
    if qs:
        path = f"{path}?{qs}"
    return await _proxy_patchform("GET", _patchform_app_url(path), headers)


@app.put("/patchform/procedures/{procedure_id}")
async def patchform_update_procedure(procedure_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "PUT", _patchform_app_url(f"/procedures/{procedure_id}"), headers, body
    )


@app.post("/patchform/procedures/{procedure_id}/status")
async def patchform_set_procedure_status(
    procedure_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url(f"/procedures/{procedure_id}/status"),
        headers,
        body,
    )


@app.delete("/patchform/procedures/{procedure_id}")
async def patchform_delete_procedure(procedure_id: str, request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "DELETE", _patchform_app_url(f"/procedures/{procedure_id}"), headers
    )


@app.get("/patchform/inbox")
async def patchform_inbox(request: Request) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    qs = request.url.query
    path = f"/inbox?{qs}" if qs else "/inbox"
    return await _proxy_patchform("GET", _patchform_app_url(path), headers)


@app.get("/patchform/procedures/{procedure_id}/applications")
async def patchform_list_applications(
    procedure_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    qs = request.url.query
    path = f"/procedures/{procedure_id}/applications"
    if qs:
        path += f"?{qs}"
    return await _proxy_patchform("GET", _patchform_app_url(path), headers)


@app.get("/patchform/applications/{application_id}")
async def patchform_get_application(
    application_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "GET", _patchform_app_url(f"/applications/{application_id}"), headers
    )


@app.get("/patchform/procedures/{procedure_id}/catalog")
async def patchform_procedure_catalog(
    procedure_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "GET", _patchform_app_url(f"/procedures/{procedure_id}/catalog"), headers
    )


@app.post("/patchform/applications/{application_id}/items")
async def patchform_add_application_item(
    application_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url(f"/applications/{application_id}/items"),
        headers,
        body,
    )


@app.post("/patchform/applications/{application_id}/items/{item_id}/file")
async def patchform_fulfill_application_item(
    application_id: str, item_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_patchform(
        "POST",
        _patchform_app_url(f"/applications/{application_id}/items/{item_id}/file"),
        headers,
        body,
        timeout=60,
    )


@app.delete("/patchform/applications/{application_id}/items/{item_id}/file")
async def patchform_clear_application_item(
    application_id: str, item_id: str, request: Request
) -> JSONResponse:
    err, headers = _patchform_headers(request)
    if err:
        return err
    return await _proxy_patchform(
        "DELETE",
        _patchform_app_url(f"/applications/{application_id}/items/{item_id}/file"),
        headers,
    )


async def _proxy_patchform_export(path: str, request: Request, fallback_name: str) -> Response:
    err, headers = _patchform_headers(request)
    if err:
        return err
    fmt = (request.query_params.get("format") or "csv").strip() or "csv"
    qs = f"?format={quote(fmt)}"
    since = (request.query_params.get("since") or "").strip()
    if since:
        qs += f"&since={quote(since)}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.get(_patchform_app_url(path) + qs, headers=headers)
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=503,
            content={
                "error": f"フォームサービスに接続できませんでした: {e}",
                "enabled": False,
            },
        )
    ctype = res.headers.get("content-type", "")
    if res.status_code == 200 and (
        ctype.startswith("text/csv") or "ndjson" in ctype
    ):
        ext = "jsonl" if fmt == "jsonl" else "csv"
        return Response(
            content=res.content,
            media_type=ctype or "text/csv",
            headers={
                "Content-Disposition": res.headers.get(
                    "content-disposition",
                    f'attachment; filename="{fallback_name}.{ext}"',
                )
            },
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "フォームサービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.get("/patchform/procedures/{procedure_id}/export")
async def patchform_export_procedure(procedure_id: str, request: Request) -> Response:
    return await _proxy_patchform_export(
        f"/procedures/{procedure_id}/export",
        request,
        f"procedure_{procedure_id}",
    )


@app.get("/patchform/applications/{application_id}/export")
async def patchform_export_application(application_id: str, request: Request) -> Response:
    return await _proxy_patchform_export(
        f"/applications/{application_id}/export",
        request,
        f"application_{application_id}",
    )


# ---------------------------------------------------------------------------
# 利用者一括管理 専用ページ(/admin/users) 用プロキシ（管理者限定）
#
# 汎用 exApp フォーム（Markdown 出力）では一覧・ドライラン・適用の往復がしづらいため、
# 専用ページから叩く構造化 REST を usermgmt-app へ転送する。backend 側で管理者権限を
# 検証（403）し、内部署名を付けて転送する。スコープは管理者専用チーム(ADMIN_TEAM_ID)。
# ---------------------------------------------------------------------------
def _usermgmt_app_url(path: str) -> str:
    if USERMGMT_APP_URL.endswith("/invoke"):
        base = USERMGMT_APP_URL[: -len("/invoke")]
    else:
        base = USERMGMT_APP_URL.rstrip("/")
    return base + path


def _usermgmt_headers(request: Request) -> tuple[JSONResponse | None, dict[str, str]]:
    claims = _claims_from_request(request)
    if not _is_system_admin(claims):
        return _forbidden("利用者一括管理には管理者権限が必要です"), {}
    user_id = _user_id(claims)
    groups_str = ",".join(claims.get("groups") or [])
    team_ids = _user_team_ids_str(user_id)
    teams_hdr = _user_teams_header(user_id)
    headers = {
        "x-api-key": RAG_API_KEY,
        "x-user-id": user_id,
        "x-user-groups": groups_str,
        "x-user-tags": team_ids,
        "x-user-teams": teams_hdr,
        "x-scope": ADMIN_TEAM_ID,
        **intauth.signed_headers(user_id, groups_str, ADMIN_TEAM_ID, team_ids),
        "Content-Type": "application/json",
    }
    return None, headers


async def _proxy_usermgmt(
    method: str,
    url: str,
    headers: dict[str, str],
    json_body: Any | None = None,
    params: dict[str, Any] | None = None,
) -> JSONResponse:
    try:
        # 適用は Keycloak への多数の書き込みを伴うため長めのタイムアウト。
        async with httpx.AsyncClient(timeout=180) as client:
            res = await client.request(
                method, url, headers=headers, json=json_body, params=params
            )
    except httpx.HTTPError as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"利用者管理サービスに接続できませんでした: {e}"},
        )
    try:
        payload = res.json()
    except ValueError:
        payload = {"error": "利用者管理サービスから不正な応答を受け取りました"}
    return JSONResponse(status_code=res.status_code, content=payload)


@app.get("/admin/users")
async def list_admin_users(request: Request) -> JSONResponse:
    err, headers = _usermgmt_headers(request)
    if err:
        return err
    qp = request.query_params
    params = {
        "search": qp.get("search") or "",
        "limit": qp.get("limit") or "200",
    }
    return await _proxy_usermgmt(
        "GET", _usermgmt_app_url("/users"), headers, params=params
    )


@app.post("/admin/users/plan")
async def plan_admin_users(request: Request) -> JSONResponse:
    err, headers = _usermgmt_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_usermgmt(
        "POST", _usermgmt_app_url("/users/plan"), headers, body
    )


@app.post("/admin/users/apply")
async def apply_admin_users(request: Request) -> JSONResponse:
    err, headers = _usermgmt_headers(request)
    if err:
        return err
    body = await request.json()
    return await _proxy_usermgmt(
        "POST", _usermgmt_app_url("/users/apply"), headers, body
    )


@app.get("/me/teams")
async def get_my_teams(request: Request) -> JSONResponse:
    """ログインユーザー自身の所属チーム（共有先の選択肢に使う）。"""
    claims = _claims_from_request(request)
    return JSONResponse(content={"teams": _member_teams(_user_id(claims))})


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
    request: Request,
    teamId: str = Query(default=""),
    exAppId: str = Query(default=""),
    createdDate: str = Query(default=""),
) -> dict[str, Any]:
    # GetInvokeExAppHistoryResponse（本人の履歴のみ）
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if not teamId or not exAppId or not createdDate:
        return {"history": None}
    if (
        teamId != COMMON_TEAM_ID
        and not _is_system_admin(claims)
        and not teams_store.is_team_member(teamId, user_id)
    ):
        return {"history": None}
    hist = teams_store.get_exapp_history(teamId, exAppId, createdDate, user_id)
    return {"history": hist}


@app.get("/exapps/artifact-carrier")
async def get_artifact_carrier(
    request: Request,
    objectKey: str = Query(default=""),
    s3Url: str = Query(default=""),
    format: str = Query(default=""),
) -> Response:
    """成果物のダウンロード URL を記載した「リンクファイル(.txt/.html)」を返す。

    LGWAN 端末は成果物本体へ直接アクセスできないため、URL を記したファイルを
    ダウンロードさせ、データ持ち出し経路でインターネット接続端末へ移して開く運用を支える。
    """
    claims = _claims_from_request(request)
    user_id = _user_id(claims)
    if not user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})

    key = (objectKey or "").strip()
    if not key and s3Url:
        key = objstore.key_from_url(s3Url) or ""
    if not key or not objstore.is_managed_key(key):
        return JSONResponse(status_code=400, content={"error": "オブジェクトキーが不正です"})

    # 所有者チェック（キーの user_hash セグメント一致。管理者は横断可）
    if not objstore.owns_key(key, user_id) and not _is_system_admin(claims):
        return _forbidden("このファイルにアクセスする権限がありません")

    url = objstore.presign_existing(key)
    if not url:
        return JSONResponse(status_code=404, content={"error": "ファイルが見つかりません"})

    display_name = objstore.filename_from_key(key)
    expiry = _carrier_expiry_text()

    fmt = (format or "").strip().lower()
    if fmt not in ("txt", "html"):
        fmt = "html" if ARTIFACT_CARRIER_FORMAT == "html" else "txt"

    if fmt == "html":
        body = _carrier_html(display_name, url, expiry)
        media_type = "text/html; charset=utf-8"
        carrier_name = f"{display_name}_link.html"
    else:
        body = _carrier_txt(display_name, url, expiry)
        media_type = "text/plain; charset=utf-8"
        carrier_name = f"{display_name}_link.txt"

    try:
        audit.record(
            request,
            action="file.carrier",
            usecase="exapp",
            output_text=f"{display_name} ({fmt})",
        )
    except Exception:  # noqa: BLE001
        pass

    ascii_name = objstore.sanitize_filename(carrier_name)
    disposition = (
        f'attachment; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(carrier_name)}"
    )
    return Response(
        content=body.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": disposition},
    )


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
    # 共通チーム・管理者ツールチームはシステム管理下の固定チームのため管理対象から除外
    teams = [
        t for t in teams if t["teamId"] not in (COMMON_TEAM_ID, ADMIN_TEAM_ID)
    ]
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
    # 新規チームには「ナレッジ検索」のみ自動登録。
    # タグ管理・登録・管理は専用ページ /knowledge（スコープ選択）で行う。
    teams_store.create_exapp(team["teamId"], _team_rag_search_app(team_name))
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
                headers={
                    "x-api-key": RAG_API_KEY,
                    # システム操作として scope をバインドして署名
                    **intauth.signed_headers("system", "", team_id),
                },
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
    email = teams_store.normalize_email(body.get("email", ""))
    if not email:
        return JSONResponse(status_code=400, content={"error": "email は必須です"})
    # 既存メンバーは追加ではなく明示的な「更新」で権限変更する（黙って上書きしない）
    if teams_store.get_team_user(team_id, email):
        return JSONResponse(
            status_code=409,
            content={
                "error": (
                    "このメールアドレスは既にこのチームのメンバーです。"
                    "権限の変更はメンバー一覧の更新から行ってください。"
                )
            },
        )
    user = teams_store.create_team_user(team_id, email, bool(body.get("isAdmin")))
    if user is None:
        return JSONResponse(status_code=409, content={"error": "既にメンバーです。"})
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
    # 管理者限定アプリ（監査ログ参照等）は非管理者に定義(apiKey含む)を返さない
    if ex_app_id in ADMIN_ONLY_EXAPP_IDS and not _is_system_admin(claims):
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
        if _is_system_admin(claims):
            hist = teams_store.get_exapp_history(team_id, ex_app_id, createdDate)
        else:
            hist = teams_store.get_exapp_history(
                team_id, ex_app_id, createdDate, user_id
            )
        if hist and objstore.is_configured():
            objstore.delete_keys(objstore.keys_from_artifacts(hist.get("artifacts")))
        if _is_system_admin(claims):
            teams_store.delete_exapp_history(team_id, ex_app_id, createdDate)
        else:
            teams_store.delete_exapp_history(
                team_id, ex_app_id, createdDate, user_id
            )
    return JSONResponse(content={})
