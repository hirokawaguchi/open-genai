# Markdown エディタ（procuretech-editor）

プロジェクト内の文書（Markdown）を編集・校正し、出力ファイルごとに章を並べて
Word / HTML などへ合成するための汎用 Markdown エディタです（route は歴史的経緯で `procuretech-editor`）。参考実装
（Flask 版 `procureTechMarkdownEditor`）を Open GENAI の exApp 規約へ移植したもので、
`docker compose up` で **標準起動** します。

情報化企画書「ナビ」（`procuretech-navigator`）が Excel の 4 分野を対話生成するのに対し、本「エディタ」は
生成済みの複数 Markdown をプロジェクト単位で管理・編集し、文書へ合成する後工程を担います。
「ヒアリングシートから生成」では、テーマ（例: 調達仕様書）を選び、必要な Excel から章別 Markdown
を外部生成 API で作成して取り込めます。

## 起動

```bash
docker compose up -d --build
```

外部公開面は持たず、庁内利用（backend 経由）のみです。
汎用生成（`procuretech-generate-app`）とヒアリングシート（`procuretech-hearing-app`）も同時に標準起動します。

## 構成

- マイクロサービス: `procuretech-editor-app`（FastAPI + SQLite + boto3 + openpyxl、ポート `8015`）
- ファイル本体は **S3 互換ストレージ（SeaweedFS）** に保存し、メタデータ（プロジェクト・ファイルの
  相対パス／種別／サイズ）は SQLite で管理する。S3 キーは相対パスを埋め込まない不透明キーとし、
  リネーム／移動は DB 更新のみ（S3 オブジェクト移動不要）、複製時のみ S3 コピーを行う。
- backend は `/procuretech-editor/*` を HMAC 付きでプロキシ（`depends_on` なし）
- 専用ページ: Open GENAI `/procuretech-editor`
- 未起動時は専用ページ・おすすめが `/config` 失敗で非表示になり、案内を表示

## 操作の流れ

