# Open GENAI

![Version](https://img.shields.io/badge/version-0.6.0-blue)
![License](https://img.shields.io/badge/license-MIT-blue)
![LLM](https://img.shields.io/badge/LLM-Ollama%20%2F%20OpenAI--compatible-0a7)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20React%20%7C%20Qdrant%20%7C%20Keycloak-success)
![Host](https://img.shields.io/badge/host-macOS%20%7C%20Linux%2BNVIDIA-lightgrey)
![Status](https://img.shields.io/badge/status-experimental-orange)

デジタル庁がオープンソースで公開したガバメント AI「源内（GENAI）」を、
**完全ローカル環境 × ローカル LLM（OpenAI 互換 API）** で動かすためのプロジェクトです。

> **バージョン:** 現在 **v0.6.0**（添付・ナレッジの個人情報検知、ナレッジ専用ページ、チャット大容量添付のマップリデュース、Dify エラー分類、MCP 公開範囲の文書化）。v0.5.0 = 本番静的ビルド/デプロイ整備・複数LLM/埋め込み/画像モデルの差し替え・SAML/認証堅牢化、v0.4.0 = 構造化 RAG・ナレッジ MCP・Dify 連携事例・マイナンバー検査、v0.3.x = 出典表示・画像生成一本化等、v0.2.x = 自治体・閉域向け拡張、v0.1.0 = ローカル源内化の第一段階。
> 変更履歴は [CHANGELOG.md](CHANGELOG.md) を参照。

> **免責 / Disclaimer**: 本リポジトリは有志による**非公式フォーク**です。デジタル庁とは一切関係がなく、
> 同庁による承認・支援を受けたものではありません。`genai-web/` はデジタル庁の
> [digital-go-jp/genai-web](https://github.com/digital-go-jp/genai-web)（MIT ライセンス）を
> ローカル動作向けに改変して同梱しています（原 LICENSE は `genai-web/LICENSE` に保持）。
> デジタル庁オリジナルの `genai-ai-api` は本リポジトリには含めていません（必要な場合は
> [digital-go-jp/genai-ai-api](https://github.com/digital-go-jp/genai-ai-api) を別途取得してください）。

ホスト OS / ハードウェアは特定環境に依存しません。macOS (Apple Silicon) でも、
Linux + NVIDIA GPU 機（例: **NVIDIA DGX Spark**）でも動作します。

源内はもともと AWS / Azure / Google Cloud などのクラウド前提
（Amazon Cognito 認証・Lambda・Bedrock 等）で作られているため、そのままでは
ローカルで動きません。本プロジェクトは以下を行うことでローカル完結させます。

- 認証（SAML）を **ローカル完結**（`backend` を SAML SP、`Keycloak` を SAML IdP として実装）
- LLM 呼び出しを **OpenAI 互換 API** 経由で行う（既定は Ollama の `/v1`。vLLM / LM Studio / OpenAI など任意の OpenAI 互換サーバに切替可）
- クラウド API（チャット履歴・推論ストリーム）を **ローカルバックエンド（FastAPI）** で代替

```
[ブラウザ] ──▶ proxy (nginx :80) ──▶ web (源内 Web / Vite)
                  │                    REST + ストリーミング
                  ├──▶ backend (FastAPI) ──▶ OpenAI 互換 LLM（Ollama 等）
                  └──▶ keycloak (/kc)      SAML IdP
```

本番は `docker-compose.prod.yml` で TLS(443) 終端。閉域検証は HTTP(80) のみ（`docker-compose.verify.yml`）。SeaweedFS（8333）は本番 compose ではホスト非公開で、成果物のダウンロードは `S3_PUBLIC_ENDPOINT` 経由のリバースプロキシを別途用意します（詳細は「成果物ファイル」節）。

> **変更履歴:** [CHANGELOG.md](CHANGELOG.md)（**v0.6.0** = PII 検知・ナレッジ専用ページ・大容量添付 mapreduce 等、**v0.5.0** = 本番静的ビルド/デプロイ整備・複数LLM/埋め込み/画像モデル差し替え・SAML/認証堅牢化、**v0.4.0** = 構造化 RAG・ナレッジ MCP・Dify 連携事例・マイナンバー検査、それ以前は CHANGELOG 参照）

## 設計思想：自治体・閉域運用への拡張

初期リリースでは「源内のクラウド依存を OSS／ローカルに置き換える」ことに集中していました。
その後、**実際の自治体（閉域・LGWAN 等）で使う**ことを想定し、思想と構成を大きく広げています。
改修の多くは **OpenGENAI レイヤ**（`backend/` と各 exApp）に集約し、上流の `genai-web` は
極力無改修のままにしています（マージ容易性・源内 UX の維持）。

### なぜ思想を変えたか

| 課題 | 方針 |
| --- | --- |
| 監査・権限・データ削除など、クラウド版が暗黙に担っていたガバナンス | マネージドサービスに頼らず **自前実装**（監査ログ・モデル制御・入力制限・契約終了時削除） |
| 組織の実態（課・横断プロジェクト）と源内のチームモデルのギャップ | **チーム主体・非階層**に整理。1 人が **複数チームに所属**できるよう拡張 |
| 管理機能を Keycloak コンソールだけに頼る運用負荷 | 管理者向け機能を **源内 UI 内の exApp** として提供（一般利用者には非表示） |
| Dify 等の第三者 URL をそのまま利用者に渡すリスク | **自前 S3 互換（SeaweedFS）** へ再ホストし、署名付き URL で受け渡し |
| 各コンテナを個別ポート公開する開発構成 | **nginx 単一入口**に統一（本番 TLS・閉域 HTTP 検証） |

### 4 つの柱

1. **自治体実務を想定した機能** — 監査ログ（3 年以上保持）、利用者 CSV 一括管理、モデル利用制御、禁止語／個人情報検知（添付警告・ナレッジラベル、任意の GiNZA NER）、プロンプトテンプレート、日程調整（オプション profile）、書類領域分割チェック（オプション profile）、契約終了時の完全削除と報告書生成
2. **チーム主体・複数所属** — 親子階層のないフラットなチーム。利用者は複数チームに所属可能。AI アプリ・RAG ナレッジ・保存プロンプトの共有は **所属チーム** を軸に制御
3. **源内 UI 制約の opt-in 拡張** — Form Spec v1（条件表示・リアクティブフォーム・プレビュー）、`dynamic_schema` による動的フォーム、各画面の折りたたみヘルプ。既存 exApp は無改修で従来どおり動作
4. **成果物のオブジェクトストレージ** — AI アプリ（Dify 等）が生成したファイルを SeaweedFS に保存し、backend 経由で署名付き URL を提示

## 構成

| ディレクトリ | 内容 |
| --- | --- |
| `genai-web/` | デジタル庁 源内 Web（フォーク + ローカル化パッチ。同梱） |
| `backend/` | ローカル LLM 用の代替バックエンド（FastAPI / Team API も兼ねる） |
| `rag-app/` | RAG を「行政実務用 AI アプリ」として提供するマイクロサービス（FastAPI） |
| `knowledge-mcp/` | ナレッジ検索 MCP（Streamable HTTP。`/retrieve` 等の薄いラッパ） |
| `whisper-app/` | 文字起こしを「AI アプリ」として提供（faster-whisper / CPU） |
| `dify-app/` | 外部 Dify（ワークフロー / チャットフロー）を「AI アプリ」として連携する汎用プロキシ（FastAPI） |
| `shared/` | 共用モジュール（`docextract.py` ドキュメント抽出、`ssrfguard.py` SSRF 対策） |
| `audit-app/` | 監査ログ参照（管理者限定 exApp） |
| `usermgmt-app/` | 利用者 CSV 一括管理（Keycloak Admin API、管理者限定 exApp） |
| `modelpolicy-app/` | モデル利用制御ポリシー管理（管理者限定 exApp） |
| `ngword-app/` | 禁止語・個人情報検知の設定（管理者限定 exApp。添付警告／ナレッジ検知／NER トグル） |
| `prompt-app/` | プロンプトテンプレートカタログ（標準／個人／グループ共有） |
| `chosei-app/` | 日程調整（オプション・`profiles: ["chosei"]`。詳細は [`docs/chosei.md`](docs/chosei.md)） |
| `doccheck-app/` | 書類領域分割チェック（オプション・`profiles: ["doccheck"]`。詳細は [`docs/doccheck.md`](docs/doccheck.md)） |
| `patchform-app/` | フォーム（オプション・`profiles: ["patchform"]`。詳細は [`docs/patchform.md`](docs/patchform.md)） |
| `procedure-mcp/` | 手続きマスタ MCP（`profiles: ["patchform"]`。公開済みのみ。詳細は [`docs/procedure-mcp.md`](docs/procedure-mcp.md)） |
| `seaweedfs/` | 成果物配信用 S3 互換ストレージ設定 |
| `scripts/` | 運用スクリプト（契約終了時の完全削除・報告書生成 等） |
| `docs/` | Open GENAI レイヤのガイド（[ナレッジ API](docs/knowledge-api.md) / [MCP](docs/knowledge-mcp.md) / [Dify 事例](docs/dify-knowledge.md)） |
| `docker-compose.yml` | **開発用**。proxy + web(Vite dev server) / backend / … をまとめて起動（HTTP :80 のみ公開、コード変更は無ビルドで即時反映） |
| `docker-compose.prod.yml` | **本番 TLS 構成**（proxy :80/:443 のみ公開。web は静的ビルド `genai-web/Dockerfile.prod` を nginx で配信） |
| `docker-compose.verify.yml` | 本番スタックを HTTP で検証／閉域運用するオーバーライド（自己署名不要。web は本番同様の静的ビルド） |
| `proxy/` | nginx リバースプロキシ設定（開発=`nginx.http.conf` / 本番TLS=`nginx.conf` / 本番HTTP検証=`nginx.verify.conf`）。成果物ファイル（SeaweedFS）用の別経路は README「成果物ファイル」節を参照 |

## オリジナル源内からの改修内容（クラウド依存 → オープンアーキテクチャ）

このプロジェクトの中心的な改修は、**源内が依存するクラウドのマネージドサービスを、すべてオープンソース/ローカルの仕組みに置き換える**ことです。置換の全体像は次のとおりです。

| 機能 | 源内オリジナル（クラウド・マネージド） | Open GENAI（オープン/ローカル置換） |
| --- | --- | --- |
| 認証 | Amazon Cognito（SAML は Cognito がブローカー） | **Keycloak**（SAML IdP）＋ `backend`（SAML SP, `python3-saml`）＋ アプリ JWT |
| API 認可 | API Gateway Authorizer / IAM | `backend` の **JWT 検証ミドルウェア** |
| LLM 推論 | Amazon Bedrock | **OpenAI 互換 API**（既定は Ollama の `/v1`。任意の互換サーバに切替可） |
| 推論ストリーム | Lambda `InvokeWithResponseStream`（Cognito Identity Pool 資格情報で直接呼び出し） | `backend` の **HTTP ストリーミング** `/predict/stream` |
| チャット履歴 | Amazon DynamoDB | **SQLite**（`backend`） |
| 保存プロンプト（systemcontexts） | Amazon DynamoDB | **SQLite**（`backend`） |
| チーム / メンバー / AI アプリ管理 | DynamoDB ＋ Cognito グループ | **SQLite** ＋ Keycloak グループ ＋ `team_users.isAdmin` |
| ファイル添付ストレージ | Amazon S3（署名付き URL） | チャット添付は `backend` **ローカル保存**。AI アプリ成果物は **SeaweedFS（S3 互換）** へ再ホストし署名付き URL で配信 |
| RAG（ベクトル検索・埋め込み） | OpenSearch / Bedrock Knowledge Base | **Qdrant** ＋ Ollama `mxbai-embed-large`（`rag-app` として） |
| 文字起こし | Amazon Transcribe ＋ S3 | **faster-whisper**（`whisper-app` を AI アプリとして） |
| 画像生成 | Amazon Bedrock（画像モデル） | **源内 Web `/image`** + ホスト **Stable Diffusion**（A1111 互換、`backend/image_gen.py` 経由） |
| ドキュメント読取（PDF 等） | Bedrock の document 入力 | **テキスト抽出**（pypdf / python-docx / openpyxl, `shared/docextract.py`） |

### 追加したコンポーネント（すべてオープンソース）

- `backend/`（FastAPI）: 源内 Web が叩くクラウド API（genU API / Team API / 推論ストリーム）を代替。SAML SP・JWT 発行/検証・ファイル保存も担当
- `rag-app/`（FastAPI）: RAG を源内の作法どおり「行政実務用 AI アプリ（exApp）」として提供
- `keycloak`（SAML IdP・ユーザー管理）/ `qdrant`（ベクトル DB）を `docker-compose.yml` に追加

### OpenGENAI レイヤで追加した機能（`fc57e53` 以降）

クラウド版源内が担っていたガバナンスを、マネージドサービスなしで再実装しています。
詳細は [CHANGELOG.md](CHANGELOG.md) を参照。

| 領域 | 実装 |
| --- | --- |
| 監査ログ | `backend/app/audit.py` + `audit-app`（3 年以上保持、利用者削除と非連動） |
| 利用者管理 | `usermgmt-app`（CSV 一括作成・更新・削除） |
| モデル制御 | `backend/app/policy.py` + `modelpolicy-app`（チーム／グループ単位） |
| 入力制限 | `backend/app/ngwords.py` + `ngword-app` + `shared/pii_scan.py`（禁止語・添付／ナレッジの個人情報検知） |
| プロンプト | `prompt-app`（テンプレート → チャットディープリンク） |
| 成果物配信 | `backend/app/objstore.py` + SeaweedFS（Dify 等の file artifact 再ホスト） |
| 内部認証 | 各 `app/intauth.py`（backend↔exApp 間 HMAC 署名） |
| SSRF 対策 | `shared/ssrfguard.py`（成果物取得・RAG URL 取込） |
| データ削除 | `scripts/purge-and-report.sh`（契約終了時の完全削除・報告書） |

### 源内 Web（`genai-web/`）への変更点

**クラウド SDK の差し替え**（初期ローカル化）に加え、**opt-in の UI 拡張**（自治体向け）を
最小限だけ加えています。Form Spec v1 の詳細は
[`FORM_SPEC.md`](genai-web/packages/web/src/features/exapp/FORM_SPEC.md) を参照。

- 追加: `packages/web/src/local/localAuth.ts` — ローカル SAML 認証のフロント側（JWT 取得/ログイン/サインアウト）
- 追加: `packages/web/.env.example` — ローカル向け `VITE_APP_*` の雛形（`cp .env.example .env`）
- 改修: `src/main.tsx` — Cognito/SAML ログインゲート → **ローカル SAML ログインゲート**（AWS Amplify 撤去）
- 改修: `src/hooks/useAuth.ts` — `fetchAuthSession()` → ローカル JWT デコード
- 改修: `src/lib/fetcher.ts` — Cognito トークン → **ローカル JWT を Bearer 送信**
- 改修: `src/lib/chatApi.ts` — `predictStream` を **Lambda 直接呼び出し → `/predict/stream` の fetch**
- 改修: `src/lib/fileApi.ts` — S3 URL 前提 → ローカル http URL に対応
- 改修: `src/components/ui/Header.tsx` — Amplify `useAuthenticator` → `localAuth.signOut`
- 改修: `src/features/chat/hooks/useFileUploadable.ts` — 添付可否を選択中モデルに連動
- 改修: `src/pages/SignedOutPage.tsx` — 再ログイン導線を追加
- 改修: `packages/common/src/application/model.ts` — ローカル（Ollama）モデルの定義 + `doc`（ドキュメント添付）フラグを有効化
- 改修: `packages/web/vite.config.ts` — コンテナ実行向けに `host`/ポーリング監視を設定
- 改修: `src/features/exapps/hooks/useGenUApps.ts` — クラウド依存の組み込み「文字起こし」をメニューから除外（ローカル Whisper の AI アプリで代替）
- 追加: AI アプリ ピン留め（利用者ごと・カテゴリ横断・上限8件）— トップページに「ピン留め」セクションを表示。`open-genai/` 拡張 + `LandingPage`/`ExAppList`/`ExAppListCard` の最小パッチ（[`OPENGENAI_PATCHES.md`](genai-web/OPENGENAI_PATCHES.md) 参照）
- 追加: プロンプトテンプレート専用ページ（`/prompts`）— 汎用 exApp フォームに代えて、一覧の検索・区分バッジ・変数入力＋ライブプレビュー・「チャットで開く」を 1 画面で操作。`open-genai/prompt-templates/` + `prompt-app` 構造化 REST + backend `/prompts/*` プロキシ。旧 `/apps/:teamId/prompt` は `/prompts` へリダイレクト（[`OPENGENAI_PATCHES.md`](genai-web/OPENGENAI_PATCHES.md) 参照）
- 改修: `src/features/team-apps/utils/endpointUrl.ts` — AI アプリのエンドポイント URL 検証を `http` も許可（ローカルのコンテナ間通信 `http://dify-app:8004/invoke` 等のため。従来は `https` 必須）
- 改修: `src/features/teams/components/DialogDeleteTeam.tsx` — チーム削除時に知識ベースも消える旨の警告を追加
- 改修: 翻訳/ダイアグラム画面の説明文をローカル実態に合わせて修正
- 追加: 各画面の折りたたみ「使い方」ヘルプ（チャット・翻訳・文字起こし・文章生成・ダイアグラム・画像生成）
- 追加: 保存プロンプトの共有 UI（全体公開・所属チーム複数選択）と `/me/teams` API 連携
- 追加: exApp Form Spec v1（`visibleWhen` / `reactive` / `preview`、`/exapps/resolve`）
- 追加: `dynamic_schema: true` によるローカル exApp の動的フォーム生成（RAG 管理等）
- 改修: ダイアグラム Mermaid 抽出の堅牢化（フェンス無し出力へのフォールバック）
- 削除: `src/components/auth/AuthWithUserpool.tsx` / `AuthWithSAML.tsx`（Cognito 専用のため不要）
- 依存削除: `aws-amplify` / `@aws-amplify/ui-react` / `@aws-sdk/client-lambda` / `@aws-sdk/client-transcribe` / `@aws-sdk/credential-providers`（`packages/web/package.json`）＋ `index.css` の Amplify CSS import
- 表記修正: 翻訳画面の「AWS の Bedrock を利用」→「ローカルの LLM(Ollama) を利用」

> 注: 源内の CDK / IaC（`packages/cdk` 等）は AWS デプロイ専用のため、本プロジェクトでは使用しません（参照のみ）。

## 前提

- Docker / Docker Compose
- OpenAI 互換 API を提供できる LLM 実行環境（既定は [Ollama](https://ollama.com/)）

## 対応ホスト / GPU

LLM・画像生成（SD）は計算資源が必要です。ホスト環境ごとの推奨構成は次のとおりです。
いずれの場合も、源内 Web / backend / 各 AI アプリのコンテナ自体はどの環境でも同じように動きます。

| ホスト | LLM(Ollama) の実行 | 画像生成(SD) の実行 | 備考 |
| --- | --- | --- | --- |
| **macOS (Apple Silicon)** | **ホスト**で実行（Metal GPU で高速） | **ホスト**で実行（A1111 等） | Docker は GPU(Metal) を使えないため、GPU を使う処理はホスト側で動かし、コンテナはそれにプロキシ |
| **Linux + NVIDIA GPU（例: NVIDIA DGX Spark）** | ホスト or **コンテナ**で実行（CUDA GPU） | ホスト or **コンテナ**で実行（CUDA GPU） | [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html) を入れればコンテナでも GPU 利用可 |
| その他 / CPU のみ | ホスト or コンテナ（低速） | CPU は非現実的 | 任意の OpenAI 互換サーバ（vLLM / LM Studio / OpenAI 等）に向けることも可能 |

- LLM の接続先は OpenAI 互換 API です。既定は `OLLAMA_BASE_URL`(+`/v1`)、`OPENAI_BASE_URL` で任意のサーバに切替できます（後述）。
- `host.docker.internal` は Docker Desktop（macOS/Windows）に加え、Linux でも `extra_hosts: host-gateway` で解決するよう設定済みです。
- Linux + NVIDIA でコンテナに GPU を割り当てる場合は、対象サービス（例 `ollama`）に `gpus: all`（または `deploy.resources.reservations.devices`）を追加してください（macOS 既定構成では不要なため同梱していません）。

## 使い方

### 1. Ollama を起動してモデルを取得

```bash
# ホストで Ollama を起動（インストール済みの場合）
ollama serve            # 別ターミナルで起動したままにする

# モデルを取得（日本語に強い Qwen2.5 を推奨）
ollama pull qwen2.5:7b
# 軽量に試すなら: ollama pull qwen2.5:3b  /  ollama pull qwen2.5:0.5b
```

> Ollama をコンテナで動かしたい場合は `docker compose --profile ollama up` を使い、
> `.env` の `OLLAMA_BASE_URL` を `http://ollama:11434` に変更してください。
> Linux + NVIDIA GPU（DGX Spark 等）では、`ollama` サービスに GPU を割り当てると
> コンテナのまま高速に動かせます（`NVIDIA Container Toolkit` 導入のうえ `gpus: all` を付与）。
> macOS では Docker から GPU を使えないため、Ollama は**ホスト**で動かすのが推奨です。

### 2. 設定

```bash
cp .env.example .env    # 必要に応じて DEFAULT_MODEL などを編集
```

```bash
cp genai-web/packages/web/.env.example genai-web/packages/web/.env    # 必要に応じて VITE_APP_MODEL_IDS などを編集
```

利用したいモデルを増やす場合は `genai-web/packages/web/.env` の
`VITE_APP_MODEL_IDS`（Ollama のモデル名と一致させる）を編集してください。
モデルの表示名は `genai-web/packages/common/src/application/model.ts` に定義しています。

#### LLM バックエンドの差し替え（OpenAI 互換）

LLM（チャット/RAG 生成/埋め込み）はすべて **OpenAI 互換 API** 経由で呼び出します。
既定では Ollama の `/v1`（`OLLAMA_BASE_URL` + `/v1`）を使います。
Ollama 以外（vLLM / LM Studio / OpenAI 等）に向けたい場合は `.env` で設定します。

```bash
# 例: 別の OpenAI 互換サーバに向ける
OPENAI_BASE_URL=http://host.docker.internal:8001/v1
OPENAI_API_KEY=sk-...   # サーバが要求する場合のみ
```

### 3. 起動

```bash
docker compose up --build
```

- 源内 Web: http://localhost/ （`.env` の `PROXY_HTTP_PORT` / `PUBLIC_URL` で変更可）
- バックエンド API: http://localhost/api/health
- Keycloak 管理: http://localhost/kc/

初回はフロントエンドの依存インストールに数分かかります。

> ポート 80 が使用中の場合は `.env` で `PROXY_HTTP_PORT=8080` と
> `PUBLIC_URL=http://localhost:8080` に設定してください。

## 動作確認

- http://localhost/api/health で `{"status":"ok"}` が返ること（モデル一覧は認証付き `GET /api/health/details`）
- http://localhost/ を開くと Keycloak のログイン画面に遷移し、`admin` / `password` でログインできること
- 「チャット」からメッセージを送り、ローカル LLM の応答がストリーミング表示されること
- 「AIアプリ」→「**ナレッジ検索**」で質問でき、出典付きで回答されること（起動済みアプリのみ一覧に表示）
- 「翻訳」「ダイアグラムを生成」「文章を生成」がローカル LLM で動作すること
- http://localhost:8333/ をブラウザで開くと XML の `AccessDenied` が表示されること（SeaweedFS S3 API の正常応答。**開発時のみホスト公開**。本番は `S3_PUBLIC_ENDPOINT` 経由のリバースプロキシのみ公開）
- （Dify 連携）[`dify-app/dsl/File Output Test.yml`](dify-app/dsl/File Output Test.yml) をデプロイし、源内 AI アプリから実行して成果物リンクが表示されること
- **開発構成**では http://localhost/kc/ の **Administration Console** に `.env` の `KEYCLOAK_ADMIN` でログインでき、realm **`open-genai`** の Users / Groups が表示されること（利用者アカウント管理用。源内ログイン画面とは別）。**本番／verify** では `/kc/admin` は nginx 既定で全拒否（`proxy/kc-admin-allow.conf` で CIDR 許可）

## 本番デプロイ

開発環境（`docker compose up`）と本番環境では、**フロントエンド（源内 Web）の配信方式**が異なります。ここでは本番デプロイの前提・初回手順・変更反映の運用をまとめます。

### 開発と本番の違い（配信方式）

| 項目 | 開発（`docker-compose.yml`） | 本番（`docker-compose.prod.yml`） |
| --- | --- | --- |
| web の配信 | **Vite dev server**（`Dockerfile.local`, :5173）をバインドマウントで起動 | **静的ビルド**（`Dockerfile.prod` で `npm run web:build` → nginx が `dist` を :80 配信） |
| フロント変更の反映 | ソース保存で**即時反映**（無ビルド・HMR） | **web イメージの再ビルドが必要**（静的バンドルにビルド時取り込み） |
| 公開 | proxy が HTTP :80 | proxy が TLS :443 終端（`proxy/nginx.conf`） |
| API 参照 | `VITE_APP_*` を実行時 env で注入 | `VITE_APP_*` を **build.args でビルド時に埋め込み** |

> backend / 各 exApp（Python）はどちらもイメージ内のコードで動くため、変更時はイメージ再ビルド＋再作成が必要です（下記「変更の反映」参照）。開発で Python 側を即時反映したい場合は各サービスにバインドマウント等を追加してください（既定は web のみ即時反映）。

### 前提

- `.env.prod` を用意（`cp .env.prod.example .env.prod` して編集）。**最低限**、次は本番用に必ず変更します。
  - `PUBLIC_URL`（例: `https://genai.example.lg.jp`。末尾スラッシュ無し）
  - `APP_JWT_SECRET` / `INTERNAL_SIGNING_SECRET`（十分長い乱数。例: `openssl rand -hex 32`）
  - `KEYCLOAK_ADMIN_PASSWORD`（**初回起動前**に設定。詳細は[認証節の「運用開始時」](#運用開始時本番閉域-パスワード変更)）
  - `S3_*`（`S3_PUBLIC_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` 等。詳細は[成果物ファイル節](#成果物ファイルseaweedfs-再ホスト)）
- TLS 証明書を `proxy/certs/{fullchain.pem,privkey.pem}` に配置（`docker-compose.prod.yml` が `/etc/nginx/certs` にマウント。詳細は [`proxy/certs/README.md`](proxy/certs/README.md)）。
- Keycloak の SAML クライアント（SP）登録を `PUBLIC_URL` に合わせる（初回 import 前に `keycloak/import/realm-open-genai.json` を編集、または admin コンソールで更新。詳細は[SAML 節](#源内側の設定変更時に必要な作業)）。

### 初回デプロイ（本番 TLS）

```bash
# 1. 設定と証明書を用意
cp .env.prod.example .env.prod        # PUBLIC_URL・各シークレット等を編集
#    proxy/certs/fullchain.pem, privkey.pem を配置

# 2. ビルドして起動（web は静的ビルドされる）
docker compose -f docker-compose.prod.yml --env-file .env.prod up --build -d

# 3. 状態確認
docker compose -f docker-compose.prod.yml --env-file .env.prod ps
```

- 公開 URL（`PUBLIC_URL`）でログイン画面（Keycloak）に遷移すること
- 初回はフロントのビルドに数分かかります
- 起動後、初期ユーザー（`admin`/`user`）の無効化・パスワード変更を必ず実施（[運用開始時](#運用開始時本番閉域-パスワード変更)）

### 変更の反映（再デプロイ）

本番はビルド済みイメージで動くため、変更箇所に応じて対象サービスを**再ビルド＋再作成**します。

| 変更した箇所 | 反映コマンド（`-f docker-compose.prod.yml --env-file .env.prod` を付与） |
| --- | --- |
| **フロント**（`genai-web/**`。プロンプト・画面・ルーティング等） | `docker compose ... up -d --build web` |
| **backend**（`backend/**`） | `docker compose ... up -d --build backend` |
| **各 exApp**（`rag-app/` 等） | `docker compose ... up -d --build <service>` |
| **氏名 NER（GiNZA）**（`PII_INSTALL_NER=1`） | `PII_INSTALL_NER=1 docker compose ... up -d --build backend rag-app`（詳細は[個人情報検知](#入力制限と個人情報検知添付ナレッジ)） |
| **proxy 設定**（`proxy/nginx.conf`） | `docker compose ... restart proxy`（設定はマウントのため再起動のみ） |
| **`.env.prod` の値**（LLM 接続・S3 公開先・`TITLE_MODE` 等） | 対象サービスを `up -d`（再作成で env 再読込。フロント埋め込み値は再ビルド） |

```bash
# 例: フロントのプロンプト/画面を変更 → web を再ビルドして差し替え
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build web
```

> **注意:** フロントの見た目・文言・プロンプトの変更は、`web` を再ビルドしない限り本番へ反映されません（静的バンドルにビルド時取り込みのため）。開発環境では即時反映されるので、この差に注意してください。

### 閉域・HTTP のみで運用/検証する場合

TLS 終端や自己署名証明書が使えず、ポート 80 のみで公開する環境（閉域検証など）向けに、本番スタックを HTTP で動かすオーバーライドを用意しています。web は本番同様の**静的ビルド**を使い、proxy だけを HTTP・静的上流用の `proxy/nginx.verify.conf` に差し替えます。

```bash
cp .env.prod.example .env.prod
#   PUBLIC_URL=http://localhost（またはホスト名）, PROXY_HTTP_PORT=80 等に編集
docker compose -f docker-compose.prod.yml -f docker-compose.verify.yml \
  --env-file .env.prod up --build -d
```

- `PUBLIC_URL` は `http://` で始めること（証明書は不要）
- ポート 80 が使用中なら `.env.prod` の `PROXY_HTTP_PORT=8080` 等に変更し、`PUBLIC_URL` も合わせる

### 前段にゲートウェイ/別リバースプロキシがある場合（SAML 注意）

`PUBLIC_URL` が SAML の SP EntityID / ACS / SLS と Keycloak の公開ホスト（`KC_HOSTNAME`）の**単一の正**になります。前段に別ホスト名のゲートウェイを置く場合は、次のいずれかにしてください。

- **公開ホストを 1 つに統一**: 利用者に見せるホスト名を `PUBLIC_URL` に設定し、ゲートウェイは `/`・`/api`・`/kc` すべてを **Host ヘッダを保持**して転送する。Keycloak の SAML クライアント（ACS/EntityID）もそのホストで登録する。
- backend は `X-Forwarded-Proto` / `X-Forwarded-Host` / `X-Forwarded-Port` から公開 URL を組み立てるため、前段プロキシはこれらを正しく付与すること（本リポジトリの `proxy/nginx.conf` は TLS 終端時に `https` / `$host` / `443` を送出）。

> 複数の公開ホストで同時に SAML を成立させることは、現状の単一 `PUBLIC_URL` 前提ではできません（EntityID/ACS が固定のため）。

### 埋め込みモデルの差し替え / ローカル日本語埋め込み（`embed` サイドカー）

RAG の埋め込みモデルは推論モデルと同様に**差し替え可能**です。既定は Ollama 上の
`mxbai-embed-large`（1024 次元）で、開発・検証・既定の本番はこのままで動きます（追加設定不要）。
挙動はすべて `rag-app` の環境変数で制御され、コードは単一パスのままです。

| 環境変数 | 既定 | 役割 |
| --- | --- | --- |
| `EMBED_MODEL` | `mxbai-embed-large` | 埋め込みモデル名 |
| `EMBED_DIM` | `1024` | ベクトル次元（Qdrant コレクション作成時に使用） |
| `QDRANT_COLLECTION` | `open_genai_rag` | 保存先コレクション |
| `EMBED_BASE_URL` | 空（=`OPENAI_BASE_URL` にフォールバック） | 埋め込みだけ別の OpenAI 互換エンドポイントへ分離する場合に設定 |
| `EMBED_API_KEY` | 空（=`OPENAI_API_KEY`） | 上記エンドポイントの API キー |
| `EMBED_QUERY_PREFIX` / `EMBED_DOC_PREFIX` | mxbai 互換（クエリのみ英語 prefix・文書なし） | モデル依存の検索クエリ/文書 prefix |

> **重要（再インデックス）:** 埋め込みモデルを変えると**ベクトル次元と意味空間が変わります**。
> Qdrant のコレクションは次元固定のため、既存コレクションへ別モデルのベクトルを混在させられません。
> モデルを変更する場合は `QDRANT_COLLECTION` を別名にし、`EMBED_DIM` を合わせたうえで**全件を再インデックス**してください。

#### ローカル日本語埋め込み（`ruri-v3` 等）を使う場合

Ollama や TEI(CPU/ORT) が配信できない埋め込みモデル（例: `cl-nagoya/ruri-v3-310m` は
ModernBERT-Ja・ONNX 非提供）は、同梱の汎用サイドカー `embed`（`sentence-transformers`／CPU）で配信できます。
このサイドカーは Compose の `profiles: ["embed"]` により**任意起動**で、既定では起動しません。
本番で日本語埋め込みが必要な場合にのみ有効化します。

```bash
# .env.prod に以下を設定（.env.prod.example の「ruri-v3-310m を使う場合」の例を参照）
#   COMPOSE_PROFILES=embed
#   EMBED_BASE_URL=http://embed:80/v1
#   EMBED_API_KEY=-
#   EMBED_MODEL=cl-nagoya/ruri-v3-310m
#   EMBED_DIM=768
#   QDRANT_COLLECTION=open_genai_rag_ruri_v3_310m   # 768 次元の別コレクション
#   EMBED_QUERY_PREFIX=検索クエリ: 
#   EMBED_DOC_PREFIX=検索文書: 

# embed サイドカーを含めて起動（COMPOSE_PROFILES=embed を .env.prod に入れれば --profile 省略可）
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile embed up -d --build embed rag-app
```

- `embed` を起動しない運用では `EMBED_BASE_URL` を外部の埋め込み API に向けても構いません（サイドカー不要）。
- 開発・検証環境では `embed` は不要です（`docker-compose.yml` / `docker-compose.verify.yml` は既定 mxbai のまま）。
- 初回起動時にモデルを HuggingFace から取得し `embed_data` ボリュームへキャッシュします（数百 MB〜。閉域では事前取得が必要）。

## ファイル添付（画像 / ドキュメント）

チャットでは画像とドキュメントを添付できます（モデルの対応機能フラグに応じて添付ボタンが出ます）。

### 画像（マルチモーダルモデル）

- モデル選択で **「Gemma 3 27B (ローカル・画像対応)」** を選ぶと画像添付が使えます
- 対応形式: `.jpg / .jpeg / .png / .webp`
- 画像は推論時に OpenAI 互換の **Vision 形式**（`image_url` data URL）で LLM に渡されます
- 他の画像対応モデル（例 `llava`, `llama3.2-vision` 等）も、`ollama pull` のうえ
  `genai-web/packages/web/.env` と `packages/common/src/application/model.ts` に画像フラグ付きで追加すれば利用できます

### ドキュメント（PDF / Word / Excel / テキスト）

- すべてのローカルモデルで **ドキュメント添付**が使えます（`doc` フラグを有効化済み）
- 対応形式: `.pdf / .docx / .xlsx / .txt / .md / .csv / .html / .json` など
- ローカル LLM はドキュメントを直接読めないため、**backend がテキストを抽出してプロンプトに注入**します（PDF=pypdf、Word=python-docx、Excel=openpyxl、テキスト=そのまま）
- 大きい添付は 30,000 文字で黙って打ち切らず、**その場でマップリデュース**（チャンク化 → 読み計画 → 抜粋 or バッチ要約）してから回答します。しきい値 `CHAT_DOC_INLINE_CHARS`（既定 60,000 文字）以下はそのまま全文注入、超過分は圧縮して参照し、「どう参照したか」を応答冒頭に短く明示します
- 安全弁として全文抽出は `MAX_CHAT_DOC_CHARS`（既定 500,000 文字）を上限とし、超えた場合のみ明示注記を付けて先頭を保持します（全文が必要な場合はナレッジ登録を利用）。ベクトル RAG 簡易登録など従来経路は引き続き `MAX_DOC_CHARS`（既定 30,000 文字）で打ち切ります
- レガシー形式（`.doc` / `.xls` のバイナリ旧形式）はテキスト抽出に未対応です
- アップロード時に個人情報が検知された場合は**警告のみ**（送信・保存は継続）。詳細は[入力制限と個人情報検知](#入力制限と個人情報検知添付ナレッジ)

> アップロードしたファイルは backend（`backend_data` ボリューム）に保存されます。

## 認証（SAML）

源内の SAML 認証を、ローカル完結する形で実装しています。

```mermaid
flowchart LR
  SPA[源内 Web] -->|未認証なら redirect| Login["backend /auth/login"]
  Login -->|SAML AuthnRequest| KC[Keycloak SAML IdP]
  KC -->|SAML Assertion| ACS["backend /auth/saml/acs"]
  ACS -->|アプリJWT発行 #token=| SPA
  SPA -->|Authorization Bearer| API[backend API]
```

- `backend` が SAML SP（`python3-saml`）として動作し、検証後にアプリ JWT を発行
- `Keycloak`（`http://localhost/kc/`）が SAML IdP 兼 **利用者アカウントの台帳**
- 各 API は JWT(Bearer) で保護（未認証は 401）

### Keycloak とは（このプロジェクトでの役割）

Keycloak は **「誰がログインできるか」** を担うコンポーネントです。源内 Web そのものではなく、
ログイン画面の裏側（IdP）と、利用者アカウントの保存場所として動きます。

| Keycloak が担うこと | 源内 / backend が担うこと |
| --- | --- |
| ログイン ID（ユーザー名）・パスワード | チャット履歴・保存プロンプト |
| メールアドレス（SAML の NameID 兼利用者 ID） | チーム・メンバー・AI アプリ（SQLite） |
| 権限グループ（`SystemAdminGroup` 等） | チーム管理者（`team_users.isAdmin`） |
| SAML で backend に属性を渡す | モデル制御・入力制限・監査ログ等 |

**整理:** 利用者を「作る／止める／システム管理者にする」→ Keycloak（または後述の CSV 一括 exApp）。
「どのチームに所属させるか」→ 源内の **チーム管理** UI。

### 2 種類の画面（混同しやすい）

| URL | 用途 | ログイン |
| --- | --- | --- |
| http://localhost/kc/ | **Keycloak**（ログインフォーム＋管理コンソール） | 管理コンソールは本番で `/kc/admin` を nginx が遮断。開発時は `.env` の `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`（既定 `admin` / `admin`） |
| http://localhost/ | **源内 Web**（利用者向け） | realm `open-genai` の利用者（例: `admin` / `password`） |

源内にログインするときに表示される画面は Keycloak の **ログインフォーム**（realm `open-genai`）です。
管理コンソールとは別物です。

> **ログインできないとき（よくある間違い）**  
> スクリーンショットの画面（`realms/master`・Administration Console）には、源内用の **`admin` / `password` は使えません**。  
> ここは Keycloak **サーバ管理者**用で、既定は **`admin` / `admin`**（`.env` の `KEYCLOAK_ADMIN` / `KEYCLOAK_ADMIN_PASSWORD`）です。  
> `admin` / `password` は http://localhost/（源内）へのログイン用です。

### 権限グループ

realm `open-genai` には次のグループがあります（`keycloak/import/realm-open-genai.json` で初期定義）。

| グループ | 意味 | 設定方法 |
| --- | --- | --- |
| `SystemAdminGroup` | **システム管理者**。全チーム管理・管理者向け exApp（監査・利用者一括・モデル制御・入力制限等） | Keycloak 管理コンソールでユーザーをこのグループに追加 |
| `UserGroup` | **一般利用者** | 新規ユーザー作成時に付与（既定） |
| `TeamAdminGroup` | **チーム管理者**（自チームのメンバー/アプリ管理） | **Keycloak では設定しない**。源内「チーム管理」でメンバーを管理者にすると、**次回ログイン時に自動付与** |

SAML 経由で backend に渡る主な属性:

- **NameID / 利用者 ID** … メールアドレス（例: `user@example.com`）
- **groups** … 上記グループ名の一覧（カンマ区切り）

### 初期ユーザー

| ユーザー名 | パスワード | グループ | 備考 |
| --- | --- | --- | --- |
| `admin` | `password` | `SystemAdminGroup` | 源内ヘッダーに管理メニュー・管理者 exApp が表示 |
| `user` | `password` | `UserGroup` | 一般利用者 |

> 初回は Keycloak の起動に数十秒かかります。源内ログインや管理コンソールが開けない場合は少し待って再試行してください。

### Keycloak 管理コンソールの操作

1. ブラウザで http://localhost/kc/ を開く
2. **Administration Console** をクリック
3. ユーザー名 `admin`、パスワード `.env` の `KEYCLOAK_ADMIN_PASSWORD`（未設定時 `admin`）でログイン
4. 左上の realm が **`open-genai`** になっていることを確認（`master` のままだと利用者が見えません）

#### 利用者を 1 人追加する

1. 左メニュー **Users** → **Add user**
2. **Username**（必須）・**Email**（推奨: 源内の利用者 ID として使われます）・姓名を入力 → **Create**
3. **Credentials** タブ → **Set password**（**Temporary** を OFF にすると初回変更を求めません）
4. **Groups** タブ → **Join Group** → 一般利用者なら `UserGroup`、システム管理者なら `SystemAdminGroup`

#### パスワードをリセットする

1. **Users** → 対象ユーザーを開く → **Credentials** → **Set password**

#### 利用者を無効化する（削除せず止める）

1. **Users** → 対象ユーザー → **Enabled** を OFF → **Save**

#### 利用者を削除する

1. **Users** → 対象ユーザー → **Delete**

> 自己登録（Sign up）は無効です（`registrationAllowed: false`）。利用者は管理者が作成します。

#### システム管理者に昇格させる

1. **Users** → 対象ユーザー → **Groups** → **Join Group** → `SystemAdminGroup`
2. ユーザーに **再ログイン** してもらう（SAML 属性が更新されるため）

#### 源内側の設定変更時に必要な作業

`.env` の `PUBLIC_URL` を変えた場合（例: ポート 8080）は、Keycloak の SAML クライアント
（Clients → `Open GENAI SP`）の **Valid redirect URIs** / **Assertion Consumer URL** も
新しい URL に合わせる必要があります。開発用の既定 import（`keycloak/import/realm-open-genai.json`）
は `http://localhost` 前提です。

### CSV 一括管理（源内の管理者 exApp）

人数が多い場合は、Keycloak 管理コンソールの代わりに源内の **「利用者一括管理」** AI アプリ
（システム管理者のみ表示）から CSV で作成・更新・削除できます。

- ヘッダー → **AI アプリ** → **利用者一括管理（管理者限定）**
- CSV 列: `action`, `username`, `email`, `name`, `password`, `groups`, `enabled` 等
- `dry_run` で事前確認 → `apply` で Keycloak に反映

詳細は exApp フォーム内の説明を参照してください。

### 運用開始時（本番・閉域）— パスワード変更

開発用の既定パスワード（`admin`/`admin`、`admin`/`password` 等）は **そのまま運用してはいけません**。
運用開始前に、少なくとも次を変更してください。

既定のまま起動すると **backend が stderr に `[SECURITY]` 警告と設定手順を出力**します（起動自体は継続します）。

| 対象 | 設定・操作 | 備考 |
| --- | --- | --- |
| **Keycloak サーバ管理者** | `.env.prod` の `KEYCLOAK_ADMIN_PASSWORD` | 管理コンソール（`master` realm）用。**初回起動前**に設定するのが確実（`keycloak_data` ボリューム作成後は環境変数だけでは変わらない） |
| **源内の初期利用者** | realm `open-genai` の Users でパスワード変更、または削除 | import 済みの `admin`/`user`（いずれも `password`）は検証用。本番では削除するか強固なパスワードに変更 |
| **新規利用者** | Keycloak 管理コンソール or 利用者一括管理 exApp | 実運用の利用者は CSV 一括登録等で個別パスワードを発行 |
| **backend JWT 署名** | `.env.prod` の `APP_JWT_SECRET` | Keycloak とは別だが、認証まわりで同時に変更必須 |
| **内部 HMAC** | `.env.prod` の `INTERNAL_SIGNING_SECRET` | backend↔exApp の `x-user-*` 偽装対策 |
| **添付 URL 署名** | 任意 `FILES_URL_SECRET`（未設定時は `APP_JWT_SECRET`） | `/api/files` の短命 HMAC |

**初回デプロイの推奨手順:**

1. `.env.prod` で次を十分長い乱数に設定（例: `openssl rand -hex 32`）: `KEYCLOAK_ADMIN_PASSWORD`・`APP_JWT_SECRET`・`INTERNAL_SIGNING_SECRET`
2. `docker compose -f docker-compose.prod.yml --env-file .env.prod up --build` で **初回起動**（以降 `keycloak_data` に管理者パスワードが固定される）
3. 管理コンソールへは `proxy/kc-admin-allow.conf` に管理網 CIDR を追記してから到達（既定は `/kc/admin` 全拒否）
4. realm `open-genai` → 初期ユーザー `admin`/`user` を無効化またはパスワード変更
5. 実利用者を登録（一括 exApp または Users から）

> 既に `keycloak_data` ボリューム付きで起動済みの環境で `KEYCLOAK_ADMIN_PASSWORD` だけ変えても反映されません。管理コンソールから master 管理者のパスワードを変更するか、検証環境なら `docker compose down -v` でボリュームごと再作成してください。

### Keycloak でやらないこと（源内で行う）

- **チームへの所属** … 「アカウント」→「チーム管理」でメンバー追加
- **チーム管理者の指定** … チーム管理でメンバーの管理者フラグ（Keycloak の `TeamAdminGroup` は自動）
- **AI アプリの登録** … チーム管理
- **監査ログ閲覧・モデル制御・禁止語** … 管理者 exApp（Keycloak では不可）

## RAG（AI アプリ）

源内の作法どおり、RAG を **外部マイクロサービス「行政実務用 AI アプリ」** として実装しています
（`ブラウザ → backend(Team API) → rag-app → Qdrant / Ollama`）。

使い方:
1. ヘッダーの **「AI アプリ」** を開く → **「ナレッジ検索」** を選択
2. 質問を入力して「実行」。知識ベースを検索し、**出典付き**で回答します
3. 必要ならタグで絞り込みます（**タグ未付与の資料は検索対象外**）

検索方式（ベクトル／構造化／ハイブリッド／全文）は UI では選びません。
対象資料の状態に応じて `rag-app` が自動選択します（後述の `/retrieve` と同じ方針）。

### 知識ベースのスコープ（チーム単位で分離）

ナレッジは **チーム（＝ RAG アプリを所有するチーム）単位で分離**されます。
フォルダ階層ではなく、**タグ（フラットなラベル）** と **URL 取り込み** で整理します。

- **共通チームの RAG**: 全認証済みユーザーが使う**共有**ナレッジ
- **チーム作成時**に次の 4 アプリを自動登録（いずれも `dynamic_schema`）
  - ナレッジ検索 / タグ管理 / ドキュメント登録 / ドキュメント管理
- 取り込み／検索／削除はすべて、そのアプリが属するチームの `scope`（= `teamId`）内に限定
- **ドキュメント登録**
  - **標準**: ツリー索引（構造化）＋ベクトル。規程・マニュアル向け
  - **簡易**: 全文保存＋ベクトル（ツリーなし）。散発的な資料向け
  - **URL**: ページ取り込み（全文＋ベクトル）。定期再クロール対象
- **URL 取り込み**: 行政 HP 等の URL を登録し、定期再クロール（`URL_FETCH_ALLOWED_HOSTS` で許可ホスト制限、SSRF 対策付き）
- **タグ**: チャンク／文書に複数タグを付与し、検索時の絞り込みに利用（未付与は登録可・検索対象外）
- **重複排除**: 同一内容のチャンクは（出典＋本文のハッシュで）重複登録されません

### ナレッジ管理 専用ページ（`/knowledge`）

**タグ管理・ドキュメント登録・ドキュメント管理**は、汎用 exApp フォームに代えて
**専用ページ `/knowledge`**（アカウントメニュー →「ナレッジ管理」）に統合しています。

- 画面先頭の **スコープセレクタ**で「共有ナレッジ（共通）」と「所属チーム」を切り替え
- **共有ナレッジの書込はシステム管理者のみ**（閲覧は全ユーザー）。チームスコープは**メンバー**が管理可能
- ドキュメント登録は**非同期**（`ingest_status`: pending → ready / error）。登録ジョブ内で索引化のあと個人情報検知し、一覧にラベル表示（詳細は[個人情報検知](#入力制限と個人情報検知添付ナレッジ)）
- 旧管理 exApp（`rag-tags` / `rag-register` / `rag-maintain` と各チームの「タグ管理／ドキュメント登録／ドキュメント管理」）は **AI アプリ一覧から廃止**し、`/knowledge` に一本化（起動時に既存レコードを削除。新規デプロイでも最初から表示されない）。万一残った旧 URL / ピン留めは `/knowledge` へ自動リダイレクト
- **ナレッジ検索**は従来どおり「AI アプリ」の「ナレッジ検索」（`rag` exApp）を使用
- 実装: `rag-app` の構造化 REST（`/knowledge/*`）を `backend` が認証・スコープ認可付きでプロキシ（詳細は [docs/knowledge-api.md](docs/knowledge-api.md)）

### RAG Retrieval API（機械向け）

人間向け Q&A は `POST /invoke`（源内 exApp）。Dify 等から節／チャンクを取り出すときは **`POST /retrieve`** など機械向け API を使います（開発時ホスト `:8001`）。

詳細・curl 事例（タグ横断／`source` 指定／サンプル登録）は **[docs/knowledge-api.md](docs/knowledge-api.md)** を参照。

最短疎通:

```bash
curl -s -X POST http://127.0.0.1:8001/retrieve \
  -H "x-api-key: local-rag-key" -H "Content-Type: application/json" \
  -d '{"question":"管理者は誰ですか","mode":"auto","top_k":4,"scope":"00000000-0000-0000-0000-000000000000","tags":["規程"]}'
```

- 埋め込み: Ollama `mxbai-embed-large` / ベクトル: Qdrant / メタ: SQLite
- E2E: `scripts/e2e-tree-rag.sh`

## 文字起こし / 画像生成

文字起こしは **外部マイクロサービスの「AI アプリ」**（`whisper-app`）として提供しています。  
画像生成は源内 Web の **「画像を生成」ページ**（`/image`）から利用します（`backend` の `/image/generate` がホスト SD へプロキシ）。

### UX 方針（源内組み込み vs exApp）

クラウド版源内には組み込みの「文字起こし」（`/transcribe`）と「画像を生成」（`/image`）があります。
Open GENAI では **機能ごとに入口を分けています**（どちらもローカルで動作するよう置き換え済み）。

| 機能 | Open GENAI での入口 | 理由（UX） |
| --- | --- | --- |
| **画像生成** | 源内オリジナル **`/image`** + ホスト **Stable Diffusion** | チャット連携・利用履歴・詳細設定など、源内組み込み UX を活かす。初期の SD 専用 exApp は重複のため廃止 |
| **文字起こし** | **exApp**（`whisper-app`） | 源内 `/transcribe` は Amazon Transcribe + S3 前提のためメニューから除外。ローカル Whisper を exApp として提供 |

**文字起こしで exApp を選んだ理由**

- 源内 `/transcribe` の主な差分は **話者分離（diarization）** だが、ローカルの faster-whisper では Transcribe 相当の話者認識は提供していない。**あえて外し**、言語指定・タイムスタンプ付き出力・**exApp 利用履歴**に寄せた
- 音声は exApp 実行時にコンテナ内で処理され、クラウドへ送信されない（源内 `/transcribe` のコードはリポジトリに残るが、Open GENAI では `/apps/.../whisper` から利用する）

### 文字起こし（ローカル Whisper）

- `whisper-app`（faster-whisper / CPU）。音声を添付して実行すると文字起こし（タイムスタンプ付き）を返します。
- モデルは `.env` の `WHISPER_MODEL`（既定 `medium`。`small`/`large-v3` も可）。初回実行時にモデルを取得し `whisper_cache` ボリュームにキャッシュします。
- クラウドの Amazon Transcribe + S3 への依存を置き換えています。

### 画像生成（源内 Web `/image` + Stable Diffusion）

`backend` の `/image/generate` が画像生成サーバへプロキシします。バックエンドは `.env` の
**`SD_BACKEND`** で切り替えます（既定 `a1111`）。画像生成サーバ本体はいずれも**アプリ外で運用**します
（RAG 埋め込みと同様、環境に応じて差し替える方針）。

| `SD_BACKEND` | 用途 | サーバ | 既定接続先 | 初期 step/cfg 目安 |
| --- | --- | --- | --- | --- |
| `a1111`（既定） | **GPU** で自前運用 | AUTOMATIC1111 互換（`/sdapi/v1/txt2img`） | `http://host.docker.internal:7860` | 50 / 7 |
| `fastsd` | **CPU-only** 環境 | [FastSD CPU](https://github.com/rupeshs/fastsdcpu)（LCM, `/api/generate`） | `http://host.docker.internal:8000` | 4 / 1 |

- **`a1111`（GPU 自前運用）**
  - macOS は Docker から GPU(Metal) を使えないため SD 本体は**ホスト**で。[AUTOMATIC1111 stable-diffusion-webui](https://github.com/AUTOMATIC1111/stable-diffusion-webui) 等を `--api` 付きで `:7860` に起動。
  - Linux + NVIDIA GPU は SD を**コンテナで GPU 実行**しても可。`SD_API_URL` をそのアドレスに設定。
- **`fastsd`（CPU-only）**
  - FastSD CPU は A1111 非互換の独自 API（`POST /api/generate`）で、backend 側に専用アダプタを実装済み。
  - FastSD 本体を外部で起動: `python src/app.py --api`（既定 `:8000`）。`.env` に `SD_BACKEND=fastsd` と、必要なら `SD_API_URL` を設定。
  - モデル/高速化は env で指定: `SD_FASTSD_USE_OPENVINO` / `SD_FASTSD_USE_LCM_LORA` / `SD_FASTSD_USE_TINY_AUTO_ENCODER` / `SD_FASTSD_USE_SAFETY_CHECKER` / `SD_FASTSD_MODEL_ID` / `SD_FASTSD_OPENVINO_MODEL_ID`（未指定は FastSD 既定）。
- **初期 step/cfg** はフロントにビルド時埋め込み（`VITE_APP_IMAGE_DEFAULT_STEP` / `VITE_APP_IMAGE_DEFAULT_CFG`。既定 50/7）。FastSD/LCM を使う本番ビルドは **4/1** を指定（`.env.prod` に設定して `web` を再ビルド）。開発は `genai-web/packages/web/.env` で指定。
- 検証用モック: `python3 scripts/mock-sd-server.py`（a1111=:7860）/ `--port 8000`（fastsd）。両バックエンドのエンドポイントに対応。
- 動作確認: `bash scripts/verify-image-gen.sh`（`SD_BACKEND` を見て疎通先を切り替え）

### AI アプリの表示（ヘルスチェック）

AI アプリ一覧（`/apps`）は各 exApp の `/health` を確認し、**起動していない（到達できない）アプリは自動的に一覧から隠します**。

## Dify 連携（AI アプリ）

外部の [Dify](https://dify.ai/) で作成した **ワークフロー / チャットフロー** を、源内の「AI アプリ」として呼び出せます。`dify-app` という汎用プロキシを 1 つ立て、**Dify のフローごとに「AI アプリ」を登録**する方式です（フロー単位に接続先・APIキー・種別を設定）。

```
[ブラウザ] → backend(Team API) → dify-app → 外部 Dify(/v1)
```

- `dify-app` は源内の AI アプリ・プロトコル（同期 `{inputs}` → `{outputs}`）を、Dify の API（`/v1/workflows/run` または `/v1/chat-messages`）に変換します。
- **UI は種別で出し分きます**。`dify_app_type` が `workflow` のアプリは従来の**フォーム実行型 UI**、`chat` のアプリは**対話型 UI**（吹き出し形式のチャット画面）で開きます。どちらも「AI アプリ」一覧に並びます。
- `dify-app` は Dify API を常に **streaming（SSE）で受信**します。**チャットフロー（`chat`）は、そのトークンをブラウザまで NDJSON で中継**し、対話 UI がタイプライター表示で逐次描画します（`/exapps/invoke/stream`）。**ワークフロー（`workflow`）は従来どおりサーバ側で集約**して同期 `outputs` として返します。
  - streaming を採用する理由: Dify は長時間実行やプロキシ切断への耐性から streaming を推奨しており、Agent 系フローは streaming のみ対応です。加えて 1.4.1〜1.13 系には blocking 指定でも `text/event-stream` を返す既知の不具合がありました（1.16 系で修正）。
- Dify 本体は本リポジトリには含めません（**既存/外部の Dify** に接続します）。セルフホスト版は `host.docker.internal` 経由でホスト上の Dify にも接続できます。**Dify クラウド版** は `dify_base_url` に `https://api.dify.ai/v1` を指定します（後述）。
- ワークフロー用アプリとチャットフロー用アプリはエンドポイントが同じ（`dify-app`）でも問題ありません。**APIキー**（ワークフロー用 / チャット用）と `dify_app_type` で区別します。

### 登録手順（チーム管理 → アプリの作成）

ヘッダー右上「アカウント」→「チーム管理」→ 対象チーム →「アプリの作成」で、以下を入力します。**フォームの項目名と入れる内容の対応に注意してください**（接続情報は「コンフィグ」、フォーム定義は「APIリクエストのデータ形式」です）。

| フォーム項目 | 入れる内容 |
| --- | --- |
| APIエンドポイントのURL | `http://dify-app:8004/invoke` |
| APIキー | Dify アプリの API キー（Dify の「APIアクセス」で発行） |
| APIリクエストのデータ形式(JSON) | フロー入力に合わせた**フォーム定義 JSON**（後述） |
| コンフィグ（JSON） | **Dify 接続情報 JSON**（接続先・種別など。後述） |

#### コンフィグ（JSON）の例（= AI アプリの config）

**コンフィグは 1 行 JSON を推奨**します（改行入りだと HTTP ヘッダ経由で `dify-app` に渡せず、404 や空フォームになることがあります）。整形表示は問題ありませんが、保存時は次のように 1 行にしてください。

```json
{"dify_base_url":"https://api.dify.ai/v1","dify_app_type":"workflow","response_field":"http_status"}
```

##### Dify クラウド版

Dify Studio の「APIアクセス」に表示される Base URL（`https://api.dify.ai/v1`）をそのまま使います。

```json
{"dify_base_url":"https://api.dify.ai/v1","dify_app_type":"workflow","response_field":"http_status"}
```

- APIキーは **`app-` で始まるワークフロー用キー**（そのアプリ専用。別フローのキーは不可）
- ワークフローを **公開** してから呼び出す
- 成果物の再ホスト（Dify ファイル URL の取得）用に `.env` へ以下を追加（ローカル／セルフホストと併用する場合はホストを追記）:

```bash
ARTIFACT_FETCH_ALLOWED_HOSTS=files.dify.ai,upload.dify.ai,host.docker.internal
```

##### セルフホスト版（Docker 等）

接続先は環境により異なります。**Dify Studio の「APIアクセス」に表示される Base URL をそのまま** `dify_base_url` に指定してください。

| 構成 | `dify_base_url` の例 |
| --- | --- |
| 標準（API が `/v1`） | `http://host.docker.internal/v1` |
| nginx 等で `/api/v1` にマウント | `http://host.docker.internal/api/v1` |

成果物ファイルの URL ホスト（`FILES_URL`）は API ホストと異なることがあります。再ホストのため `.env` の `ARTIFACT_FETCH_ALLOWED_HOSTS` に **ファイル URL のホスト名** を追加してください（例: `host.docker.internal`、公開ドメイン、リバプロのホスト名）。allowlist に載せたホストは private IP 解決も許可されます。

```json
{"dify_base_url":"http://host.docker.internal/v1","dify_app_type":"workflow","response_field":"result"}
```

```json
{"dify_base_url":"http://host.docker.internal/v1","dify_app_type":"chat","query_field":"query"}
```

- `dify_base_url`: Dify の API ベース URL（末尾 `/v1` または環境の表示どおり）。**必須**（未設定時は `.env` の `DIFY_BASE_URL` を使用）。
- `dify_app_type`: `workflow` または `chat`（既定 `chat`）。
- `query_field`（chat）: ユーザー入力をどの入力キーから取るか（既定 `query`、後方互換で `question` も可）。
- `response_field`（workflow）: Dify の `outputs` から表示に使うキー。
  文字列（`"report"`）または配列（`["report","citations"]`）を指定可。
  エイリアス `response_fields` も可。未指定なら `report` 等を優先。
- 出典アコーディオン: workflow の `citation_artifacts`（JSON 配列、または
  `mime_type=text/x.open-genai.citation` 相当）を `dify-app` が artifacts に載せ、
  源内 UI（`ExAppCitations`）でリンク風見出し＋展開本文として表示する。
- `file_var`（任意, chat / workflow 共通）: 添付ファイルを渡す Dify の入力変数名。通常は `/v1/parameters` から**自動検出**するため指定不要。
- `excel_map` / `excel_var` / `excel_sheet` / `excel_forward`（任意）: 様式 Excel のセル値を開始変数へ注入する opt-in 設定。未設定時は従来どおり。
- `output_mode=xlsx_fill` / `excel_write_map` / `excel_values_field` / `excel_output_filename`（任意）: 様式への書き戻し成果物。未設定時は従来どおり。詳細は後述の「フォーム／様式 Excel からファイル生成」。

> 「コンフィグ（JSON）」の既定値 `{"max_payload_size":"6MB"}` は、上記の Dify 接続情報に置き換えて構いません。

#### OpenGENAI ナレッジ連携（Dify）

検索の正本は `rag-app` の HTTP API。Dify 側は **HTTP ノード** か **Agent + MCP** で組みます。

| 経路 | DSL | ガイド |
| --- | --- | --- |
| HTTP 固定 WF（入門・本丸） | [`OpenGENAI-KnowledgeAgent.yml`](dify-app/dsl/OpenGENAI-KnowledgeAgent.yml) | [docs/dify-knowledge.md](docs/dify-knowledge.md) 事例 1 |
| Agent + MCP | [`OpenGENAI-KnowledgeAgent.chatflow.yml`](dify-app/dsl/OpenGENAI-KnowledgeAgent.chatflow.yml) | [docs/knowledge-mcp.md](docs/knowledge-mcp.md) / 事例 2 |
| 応用（議事録スタンス） | [`OpenGENAI-MinutesStance.yml`](dify-app/dsl/OpenGENAI-MinutesStance.yml) | [docs/dify-knowledge.md](docs/dify-knowledge.md) 事例 3 |

サンプル文書: [`knowledge-qa-sample.md`](dify-app/dsl/samples/knowledge-qa-sample.md)（入門）、[`minutes-stance-sample.md`](dify-app/dsl/samples/minutes-stance-sample.md)（応用）。

セルフホスト Dify では SSRF 許可が必要です（詳細はガイド）:

```bash
SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal
```

> **⚠️ セキュリティ（ナレッジ MCP の公開範囲）:** `knowledge-mcp` は **無認証**で、
> `scope`(teamId) を呼び出し側が任意指定できるため、到達できる者は全チームのナレッジを読めます。
> 既定の `KNOWLEDGE_MCP_BIND` は **`127.0.0.1`**（同一ホストの Dify 向け）。
> LGWAN-ASP の転送対象に載せないでください（詳細: [docs/knowledge-mcp.md](docs/knowledge-mcp.md)）。
>
> `procedure-mcp`（`profiles: ["patchform"]`）も無認証です。到達できる者は公開済み手続きの対応表を読めます。
> 既定の `PROCEDURE_MCP_BIND` は `127.0.0.1`。詳細: [docs/procedure-mcp.md](docs/procedure-mcp.md)。

源内登録の例（workflow / chat）:

```json
{"dify_base_url":"http://host.docker.internal:8088/v1","dify_app_type":"workflow","response_field":"report"}
```

```json
{"dify_base_url":"http://host.docker.internal:8088/v1","dify_app_type":"chat","query_field":"query"}
```

#### 検証用ワークフロー（SeaweedFS ファイル出力テスト）

リポジトリ同梱の DSL を Dify にインポートして、ファイル出力 → SeaweedFS 再ホストの経路を検証できます。

| ファイル | 内容 |
| --- | --- |
| [`dify-app/dsl/File Output Test.yml`](dify-app/dsl/File Output Test.yml) | 公開 URL から PDF を取得し `result_file` として返すワークフロー |
| [`dify-app/dsl/MultiFileGenerator.yml`](dify-app/dsl/MultiFileGenerator.yml) | 複数文書から `markdown` / `html` / `text` / `json` / `docx` / `pptx` を生成。`html` は単一自己完結（デジタル庁デザインシステム風）。署名 URL またはローカルでブラウザ表示可能 |
| [`dify-app/dsl/FormFileGenerator.yml`](dify-app/dsl/FormFileGenerator.yml) | **フォーム項目（開始変数）から Dify 側でプロンプトを組み立て**、同系のファイル成果物を生成。任意の参考資料（`ref_files`）と様式 Excel セル注入（`excel_map`）を併用可 |

**手順:**

1. Dify Studio →「DSL から作成」→ 上記 YAML をインポート → **公開**
2. 「APIアクセス」で API キー（`app-...`）を発行
3. 源内「チーム管理」→「アプリの作成」
   - endpoint: `http://dify-app:8004/invoke`
   - APIキー: 手順 2 のキー
   - コンフィグ: 上記クラウド版 JSON（`response_field` は `http_status` 推奨）
   - データ形式: **空**（`/schema` から `file_url` フォームが自動生成）
4. アプリを実行 → レスポンスに `200` と「生成されたファイル」欄が出ること
5. 配信方式（`ARTIFACT_DELIVERY_MODE`）に応じて表示を確認
   - `open`: 「生成されたファイル」がダウンロードリンク／ボタンになり、SeaweedFS の署名付き URL（開発時は `localhost:8333`、本番は `S3_PUBLIC_ENDPOINT`）で取得できること
   - `carrier`: URL は画面に出ず、ファイル名と LGWAN 向け案内＋「〇〇 のリンクファイル」ボタンが表示されること（後述の [LGWAN 端末での成果物取得](#lgwan-端末での成果物取得配信方式-open--carrier) で検証）

**Dify API の疎通確認（任意）:**

```bash
curl -s -w "\nHTTP %{http_code}\n" \
  -X POST "https://api.dify.ai/v1/workflows/run" \
  -H "Authorization: Bearer app-<あなたのキー>" \
  -H "Content-Type: application/json" \
  -d '{"inputs":{"file_url":"https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"},"response_mode":"blocking","user":"test"}'
```

`HTTP 200` かつ `status: succeeded` なら Dify 側は正常です。

#### フォーム／様式 Excel からファイル生成（FormFileGenerator）

既存の `dify-app` を使った **opt-in 拡張**です。`excel_map` を書かない従来アプリの挙動は変わりません。

**役割分担**

| 関心事 | 正本 |
| --- | --- |
| 変数名・型・必須 | Dify 開始変数 |
| プロンプト組み立て | Dify（FormFileGenerator の「プロンプト組み立て」Code） |
| ラベル・説明・記入例 | 源内 Form Spec（`title` / `desc`）。キー名＝開始変数名 |
| 様式 Excel → 変数 | exApp `config` の `excel_map`（dify-app が invoke 前に注入） |

**A. フォーム駆動**

1. [`FormFileGenerator.yml`](dify-app/dsl/FormFileGenerator.yml) を Dify にインポートして公開し、API キーを発行
2. 源内「アプリの作成」
   - endpoint: `http://dify-app:8004/invoke`
   - コンフィグ（1 行）例: `{"dify_base_url":"https://api.dify.ai/v1","dify_app_type":"workflow","response_field":"result","file_var":"ref_files"}`
   - **データ形式**: [`form-file-generator-placeholder.json`](dify-app/dsl/samples/form-file-generator-placeholder.json) の内容を貼る（`desc` で入力支援。キーは `title` / `dept` / `request` / 任意の `ref_files` 等）
3. 実行 → 「生成されたファイル」が表示されること

自動フォーム（データ形式を空）でも動きますが、Dify の label しか出ないため、業務利用では Form Spec の `desc` 付きを推奨します。

**参考資料（`ref_files`）**は任意・複数可です。様式 Excel とは別欄で、PDF / Word 等を添付して生成の根拠に使えます。

**B. 様式 Excel 駆動（同じ WF）**

セル値を開始変数へ注入し、同じ FormFileGenerator でプロンプト組み立て〜生成します。参考資料も同じ画面から別途添付できます。

1. 上記と同じ DSL / API キーで別アプリ（または同じアプリ）を登録
2. **データ形式**: [`form-file-generator-excel-placeholder.json`](dify-app/dsl/samples/form-file-generator-excel-placeholder.json)（`form_xlsx` と `ref_files` が分かれている）
3. **コンフィグ**例（[`form-file-generator-excel-config.json`](dify-app/dsl/samples/form-file-generator-excel-config.json) を 1 行化）:

```json
{"dify_base_url":"https://api.dify.ai/v1","dify_app_type":"workflow","response_field":"result","file_var":"ref_files","excel_var":"form_xlsx","excel_map":{"title":"B2","dept":"C5","request":"B12"},"excel_sheet":"様式","excel_forward":false}
```

| config キー | 意味 | 既定 |
| --- | --- | --- |
| `excel_map` | 開始変数名 → セル参照（`B2` / `Sheet1!C5` / `'様式'!A1`） | **未設定なら何もしない（後方互換）** |
| `excel_var` | 様式ファイルのフォームキー | `form_xlsx` |
| `excel_sheet` | セル参照にシートが無いときの既定シート | 先頭シート |
| `excel_forward` | `true` なら様式ファイルを Dify にも転送 | `false`（セル注入のみ。参考資料 `ref_files` は別途転送される） |
| `file_var` | 参考資料を渡す Dify 変数名 | 自動検出。Excel 併用時は `ref_files` を明示推奨 |
| `output_mode` | `xlsx_fill` で様式への**書き戻し**成果物を生成 | 未設定＝従来の文章ファイル経路のまま |
| `excel_write_map` | 書き戻しキー → セル参照 | `output_mode=xlsx_fill` 時に必要 |
| `excel_values_field` | Dify outputs 内の値辞書キー | `excel_values` |
| `excel_output_filename` | 書き戻し後のファイル名 | `<元名>_filled.xlsx` |

既にフォームで値が入っているキーは Excel で上書きしません。`.xlsx` / `.xlsm` のみ対応です。

**C. 様式 Excel 書き戻し（workflow / chat 共通）**

文章ファイル（docx 等）ではなく、**アップロードした様式のセルを更新した xlsx** を成果物にします。判断・文案は Dify、セル書き込みは `dify-app`（config）です。

1. データ形式は B と同じ（`form_xlsx` ＋任意の `ref_files`）
2. コンフィグ例: [`form-file-generator-excel-fill-config.json`](dify-app/dsl/samples/form-file-generator-excel-fill-config.json)
3. Dify は書き戻し値を次のいずれかで返す（値があるときだけ xlsx を付与。下書きターンでは付与しない）
   - workflow: outputs の `excel_values`（JSON/dict）。例: `{"summary":"…","result":"…"}`
   - または outputs に `excel_write_map` と同じキーを個別出力
   - chat: 回答中の JSON（または \`\`\`json フェンス）。例: `{"summary":"…"}`
4. `dify-app` がテンプレへ書き、artifacts としてダウンロード可能にする（backend が SeaweedFS へ再ホスト）

チャットでは C+B（下書き→「ファイル出力」等の明示）と組み合わせ、**出力ターンだけ** `excel_values` を返す設計を推奨します。

DSL を再生成する場合: `python3 dify-app/scripts/generate_form_file_generator_dsl.py`

#### トラブルシュート（Dify 連携）

| 症状 | よくある原因 | 対処 |
| --- | --- | --- |
| `404`（ワークフロー呼び出し失敗） | `dify_base_url` が誤り（クラウドなのに `host.docker.internal` 等） | `https://api.dify.ai/v1` に修正 |
| `401` | API キー不一致・未公開 | 正しい `app-` キー、ワークフロー公開を確認 |
| 入力フォームが出ない / 実行しても何も表示されない | コンフィグ JSON の改行 | 1 行 JSON に修正し backend 再起動 |
| `※必須` エラー（値が入っているのに） | 動的スキーマの `default_value` 未同期 | ページをリロード（修正済み。古い web イメージの場合は再ビルド） |
| ファイルリンクが Dify 直 URL のまま（`host.docker.internal` 等） | 再ホスト失敗。`ARTIFACT_FETCH_ALLOWED_HOSTS` に **ファイル URL のホスト**が無い、または backend 未再起動 | `.env` に該当ホスト（例: `host.docker.internal`）を追加し `docker compose up -d backend`。成功時は SeaweedFS の署名付き URL になる |
| `502`（源内からの実行） | `dify-app` 未起動、コンフィグ改行 | `docker compose ps`、コンフィグを確認 |

#### APIリクエストのデータ形式(JSON) の例（= AI アプリの placeholder / 入力フォーム）

入力フォームは [AI アプリ API 仕様](genai-web/docs/AIアプリAPI仕様.md) に従って定義します。**フォームの各キーが Dify の入力変数名に対応**します。

ワークフロー（フォーム型）の例:

```json
{
  "query": {
    "title": "入力",
    "type": "textarea",
    "required": true
  }
}
```

> フォーム型（ワークフロー）は、このデータ形式を**空のまま**にすると、アプリを開いたときに `dify-app` が Dify の `/v1/parameters` から入力フォームを**自動生成**します（手書き不要）。Dify のコンポーネント（`text-input`/`paragraph`/`number`/`select`/`file`/`file-list`）を源内のフォーム項目に変換します。手書きで定義した場合はそちらが優先されます。

チャットフロー（`dify_app_type: "chat"`）は**対話型 UI で開くため、このフォーム定義は画面には使われません**。空のままで構いません。

```json
{
  "query": { "title": "メッセージ", "type": "textarea", "required": true }
}
```

### チャットフロー = 対話型 UI（対話できる）

`dify_app_type` を `chat` にしたアプリは、源内が **対話型 UI**（吹き出し形式のチャット画面）で開きます。フォーム実行型ではなく、メッセージを送るたびに会話が継続します。

- 会話の文脈は、源内が会話ごとに発行する `sessionId` を `dify-app` が **Dify の `conversation_id` に対応付けて保持**することで維持されます（SQLite, `dify_app_data` ボリューム）。
- 画面の **「新しい会話」** ボタンで `sessionId` をリセットし、新しい Dify 会話を開始できます。
- 画像 / ドキュメントの添付に対応します（`dify-app` が `/v1/files/upload` 経由で Dify に渡します）。**「ファイルを添付」ボタンは、アプリがファイルを受け付けられる場合のみ表示**されます（下記「ファイル添付」の判定条件を参照）。ファイルを使わないエージェント（例: ナレッジ検索エージェント）ではボタンは出ません。
- チャットフロー用アプリには **チャットフローの API キー** を登録してください（ワークフローとはキーで区別）。

> 補足: フォーム型アプリ（ワークフロー等）でも、placeholder に `conversation_history` キーを含めると実行結果に「会話を続ける」ボタンが出ます（疑似チャット）。チャットフローは上記の対話型 UI を使うため、この指定は不要です。
>
> AI アプリの実行履歴は backend(SQLite, `backend_data` ボリュームの `open-genai-teams.db`) に保存されます。

### ファイル添付

添付ファイルは Dify の `/v1/files/upload` にアップロードし、`upload_file_id` 参照として渡します。ファイル種別（image / audio / video / document）は MIME から自動判定します。

ファイル入力変数の解決は **チャットフロー / ワークフロー共通** で、次の順に行います（**変数名は源内側で固定しません**。フロー作成により変わってよい）。

1. `config` の `"file_var": "<変数名>"`（画面から明示指定・任意の上書き）
2. Dify の `/v1/parameters` から `file` / `file-list` 型の入力変数（例: `upload_files`）を**自動検出**
3. 上記で解決できない場合のフォールバック
   - チャットフロー: メッセージ添付（`sys.files`）として送信
   - ワークフロー: 源内フォームのキー名を Dify 変数名として割り当て

- 変数の型（`file` / `file-list`）も `/v1/parameters` から判定し、単一/配列で渡します。
- Dify 側でフローが「メッセージ添付」ではなく「入力変数(file-list)」でファイルを受け取る設計（`file_upload.enabled: false` でも入力変数は利用可）にも対応します。

#### 添付ボタンの表示可否（能力検知）

対話型 UI の「ファイルを添付」ボタンは、`dify-app` の `/schema` が返す `features.file_attach` が `true` のときだけ表示されます。判定は次の順で行い、いずれにも該当しない場合や `/parameters` の取得に失敗した場合は **非表示（fail-closed）** です。

1. `config` の `"file_attach": true` / `false`（明示指定。`false` は他条件より優先して強制 OFF）
2. `config` に `"file_var"` が設定されている
3. Dify の `/v1/parameters` の `user_input_form` に `file` / `file-list` 型の入力変数がある
4. Dify の `/v1/parameters` の `file_upload.enabled` が `true`（メッセージ添付 `sys.files` 経路）

これにより、`file_upload.enabled: false` かつ file 入力変数を持たないアプリ（例: ナレッジ検索エージェント）では、押しても効かない添付ボタンが表示されなくなります。

### 成果物ファイル（SeaweedFS 再ホスト）

Dify 等が返すファイル URL をそのまま利用者に渡さず、`backend` が **SeaweedFS（S3 互換）**
へ再アップロードし、**署名付き URL** を outputs に注入します。

```
[ブラウザ] → backend → (Dify からファイル取得) → SeaweedFS へ保存
                ↓
         署名付き URL を outputs / 履歴に記録
                ↓
[ブラウザ] ──GET──→ （公開経路）──→ SeaweedFS
```

- ドキュメント類は Markdown のダウンロードリンクとして提示（画像はインライン `content` があれば従来どおり）
- 監査ログに `file.output` を記録
- オブジェクトキーにメールアドレス等は載せず、ユーザ ID の **SHA-256 ハッシュ** を使用
- 詳細は [CHANGELOG.md](CHANGELOG.md) の「生成ファイルのオブジェクトストレージ配置」を参照

#### 環境変数（`.env`）

| 変数 | 既定（開発） | 説明 |
| --- | --- | --- |
| `S3_ENDPOINT_URL` | `http://seaweedfs:8333` | backend → SeaweedFS（**内部**。アップロード・削除） |
| `S3_PUBLIC_ENDPOINT` | `http://localhost:8333` | **利用者向け署名付き URL のホスト**（下記リバースプロキシ） |
| `S3_BUCKET` | `open-genai` | バケット名 |
| `S3_PRESIGN_EXPIRY` | `86400`（24h） | 署名付き URL の有効期限（秒）。**ファイル本体の保持期限ではない** |
| `S3_ARTIFACT_RETENTION_DAYS` | `30` | 成果物と実行履歴の保持日数（超過分を日次削除。`0` で無効） |
| `S3_ARTIFACT_PURGE_INTERVAL` | `86400` | 上記パージの実行間隔（秒） |
| `ARTIFACT_FETCH_ALLOWED_HOSTS` | （空） | 成果物取得を許可するホスト。クラウドは `files.dify.ai,upload.dify.ai`、ローカルは `host.docker.internal`、セルフホストは FILES_URL のホストを追加。allowlist ホストは private IP も可 |
| `ARTIFACT_DELIVERY_MODE` | `open`（本番既定 `carrier`） | 配信方式。`open`=結果画面に直接リンク、`carrier`=リンクファイル持ち出し（下記 LGWAN） |
| `ARTIFACT_CARRIER_FORMAT` | `txt` | `carrier` 時のリンクファイル形式（`txt` / `html` / `both`） |

#### 署名付き URL について

利用者に見える `X-Amz-*` クエリは **S3 互換の一時ダウンロードチケット** です。シークレットキーは含まれません。URL を知っている人は有効期限内にダウンロードできます（ブラウザ履歴・ログに残る点に注意）。

- **URL の期限切れ**（`S3_PRESIGN_EXPIRY`）≠ **ファイル削除**（`S3_ARTIFACT_RETENTION_DAYS`）
- 利用履歴を UI から削除すると、紐づく SeaweedFS 上のファイルも削除されます
- 保持日数を超えた成果物と実行履歴は、backend 起動時のバックグラウンド処理で自動削除されます

#### LGWAN 端末での成果物取得（配信方式: `open` / `carrier`）

LGWAN 端末からは、SeaweedFS の署名付き URL も、後述のリバースプロキシの公開 URL も、
**通常はそのままダウンロードできません**（インターネット側の宛先に届かないため）。そこで
配信方式を `ARTIFACT_DELIVERY_MODE` で切り替えられます。

| モード | 挙動 | 想定環境 |
| --- | --- | --- |
| `open` | 結果画面・履歴に署名付き URL を直接リンク表示（クリックで取得） | 開発、成果物へ直接到達できる環境 |
| `carrier` | URL を画面に出さず、**URL を記載した「リンクファイル(.txt/.html)」**をダウンロードさせる | LGWAN 等、本体へ直接到達できない環境 |

`carrier` の運用フロー:

```mermaid
flowchart LR
  subgraph lgwan [LGWAN端末]
    UI["源内 結果画面"]
    Carrier["リンクファイル(.txt/.html)"]
  end
  subgraph net [インターネット接続端末]
    File["成果物本体"]
  end
  UI -->|"リンクファイルをDL（源内API経由）"| Carrier
  Carrier -->|"データ持ち出し経路で移送"| net
  Carrier -->|"記載URLを開く"| File
```

1. AI アプリ実行後、結果画面の「ファイル一覧」に **ファイル名のみ**が表示されます（生 URL は非表示）。
2. 「〇〇 のリンクファイル」ボタンで `.txt`（既定）または `.html` を源内ポータル（`/api/...`）経由でダウンロード。
3. 職員が承認済みのデータ持ち出し経路でインターネット接続端末へ移送。
4. リンクファイル内の URL を別端末で開き、成果物本体を取得。

補足:

- リンクファイルは backend の `GET /exapps/artifact-carrier` が生成します。**所有者チェック**（オブジェクトキーのユーザーハッシュ照合）を行い、本人の成果物のみ発行します。
- リンクファイルには URL の**有効期限**（`S3_PRESIGN_EXPIRY` 起点）を記載します。持ち出しの遅延を見込み、本番では期限を長め（例: 72 時間）に設定することも検討してください。
- リンクファイル自体が有効な URL を含む**秘密情報**です。第三者に共有しないよう画面と文面で案内しています。
- 形式は `.txt` が最も持ち出しフィルタを通しやすく、`.html` はクリック可能なリンクと URL コピー欄を備えます（外部スクリプト・外部リソースなしの静的 HTML）。

##### 動作検証（`carrier` モード）

同梱の [`dify-app/dsl/File Output Test.yml`](dify-app/dsl/File Output Test.yml)（前述の「検証用ワークフロー」で登録した AI アプリ）を使って、`carrier` の一連の流れを確認できます。

1. `.env` に `ARTIFACT_DELIVERY_MODE=carrier`（形式を試す場合は `ARTIFACT_CARRIER_FORMAT=txt` / `html`）を設定し、backend を再起動:

```bash
docker compose up -d backend
```

2. 上記 AI アプリを実行（`file_url` は既定の PDF のままで可）。
3. 結果画面で次を確認:
   - 「生成されたファイル」に **URL が表示されず**、ファイル名と LGWAN 向け案内が出ること
   - 「〇〇 のリンクファイル」ボタンで `.txt`（または `.html`）がダウンロードされること
   - リンクファイルの中身に **ダウンロード URL** と **有効期限** が記載されていること
4. リンクファイル内の URL を（LGWAN 外の）ブラウザで開き、成果物 PDF が取得できること。
5. 別ユーザーの成果物キーで `GET /exapps/artifact-carrier` を叩くと `403` になること（所有者チェック。任意）。

curl でのリンクファイル取得確認（任意。`objectKey` は結果 API の `artifacts[].object_key`）:

```bash
curl -s -D - -o link.txt \
  -H "Authorization: Bearer <源内のアプリJWT>" \
  "http://localhost:8000/exapps/artifact-carrier?objectKey=exapp/<hash>/<uuid>/dummy.pdf"
cat link.txt
```

> `open` モードに戻すには `ARTIFACT_DELIVERY_MODE=open` にして backend を再起動します。同じ AI アプリで、今度は「生成されたファイル」がダウンロードリンクになることを確認できます。

#### リバースプロキシ（SeaweedFS の公開経路）

**SeaweedFS のポート（8333）をインターネットに直接公開しない** 構成を想定しています（`docker-compose.prod.yml` ではホスト公開なし）。利用者が取得する URL は **`S3_PUBLIC_ENDPOINT`** で決まり、コード変更は不要です。プロキシを用意したら `.env` の `S3_PUBLIC_ENDPOINT` だけ差し替えて `backend` を再起動してください。

| 役割 | 設定例 |
| --- | --- |
| 内部（backend → SeaweedFS） | `S3_ENDPOINT_URL=http://seaweedfs:8333`（変更不要） |
| 公開（署名付き URL のホスト） | `S3_PUBLIC_ENDPOINT=https://files.example.lg.jp` |

**推奨:** 源内本体（`proxy/nginx.conf` の `/`・`/api/`）とは別ホスト、または別サーバブロックで SeaweedFS に転送する。

nginx 設定例（専用サブドメイン `files.example.lg.jp` → SeaweedFS）:

```nginx
server {
    listen 443 ssl;
    server_name files.example.lg.jp;

    ssl_certificate     /etc/nginx/certs/fullchain.pem;
    ssl_certificate_key /etc/nginx/certs/privkey.pem;

    client_max_body_size 64m;
    resolver 127.0.0.11 valid=30s ipv6=off;

    location / {
        set $s3_upstream http://seaweedfs:8333;
        proxy_pass $s3_upstream;
        proxy_http_version 1.1;
        # 署名付き URL の検証のため Host をクライアントがアクセスしたホストに合わせる
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_buffering off;
    }
}
```

この場合 `.env.prod` では:

```bash
S3_PUBLIC_ENDPOINT=https://files.example.lg.jp
```

署名付き URL は `https://files.example.lg.jp/open-genai/exapp/<hash>/<uuid>/output.pdf?X-Amz-...` の形になります。**パスとクエリはプロキシがそのまま SeaweedFS に転送**してください（書き換えないこと）。

開発時のみ `docker-compose.yml` が `8333:8333` をホストに公開しているため、`S3_PUBLIC_ENDPOINT=http://localhost:8333` でそのまま検証できます。

> LGWAN 端末がこの公開 URL にも到達できない場合は、上記「LGWAN 端末での成果物取得」の `carrier` モードを使い、URL を記載したリンクファイルを持ち出して別端末で開いてください。

### 制約

- **チャットフロー**は NDJSON ストリーミングでトークンを逐次表示します（`/exapps/invoke/stream`）。**ワークフロー / フォーム実行型は同期形式**（`{inputs}` → `{outputs}`）で、完了後に一括表示します。いずれも非同期ポーリング形式は未対応です。
- 会話継続は**チャットフロー**が対象です（ワークフローは状態を持ちません）。

## チーム / AI アプリ管理

源内の「チーム管理」をローカル(SQLite)で実装しています。オリジナル源内のチーム概念を
**拡張**しており、自治体の実態に合わせた運用を想定しています。

### チームモデル（源内からの拡張）

- **フラットなチーム**: 親子階層は持たない。課・プロジェクト・横断チームなどを同列のチームとして管理
- **複数所属**: 1 人の利用者が **複数チーム** に所属可能（`team_users` の `(teamId, userId)` 複合キー）
- **可視範囲**: 利用者は **所属チーム + 共通チーム** の公開 AI アプリを利用可能
- **保存プロンプトの共有**: 作成時に「全体公開」または **所属チーム（複数選択）** を指定可能。
  チーム ID が共有タグとして保存され、所属メンバーが利用できる

### 権限

- チーム・メンバー・AI アプリの作成/編集/削除（ヘッダー右上「アカウント」→「チーム管理」）
- 権限モデル:
  - `SystemAdminGroup`（Keycloak グループ）: 全チームを管理。チーム作成/削除が可能
  - チーム管理者（`team_users.isAdmin`）: 自チームのメンバー/アプリを管理。**ログイン時に自動で `TeamAdminGroup` が付与**され、Keycloak 側でのグループ手動設定は不要
  - 一般メンバー: 所属チーム + 共通チームのアプリを閲覧・実行
- 共通チーム（`00000000-0000-0000-0000-000000000000`）のアプリは全認証済みユーザーが利用可能
- **管理者ツール**（監査・利用者一括・モデル制御・入力制限・RAG 管理）は専用チームに配置され、**システム管理者のみ**に表示
- **チーム作成時**: そのチーム専用の「ナレッジ検索」アプリを自動登録（タグ管理・登録・管理は専用ページ `/knowledge` のスコープ選択で実施）
- **チーム削除時**: メンバー・AI アプリ設定に加え、**そのチームの知識ベース（Qdrant）も自動消去**
- AI アプリは「リクエスト形式」(JSON) でフォームUIを定義し、外部マイクロサービスの REST API（同期: `{inputs}` → `{outputs}`）を呼び出します（[AI アプリ API 仕様](genai-web/docs/AIアプリAPI仕様.md) 準拠）。OpenGENAI 拡張の Form Spec v1 により条件表示・リアクティブフォームも利用可能

データは `backend_data` ボリュームの `open-genai-teams.db` に保存されます。

## 管理者向け exApp（システム管理者限定）

一般利用者には表示されず、実行も拒否されます。源内 UI 内で運用タスクを完結させるための exApp です。

| exApp | 用途 |
| --- | --- |
| 監査ログ参照 | 利用状況・内容ログの検索・閲覧 |
| 利用者一括管理 | CSV による Keycloak 利用者の作成・更新・削除 |
| モデル利用制御 | グループ／チーム別の利用可能モデル設定 |
| 入力制限 | 禁止語・カスタム正規表現、添付警告／ナレッジ検知／NER のトグル、マイナンバー検査 |
| プロンプトテンプレート | 標準／個人／グループ共有テンプレートの管理 |

## 入力制限と個人情報検知（添付・ナレッジ）

禁止語ブロックに加え、**氏名・住所・電話番号・マイナンバー**を種別付きで検知できます。
匿名化は行わず、**警告／ラベル表示のみ**（アップロードやナレッジ登録自体は止めません）。
実装の中核は `shared/pii_scan.py` です。

### 動作概要

| 経路 | タイミング | 利用者向けの見え方 |
| --- | --- | --- |
| チャット等の添付 | `PUT /files` 保存と同時（同期）。先頭 `PII_NER_MAX_CHARS`（既定 8,000）文字まで NER | 添付行に種別と検知箇所の抜粋付き警告。送信は可能 |
| ナレッジ登録 | 非同期ジョブ内で索引化のあと検知（`PII_KNOWLEDGE_NER_MAX_CHARS` 既定 200,000） | `/knowledge` のドキュメント一覧に `pii_labels` 等を表示 |
| プロンプト本文 | 従来どおり禁止語・カスタム正規表現・マイナンバー検査 | ヒット時はブロック（従来仕様） |

管理者向け **入力制限** exApp で次を切り替えられます。

- 添付アップロード時の個人情報警告（`warn_attachments`）
- ナレッジ登録時の個人情報検知（`scan_knowledge_pii`）
- 氏名・住所の NER 検知（`check_pii_ner`。GiNZA 未導入時は実質オフ）
- マイナンバー検査・禁止ワード・カスタム正規表現（従来どおり）

### 検知方式

| 種別 | 方式 | 備考 |
| --- | --- | --- |
| 電話番号 | 正規表現 | イメージへの GiNZA 導入不要 |
| マイナンバー | 検査用数字（総務省令） | 単なる 12 桁数字では検知しない |
| 住所 | 都道府県＋市区町村などのパターン ＋ 任意の NER | NER は GiNZA 導入時 |
| 氏名 | 任意の NER（GiNZA / spaCy） | 未導入なら氏名 NER はスキップ。明らかな誤検知はフィルタ |

### GiNZA（spaCy）のセットアップ

氏名 NER と住所 NER 強化には、**spaCy 系の日本語モデル GiNZA**（`ginza` + `ja-ginza`）を
`backend` / `rag-app` イメージに入れます。既定ビルド（`PII_INSTALL_NER=0`）では入れず、
電話・マイナンバー・住所パターンだけが動きます（イメージを軽量に保つため）。

Dockerfile（`backend/Dockerfile` / `rag-app/Dockerfile`）はビルド引数で分岐します。

```dockerfile
ARG PII_INSTALL_NER=0
RUN if [ "$PII_INSTALL_NER" = "1" ]; then \
      pip install --no-cache-dir 'ginza>=5.1.3' 'ja-ginza>=5.1.3'; \
    fi
```

Compose は `.env` / `.env.prod` の `PII_INSTALL_NER` を build args に渡します。

```bash
# --- 開発 ---
# .env に PII_INSTALL_NER=1 を設定してから再ビルド（またはコマンド先頭で渡す）
PII_INSTALL_NER=1 docker compose up -d --build backend rag-app

# --- 本番 ---
# .env.prod に PII_INSTALL_NER=1 を設定してから:
PII_INSTALL_NER=1 docker compose -f docker-compose.prod.yml --env-file .env.prod \
  up -d --build backend rag-app
# backend 再作成直後に proxy が一時的に名前解決に失敗する場合は:
docker restart open-genai-proxy
```

確認の目安:

- コンテナ内で `python -c "import spacy; spacy.load('ja_ginza'); print('ok')"` が通る
- 入力制限で「氏名・住所の NER 検知」を「する」にしたうえで、氏名を含むテキスト添付で警告が出る
- GiNZA 読込に失敗してもサービスは起動し、電話・マイナンバー等は継続動作する（ログに `[pii_scan] GiNZA 読込失敗`）

| 変数 | 既定 | 役割 |
| --- | --- | --- |
| `PII_INSTALL_NER` | `0` | ビルド時に GiNZA を入れるか（`1` で有効） |
| `PII_NER_MAX_CHARS` | `8000` | 同期添付経路の NER 対象文字数上限 |
| `PII_KNOWLEDGE_NER_MAX_CHARS` | `200000` | ナレッジ非同期経路の NER 対象文字数上限 |

注意:

- GiNZA 導入でイメージサイズとビルド時間が増えます（初回は依存取得のためネットワークが必要。閉域では事前に依存をキャッシュ／ミラーしてください）
- `ja-ginza-electra` は既定では入れません（より重い）。必要なら Dockerfile の `pip install` 行を拡張してください
- 検知は補助であり、**網羅や誤検知ゼロを保証しません**。運用では警告を確認し、本番文書での誤検知を見てトグルやフィルタを調整してください

## 制限事項（ローカル版）

- 画像生成は源内 Web の **「画像を生成」**（`/image`）を利用します。ホストで A1111 互換 SD サーバ（または `scripts/mock-sd-server.py`）が必要です。
- AI アプリの呼び出しは、Dify チャットフローが NDJSON ストリーミング、それ以外（ワークフロー / フォーム実行型）は同期形式（非同期のポーリング形式は未対応）
- 添付のうち **動画** はローカル LLM が直接扱えないため未対応（画像・ドキュメントは対応）
- 認証は SAML（Keycloak）で行います。開発用は HTTP・既定パスワードです。
  **閉域・本番**では `docker-compose.prod.yml`、TLS 証明書、`INTERNAL_SIGNING_SECRET`、
  `S3_*`、SSRF 許可ホスト等を必ず見直してください（`.env.prod.example` 参照）

## 貢献・セキュリティ

- 貢献の進め方: [CONTRIBUTING.md](CONTRIBUTING.md)
- 行動規範: [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- 脆弱性報告: [SECURITY.md](SECURITY.md)（GitHub Security Advisories を優先。公開 Issue も可だが詳細・PoC は禁止）

## ライセンス

- 本プロジェクト独自のコード（`backend/`, `rag-app/`, `whisper-app/`, `shared/`,
  `docker-compose.yml` 等）は **MIT License**（ルート [`LICENSE`](LICENSE)）。
- 同梱の `genai-web/` の出自・第三者通知は [`NOTICE`](NOTICE) および
  `genai-web/LICENSE`・`genai-web/THIRD-PARTY-NOTICES.txt` を参照してください。
- 本リポジトリはデジタル庁とは無関係の非公式フォークです（上部の免責を参照）。
