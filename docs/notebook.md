# ノートブック

参考資料を取込時に構造化し、項目として整理する専用ページです。
文書生成用の **ヒアリングシート（Excel）** も同じノートから出せます。
`exAppId` は `notebook`、画面は `/notebook` です（旧 `/hearing-sheet` `/procuretech-hearing` はリダイレクト）。

- 専用ページ: `/notebook`
- フロント: `genai-web/packages/web/src/open-genai/notebook/`（`NotebookPage`）
- マイクロサービス: `notebook-app`（コンテナ `open-genai-notebook-app`。FastAPI + SQLite、ポート `8017`）
- `docker compose up -d` で **標準起動**（プロファイル不要）

情報化企画書ナビ（`procuretech-navigator`）が Excel の固定欄を対話で埋めるのに対し、
本アプリは項目名＝設問を自由に増減し、取込済みソースの該当節だけを材料に行ごと生成します。
既存ナレッジの参照と、同じソースでの対話もできます。対話は項目の補助です。
記入済みシートは Markdown エディタの「ヒアリングシートから生成」で
テーマ「ヒアリングシート」を選んで読み込みます（hearing から generate-app は呼びません）。
読み込み後は設問ごとの材料ファイル（`01_設問名.md`）と、生成指示に基づく成果物
（`生成文書.md`）がプロジェクトに入ります。

## シート契約

先頭シートの契約です。

| セル | 内容 |
| --- | --- |
| `B1` | 種別マーカー `hearing-sheet`（情報化企画書の `systemplan` / `global` と同じ位置。旧 `navigation-sheet` も読む） |
| A 列 `ナビゲーション` の B | Markdown 表 `\| 項目 \| 値 \|` |
| A 列 `生成指示` の B | generate-app が成果物 Markdown（`生成文書.md`）を書くための処理指示 |

画面では項目を構造化編集し、xlsx 書き出し時だけ表へシリアライズします。
空雛形は本ページと `GET /template/hearing`（generate-app。`navigation` も可）から取得できます。

詳細は [`docs/procuretech-generate-contract.md`](procuretech-generate-contract.md) を参照してください。

## 起動

```bash
docker compose up -d --build
```

庁内利用のみ（backend → 本サービス）。外部公開面は持ちません。
行ごとの生成を使う場合は OpenAI 互換 LLM（既定は Ollama）が必要です。`HEARING_LLM=0` なら手入力のみです。

## 構成

- backend は `/notebook/*` を HMAC 付きでプロキシ（旧 `/procuretech-hearing/*` はエイリアス）
- 参考ファイルの本文化はナレッジと同じ `shared/docextract.py`。取込時に節へ分け、生成・対話は節を選ぶ（Qdrant は使わない）
- 既存ナレッジをソースに足すときは、backend が rag-app からスナップショットしてノートへ隔離する（チームのナレッジ検索には出ない）
- 対応拡張子: `.pdf` `.docx` `.xlsx` `.pptx` `.txt` `.md` `.csv` `.html` `.json`
- 上限は `MAX_DOC_BYTES`（既定 20MB）。スキャン PDF は OCR なしで失敗します

## 環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `NOTEBOOK_APP_URL` | `http://notebook-app:8017/invoke` | backend からの接続先（旧 `PROCURETECH_HEARING_APP_URL` も可） |
| `NOTEBOOK_PORT` | `8017` | 開発時のホスト公開ポート（旧 `PROCURETECH_HEARING_PORT` も可） |
| `HEARING_RETENTION_DAYS` | `30` | 作業の保持日数 |
| `MAX_DOC_BYTES` | `20971520` | 参考ファイルの上限 |
| `HEARING_LLM` | `1` | `0` で行ごと生成を無効化 |
| `PROCURETECH_MODEL` | `DEFAULT_MODEL` または `qwen2.5:7b` | 行ごと生成のモデル |