1. 「プロジェクト選択」タブで案件フォルダを新規作成、または既存を開く。
2. 「編集」タブの「ファイル管理」から Markdown を新規作成・アップロード・リネーム・複製・削除する。
3. エディタ（`@uiw/react-md-editor`）で本文を編集し、分割／編集／プレビューを切り替えて保存する。
   - ツールバーの画像ボタンからローカル画像を選ぶと、案件フォルダの `images/` へアップロードされ、
     相対パス（例: `![図](images/foo.png)`）で本文へ埋め込まれる。保存内容は相対パスのまま保持し、
     プレビューでは presigned URL に差し替えて表示する。
   - ツールバーの図ボタンから、説明文と図タイプ（AI 自動判定 / フローチャート等）を指定して
     Mermaid 図を生成し、` ```mermaid ` ブロックとして本文へ挿入する。プレビューに図として描画される。
     生成は既存「ダイアグラムを生成」と同じ genU 推論（`/predict` + 図タイプ別プロンプト）を再利用。
   - プレビュー上部の「プレビュー表示」で見出し・表のスタイルを切り替えられる（表示専用・保存内容は不変）。
     - **プレーン**（既定）／**調達仕様書風**（見出し1→「第N章」、以下 `N.N`／`N.N.N`／`(N)`／`○`、表罫線）
       ／**番号付き**（`1`／`1.1`／`1.1.1`）。調達仕様書風は spec-app の Word 出力（`custom-reference.docx`）の
       見た目に寄せたもの。選択はブラウザに記憶される。フォントは現行のまま。
4. 「編集」タブの「ヒアリングシートから生成」ボタンで、まず生成する文書の**テーマ**（例: 調達仕様書）
   を選ぶ。次にテーマが要求するヒアリングシート（例: `systemplan.xlsx` / `global.xlsx`）をアップロード
   すると、テーマに紐づく外部「文書生成」API で Markdown を生成し、結果をプロジェクトへ取り込む。
   ヒアリングシートでは設問ごとの材料ファイルに加え、生成指示から成果物 `生成文書.md` を作る。
   生成ロジック（テンプレート＋LLM/Dify）は差し替え可能な非公開サービスに閉じ込め、結果は zip で受け取る
   ため Nextcloud に依存しない。各入力は B1 マーカーで様式を検証してから送信する。
   テーマ↔ヒアリングシート↔API の紐づけは管理者が `EDITOR_GENERATE_THEMES`(JSON) で設定する。
5. 「書き出し・統合」タブで、**出力ファイル**ごとに含める章（Markdown）と順番・形式を指定して
   **合成**する。形式は `docx`（既定）/ `html` / `pptx` / `txt` / `md`。テーマの既定定義（例: 調達仕様書＝background〜other、RFI、見積総括表、一次審査表）を
   初期表示し、プロジェクト単位で並べ替え・ON/OFF・出力ファイル追加を上書きできる（「定義を保存」で永続化）。
   ヒアリングシートテーマは、生成指示の成果物（`section_key=generated`、
   ファイル名 `生成文書.md`）だけを既定の「文書」へ入れる。設問ごとの材料ファイルは
   「Markdownファイルを追加」から足せる。成果物が無ければ文書は空のまま。
   「書き出す」を押すと、ExApp が定義に従い各出力を組み立てる**非同期ジョブ**を開始し、
   待ち画面に進捗パーセントと作業中ステップ（文書合成／Excel 作成／保存）を出す。
   成果物は 1 つの zip にまとめる。配信は AI アプリ成果物と同じ
   `ARTIFACT_DELIVERY_MODE` に従う（`open`=署名付き URL、`carrier`=案内ファイル）。
   - 出力ファイルには 2 種類ある。
     - **kind=markdown**: 含める章を順に集約する。`format=docx`（省略時）はテーマの `{api_url}/compose`、
       `html` / `pptx` / `txt` / `md` は汎用合成サービス（`EDITOR_COMPOSE_URL`＝generate-app）へ送る。
     - **kind=excel**（見積総括表・一次審査表）: 取り込み時ではなく**書き出し時に**、その時点の
       （編集済み）章 Markdown＋保存パラメータから Excel を生成する（テーマの `{api_url}/excel`）。
       生成方法は `builder`（`quotation`／`primaryexam`）で示し、ソース章は生成側が決める。
       対象章が無い等で生成できない出力はスキップし、書き出し後に理由を表示する。
   - 章の参照は生成時に付与した安定 ID（`section_key`）で行うため、ファイル名を変更しても定義は壊れない。
     手動で追加した Markdown/テキストは `file_id` で参照する。

## API（ExApp / backend プロキシ共通のパス）

| メソッド・パス | 用途 |
|---|---|
| `GET /procuretech-editor/config` | 有効状態・ストレージ/生成の構成状況 |
| `GET /procuretech-editor/projects` | プロジェクト一覧 |
| `POST /procuretech-editor/projects` | プロジェクト作成（`{name}`） |
| `GET /procuretech-editor/projects/{id}` | プロジェクト詳細＋ファイル一覧 |
| `DELETE /procuretech-editor/projects/{id}` | プロジェクト削除（S3 も purge） |
| `GET /procuretech-editor/projects/{id}/files` | ファイル一覧 |
| `GET /procuretech-editor/projects/{id}/files/content?path=` | 内容取得（テキストは本文、バイナリは署名付き URL） |
| `POST /procuretech-editor/projects/{id}/files/save` | テキスト保存（`{path, content}`） |
| `POST /procuretech-editor/projects/{id}/files/upload` | アップロード（`{filename, content_b64, dir?, validate_type?}`） |
| `POST /procuretech-editor/projects/{id}/dir` | 空フォルダ作成（`.keep` センチネル） |
| `POST /procuretech-editor/projects/{id}/files/rename` | リネーム（`{old_path, new_path}`） |
| `POST /procuretech-editor/projects/{id}/files/duplicate` | 複製（`{path, new_path?}`） |
| `POST /procuretech-editor/projects/{id}/files/delete` | 削除（`{path}`） |
| `POST /procuretech-editor/projects/{id}/export` | Word 変換開始（zip 送信、`{options}`） |
| `GET /procuretech-editor/conversions/{request_id}?project_id=` | 変換ステータス／結果取得 |
| `POST /procuretech-editor/projects/{id}/generate` | 生成開始（`{theme, inputs:{<key>:<b64>}, doc_type?}`） |
| `GET /procuretech-editor/projects/{id}/generations/{request_id}` | 生成ステータス確認／成功時に結果 zip を取り込み |
| `GET /procuretech-editor/projects/{id}/generations/{request_id}/waiting` | 生成ジョブの待ち画像（PNG。`images/{id}_waiting.png` に保存） |
| `GET /procuretech-editor/projects/{id}/waiting-picture` | 書き出し待ち用の画像（Markdown 生成時の既存 PNG。無ければフォールバック） |
| `GET /procuretech-editor/projects/{id}/composition` | 合成定義（保存済み or テーマ既定）と参照可能ファイル一覧 |
| `PUT /procuretech-editor/projects/{id}/composition` | 合成定義を保存（`{composition:{theme, outputs}}`） |
| `POST /procuretech-editor/projects/{id}/compose` | 合成ジョブ開始（`request_id`。進捗は GET） |
| `GET /procuretech-editor/projects/{id}/composes/{request_id}` | 合成進捗（`progress` / `current_step`。完了時は zip の `object_key`。LGWAN の `carrier` では案内ファイル） |

すべて `user_id`（backend が JWT から付与し HMAC 署名）でスコープし、他ユーザーの
プロジェクトは参照・変更できません。

## 環境変数

| 変数 | 既定 | 用途 |
|---|---|---|
| `PROCURETECH_EDITOR_APP_URL` | `http://procuretech-editor-app:8015/invoke` | backend からの接続先 |
| `PROCURETECH_EDITOR_PORT` | `8015` | 開発時のホスト公開ポート |
| `EDITOR_DB_PATH` | `/data/procuretech_editor.db` | メタデータ SQLite |
| `EDITOR_MAX_UPLOAD_BYTES` | `20971520` | アップロード上限（約 20MB） |
| `EDITOR_S3_PREFIX` | `procuretech-editor` | S3 キー接頭辞（backend 成果物と分離） |
| `S3_*` | backend と共有 | SeaweedFS 等の接続情報 |
| `EDITOR_GENERATE_URL` | （空） | 外部「文書生成」API のベース URL。未設定なら「Excel から生成」は無効表示 |
| `EDITOR_GENERATE_API_KEY` | （空） | 生成 API へ送る `X-API-Key`（任意） |
| `EDITOR_GENERATE_TIMEOUT` | `180` | 生成 API のタイムアウト秒 |
| `EDITOR_GENERATE_DOC_TYPE` | `specification` | 既定の文書種別（`doc_type` 未指定時） |
| `EDITOR_GENERATE_THEMES` | （空） | テーマ定義(JSON)。未設定ならヒアリングシート＋調達仕様書 |

