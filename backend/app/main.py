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

from shared import ssrfguard

from . import audit, auth, image_gen, intauth, llm, ngwords, objstore, policy, storage, teams_store

# ファイル添付の保存先と、ブラウザから見たバックエンドの公開 URL
FILES_DIR = os.environ.get("FILES_DIR", "/data/files")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://localhost:8000")

# リバースプロキシが /api を除去して転送する場合の公開 API パス prefix（SAML Recipient 検証用）
PUBLIC_API_PATH_PREFIX = os.environ.get("PUBLIC_API_PATH_PREFIX", "/api").rstrip("/")

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

# 禁止ワード/機密情報 入力制限「AI アプリ」連携先（管理者限定）
NGWORD_APP_URL = os.environ.get("NGWORD_APP_URL", "http://ngword-app:8008/invoke")

# プロンプトテンプレート「AI アプリ」連携先（全ユーザー利用可）
PROMPT_APP_URL = os.environ.get("PROMPT_APP_URL", "http://prompt-app:8009/invoke")

# 管理者(SystemAdminGroup)のみに一覧表示・実行を許可する exApp
# （rag-manage は共有ナレッジの管理＝共通チームのため管理者限定）
ADMIN_ONLY_EXAPP_IDS = {"audit", "usermgmt", "modelpolicy", "ngword", "rag-manage"}

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
        "- **タグ**: 分類ラベルです。指定すると、そのタグの付いた資料だけを検索します"
        "（複数選択可・未指定なら全体を検索）。\n"
        "- **参照件数**: 多いほど広く探しますが、無関係な資料が混ざることもあります（1〜10）。\n\n"
        "## こんなときは\n\n"
        "- 期待した資料が出ない: タグ指定を外す／件数を増やす／質問の言い回しを変える。\n"
        "- 一度だけ資料を読ませたい: チャットのファイル添付をご利用ください"
        "（この共有ナレッジには保存されません）。\n"
        "- 資料の追加・修正: 「ナレッジ管理」（管理者）で行います。"
    ),
    "copyable": False,
    "status": "published",
}

