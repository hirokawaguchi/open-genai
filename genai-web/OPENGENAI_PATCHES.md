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

### Open GENAI 専用（upstream 非依存・コンフlict しにくい）

| パス | 内容 |
|------|------|
| `packages/web/src/open-genai/app-pins/` | ピン留め API hooks・振り分けユーティリティ・`PinnedAppsSection` |
| `packages/web/src/open-genai/image-health/` | 画像生成サーバ稼働確認フック `useImageAvailable` |
| `backend/app/teams_store.py` | `user_app_pins` テーブル |
| `backend/app/image_gen.py` | `is_sd_up()` による SD 稼働確認 |
| `backend/app/main.py` | `GET/POST/DELETE /my/app-pins`, `GET /image/health` |

## 後方互換

- `pinControl` 未指定時、`ExAppListCard` は従来どおり（源内単体でも動作）
- `GET /my/app-pins` 失敗時、フロントは `[]` 扱いでピンなし表示にフォールバック
- `PinnedAppsSection` はピン 0 件・取得失敗時に何も描画しない（トップページに影響なし）
