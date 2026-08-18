# フォーム（patchform）

庁内・外部回答者向けのオンラインフォームです。Compose の **profile `patchform`** でオプション起動します。画面上の日本語名は「フォーム」です。

## 起動

```bash
# 開発
docker compose --profile patchform up -d --build

# または .env に
# COMPOSE_PROFILES=patchform
```

本番も同様に `COMPOSE_PROFILES=patchform` または `--profile patchform` を付けます。`PATCHFORM_PUBLIC_ENDPOINT` に外部公開 URL を設定してください。

## 構成

| 経路 | 用途 |
|------|------|
| Open GENAI `/patchform` | 認証済みの作成・回答・集計（DADS 専用画面） |
| `PATCHFORM_PUBLIC_ENDPOINT/public/...` | ゲスト回答（別ホストのリバースプロキシ） |

- マイクロサービス: `patchform-app`（FastAPI + SQLite）
- backend は `/patchform/*` を HMAC 付きでプロキシ（`depends_on` なし）
- 未起動時は専用ページが有効化手順を表示し、exApp 一覧は `/health` 失敗で非表示

## 外部公開（デュアルイングレス）

Open GENAI 本体の nginx からゲスト API を晒さないでください。別ホストで [`proxy/patchform.public.conf.example`](../proxy/patchform.public.conf.example) を参考に **`/public` のみ** upstream します。

開発時は `patchform-app` のホストポート（既定 `8012`）でゲスト UI を直接確認できます。

LGWAN から外部 URL に届かない場合は、フォーム画面の「リンクファイル」を持ち出して別端末で開きます。

## データ保持

- 既定で作成から **365 日**経過したフォームを自動削除（`PATCHFORM_RETENTION_DAYS`）。フォームごとに変更可
- データはボリューム `patchform_app_data`（`/data/patchform.db`）
- バックアップは当該ボリュームまたは DB ファイルのコピーで行う

## フォーム定義

定義は JSON 契約 `opengenai-patchform/1` です。カタログに無い部品、または未実装（`enabled: false`）の部品は保存できません。

現在利用できる部品: text, textarea, email, phone, number, select, radio, checkbox, slider, rating, date, time, datetime-local, daterange, file, address_composite, user_info_composite, company_info_composite, financial_institution_composite, calculated, text_display, image_display, divider, page_break, password, mynumber（庁内専用・暗号化）, matrix_question, signature_pad, location, qr_scanner, image_recognition, document_reader

各部品には任意で IMI 語彙（`imi_type`）を付けられます。マイナンバーは `internal` 以外の公開範囲では配置できません。画像認識は Vision モデル、文書読取はテキストファイルを自動抽出し、失敗時は手入力できます。

庁内の詳細画面では回答内容を開き、CSV / JSONL で書き出せます。ゲスト送信前には確認画面が出ます。

## LLM アシスト（庁内のみ）

OpenAI 互換 API（既定は Ollama）でフォーム定義の作成・修正と案内文下書きを行います。失敗時は自治体向けテンプレートにフォールバックします。ゲスト公開面には出しません。

## 環境変数

| 変数 | 説明 | 例 |
|------|------|-----|
| `COMPOSE_PROFILES` | `patchform` を含めると起動 | `patchform` |
| `PATCHFORM_APP_URL` | backend → サービス | `http://patchform-app:8012/invoke` |
| `PATCHFORM_PUBLIC_ENDPOINT` | 外部共有 URL のホスト | `https://form.example.lg.jp` |
| `PATCHFORM_PUBLIC_PORT` | 開発時ホスト公開ポート | `8012` |
| `PATCHFORM_RETENTION_DAYS` | 既定の保持日数 | `365` |
| `PATCHFORM_MODEL` | アシスト用モデル | `qwen2.5:7b` |
| `PATCHFORM_VISION_MODEL` | 画像認識用 Vision モデル | `gemma3:12b` |
| `PATCHFORM_ENCRYPT_KEY` | マイナンバー暗号化鍵（Fernet）。未設定時は内部署名鍵から導出 | |
