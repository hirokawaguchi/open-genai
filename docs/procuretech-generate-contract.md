# 文書生成・合成サービス 連携契約（procuretech-editor）

`procuretech-editor`（Markdown エディタ）は、ヒアリングシート（Excel）から章別 Markdown を
生成し、出力ファイルを Word/Excel に組み立てる後段処理を、**差し替え可能（pluggable）な外部
サービス**に委譲します。生成ロジック（テンプレート・プロンプト・LLM/Dify 連携）は非公開の
別サービスに閉じ込め、Open GENAI 本体はこの契約に沿って HTTP で呼び出すだけです。

公開リポジトリには、この契約を満たす**公開の汎用リファレンス実装** `procuretech-generate-app/`
を同梱しています。LLM/Dify には依存せず、同梱の簡単なヒアリングシート
（`materials/hearing/hearing-sample.xlsx`）を読み取り、章別 Markdown の生成・Word(.docx) 合成・
様式ダウンロードまで一通り動作します。テーマ無しの「素の文書」の Word 化の既定バックエンドでもあり
（`EDITOR_COMPOSE_URL`）、`procuretech-editor` プロファイルで同時起動します。本番のテーマ固有
生成サービス（例: 調達仕様書）は非公開のため本リポジトリには含めません。

- 呼び出し元クライアント: `procuretech-editor-app/app/generate.py`
- 汎用リファレンス実装（生成側）: `procuretech-generate-app/app/main.py`

## エンドポイント一覧

| メソッド / パス | 用途 |
| --- | --- |
| `POST {base_url}/generate` | 生成ジョブ開始（multipart で Excel をアップロード） |
| `GET  {base_url}/status/{request_id}` | 進捗ポーリング |
| `GET  {base_url}/result/{request_id}` | 生成結果 zip の取得 |
| `POST {base_url}/compose` | 順序付き Markdown を Word(`.docx`) に合成し zip で返す |
| `POST {base_url}/excel` | 書き出し時に、その時点の章 Markdown＋保存パラメータから Excel を生成（任意実装） |
| `GET  {base_url}/template/{input_key}` | 入力（ヒアリングシート）の様式ファイルを配信（任意実装） |

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
  - 任意で `template_data.json`（書き出し時の Excel 生成に使う保存パラメータ。
    例: `{"nextyear":"2027","phaselist":"1, 2, 3","projectName":"…"}`）。
    Open GENAI 側はファイルとして取り込まず、プロジェクトのパラメータとして保持し、
    `/excel` 呼び出し時に `params` として送り返す。

### POST /compose

- `application/json`

```json
{
  "outputs": [
    {
      "name": "調達仕様書",
      "sections": [
        { "filename": "section1.md", "content": "# 背景\n...\n![図](images/zu1.png)" },
        { "filename": "section2.md", "content": "# 目的\n..." }
      ]
    }
  ],
  "reference": "specification",
  "assets": {
    "images/zu1.png": "<base64>"
  }
}
```

- `outputs[].sections` は**呼び出し元で解決済みの本文を順序どおり**に並べたもの。
  生成側はこれを連結して `.docx` に変換します（本番は pandoc、実装サンプルは python-docx を使用）。