## テーマ設定（EDITOR_GENERATE_THEMES）

生成する文書の「テーマ」ごとに、必要なヒアリングシート（入力 Excel）と呼び出す生成 API を
管理者が JSON で紐づけます（1 行の JSON 文字列を環境変数へ設定）。未設定時は
ヒアリングシート（`procuretech-generate-app` / hearing で作った Excel）と
調達仕様書（`EDITOR_GENERATE_URL` / `systemplan` + `global`）の 2 テーマを持ちます。
画面に出すのは、各テーマの生成 API（`GET {api_url}/health`）が応答するときだけです。
generate-app は標準起動なのでヒアリングシートは常に出ます。spec-app はオプションなので、
未起動なら調達仕様書は出ません。カスタム JSON を置いた場合も、`navigation` が無ければ先頭に足します。

```json
[
  {
    "id": "procurement_spec",
    "label": "調達仕様書",
    "description": "情報化企画書と全般的事項から調達仕様書の章別 Markdown を生成します。",
    "doc_type": "specification",
    "api_url": "http://procuretech-spec-app:8016",
    "api_key": "（任意）",
    "inputs": [
      {"key": "systemplan", "label": "情報化企画書（systemplan.xlsx）", "marker": "systemplan", "accept": ".xlsx"},
      {"key": "global", "label": "全般的事項（global.xlsx）", "marker": "global", "accept": ".xlsx"}
    ]
  }
]
```

