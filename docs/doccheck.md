# 書類チェック（doccheck）

申請書類スキャンを領域分割し、OCR 候補と切り出し画像を庁内外へ分散チェックさせて補正データを作る機能です。Compose の **profile `doccheck`** でオプション起動します。

## クイック検証

1. `docker compose --profile doccheck up -d --build`
2. `/doccheck` → **テンプレート** で見本画像と領域を設定
3. **単件投入** または **バッチ** でスキャンを登録・配信
4. **チェック** タブ、または `http://localhost:8011/public/` で確認

同梱デモ画像は `doccheck-app/samples/demo-form.png`（`demo-template` の見本としても利用）。  
必要なら API `POST /doccheck/demo/seed` で PoC 投入も可能（UI からは撤去）。

## 連続スキャン（バッチ）運用

同じ様式が数百件届く想定向けです。

1. `/doccheck` → **バッチ** タブ
2. 帳票テンプレを選び、連続スキャン画像を複数選択して投入  
   - `1件あたりページ数=1` なら画像1枚＝申請1件（500枚→500件）
3. バックグラウンドで領域分割・OCR・（任意で）配信
4. チェック／裁定が進んだら **完了分 CSV** または **JSONL** をダウンロード

### 出力形式

| format | 用途 |
|--------|------|
| `csv` | 業務システム取込（1行＝1申請、列＝項目名） |
| `jsonl` | システム連携（1行1 JSON） |
| `json` | まとめて確認 |

API 例:

```http
GET /doccheck/batches/{batchId}/export?format=csv&status=completed
GET /doccheck/batches/{batchId}/export?format=jsonl&status=all
POST /doccheck/batches
```

`status=completed` が既定。裁定待ちを含めたい場合は `completed,needs_arbitration` または `all`。

## 削除

- 書類: ダッシュボードの「削除…」（確認ダイアログ＋タイトル再入力）、または `DELETE /doccheck/documents/{id}`
- バッチ: 「削除…」（確認＋バッチ名再入力）、または `DELETE /doccheck/batches/{id}`

## 単件の出力

- ダッシュボードの「JSONダウンロード」で確定結果を即ダウンロードし、画面にもプレビュー表示
- 大量件数はバッチタブの CSV / JSONL を利用

## テンプレート・領域設定

1. `/doccheck` → **テンプレート** タブ
2. 既存を選ぶか新規作成
3. 見本スキャンをアップロード（下絵）
4. 画像上をドラッグして領域を追加・移動・リサイズ（最大50。環境変数 `DOCCHECK_MAX_REGIONS` で変更可）
5. 名前・種別・手書き・トラップ等を設定して保存

- 座標は正規化 0–1。クロップ時の余白オーバーラップ（既定8%）はサーバが自動付与
- 自由文は行ごと・行内を複数枠に手動分割する想定（第1版は自動分割なし）
- テンプレート削除: `DELETE /doccheck/templates/{id}`（書類／バッチ参照中は不可。`demo-template` は削除不可）
- API: `POST /doccheck/templates/{id}/sample`、`PUT /doccheck/templates/{id}/regions`、`GET ...?include_sample=1`

## 起動

```bash
# 開発
docker compose --profile doccheck up -d --build

# または .env に
# COMPOSE_PROFILES=doccheck
```

本番も同様に `COMPOSE_PROFILES=doccheck` または `--profile doccheck` を付けます。`DOCCHECK_PUBLIC_ENDPOINT` に外部公開 URL を設定してください。

## 構成

| 経路 | 用途 |
|------|------|
| Open GENAI `/doccheck` | 認証済みの投入・配信・庁内チェック・裁定・スコア |
| `DOCCHECK_PUBLIC_ENDPOINT/public/...` | ゲストチェック（別ホストのリバースプロキシ） |

- マイクロサービス: `doccheck-app`（FastAPI + SQLite + Pillow）
- backend は `/doccheck/*` を HMAC 付きでプロキシ（`depends_on` なし）
- 未起動時は専用ページが有効化手順を表示し、exApp 一覧は `/health` 失敗で非表示になり得ます

## 外部公開（デュアルイングレス）

Open GENAI 本体の nginx からゲスト API を晒さないでください。別ホストで [`proxy/doccheck.public.conf.example`](../proxy/doccheck.public.conf.example) を参考に **`/public` のみ** upstream します。

開発時は `doccheck-app` のホストポート（既定 `8011`）でゲスト UI を直接確認できます。

