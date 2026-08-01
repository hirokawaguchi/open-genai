# Open GENAI パッチ一覧（源内 upstream 追随用）

Open GENAI は [digital-go-jp/genai-web](https://github.com/digital-go-jp/genai-web) をフォークして同梱しています。
upstream のバージョンアップ後は、本ファイルの差分箇所を順に当て直してください。

## upstream マージ手順

1. upstream `genai-web` を merge（または cherry-pick）
2. 下記「パッチ対象ファイル」を diff 確認し、Open GENAI 固有の変更を再適用
3. `packages/web/src/open-genai/` は新規ディレクトリのため通常コンフlict しない
4. `backend/` の変更は upstream genai-web とは独立（別途 Open GENAI リポジトリ側を確認）

## パッチ対象ファイル

### 認証・API 接続（初期ローカル化）

| ファイル | 内容 |
|---------|------|
| `packages/web/src/local/localAuth.ts` | ローカル SAML / JWT |
| `packages/web/src/main.tsx` | ローカルログインゲート |
| `packages/web/src/lib/fetcher.ts` | Bearer JWT 送信 |
| `packages/web/src/lib/chatApi.ts` | `/predict/stream` 直接 fetch |
| その他 | [README.md](../README.md)「源内 Web への変更点」参照 |

### AI アプリ ピン留め（Open GENAI 拡張）

利用者ごとに、よく使う AI アプリをピン留めする（カテゴリ横断・本人のみ・上限 8 件）。
ピン留めしたアプリは **トップページ** の「ピン留め」セクションに表示し、
アプリ一覧（`/apps`）では各カードのボタンで pin/unpin できる（一覧からは除外しない）。

| ファイル | 変更内容 |
|---------|---------|
| `packages/web/src/features/landing/LandingPage.tsx` | 「ピン留め」セクション（`PinnedAppsSection`）を Suspense 境界で追加 / 既定「画像を生成」カードを SD 稼働時のみ表示 |
| `packages/web/src/features/exapps/components/ExAppList.tsx` | 各カードにピン留めボタンを付与 |
| `packages/web/src/features/exapps/components/ExAppListCard.tsx` | 任意 prop `pinControl` でピンボタンを描画 |
| `packages/web/src/features/exapps/hooks/useGenUApps.ts` | 「画像を生成」を SD ヘルスチェック(`useImageAvailable`)で出し分け |

### 画像生成(SD)ヘルスチェックによる表示出し分け

画像生成サーバ(A1111 互換)が停止しているときは「画像を生成」を一覧・トップから隠す
（他 exApp の `/health` チェックに準拠）。

### プロンプトテンプレート専用ページ（Open GENAI 拡張）

汎用 exApp フォーム（縦並び select）では操作が直感的でないため、プロンプトテンプレート
だけは専用ページ（`/prompts`）で「一覧 → 変数入力 → プレビュー → チャットへ」という
カタログ型 UI を提供する。テンプレートの CRUD・変数置換は `prompt-app` の構造化 REST を
使い、チャットへは `navigate('/chat', { state })` で流し込む（URL 長制限を受けない）。
従来の汎用 exApp 画面（`/apps/:teamId/prompt`）は `/prompts` へリダイレクトする。

| ファイル | 変更内容 |
|---------|---------|
| `packages/web/src/routes.tsx` | `/prompts` ルート追加、`/apps/:teamId/prompt` → `/prompts` リダイレクト |
| `packages/web/src/layout/navItems.ts` | おすすめに「プロンプトテンプレート」、`pinnedAppHref` で `prompt` を `/prompts` に振替 |

### 監査ログ専用ページ（Open GENAI 拡張・管理者限定）

管理系の第一弾。汎用 exApp フォーム（Markdown 出力）では詳細確認・全文閲覧・エクスポート
がしづらいため、監査ログは専用ページ（`/admin/audit`）で「フィルタ → テーブル → 全文 →
エクスポート」を提供する。backend に既存の管理者限定 REST（`GET /admin/audit-logs`(/export)）が
あるため、マイクロサービスや backend プロキシの追加は不要で、フロントの専用ページのみで実現。
入力・出力の全文は `<pre>` にプレーンテキストとして表示（React 既定エスケープで XSS 安全）。
従来の汎用 exApp 画面（`/apps/:teamId/audit`）は `/admin/audit` へリダイレクトする。

| ファイル | 変更内容 |
|---------|---------|
| `packages/web/src/routes.tsx` | `/admin/audit` ルート追加、`/apps/:teamId/audit` → `/admin/audit` リダイレクト |
| `packages/web/src/layout/navItems.ts` | `pinnedAppHref` で `audit` を `/admin/audit` に振替（管理者限定のためおすすめには非追加） |

### 利用者一括管理 専用ページ（Open GENAI 拡張・管理者限定）

管理系の第二弾。汎用 exApp フォーム（操作 select ＋ Markdown 出力）では一覧・ドライラン・
適用の往復がしづらいため、専用ページ（`/admin/users`）で「利用者一覧（検索）」と
「CSV一括処理（ドライラン → 確認ダイアログ → 適用）」をタブで提供する。更新系のため、
プロンプト同様に `usermgmt-app` へ構造化 REST を追加し、`backend` が管理者権限を検証（403）
のうえ HMAC 署名付きでプロキシする。従来の汎用 exApp 画面（`/apps/:teamId/usermgmt`）は
`/admin/users` へリダイレクトする。

| ファイル | 変更内容 |
|---------|---------|
| `packages/web/src/routes.tsx` | `/admin/users` ルート追加、`/apps/:teamId/usermgmt` → `/admin/users` リダイレクト |
| `packages/web/src/layout/navItems.ts` | `pinnedAppHref` で `usermgmt` を `/admin/users` に振替（管理者限定のためおすすめには非追加） |

### モデル利用制御・入力制限 専用ページ（Open GENAI 拡張・管理者限定）

管理系の第三弾。モデル利用制御（`/admin/model-policy`）と入力制限＝禁止ワード（`/admin/ngword`）
を専用ページ化。いずれも設定保存型のため、**読み取りは backend が読み取り専用で直接参照**し
（`policy` / `ngwords` モジュール）、**書き込みは単一ライターの各サービスへプロキシ**する
（`modelpolicy-app` / `ngword-app`）。モデル利用制御は利用可能モデルとチームを
チェックボックスで選択でき、入力制限は禁止ワード・正規表現・マイナンバー検査などを
フォームで編集できる（保存時に確認ダイアログ、正規表現はクライアントでも検証）。
従来の汎用 exApp 画面（`/apps/:teamId/modelpolicy`・`/apps/:teamId/ngword`）はリダイレクトする。

| ファイル | 変更内容 |
|---------|---------|
| `packages/web/src/routes.tsx` | `/admin/model-policy`・`/admin/ngword` ルート追加、旧 exApp URL をリダイレクト |
| `packages/web/src/layout/navItems.ts` | `pinnedAppHref` で `modelpolicy`・`ngword` を各専用ページに振替（管理者限定のためおすすめには非追加） |

### Open GENAI 専用（upstream 非依存・コンフlict しにくい）

| パス | 内容 |
|------|------|
| `packages/web/src/open-genai/app-pins/` | ピン留め API hooks・振り分けユーティリティ・`PinnedAppsSection` |
| `packages/web/src/open-genai/image-health/` | 画像生成サーバ稼働確認フック `useImageAvailable` |
| `packages/web/src/open-genai/prompt-templates/` | プロンプトテンプレート専用ページ（`PromptTemplatesPage` ほか） |
| `packages/web/src/open-genai/admin-audit/` | 監査ログ専用ページ（`AuditLogsPage`・`useAuditLogs`・`types`／管理者限定） |
| `packages/web/src/open-genai/admin-usermgmt/` | 利用者一括管理 専用ページ（`UserMgmtPage`・`UserCsvSection`・`useUserMgmt`・`types`／管理者限定） |
| `packages/web/src/open-genai/admin-modelpolicy/` | モデル利用制御 専用ページ（`ModelPolicyPage`・`useModelPolicy`・`types`／管理者限定） |
| `packages/web/src/open-genai/admin-ngword/` | 入力制限（禁止ワード）専用ページ（`NgWordPage`・`useNgword`・`types`／管理者限定） |
| `backend/app/teams_store.py` | `user_app_pins` テーブル |
| `backend/app/image_gen.py` | `is_sd_up()` による SD 稼働確認 |
| `backend/app/main.py` | `GET/POST/DELETE /my/app-pins`, `GET /image/health`, `GET/POST/DELETE /prompts/templates`, `POST /prompts/templates/{id}/render`, `GET /admin/users`, `POST /admin/users/plan`, `POST /admin/users/apply`, `GET/POST /admin/model-policy`, `GET/POST /admin/ngword` |
| `prompt-app/app/main.py` | 構造化 REST（`/templates` 一覧・作成・削除、`/templates/{id}/render`）。`/schema`・`/resolve`・`/invoke` も後方互換で維持 |
| `usermgmt-app/app/main.py` | 構造化 REST（`GET /users`、`POST /users/plan`、`POST /users/apply`）。`/invoke`（Markdown）も後方互換で維持 |
| `modelpolicy-app/app/main.py` | 構造化 REST（`POST /policy` 書き込み）。`/schema`・`/invoke` も後方互換で維持（読取は backend が直接参照） |
| `ngword-app/app/main.py` | 構造化 REST（`POST /rules` 書き込み）。`/schema`・`/invoke` も後方互換で維持（読取は backend が直接参照） |

### ナレッジ管理 専用ページ（Open GENAI 拡張）

汎用 exApp フォームの制約を避け、**タグ管理・ドキュメント登録・ドキュメント管理**を
`/knowledge` の 1 画面に統合。先頭のスコープセレクタで「共有ナレッジ（共通）」と
「所属チーム」を切り替える。ナレッジ検索は従来どおり `rag` exApp を維持。

| パス | 内容 |
|------|------|
| `packages/web/src/open-genai/knowledge/` | 専用ページ（`KnowledgePage` / `TagsSection` / `RegisterSection` / `DocsSection` / `TagPicker` / `Notice`）と SWR フック（`useKnowledge.ts`）・型（`types.ts`） |
| `packages/web/src/routes.tsx` | `/knowledge` ルート追加。`apps/:teamId/rag-tags` `rag-register` `rag-maintain` を `/knowledge` へリダイレクト |
| `packages/web/src/layout/navItems.ts` | `KNOWLEDGE_PATH` 定数。`pinnedAppHref` で 3 種の管理 exApp ピンを `/knowledge` へ振替 |
| `packages/web/src/layout/navItems.ts` | 「ナレッジ管理」を `useRecommendedNavItems`（おすすめ）に追加。ナレッジは全チーム共通の専用ページに統合されたため、独立/管理者メニューではなく「おすすめ」に配置（旧管理 exApp カード廃止に伴う入口の置換）。SideNav / MobileMenu(sidebar) / LandingPage の「おすすめ」に自動反映 |
| `rag-app/app/main.py` | 構造化 REST（`/knowledge/tags` 系・`/register`・`/urls` 系・`/docs/delete`・`/docs/retag`・`/clear`）。既存 `/invoke` action と書込ロジックを共用（`_kb_*`） |
| `backend/app/main.py` | `/knowledge/*` 認可付きプロキシ（`_proxy` 相当の `_knowledge_get/_knowledge_post`）。共有=管理者のみ書込、チーム=メンバー、`refresh/clear`=管理者。`GET /knowledge/scopes` |
| `backend/app/main.py`（旧 exApp 廃止） | 共通 `rag-tags`/`rag-register`/`rag-maintain` を `EXAPP_SEEDS` から除外し `RETIRED_SEED_EXAPP_IDS` へ追加（起動時削除）。各チームは `_ensure_team_rag_search()` で「ナレッジ検索」1 つに整理し旧管理系を削除。`create_team` も検索のみ自動登録（管理は `/knowledge`） |

## 後方互換

- `pinControl` 未指定時、`ExAppListCard` は従来どおり（源内単体でも動作）
- `GET /my/app-pins` 失敗時、フロントは `[]` 扱いでピンなし表示にフォールバック
- `PinnedAppsSection` はピン 0 件・取得失敗時に何も描画しない（トップページに影響なし）
- プロンプトテンプレートの旧 exApp API（`/schema`・`/resolve`・`/invoke`）は維持するため、
  ブックマーク・履歴リンク・旧クライアントも従来どおり動作する