- `api_url` 省略時は `EDITOR_GENERATE_URL`、`api_key` 省略時は `EDITOR_GENERATE_API_KEY` を使う。
- `marker` を指定した入力は、送信前に先頭シート B1 セルの様式を検証する。
- `/config` は秘匿情報（`api_url`/`api_key`）を除いた `generate_themes` をフロントへ返す。
- 将来的には管理 UI からの編集に対応予定（現状は設定ファイル/環境変数）。

## 外部「文書生成」API 契約（ヒアリングシート → 章別 Markdown）

生成ロジック（テンプレート・LLM/Dify 呼び出し等）はソース非公開の別サービスに閉じ込め、
テーマの `api_url`（省略時 `EDITOR_GENERATE_URL`）で差し替え可能にします。結果は **zip で
受け取る**ため Nextcloud に依存しません。

- `POST {api_url}/generate`
  - multipart: テーマの各入力（`inputs[].key` をフィールド名としたファイル。例: `systemplan`, `global`）
  - form `username`、任意で `doc_type`, `options`(JSON 文字列)
  - `api_key`（省略時 `EDITOR_GENERATE_API_KEY`）が設定されていれば `X-API-Key` を付与
  - 応答 JSON（`request_id` を含む）
- `GET {api_url}/status/{request_id}`
  - 応答 JSON（`status`: `processing`/`success`/`error`、`progress`、任意で `error`）
- `GET {api_url}/result/{request_id}`
  - 応答 `application/zip`（`section*.md` 等を格納。任意で `sections.json` マニフェストを同梱）

ExApp は成功を検知すると結果 zip を展開し、プロジェクトへ取り込みます（`.keep` や隠しファイル、
`sections.json` は除外）。取り込み済みジョブは再取得せずキャッシュを返します。ジョブは開始時の
テーマを記憶し、ステータス確認・結果取得も同じテーマの API へ向けます。

### section key（`sections.json`）

生成結果 zip に `sections.json` を含めると、各ファイルへ**安定 ID（section key）**を関連付けて取り込みます。
これにより、後述の合成定義がファイル名の変更に強くなります（合成は section key、無い手動ファイルは
`file_id` で参照）。

```json
{
  "theme": "procurement_spec",
  "sections": [
    {"file": "section1.md", "section_key": "background", "title": "背景", "order": 1},
    {"file": "section2.md", "section_key": "businessPurpose", "title": "…", "order": 2}
  ]
}
```

## 出力ファイルの合成契約

「書き出し・統合」タブの合成は、順序付き本文を `{api_url}/compose`（docx）または
`EDITOR_COMPOSE_URL/compose`（html / pptx / txt / md）へ送ります。テーマ定義には section カタログ
（`sections`）と既定の合成定義（`outputs`）を持たせ、`/config` および `/composition` でフロントへ公開します。

- `POST …/compose`
  - JSON `{ "outputs": [ { "name": "調達仕様書", "format"?: "docx", "sections": [ {"filename": "section1.md", "content": "…"}, … ] }, … ], "reference"?: "specification", "assets"?: {"images/zu1.png": "<base64>"} }`
  - `format` は `docx`（既定）/ `html` / `pptx` / `txt` / `md`
  - `api_key`（省略時 `EDITOR_GENERATE_API_KEY`）が設定されていれば `X-API-Key` を付与
  - 応答 `application/zip`（出力ファイル毎に `<name>.<format>` を格納）

ExApp（`POST /projects/{id}/compose`）は、保存済み合成定義（無ければテーマ既定）に従い、有効な出力ごとに
section key／file_id を解決して本文を順に集約し、形式に応じて合成 API へ送信します。`kind=excel` の出力は書き出し時に
`{api_url}/excel` を呼び、その時点の章 Markdown＋保存パラメータから Excel を生成します（対象章が無い等で
生成できない出力は `skipped` として理由を返す）。成果物を 1 つの zip にまとめて S3 に置き、
署名付き URL（`download_url`）として返します。

### 画像・Mermaid 図の埋め込み

- **画像**: 本文の `![alt](images/…)` が参照する画像を ExApp が S3 から集め、`assets`（`{相対パス: base64}`）
  として合成 API へ同送します。視覚形式（docx / html / pptx）では埋め込み（html は data URI の単一ファイル）。
  md / txt は参照またはプレースホルダのまま。外部 URL・`data:` は対象外。