- `reference` は任意（Word のスタイル参照ドキュメントの種別など）。
- `assets` は任意。本文が参照する**画像を `{相対パス: base64}`** で渡す。生成側は本文と
  同じ相対パスに画像を配置してから変換することで、Word へ画像を埋め込む
  （pandoc は入力 Markdown と同じディレクトリを `--resource-path` に含めて解決する）。
  相対パスは Markdown の画像記法 `![alt](相対パス)` と一致させること。
  **Mermaid 図はコードのままでは画像化されない**ため、呼び出し元（エディタ）が
  合成前に PNG 画像へ変換して `assets` に載せ、本文の ```` ```mermaid ```` ブロックを
  画像参照へ差し替えてから送る。
- 応答: `application/zip`。出力ファイルごとに `<name>.docx` を格納。

### POST /excel

Excel 出力（見積費用総括表・プロポーザル一次審査表など）は、**書き出し（合成）時**に
その時点の（編集済み）章 Markdown と保存パラメータから生成する。

- `application/json`

```json
{
  "builder": "quotation",
  "params": { "nextyear": "2027", "phaselist": "1, 2, 3", "projectName": "…", "username": "…" },
  "sections": { "background": "# 背景\n…", "system": "# システム要件\n…" }
}
```

- `builder`: 生成方法の識別子（例: `quotation`=見積費用総括表 / `primaryexam`=一次審査表）。
  どの章を使うか・LLM/Dify をどう呼ぶかは**生成側が builder ごとに決める**。
- `params`: 生成時に保存したパラメータ（`/generate` の `template_data.json` 由来）。
- `sections`: 現時点の（編集済み）章本文を `{section_key: 本文}` で渡す。生成側は builder に
  必要な章だけ使う。**ソース章が欠落していればその章はスキップ**して部分的に作成する。
- 応答:
  - `200`: `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`（xlsx バイト列）。
  - `422`: 生成対象なし・パラメータ不足など、**この出力をスキップすべき**とき（`{"error": "…"}`）。
    呼び出し元は当該出力を最終 zip から外し、利用者に理由を提示する。
  - `400`/`5xx`: 不正・失敗。

### GET /template/{input_key}

- テーマ定義の入力 `key`（例: `systemplan`, `global`, `hearing`）に対応する**ヒアリングシート様式**
  （空フォームの Excel）を配信する。実装は任意（未対応なら `404`）。
- 応答: `200` で `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`、
  `Content-Disposition: attachment; filename="..."`。見つからなければ `404`。
- テーマ定義の入力に `"template": true` を付けると、エディタの生成ダイアログに
  「様式をダウンロード」リンクが表示され、`GET /procuretech-editor/themes/{theme}/inputs/{key}/template`
  経由でこのファイルが配布される（ExApp が取得して署名付き URL で返す）。

## 結果 zip の構造 と `sections.json`

`sections.json` を zip に含めると、各ファイルへ**安定 ID（`section_key`）**を関連付けて取り込みます。
これにより、後段の合成定義がファイル名の変更に強くなります。

```json
{
  "theme": "procurement_spec",
  "sections": [
    { "file": "section1.md", "section_key": "background",       "title": "背景",         "order": 1 },
    { "file": "section2.md", "section_key": "businessPurpose",  "title": "目的",         "order": 2 },
    { "file": "rfi1.md",     "section_key": "rfi",              "title": "情報提供依頼",  "order": 10 }
  ]
}
```

- `section_key`: 章の安定 ID。合成定義（どの出力にどの章をどの順で入れるか）はこの ID で参照する。
  `sections.json` に載っていない手動アップロードのファイルは `file_id` で参照する。
- `order`: 取り込み時の表示順の目安。

## Excel 出力（書き出し時に生成）

見積費用総括表・プロポーザル一次審査表のような **Excel 出力は `/generate` 時に固定せず、
書き出し（合成）時に `/excel` で生成**する。これにより、取り込み後に章 Markdown を編集した
内容が Excel（特に一次審査表）にも反映される（参考実装と同じ運用）。

- 合成定義では出力種別 `kind=excel` と生成方法 `builder`（例 `quotation` / `primaryexam`）を持つ。
  ソース章は生成側が決めるため、Excel 出力は `items`（章の並び）を持たない。
- 書き出し時、Open GENAI 側は有効な Excel 出力ごとに `/excel` を呼び、返った xlsx を
  最終 zip（`.docx` と同じ zip）に同梱する。`422`（対象章なし等）ならその出力を外し、
  利用者へ理由を提示する。
- 見積費用総括表は Markdown に依存せず `params`（`nextyear`/`phaselist`）から作る。
  一次審査表は `sections` の該当章（section2/4/5/6 相当）を LLM/Dify で要件抽出して作る。

## テーマ定義（管理者設定）

テーマ↔ヒアリングシート↔API の紐づけは環境変数 `EDITOR_GENERATE_THEMES`(JSON 配列) で与える。
未設定時は `EDITOR_GENERATE_URL` を用いる単一テーマ（調達仕様書）を既定で使う。

```json
[
  {
    "id": "procurement_spec",
    "label": "調達仕様書",
    "doc_type": "specification",
    "api_url": "http://procuretech-spec-app:8016",
    "api_key": "",
    "inputs": [
      { "key": "systemplan", "label": "情報化企画書（systemplan.xlsx）", "marker": "systemplan", "accept": ".xlsx", "template": true },
      { "key": "global",     "label": "全般的事項（global.xlsx）",       "marker": "global",     "accept": ".xlsx", "template": true }
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
| `EDITOR_COMPOSE_URL` | `http://procuretech-generate-app:8016` | 素の文書（テーマ無し）の Word 合成先（汎用サービス） |
| `EDITOR_COMPOSE_API_KEY` | `EDITOR_GENERATE_API_KEY` | 汎用合成サービスへ付与するキー |

## ローカル検証（汎用リファレンス実装）

契約を満たす**公開の汎用リファレンス実装** `procuretech-generate-app` は `procuretech-editor`
プロファイルで同時起動します。`/generate`・`/status`・`/result`・`/compose`・`/excel`・`/template`
を実装し、同梱の簡単なヒアリングシートで生成〜Word 合成〜様式ダウンロードまで一通り確認できます
（LLM/Dify 不要）。テーマ無しの素の文書の Word 化は既定でこのサービスが担います。

```bash
docker compose --profile procuretech-editor up -d
# これ単体を生成 API にも使う場合は EDITOR_GENERATE_URL=http://procuretech-generate-app:8016 を設定
```

単一入力のサンプルテーマ（ヒアリングシート 1 枚）を試すには、`EDITOR_GENERATE_THEMES` に次を設定します。

```json
[
  {
    "id": "sample",
    "label": "サンプル文書",
    "doc_type": "sample",
    "api_url": "http://procuretech-generate-app:8016",
    "inputs": [
      { "key": "hearing", "label": "ヒアリングシート（hearing-sample.xlsx）", "marker": "hearing-sample", "accept": ".xlsx", "template": true }
    ],
    "sections": [
      { "key": "background", "label": "背景" },
      { "key": "purpose", "label": "目的" },
      { "key": "target", "label": "対象業務" },
      { "key": "requirements", "label": "主要要件" },
      { "key": "schedule", "label": "想定スケジュール" }
    ],
    "outputs": [
      { "id": "doc", "name": "サンプル文書", "kind": "markdown", "sections": ["background", "purpose", "target", "requirements", "schedule"] }
    ]
  }
]
```

本番の非公開生成サービスを使う場合は、gitignore 対象のオーバーレイ
`docker-compose.procuretech-spec.yml` を重ねて起動します。

```bash
docker compose \
  -f docker-compose.yml -f docker-compose.procuretech-spec.yml \
  --profile procuretech-editor --profile procuretech-spec up -d
# .env で EDITOR_GENERATE_URL=http://procuretech-spec-app:8016 を設定
```
