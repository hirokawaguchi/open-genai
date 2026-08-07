# Changelog

[Semantic Versioning](https://semver.org/) に従います。実験段階のため **0.x** 系とし、
`1.0.0` は本番運用・experimental 解除時を想定しています。

| タグ | コミット | 位置づけ |
| --- | --- | --- |
| [v0.1.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.1.0) | `fc57e53` | 源内のローカル完結化（第一段階） |
| [v0.2.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.2.0) | `6d594d5` 以降 | 自治体・閉域（LGWAN 等）向け拡張 |
| [v0.2.1](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.2.1) | `be88a0d` 以降 | セキュリティ更新・リリース前品質保証 |
| [v0.3.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.3.0) | `daac82e` 以降 | 画像生成の源内一本化・アプリピン留め・LGWAN 成果物キャリア配信 |
| [v0.3.1](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.3.1) | `e047dae` 以降 | 起動手順の修正・CI 修正・添付拡張子判定の修正 |
| [v0.3.2](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.3.2) | `1a9eb42` 以降 | 出典表示・ローカルDify成果物取得・Enter送信など |
| [v0.4.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.4.0) | `96f3484` | 構造化 RAG・ナレッジ MCP・Dify 連携事例・マイナンバー検査 |
| [v0.5.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.5.0) | `9e4015f` | 本番静的ビルド/デプロイ整備・複数LLM/埋め込み/画像モデルの差し替え・SAML/認証堅牢化 |
| [v0.6.0](https://github.com/hirokawaguchi/open-genai/releases/tag/v0.6.0) | `340e88e` | 添付・ナレッジの個人情報検知、ナレッジ専用ページ、チャット大容量添付、Dify エラー分類、OSS ガバナンス整備 |

## 設計思想の転換（0.1 → 0.2）

| 観点 | v0.1.0（ローカル源内化） | v0.2.0（自治体・閉域向け） |
| --- | --- | --- |
| 目的 | 源内を OSS／ローカルスタックで再現する | 自治体の実務・ガバナンス要件を満たしつつ、源内 UX を活かす |
| 改修の置き場 | `backend/` と最小限の `genai-web/` パッチ | **OpenGENAI レイヤ**（`backend/` + 各 exApp + `shared/`） |
| 利用者モデル | 源内準拠のチーム管理 | **チーム主体・非階層・複数所属** |
| 管理機能 | Keycloak コンソール等 | 管理者向け **exApp**（監査・利用者一括・モデル制御等） |
| ファイル出力 | backend ローカル保存 / Dify 直リンク | **SeaweedFS（S3 互換）** へ再ホスト |
| 公開面 | 各サービスを個別ポート公開 | **nginx 単一入口**（本番 TLS / 閉域 HTTP 検証） |

---

## [Unreleased]

### 日程調整（chosei）オプション機能

- `chosei-app`（FastAPI + SQLite）を Compose `profiles: ["chosei"]` でオプション起動
- 庁内は専用ページ `/chosei`（DADS）。外部ゲストは `CHOSEI_PUBLIC_ENDPOINT` の `/public` のみ（デュアルイングレス）
- 暗証番号は bcrypt ハッシュ保存。保持日数は `CHOSEI_RETENTION_DAYS`（既定 90 日）
- LLM アシスト（庁内のみ）: 最適日提案・自然文からの日程候補・案内文下書き（Ollama 等の OpenAI 互換 API）
- 詳細は [`docs/chosei.md`](docs/chosei.md)

## [0.6.0] - 2026-08-06

添付・ナレッジの個人情報検知、ナレッジ管理の専用ページ化、チャット大容量添付のマップリデュース、
Dify エラー分類の改善に加え、公式リポジトリとしてのガバナンス文書（貢献・セキュリティ・行動規範）を整備。

### 添付・ナレッジの個人情報検知（警告／ラベル）

- `shared/pii_scan.py`: 氏名・住所・電話番号・マイナンバーを種別付きで検知（匿名化なし）。電話・マイナンバーは正規表現／検査数字、住所はパターン補助、氏名・住所 NER は任意の GiNZA（`PII_INSTALL_NER=1` ビルド）
- チャット等: `PUT /files` 保存と同時に警告（`warned` / `categories`）。フロントは添付行に種別を表示（送信は可）
- ナレッジ: 登録を非同期化（`ingest_status`）。ジョブ内で索引化のあと PII 検知し、`DocsSection` にラベル表示。`NGWORD_DB_PATH` を rag-app が backend_data 経由で参照
- 入力制限画面: 添付警告・ナレッジ検知・NER のトグルを追加
- README: 動作概要と GiNZA（spaCy）セットアップ（`PII_INSTALL_NER`）を追記。`.env.example` / `.env.prod.example` に変数例を追加

### 通常チャット添付の大容量対応（その場マップリデュース）

- backend: チャット添付を 30,000 文字で黙って打ち切る挙動を廃止し、`shared/docextract.py` に切り捨てなしの `extract_doc_text_full` を追加（安全弁 `MAX_CHAT_DOC_CHARS` 既定 500,000、超過は明示注記で先頭保持）
- backend: `doc_mapreduce.py` を新設し、`chat_once`/`chat_stream` の前段でチャンク化 → 読み計画 → 抜粋 or バッチ要約を実施。しきい値 `CHAT_DOC_INLINE_CHARS`（既定 60,000）以下は全文注入、超過は圧縮して参照し「どう参照したか」を応答冒頭に明示（LLM 呼び出しは注入可能にしてテスト可能化）
- ベクトル RAG 簡易登録など従来経路の `MAX_DOC_CHARS`（30,000）切り捨ては据え置き（影響をチャットに限定）。ナレッジ登録の構造化/ベクトル hybrid とは別物（索引を作らず 1 リクエスト内で圧縮）

### Dify exApp のエラー分類と大容量処理の可視化（PR #29 残リスク緩和）

- dify-app: `classify_provider_error` を HTTP status ベースに拡張。429→レート制限、413/本文の context 超過→入力過大、その他 4xx→入力不備、5xx→接続失敗と分類し、**Dify の 4xx を「接続できません」に誤変換しない**（`_run_workflow`/chat の `default_code` はフォールバックのみ）
- dify-app（MultiFileGenerator DSL）: 270,000 文字超のサイレント切り捨てと、大容量時の区間抽出／代表要約を**黙って欠落させず可視化**。文書準備ノードで `truncated`/`kept_chars`/`coverage_note` を算出し、出力整形で表示用テキスト（`result_text`）にのみ注意文を前置（**ファイル本文 `content` は json/html を壊さないよう clean を維持**）
- 運用注意: 更新した [dify-app/dsl/MultiFileGenerator.yml](dify-app/dsl/MultiFileGenerator.yml) を Dify へ再インポート／公開する必要がある

### ナレッジ管理 専用ページ化

汎用 exApp フォームの制約を解消するため、**タグ管理・ドキュメント登録・ドキュメント管理**を
専用ページ `/knowledge` に統合。先頭のスコープセレクタで「共有ナレッジ（共通）」と
「所属チーム」を切り替えて操作できる（ナレッジ検索は従来の `rag` exApp を維持）。

- rag-app: 構造化 REST を追加（タグ CRUD／登録（ファイル base64・URL）／削除・タグ付け替え／URL 再取得／全消去）。既存 `/invoke` の action と書込ロジックを関数抽出して共用
- backend: `/knowledge/*` 認可付きプロキシと `GET /knowledge/scopes` を追加。共有スコープの書込は管理者のみ、チームスコープはメンバー（`refresh`/`clear` は管理者）
- genai-web: 専用ページ（`open-genai/knowledge/`）・ルート追加・旧管理 exApp（`rag-tags`/`rag-register`/`rag-maintain`）から `/knowledge` へのリダイレクト・ナビ導線
- 旧管理系 exApp の廃止: 共通の `rag-tags`/`rag-register`/`rag-maintain` と各チームの「タグ管理／ドキュメント登録／ドキュメント管理」を **メニュー（AI アプリ一覧）から除去**。起動時に既知ロール（`tags`/`register`/`maintain`/旧 `manage`）のレコードのみ削除し、シード・新規チーム自動登録の対象からも外した（**ナレッジ検索 `rag` は維持**。独自 RAG exApp は削除しない）
- 後方互換: 既存 `/schema` `/invoke`（`rag_role` 分岐）は残置のため、万一の旧ピン留め URL もルートで `/knowledge` へ誘導

### セキュリティ / ドキュメント

- ナレッジ検索 MCP（`knowledge-mcp` `:8002/mcp`）が**無認証**で `scope`(teamId) を任意指定でき、到達できれば全チームのナレッジを読める点を明文化。dev `docker-compose.yml` に公開バインドを制御する `KNOWLEDGE_MCP_BIND`（既定 `0.0.0.0` で従来挙動）を追加し、`.env.example`・README・[docs/knowledge-mcp.md](docs/knowledge-mcp.md) に公開範囲の絞り方（loopback/gateway バインド・FW・認証付きリバプロ）を追記。挙動の既定値は不変で、既存環境への影響はない

### OSS ガバナンス

- ルートに `SECURITY.md`（Advisories 優先・公開 Issue 可だが詳細禁止）、`CONTRIBUTING.md`、`CODE_OF_CONDUCT.md`、Issue/PR テンプレートを追加
- `LICENSE` を純粋な MIT 本文に整理し、同梱源内・非公式フォークの注記を `NOTICE` へ分離
- `genai-web/.github` にあった上流向け SECURITY / CODEOWNERS / Issue・PR テンプレを除去し、親リポ方針との混同を防ぐ注記を追加
- 顧客・個別案件の検討ドキュメントはオフィシャル公開物に含めない方針を `.gitignore` / CONTRIBUTING で明文化

---

## [0.5.0] - 2026-07-30

別環境での実運用で見つかった修正・改善をまとめて反映。**本番デプロイの整備**、
**推論/埋め込み/画像の各モデルを環境に応じて差し替えられる自由度**、**SAML・認証の堅牢化**が主軸。
既定値は従来挙動を維持しており、開発・検証・既存本番への影響はない。

### モデル利用制御・入力制限 専用ページ（管理者限定・管理系の第三弾）

- モデル利用制御を専用ページ（`/admin/model-policy`）へ移行。制御の有効/無効、全ユーザー共通の許可モデル、チーム別の追加許可を、利用可能モデルのチェックボックスで直感的に設定できる（一覧にないモデルIDの追加も可能）
- 入力制限（禁止ワード・機密情報）を専用ページ（`/admin/ngword`）へ移行。有効/無効・大文字小文字の区別・マイナンバー検査のトグル、禁止ワード・正規表現パターンの編集をフォームで行える（正規表現はクライアントでも検証、保存時に確認ダイアログ）
- 設定保存型のため、読み取りは backend が読み取り専用で直接参照し、書き込みのみ単一ライターの `modelpolicy-app`（`POST /policy`）／`ngword-app`（`POST /rules`）へプロキシ（`backend` は `GET/POST /admin/model-policy`・`GET/POST /admin/ngword` で管理者権限を検証）
- 旧 exApp 画面（`/apps/:teamId/modelpolicy`・`/apps/:teamId/ngword`）は各専用ページへリダイレクト。`/schema`・`/invoke` は後方互換で維持

### 利用者一括管理 専用ページ（管理者限定・管理系の第二弾）

- 管理者向けの利用者一括管理を汎用 exApp フォームから専用ページ（`/admin/users`）へ移行。「利用者一覧（検索・件数指定）」と「CSV一括処理（ドライラン → 確認ダイアログ → 適用）」をタブで操作でき、ドライラン結果・適用結果を表で確認できる
- 更新系のため `usermgmt-app` に構造化 REST（`GET /users`、`POST /users/plan`、`POST /users/apply`）を追加。`backend` は `/admin/users`(/plan,/apply) として管理者権限を検証（403）のうえ HMAC 署名付きでプロキシ
- CSV はファイル読み込み／貼り付けの両対応。password 列を含むため取り扱い注意を明記
- 旧 exApp 画面（`/apps/:teamId/usermgmt`）は `/admin/users` へリダイレクト。`/invoke`（Markdown 出力）は後方互換で維持

### 監査ログ専用ページ（管理者限定・管理系の第一弾）

- 管理者向けの監査ログ参照を汎用 exApp フォームから専用ページ（`/admin/audit`）へ移行。ユーザーID・アクション種別・キーワード・期間（JST）・表示件数での絞り込み、テーブル表示（日時は JST 表示）、ページング、行ごとの入力/出力全文表示、JSONL エクスポートを 1 画面で操作できる
- backend の既存 API（`GET /admin/audit-logs`(/export)、`_is_system_admin` で 403 ガード）をそのまま利用。マイクロサービスや backend プロキシの追加は不要
- 入力・出力の全文はプレーンテキスト（`<pre>`）で表示し、React 既定エスケープで XSS を防止
- 旧 exApp 画面（`/apps/:teamId/audit`）は `/admin/audit` へリダイレクト。旧 `audit-app` は無改修で維持

### プロンプトテンプレート専用ページ

- 汎用 exApp フォームの縦並び select をやめ、プロンプトテンプレートを専用ページ（`/prompts`）に。一覧の検索・区分バッジ（標準／共有／個人）、変数入力とライブプレビュー、「チャットで開く」までを 1 画面で操作できる
- `prompt-app` に構造化 REST（`/templates` 一覧・作成・削除、`/templates/{id}/render`）を追加。`backend` は `/prompts/*` として HMAC 署名付きでプロキシ
- チャットへは `navigate('/chat', { state })` で流し込むため、長文でも URL 長制限を受けない
- 旧 exApp 画面（`/apps/:teamId/prompt`）は `/prompts` へリダイレクト。`/schema`・`/resolve`・`/invoke` は後方互換で維持

### 本番配信 / デプロイ

- 本番 web を Vite dev server から**静的ビルド配信（`Dockerfile.prod` + nginx）**に変更し、dev/prod の差異を compose で吸収（#18）
- 閉域・HTTP 検証（`docker-compose.verify.yml` / `proxy/nginx.verify.conf`）を静的ビルドに整合
- 本番デプロイ手順（初回 TLS 展開・変更反映・閉域検証・前段ゲートウェイ時の SAML 注意）を README に整備（#19）

### モデル差し替えの自由度（推論 / 埋め込み / 画像）

- 複数の OpenAI 互換 LLM プロバイダを `modelId` ごとに振り分ける `LLM_PROVIDERS`（Azure/OpenAI/Gemini/Ollama 等。`auth_header`/`api-version` 対応）（#7）
- RAG 埋め込みモデルを env で差し替え可能化（`EMBED_BASE_URL`/`EMBED_MODEL`/`EMBED_DIM`/`QDRANT_COLLECTION`/prefix）。ローカル日本語埋め込み（ruri-v3 等）向けに OpenAI 互換 `embed` サイドカーを `profiles: ["embed"]` でオプトイン追加。既定は現行 mxbai 互換を維持（#21）
- 画像生成に `SD_BACKEND=a1111|fastsd` を追加。CPU-only 環境向けに FastSD CPU（LCM）アダプタを実装（既定は現行 A1111）。初期 step/cfg を `VITE_APP_IMAGE_DEFAULT_STEP`/`_CFG` でビルド時に切替（#22）

### SAML / 認証の堅牢化

- SAML ACS のプロキシヘッダ（`X-Forwarded-Proto`/`Host`/`Port`）対応で TLS 終端配下でも ACS/EntityID を正しく構築。Keycloak の重複属性を許容（#16）
- 認証エラー時に localStorage の壊れた JWT を残さず、`/auth-error` からログインへ戻す導線と 401 の自己回復を追加（#17）

### UI / UX

- ナビ配置を `VITE_APP_NAV_LAYOUT=header|sidebar` で選択可能に（サイドバー: おすすめ / ピン留め / 全AIアプリ）（#20）
- ヘッダーのアカウント表示をログイン中ユーザ名（なければ email）に変更（デスクトップ/モバイル両対応）（#23）
- チャットタイトル生成を `TITLE_MODE=heuristic|llm` で切替可能に（既定は非 LLM のヒューリスティック。拒否文がタイトル化される問題を回避）（#15）

### RAG / AI アプリ / 修正

- 管理者向け利用者一覧表示（#10）
- Dify 連携アプリで `hide_inputs` / `default_inputs` による入力の非表示・既定注入（#13）
- RAG タグ名の Unicode NFC 正規化（表記ゆれ防止）（#14）
- .docx 添付の表（テーブル）テキスト抽出に対応（#9）
- Dify MultiFileGenerator の出力形式に単一 HTML（自己完結・デジタル庁デザインシステム風）を追加。`dify-app` の MIME→拡張子補正に `text/html` を追加

---

## [0.4.0] - 2026-07-25

### 構造化 RAG と検索モード自動選択

- 規程・マニュアル向けのツリー索引（`ingest_tree` / PageIndex 系）と共通 `POST /retrieve` を追加
- `mode=auto` で候補に応じて `full` / `hybrid` / `vector` / `tree` を自動選択
- 簡易・URL 登録でも全文を保持。タグ未付与は検索対象外
- ナレッジ UI を検索／タグ／登録／管理に分割し、タグ中心の運用に整理

### ナレッジ検索 MCP と機械向け API

- `knowledge-mcp`（Streamable HTTP `:8002/mcp`）を追加。`knowledge_list_tags` / `knowledge_list_docs` / `knowledge_search` で `rag-app` をラップ
- `rag-app` に機械向け `GET /knowledge/tags` を追加し、`GET /knowledge/docs` も API キーのみで利用可能に
- `knowledge_search` / `/retrieve` で `source`・`doc_id` による資料内検索を全 mode に通す（`auto` 時は構造化なら tree、なければ vector）
- 出典アコーディオン表示名に節タイトル・ページ範囲を付与（例: `[2] 規程.pdf / 第3章 / p.10-12`）

### Dify 連携（事例 DSL・出典抽出）

- HTTP 固定 WF（根拠付き Q&A）: [`OpenGENAI-KnowledgeAgent.yml`](dify-app/dsl/OpenGENAI-KnowledgeAgent.yml)
- Agent + MCP chatflow: [`OpenGENAI-KnowledgeAgent.chatflow.yml`](dify-app/dsl/OpenGENAI-KnowledgeAgent.chatflow.yml)
- 応用例（議事録スタンス）: [`OpenGENAI-MinutesStance.yml`](dify-app/dsl/OpenGENAI-MinutesStance.yml)
- `dify-app` が Agent の `agent_log` / ツール応答から `citation_artifacts` を拾い、回答本文の `[n]` に合わせて出典を絞り込み

### ドキュメント

- 公開ガイド: [`docs/knowledge-api.md`](docs/knowledge-api.md) / [`docs/knowledge-mcp.md`](docs/knowledge-mcp.md) / [`docs/dify-knowledge.md`](docs/dify-knowledge.md)
- README の API／Dify 詳細を上記へ移し、リンク中心に短縮

### 個人番号（マイナンバー）検査

- `shared/mynumber.py` と禁止語ルールの `check_mynumber` を追加（検査数字一致のみブロック）
- 旧設定の `\d{12}` 単純一致はマイナンバー検査へ委譲。UUID（teamId 等）は誤検知しないよう除外

### テスト

- 出典抽出・MCP ヘルパ・マイナンバー・retrieve の `source` 正規化などの回帰テストを追加
- `scripts/run-regression-tests.sh` で venv の pytest を明示し、`conftest` の import パスを修正

---

## [0.3.2] - 2026-07-17

### 出典表示（RAG / Dify）

- RAG 検索ヒットと Dify Knowledge Retrieval の引用を `text/x.open-genai.citation` artifact として返し、源内 UI でアコーディオン表示（`ExAppCitations`）
- ダウンロード一覧からは citation を除外し、ファイル成果物と分離

### ローカル／セルフホスト Dify 向け成果物取得

- SSRF ガードで allowlist ホストの private/loopback 解決を許可（リンクローカルは拒否のまま）
- `ARTIFACT_FETCH_ALLOWED_HOSTS` に `host.docker.internal` 等を載せる手順を README / `.env.example` に明記

### UX

- 入力欄の送信を Enter（Shift+Enter で改行、IME 変換中は除外）に統一
- AI アプリ複製で endpoint / apiKey を編集可能にし、入力フォーム JSON（`uiFormat`）を任意化

### ナレッジ管理

- `rag-manage` を共有チーム（COMMON）へ移設し、旧 ADMIN スコープのチャンク／URL を一度きり移行
- シードアプリの teamId 変更時に履歴・ピン留めを追随

### Added

- 検証用 Dify DSL: `DeepResearch` / `DeepResearch.chatflow` / `MultiFileGenerator`

---

## [0.3.1] - 2026-07-14

### Fixed

- README の使い方に `genai-web/packages/web/.env` 作成手順を追加し、`.env.example` の `VITE_APP_MODEL_IDS` 既定値を README 推奨の `qwen2.5:7b` に合わせる（[#2](https://github.com/hirokawaguchi/open-genai/issues/2) / [#3](https://github.com/hirokawaguchi/open-genai/pull/3)）
- 添付ファイルの拡張子判定を大文字・小文字非依存にする
- CI `python-regression` の失敗と GitHub Actions の Node 20 非推奨警告を解消

---

## [0.3.0] - 2026-07-07

### 画像生成の源内一本化

- `sd-app` を廃止し、画像生成を源内 `/image` + `backend/app/image_gen.py`（A1111 互換）に統合
- 汎用 AI アプリ・画像の実行履歴を usecase 別に保存・復元、詳細設定からの永続化
- 画像生成(SD)サーバのヘルスチェック（`/image/health`）に連動し、停止時は「画像を生成」を一覧・トップから非表示

### AI アプリのピン留め

- 利用者ごとに AI アプリをピン留め（カテゴリ横断・本人のみ・上限 8 件）。トップページに「ピン留め」セクションを表示（`open-genai/app-pins/`）

### 成果物配信（SeaweedFS）と LGWAN 対応

- Dify 成果物の SeaweedFS 再ホストを整理し、保持期限超過分と実行履歴連動での自動削除を追加（`S3_ARTIFACT_RETENTION_DAYS` / `S3_ARTIFACT_PURGE_INTERVAL`）
- **LGWAN 向けキャリア配信**を追加（`ARTIFACT_DELIVERY_MODE=carrier`）。署名付き URL を画面に出さず、URL を記載したリンクファイル（`.txt` / `.html`）を所有者チェック付き `GET /exapps/artifact-carrier` から発行し、データ持ち出し後に別端末で開く運用に対応（`ARTIFACT_CARRIER_FORMAT`）
- 検証用 Dify DSL `dify-app/dsl/File Output Test.yml` と、Dify 連携・キャリア配信・リバースプロキシの手順を README に追記

### Fixed

- `.gitignore` を強化（`.env.prod`、テスト生成物、証明書拡張子）。`genai-web/packages/web/.env` の追跡をやめ `.env.example` を追加
- CI `web-regression` の `npm ci` 失敗を修正（`genai-web/package-lock.json` を同期、Node 22.22.2 に合わせる）

### 移行上の注意（0.2 → 0.3）

- `sd-app` を利用していた場合はサービスを削除（compose から除外済み。画像生成は源内 `/image` に統合）
- 閉域（LGWAN 等）では `ARTIFACT_DELIVERY_MODE=carrier` を推奨（本番 compose 既定は `carrier`、開発は `open`）

---

## [0.2.1] - 2026-07-04

### Security

- Python 依存（fastapi / starlette / PyJWT / pypdf / python-multipart / requests）を既知脆弱性修正版へ更新
- リリース前チェック用 `scripts/audit-python-deps.sh` と GitHub Actions ワークフロー `python-deps-audit` を追加

### Testing

- Open GENAI レイヤのリグレッションテスト（pytest 27件 + genai-web Open GENAI 向け Vitest）を追加
- リリース前一括実行用 `scripts/pre-release-check.sh` と CI ワークフロー `regression-tests` を追加

---

## [0.2.0] - 2026-07-04

### 自治体・閉域運用を想定した機能追加

- **監査ログ**（`backend/app/audit.py`, `audit-app/`）— 3 年以上保持、利用者削除と非連動
- **チャット履歴の利用者分離**（`chats.userId`）
- **利用者一括管理**（`usermgmt-app/`）— CSV + Keycloak Admin API
- **モデル利用制御**（`modelpolicy-app/`）
- **入力制限**（`ngword-app/`）— 禁止語・PII 正規表現
- **プロンプトテンプレート**（`prompt-app/`）
- **契約終了時のデータ完全削除**（`scripts/purge-and-report.sh`）

### チーム主体・複数所属への拡張

- 1 人複数チーム所属、保存プロンプトのチーム共有（`sharedTags`）
- RAG を「ナレッジ検索」「ナレッジ管理」に分割、**タグ + URL** モデル

### 源内 UI 制約の opt-in 拡張

- OpenGENAI exApp Form Spec v1（`visibleWhen` / `reactive` / `preview`）
- 各画面の折りたたみヘルプ、ダイアグラム Mermaid 抽出の堅牢化

### 生成ファイルのオブジェクトストレージ

- SeaweedFS + `backend/app/objstore.py`、Dify 成果物の再ホスト

### インフラ・セキュリティ

- nginx リバースプロキシ単一入口（`docker-compose.prod.yml`, `docker-compose.verify.yml`）
- 内部 HMAC 署名（`intauth.py`）、SSRF 対策（`shared/ssrfguard.py`）

### Fixed

- SeaweedFS healthcheck、backend の `depends_on: service_healthy`
- `/exapps/history` の IDOR 修正、履歴削除を本人のみに限定
- 管理者ツールチームのアプリを非システム管理者の一覧から除外

### 移行上の注意（0.1 → 0.2）

- アクセス URL が `http://localhost:5173` / `:8000` から **`http://localhost/`（proxy 経由）** に変更
- **`INTERNAL_SIGNING_SECRET`** を backend と全 exApp で同一値に設定（本番必須）
- RAG のフォルダ階層モデル（中間版）は **タグ + URL モデル** に置き換え

---

## [0.1.0] - 2026-06-27

源内（genai-web）を **クラウド依存から切り離し、ローカル LLM で完結**させる第一段階のリリース。

### Added

- **`backend/`** — FastAPI 代替 API（チャット履歴・推論ストリーム・Team API）、SAML SP + JWT
- **`genai-web/`** — デジタル庁源内 Web のローカル化パッチ（Cognito/Amplify 撤去、ローカル JWT）
- **`rag-app/`** — Qdrant + Ollama 埋め込みによる RAG AI アプリ
- **`whisper-app/`**, **`sd-app/`** — 文字起こし・画像生成 AI アプリ
- **`dify-app/`** — 外部 Dify ワークフロー／チャットフロー連携（`21f9436`）
- **`shared/docextract.py`** — PDF/Word/Excel テキスト抽出
- **Keycloak** — SAML IdP、realm `open-genai` 初期 import
- **`docker-compose.yml`** — web / backend / 各 AI アプリ / qdrant / keycloak を一括起動
- チーム・AI アプリ管理（SQLite）、共通チーム RAG、チーム単位ナレッジ分離

### 構成（v0.1.0 時点）

- 各サービスを **個別ポート公開**（web `:5173`, backend `:8000`, Keycloak `:8088` 等）
- ファイル添付は backend ローカル保存
- Dify ファイル出力は第三者 URL をそのまま提示

---

[Unreleased]: https://github.com/hirokawaguchi/open-genai/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.2...v0.4.0
[0.3.2]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/hirokawaguchi/open-genai/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hirokawaguchi/open-genai/releases/tag/v0.1.0