LGWAN から外部 URL に届かない場合は、公開 URL を別端末へ持ち出して開きます。

## 合意形成（初期ルール）

- 領域ごとに最大 3 名（1 庁内 + 2 外部）へ割当
- 正規化後テキストが **2 件以上一致**し、かつ次のいずれかで採用  
  - 一致集合に庁内回答が含まれる  
  - または割当済み全員が一致
- 不一致は裁定キューへ
- テンプレートにトラップ領域（既知正解）を含め、外部の乱答を検知
- **裁定タブ／API** は `TeamAdminGroup` または `SystemAdminGroup` のみ（一般職員には非表示・403）

## OCR

| `DOCCHECK_OCR_ENGINE` | 動作 |
|----------------------|------|
| `hybrid`（開発既定） | PP-OCR（本家→RapidOCR）→ 低信頼なら Vision |
| `paddleocr`（本番推奨） | **本家 PaddleOCR 優先**。未導入・arm64 は RapidOCR にフォールバック |
| `paddle` / `rapidocr` | RapidOCR（ONNX）のみ |
| `vision` | Vision LLM のみ（既定 `gemma3:27b`） |
| `tesseract` / `none` | 印刷向け / OCR なし |

### 本家 PaddleOCR（AMD64）

既定イメージは RapidOCR のみ（arm64 開発向け）。AMD64 本番で本家を入れる場合:

```bash
# .env
DOCCHECK_INSTALL_PADDLEOCR=1
DOCCHECK_OCR_ENGINE=paddleocr

docker compose --profile doccheck build --no-cache doccheck-app
docker compose --profile doccheck up -d doccheck-app
```

- `DOCCHECK_PADDLEOCR_FORCE=1` … arm64 でも本家を試す（通常不要）
- `DOCCHECK_PADDLE_MIN_CONF` … hybrid 時に Vision へ落とす閾値（既定 0.50）
- パッケージ定義: `doccheck-app/requirements-paddleocr.txt`

## スキャンと割当

- 投入時に画像を **OCR 向け正規化**（グレースケール・コントラスト補正・長辺リサイズ。既定は A4@300dpi 相当）
- **読み取りテスト**（旧・単件）: 割当 **1** 人で自動配信（動作確認用）
- **バッチ**: 割当 **3** 人（庁内1＋外部2。`DOCCHECK_ASSIGNEES`）
- 領域クロップ時の余白オーバーラップは `DOCCHECK_OVERLAP_RATIO`（既定 8%）

## 環境変数

| 変数 | 説明 | 例 |
|------|------|-----|
| `COMPOSE_PROFILES` | `doccheck` を含めると起動 | `doccheck` |
| `DOCCHECK_APP_URL` | backend → サービス | `http://doccheck-app:8011/invoke` |
| `DOCCHECK_PUBLIC_ENDPOINT` | 外部共有 URL のホスト | `https://doccheck.example.lg.jp` |
| `DOCCHECK_PUBLIC_PORT` | 開発時ホスト公開ポート | `8011` |
| `DOCCHECK_OCR_ENGINE` | `hybrid` / `paddleocr` / `paddle` / `vision` / … | `hybrid` |
| `DOCCHECK_INSTALL_PADDLEOCR` | ビルド時に本家を入れる（`1`） | `0` |
| `DOCCHECK_VISION_MODEL` | Vision LLM モデル名 | `gemma3:27b` |
| `DOCCHECK_PADDLE_MIN_CONF` | hybrid 時の PP-OCR 最低信頼度 | `0.50` |
| `DOCCHECK_PADDLEOCR_FORCE` | arm64 でも本家を試す | `0` |
| `DOCCHECK_PADDLEOCR_LANG` | 本家の言語コード | `japan` |
| `DOCCHECK_ASSIGNEES` | バッチの領域あたり割当人数 | `3` |
| `DOCCHECK_SINGLE_ASSIGNEES` | 読み取りテストの割当人数 | `1` |
| `DOCCHECK_OCR_NORMALIZE` | 投入時の画像正規化 | `1` |
| `DOCCHECK_OCR_LONG_EDGE` | 正規化後の長辺ピクセル | `3508` |
| `DOCCHECK_OVERLAP_RATIO` | 領域オーバーラップ率 | `0.08` |

## データ

- SQLite: ボリューム `doccheck_app_data`（`/data/doccheck.db`）
- 画像: `/data/images/`
- 庁内スコアはサーバ永続。外部ゲストの累計件数はブラウザ `localStorage` のみ