# 共有ナレッジの「管理」アプリ（管理者限定）。検索は含めない。
RAG_MANAGE_SEED: dict[str, Any] = {
    "exAppId": "rag-manage",
    "teamId": ADMIN_TEAM_ID,
    "exAppName": "ナレッジ管理（管理者）",
    "endpoint": RAG_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": '{"dynamic_schema": true, "rag_role": "manage"}',
    "placeholder": "",
    "description": "共有ナレッジのドキュメント・タグ・URL を管理します（システム管理者のみ）。",
    "howToUse": (
        "## このアプリでできること（管理者）\n\n"
        "検索アプリが参照する共有ナレッジ（登録資料・取り込みURL）を整備します。"
        "「操作」を選ぶと、それに必要な入力欄だけが表示されます。\n\n"
        "## ドキュメントを登録する\n\n"
        "1. 「操作」で「ドキュメント登録（タグ付け）」を選びます。\n"
        "2. 「登録するドキュメント」にファイルを添付します"
        "（PDF/Word/Excel/テキスト/Markdown/CSV/HTML 等）。\n"
        "3. 「付与するタグ」に分類ラベルを `,` または `;` 区切りで入力します（例 `総務,例規`）。\n"
        "4. 「実行」で登録します。登録後は検索アプリで参照されます。\n\n"
        "## 一覧・削除\n\n"
        "- 「ドキュメント一覧」: 登録済みの資料を確認（タグで絞り込み可）。\n"
        "- 「ドキュメント削除」: 対象を選んで削除します（確認ダイアログあり・元に戻せません）。\n\n"
        "## URL を取り込む（自動更新の対象）\n\n"
        "1. 「操作」で「URL取り込み」を選びます。\n"
        "2. 「取り込む URL」に http/https の URL を入力し、必要ならタグを付けます。\n"
        "3. 取り込んだ URL は定期的に再取得され、内容の更新に追従します。\n"
        "- 「URL一覧」「URL削除」「URL再取り込み」で管理できます。\n\n"
        "## 注意\n\n"
        "- 「ナレッジを全消去」はこの共有ナレッジを空にします（確認あり・元に戻せません）。\n"
        "- アクセス制御はチーム単位です。共有ナレッジは全員が参照できます。\n"
        "- チーム専用ナレッジは、各チームの「ナレッジ管理」アプリから管理してください。"
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
    '{'
    '"operation":{"type":"select","title":"操作",'
    '"desc":"まずドライランで内容を確認し、問題なければ適用してください。",'
    '"items":[{"title":"ドライラン（変更しない）","value":"dry_run"},'
    '{"title":"適用（Keycloakに反映）","value":"apply",'
    '"confirm":"CSVの内容をKeycloakに反映します（利用者の作成・更新・削除を含む）。'
    '削除は元に戻せません。ドライランで確認済みですか？"}],'
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
    "teamId": ADMIN_TEAM_ID,
    "exAppName": "利用者一括管理（管理者限定）",
    "endpoint": USERMGMT_APP_URL,
    "apiKey": RAG_API_KEY,
    "config": "",
    "placeholder": _USERMGMT_FORM,
    "description": "CSV で利用者アカウントを一括登録/更新/削除します（システム管理者のみ）。",
    "howToUse": (
        "## このアプリでできること（管理者）\n\n"
        "CSV を使って利用者アカウント（Keycloak）を一括で作成・更新・削除します。\n\n"
        "## CSV の準備\n\n"
        "1行目に見出し、2行目以降に利用者を記載します。見出し例:\n\n"
        "```\naction,username,email,name,password,groups,enabled\n"
        "upsert,yamada,yamada@example.com,山田太郎,Passw0rd!,UserGroup,true\n```\n\n"
        "- **action**: `create`（新規）/`update`（更新）/`delete`（削除）/`upsert`（無ければ作成・あれば更新／既定）。\n"
        "- **username**: 必須。ログインID。\n"
        "- **email / name**: メールアドレス・氏名。\n"
        "- **password**: 新規作成時の初期パスワード（更新時は変更したい場合のみ）。\n"
        "- **groups**: 権限グループ（例 `SystemAdminGroup`＝システム管理者）。`;` か `,` 区切り。\n"
        "- **enabled**: 有効/無効（`true`/`false`）。\n\n"
        "## 操作手順\n\n"
        "1. CSV ファイルを添付するか、「CSV（貼り付け）」に直接貼り付けます。\n"
        "2. 「操作」で「ドライラン」を選んで実行し、**対象と操作内容を必ず確認**します（この時点では変更されません）。\n"
        "3. 問題なければ「操作」を「適用」にして実行します（確認ダイアログが表示されます）。\n\n"
        "## 注意\n\n"
        "- 「適用」は作成・更新・**削除**を伴い、削除は元に戻せません。必ずドライランで確認してください。\n"
        "- パスワード列を含む CSV の保管・共有には十分注意してください。"
    ),
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
        "- 禁止ワード・機密情報パターンは1行に1件で入力します。\n"
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


def _team_rag_manage_app(team_name: str) -> dict[str, Any]:
    return {
        "exAppName": f"{team_name}のナレッジ管理",
        "endpoint": RAG_APP_URL,
        "apiKey": RAG_API_KEY,
        "config": '{"dynamic_schema": true, "rag_role": "manage"}',
        "placeholder": "",
        "description": f"「{team_name}」チームのナレッジ管理（ドキュメント/タグ/URL）です。",
        "howToUse": (
            "## 使い方\n\n"
            "このチームのナレッジを整備します。\n\n"
            "- ドキュメントの登録（タグ付け）／一覧／削除、タグ一覧の確認\n"
            "- URL の取り込み/一覧/削除/再取り込み・全消去は管理者\n"
        ),
        "copyable": False,
        "status": "published",
    }


def _rag_role_of(app: dict[str, Any]) -> str | None:
    try:
        cfg = json.loads(app.get("config") or "{}")
    except (json.JSONDecodeError, TypeError):
        return None
    return cfg.get("rag_role")


def _ensure_team_rag_split() -> None:
    """既存チームの RAG アプリを「検索」「管理」の2アプリに分割・最新化する（冪等）。

    role は config の rag_role で判定する（placeholder は動的フォーム化で空のため）。
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
        if not apps:
            continue
        # 既存の検索/管理アプリは表示名・説明を最新定義へ更新（リネーム等の反映）
        for a in apps:
            role = _rag_role_of(a)
            if role == "search":
                teams_store.update_exapp(team_id, a["exAppId"], _team_rag_search_app(tname))
            elif role == "manage":
                teams_store.update_exapp(team_id, a["exAppId"], _team_rag_manage_app(tname))
        has_search = any(_rag_role_of(a) == "search" for a in apps)
        has_manage = any(_rag_role_of(a) == "manage" for a in apps)
        legacy = [a for a in apps if _rag_role_of(a) not in ("search", "manage")]
        # 旧・統合アプリで不足ロール（検索→管理の順）を補填し、余剰は削除して重複を防ぐ。
        for a in legacy:
            if not has_search:
                teams_store.update_exapp(
                    team_id, a["exAppId"], _team_rag_search_app(tname)
                )
                has_search = True
            elif not has_manage:
                teams_store.update_exapp(
                    team_id, a["exAppId"], _team_rag_manage_app(tname)
                )
                has_manage = True
            else:
                # 検索・管理が揃っているのに残るレガシーは重複のため削除
                teams_store.delete_exapp(team_id, a["exAppId"])
        if not has_search:
            teams_store.create_exapp(team_id, _team_rag_search_app(tname))
        if not has_manage:
            teams_store.create_exapp(team_id, _team_rag_manage_app(tname))


EXAPP_SEEDS = [
    RAG_SEED,
    RAG_MANAGE_SEED,
    WHISPER_SEED,
    AUDIT_SEED,
    USERMGMT_SEED,
    MODELPOLICY_SEED,
    NGWORD_SEED,
    PROMPT_SEED,
]

# 源内 Web の汎用ページに統合したため exApp 登録を廃止した ID
RETIRED_SEED_EXAPP_IDS = ["sd"]


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


# 成果物取得（SSRF 対策）の設定
# - ARTIFACT_FETCH_ALLOWED_HOSTS が指定されていれば、そのホストのみ取得を許可（推奨）。
# - 未指定でも、プライベート/ループバック/リンクローカル等の内部宛先は常に拒否する。
# - 取得は shared.ssrfguard 経由（DNS リバインディング対策・リダイレクト都度検証つき）。
_ARTIFACT_ALLOWED_HOSTS = {
    h.strip().lower()
    for h in os.environ.get("ARTIFACT_FETCH_ALLOWED_HOSTS", "").split(",")
    if h.strip()
}
_ARTIFACT_MAX_BYTES = int(os.environ.get("ARTIFACT_MAX_BYTES", str(50 * 1024 * 1024)))


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

    - `content`(base64) のアーティファクト（例: 画像）はインライン用にそのまま。
    - `file_url`(外部参照, 例: Dify 署名URL) は実体を取得し、S3 互換(SeaweedFS)へ
      アップロードして**自前の署名付き URL**へ差し替え、`outputs` に DL リンクを付す。
    - オブジェクトストレージ未設定時は、取得元 URL をそのままリンクとして提示（フォールバック）。
    """
    if not artifacts or not isinstance(artifacts, list):
        return outputs, artifacts

    links: list[tuple[str, str, str]] = []
    new_arts: list[Any] = []
    for a in artifacts:
        if not isinstance(a, dict):
            new_arts.append(a)
            continue
        if a.get("content"):
            new_arts.append(a)  # インライン（画像等）はそのまま
            continue
        file_url = a.get("file_url") or ""
        name = a.get("display_name") or "file"
        mime = a.get("mime_type") or ""
        if not file_url:
            new_arts.append(a)
            continue

        data: bytes | None = None
        if file_url.startswith("http://") or file_url.startswith("https://"):
            data, fetched_mime = await _fetch_artifact(file_url)
            if data is not None:
                mime = mime or fetched_mime

        presigned = None
        if data is not None and objstore.is_configured():
            presigned = objstore.put_and_presign(
                data, filename=name, content_type=mime, user_id=user_id
            )

        final_url = presigned or file_url
        # http(s) 以外(javascript:/data:/相対 等)はリンク化・成果物化しない（注入防止）
        safe_url = final_url if _is_http_url(final_url) else ""
        new_arts.append({**a, "file_url": safe_url})
        if safe_url:
            links.append((name, safe_url, (mime or "").split(";")[0].strip()))
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

    if links and isinstance(outputs, str):
        lines = ["", "## 生成されたファイル", ""]
        for name, url, mime in links:
            # 表示名は Markdown/HTML を無効化（リンク注入・フィッシング防止）
            suffix = f"（{_md_escape(mime)}）" if mime else ""
            lines.append(f"- [{_md_escape(name)}]({url})" + suffix)
        outputs = outputs + "\n" + "\n".join(lines)
    return outputs, new_arts

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
    for ex_app_id in RETIRED_SEED_EXAPP_IDS:
        teams_store.delete_exapp(COMMON_TEAM_ID, ex_app_id)
    # 既存チームの RAG アプリを「検索」「管理」に分割・最新化（冪等）。
    try:
        _ensure_team_rag_split()
    except Exception as e:  # noqa: BLE001
        print(f"[startup] チーム RAG の分割・最新化に失敗: {e}")
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
    forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
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
        stored_images.append({"fileUrl": f"{PUBLIC_BASE_URL}/files/{key}"})

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
        "x-app-config": app_def.get("config", "") or "",
        # 会話継続(疑似チャット)用のセッション ID
        "x-session-id": session_id,
        # 内部サービス間の署名（x-user-*・x-scope の偽装を防ぐ）
        **intauth.signed_headers(user_id, _groups_str, team_id, _team_ids),
        "Content-Type": "application/json",
    }
    # モデル制御は保存時にチーム名→IDの解決・表示に全チーム(id+name)を使う
    if ex_app_id == "modelpolicy":
        _invoke_headers["x-teams"] = _all_teams_header()
    try:
        async with httpx.AsyncClient(timeout=600) as client:
            res = await client.post(
                app_def["endpoint"],
                json={"inputs": inputs},
                headers=_invoke_headers,
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

    # 成果物ファイルを自前オブジェクトストレージへ再ホスト（署名付き URL 化）
    try:
        outputs, artifacts = await _rehost_artifacts(request, user_id, outputs, artifacts)
    except Exception as e:  # noqa: BLE001 - 失敗時は元の結果を返す
        print(f"[exapps] 成果物の再ホストに失敗: {e}")

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
        "x-app-config": app_def.get("config", "") or "",
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
                    "x-app-config": app_def.get("config", "") or "",
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
    # 新規チームに「検索」「管理」の2アプリを自動登録（利用と管理を分離・ナレッジはチームに閉じる）
    teams_store.create_exapp(team["teamId"], _team_rag_search_app(team_name))
    teams_store.create_exapp(team["teamId"], _team_rag_manage_app(team_name))
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
            teams_store.delete_exapp_history(team_id, ex_app_id, createdDate)
        else:
            teams_store.delete_exapp_history(
                team_id, ex_app_id, createdDate, user_id
            )
    return JSONResponse(content={})
