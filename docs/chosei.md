# 日程調整（chosei）

庁内・外部参加者向けの日程調整機能です。Compose の **profile `chosei`** でオプション起動します。

## 起動

```bash
# 開発
docker compose --profile chosei up -d --build

# または .env に
# COMPOSE_PROFILES=chosei
```

本番も同様に `COMPOSE_PROFILES=chosei` または `--profile chosei` を付けます。`CHOSEI_PUBLIC_ENDPOINT` に外部公開 URL を設定してください。

## 構成

| 経路 | 用途 |
|------|------|
| Open GENAI `/chosei` | 認証済みの作成・回答・集計（DADS 専用画面） |
| `CHOSEI_PUBLIC_ENDPOINT/public/...` | ゲスト回答（別ホストのリバースプロキシ） |

- マイクロサービス: `chosei-app`（FastAPI + SQLite）
- backend は `/chosei/*` を HMAC 付きでプロキシ（`depends_on` なし）
- 未起動時は専用ページが有効化手順を表示し、exApp 一覧は `/health` 失敗で非表示

## 外部公開（デュアルイングレス）

Open GENAI 本体の nginx からゲスト API を晒さないでください。別ホストで [`proxy/chosei.public.conf.example`](../proxy/chosei.public.conf.example) を参考に **`/public` のみ** upstream します。

開発時は `chosei-app` のホストポート（既定 `8010`）でゲスト UI を直接確認できます。

LGWAN から外部 URL に届かない場合は、イベント画面の「リンクファイル」を持ち出して別端末で開きます。

## データ保持

- 既定で作成から **90 日**経過したイベントを自動削除（`CHOSEI_RETENTION_DAYS`）
- データはボリューム `chosei_app_data`（`/data/chosei.db`）
- バックアップは当該ボリュームまたは DB ファイルのコピーで行う

## LLM アシスト（庁内のみ）

OpenAI 互換 API（既定は Ollama）を使い、次を提供します（ゲスト公開面には出しません）。

| 機能 | API | UI |
|------|-----|-----|
| 最適日の提案 | `POST /chosei/events/{id}/assist/recommend` | イベント詳細 |
| 自然文→日程候補 | `POST /chosei/assist/parse-dates` | 作成画面 |
| 案内文の下書き | `POST /chosei/events/{id}/assist/invite` | イベント詳細 |

LLM 失敗時、最適日提案は ○△× の簡易スコアにフォールバックします。

## 環境変数

| 変数 | 説明 | 例 |
|------|------|-----|
| `COMPOSE_PROFILES` | `chosei` を含めると起動 | `chosei` |
| `CHOSEI_APP_URL` | backend → サービス | `http://chosei-app:8010/invoke` |
| `CHOSEI_PUBLIC_ENDPOINT` | 外部共有 URL のホスト | `https://chosei.example.lg.jp` |
| `CHOSEI_PUBLIC_PORT` | 開発時ホスト公開ポート | `8010` |
| `CHOSEI_RETENTION_DAYS` | 保持日数 | `90` |
| `CHOSEI_MODEL` | アシスト用モデル | `qwen2.5:7b`（未設定時は `DEFAULT_MODEL`） |
| `OLLAMA_BASE_URL` / `OPENAI_BASE_URL` | LLM エンドポイント | 他サービスと同様 |
