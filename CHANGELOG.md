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

[Unreleased]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.2...HEAD
[0.3.2]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.1...v0.3.2
[0.3.1]: https://github.com/hirokawaguchi/open-genai/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/hirokawaguchi/open-genai/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/hirokawaguchi/open-genai/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/hirokawaguchi/open-genai/releases/tag/v0.1.0
