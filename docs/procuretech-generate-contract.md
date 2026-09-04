# 文書生成・合成サービス 連携契約（procuretech-editor）

`procuretech-editor`（Markdown エディタ）は、ヒアリングシート（Excel）から章別 Markdown を
生成し、出力ファイルを Word/Excel に組み立てる後段処理を、**差し替え可能（pluggable）な外部
サービス**に委譲します。生成ロジック（テンプレート・プロンプト・LLM/Dify 連携）は非公開の
別サービスに閉じ込め、Open GENAI 本体はこの契約に沿って HTTP で呼び出すだけです。

公開リポジトリには、この契約を満たす**リファレンス実装（モック）** `procuretech-generate-mock/`
を同梱しています（LLM/Dify は呼ばず、アップロード Excel の一部セルを反映したサンプルを返す）。
本番の生成サービスは非公開のため本リポジトリには含めません。

- 呼び出し元クライアント: `procuretech-editor-app/app/generate.py`
- リファレンス実装（生成側）: `procuretech-generate-mock/app/main.py`

## エンドポイント一覧

| メソッド / パス | 用途 |
| --- | --- |
| `POST {base_url}/generate` | 生成ジョブ開始（multipart で Excel をアップロード） |
| `GET  {base_url}/status/{request_id}` | 進捗ポーリング |
| `GET  {base_url}/result/{request_id}` | 生成結果 zip の取得 |
| `POST {base_url}/compose` | 順序付き Markdown を Word(`.docx`) に合成し zip で返す |

`base_url` はテーマ定義の `api_url`（省略時は環境変数 `EDITOR_GENERATE_URL`）。
`api_key` が設定されている場合、すべてのリクエストに `X-API-Key` ヘッダを付与します
（省略時は `EDITOR_GENERATE_API_KEY`）。

### POST /generate

- `multipart/form-data`
  - ファイル: テーマ定義の各入力 `key`（例: `systemplan`, `global`）＝アップロード Excel。
  - フォーム: `username`（利用者識別）, `doc_type`（テーマの文書種別。例 `specification`）,
    `options`（任意の JSON 文字列）。
- 応答: `{"request_id": "<id>"}`（`200` または `202`）。

### GET /status/{request_id}

- 応答: `{"status": "processing" | "success" | "error", "progress": <0-100>, "current_step"?: str, "error"?: str}`
- `error` のときは `error` にユーザー提示用メッセージ（例: Dify 失敗理由）を入れることを推奨。

### GET /result/{request_id}

- 応答: `application/zip`。中身は以下（詳細は「結果 zip の構造」）。
  - 章別 Markdown（`section*.md`, `README.md`, `rfi1.md` など）
  - `sections.json`（各ファイルへ安定 ID＝`section_key` を付与するマニフェスト）
  - 任意で Excel 出力（`quotation.xlsx`, `primaryexam.xlsx` など）

### POST /compose

- `application/json`

```json
{
  "outputs": [
    {
      "name": "調達仕様書",
      "sections": [
        { "filename": "section1.md", "content": "# 背景\n..." },
        { "filename": "section2.md", "content": "# 目的\n..." }
      ]
    }
  ],
  "reference": "specification"
}
```

- `outputs[].sections` は**呼び出し元で解決済みの本文を順序どおり**に並べたもの。
  生成側はこれを連結して `.docx` に変換します（リファレンスの本番実装は pandoc を使用）。
- `reference` は任意（Word のスタイル参照ドキュメントの種別など）。
- 応答: `application/zip`。出力ファイルごとに `<name>.docx` を格納。

## 結果 zip の構造 と `sections.json`

`sections.json` を zip に含めると、各ファイルへ**安定 ID（`section_key`）**を関連付けて取り込みます。
これにより、後段の合成定義がファイル名の変更に強くなります。

```json
{
  "theme": "procurement_spec",
  "sections": [
    { "file": "section1.md", "section_key": "background",       "title": "背景",         "order": 1 },
    { "file": "section2.md", "section_key": "businessPurpose",  "title": "目的",         "order": 2 },
    { "file": "rfi1.md",     "section_key": "rfi",              "title": "情報提供依頼",  "order": 10 },
    { "file": "quotation.xlsx",   "section_key": "quotation",   "title": "見積費用総括表",     "order": 11 },
    { "file": "primaryexam.xlsx", "section_key": "primaryexam", "title": "プロポーザル一次審査表", "order": 12 }
  ]
}
```

- `section_key`: 章の安定 ID。合成定義（どの出力にどの章をどの順で入れるか）はこの ID で参照する。
  `sections.json` に載っていない手動アップロードのファイルは `file_id` で参照する。
- `order`: 取り込み時の表示順の目安。

## Excel 出力（合成を経由しない出力）

見積費用総括表・プロポーザル一次審査表のような **Excel 出力は `/compose` を通さない**。
これらは `/generate` の中で生成側が Excel を作り、結果 zip に `quotation.xlsx` /
`primaryexam.xlsx` として含める（`sections.json` で `section_key` を付与）。合成エディタ上では
出力種別 `kind=excel` として扱い、Open GENAI 側が**生成済みの Excel 実体をそのまま最終 zip に
同梱**する（`.docx` と `.xlsx` を 1 つの zip にまとめて返す）。

## テーマ定義（管理者設定）

テーマ↔ヒアリングシート↔API の紐づけは環境変数 `EDITOR_GENERATE_THEMES`(JSON 配列) で与える。
未設定時は `EDITOR_GENERATE_URL` を用いる単一テーマ（調達仕様書）を既定で使う。

```json
[
  {
    "id": "procurement_spec",
    "label": "調達仕様書",
    "doc_type": "specification",
    "api_url": "http://procuretech-generate-mock:8016",
    "api_key": "",
    "inputs": [
      { "key": "systemplan", "label": "情報化企画書（systemplan.xlsx）", "marker": "systemplan", "accept": ".xlsx" },
      { "key": "global",     "label": "全般的事項（global.xlsx）",       "marker": "global",     "accept": ".xlsx" }
    ]
  }
]
```

## 関連環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `EDITOR_GENERATE_URL` | （空） | 既定テーマの生成/合成サービス base URL |
| `EDITOR_GENERATE_API_KEY` | （空） | `X-API-Key` に付与するキー |
| `EDITOR_GENERATE_TIMEOUT` | `180` | 呼び出しタイムアウト（秒） |
| `EDITOR_GENERATE_DOC_TYPE` | `specification` | 既定テーマの `doc_type` |
| `EDITOR_GENERATE_THEMES` | （空） | テーマ定義（JSON 配列） |

## ローカル検証（モック）

契約互換のモックを Compose profile で起動できます（生成 `/generate`・`/status`・`/result` を実装。
`/compose` は本番生成サービス側の責務のため、モックには含めていません）。

```bash
docker compose \
  --profile procuretech-editor --profile procuretech-editor-mock up -d
# .env で EDITOR_GENERATE_URL=http://procuretech-generate-mock:8016 を設定
```

本番の非公開生成サービスを使う場合は、gitignore 対象のオーバーレイ
`docker-compose.procuretech-spec.yml` を重ねて起動します。

```bash
docker compose \
  -f docker-compose.yml -f docker-compose.procuretech-spec.yml \
  --profile procuretech-editor --profile procuretech-spec up -d
# .env で EDITOR_GENERATE_URL=http://procuretech-spec-app:8016 を設定
```