- **Mermaid 図**: 生成サービスはコードのままでは図にできないため、フロントが**視覚形式の合成時に**
  ` ```mermaid ` ブロックをブラウザで PNG 画像化して `images/` へアップロードし、本文を画像参照へ差し替えた内容を
  `overrides`（`{file_id: 本文}`）として渡します。md / txt では overrides を適用せず、Mermaid ソースを残します。
  保存済みの `.md` 本文は変更しません。

### Excel 出力（見積総括表・一次審査表）

これらは取り込み時ではなく、**書き出し（合成）時**に生成サービス（`procuretech-spec-app`）の
`POST /excel` を呼んで作ります。参考実装と同じ運用で、**その時点の（編集済み）章 Markdown** を
反映できます。合成定義では出力種別 `kind=excel` と生成方法 `builder` を持ち、ソース章は生成側が
決めます（章の並び `items` は持たない）。生成時に保存したパラメータ（`nextyear`/`phaselist`/
`projectName` を含む `template_data.json`）は ExApp がプロジェクト単位で保持し、`/excel` の `params`
として送り返します。

- 見積総括表（`builder=quotation`）: Markdown 非依存。翌年度（`nextyear`）で年度セルを埋め、
  有効フェーズ以外を `-----` にする。Dify 不要。
- 一次審査表（`builder=primaryexam`）: section2/4/5/6 相当の（編集済み）Markdown を追加 Dify
  ワークフロー（`dify_keys.json` の `criteria_section2/4/5/6`）へ送り、要件を抽出してテンプレを加工する。
  ソース章が欠落していればその章はスキップして部分的に作成する。

対象章が無い等で生成できない出力はスキップし、書き出し後に理由を表示する（本文＝Word 合成は成功扱い）。

公開の汎用リファレンス実装（`procuretech-generate-app/`）を同梱しており、標準起動します。
`/generate` は LLM/Dify なしでナビゲーションシートから章を作ります。
テーマ無しの「素の文書」の合成は既定でこのサービスが担います
（`EDITOR_COMPOSE_URL=http://procuretech-generate-app:8016`）。
入力シートは `procuretech-hearing-app`（`/hearing-sheet`）で作れます。
視覚形式（docx / html / pptx）の見た目はデジタル庁デザインシステム（DADS）に揃える
（Blue 900・Solid Gray・Noto Sans JP）。pptx は `OPENAI_BASE_URL` があるとき、章・節から
多様な layout を選び、簡潔化した根拠原文をスピーカーノートに残す。未設定・失敗時は見出し分割の
決定論変換。調達仕様書テーマの docx は従来どおり spec-app / pandoc
（`custom-reference.docx`）側のスタイル。

```bash
docker compose up -d
# これ単体を生成 API にも使う場合は EDITOR_GENERATE_URL=http://procuretech-generate-app:8016 を設定
```

## AI 文書構成（編集アシスト）

編集画面の右側ツールバー（魔法の杖）から、**選択したテキスト（未選択なら本文全体）**を対象に、
AI で「リライト／加筆／要約／整形」または任意の追加指示による変換を行えます。エンジンは AI 図生成と
同じ genU 推論（`predict`）で、テーマに依存しません。結果はモーダルのプレビューで手直しでき、
「選択を置換／本文を置換」「後ろに挿入」「再生成」から反映します（実行しても自動では本文を書き換えません）。

## 後続フェーズ（未実装）

- AI 校正（OpenAI 互換 LLM）。`llm.py` を同梱済み（将来利用）。

（実装済み）画像のアップロード＆本文への埋め込み、既存「ダイアグラムを生成」連携による
Mermaid 図の生成・本文書き戻しは「操作の流れ」の 3、Excel からの章別 Markdown 生成は「操作の流れ」の 4 を参照。

## テスト

- backend: `procuretech-editor-app/tests`（`excel` 検証・`store` CRUD・`convert`/`generate` クライアント・API）
- frontend: `packages/web/src/open-genai/procuretech-editor/format.test.ts`
