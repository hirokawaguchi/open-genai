# ノートブック

参考資料を取込時に構造化し、項目として整理する専用ページです。
Markdown エディタに読み込ませる **ヒアリングシート（Excel）** も同じノートから出せます。
`exAppId` は `notebook`、画面は `/notebook` です（旧 `/hearing-sheet` `/procuretech-hearing` はリダイレクト）。

- 専用ページ: `/notebook`
- フロント: `genai-web/packages/web/src/open-genai/notebook/`（`NotebookPage`）
- マイクロサービス: `notebook-app`（コンテナ `open-genai-notebook-app`。FastAPI + SQLite、ポート `8017`）
- `docker compose up -d` で **標準起動**（プロファイル不要）

情報化企画書ナビ（`procuretech-navigator`）が Excel の固定欄を対話で埋めるのに対し、
本アプリは項目名＝設問を自由に増減し、取込済みソースの該当節だけを材料に行ごと生成します。
既存ナレッジの参照と、同じソースでの対話もできます。対話は項目の補助です。
対話にはスキル（性格と手順）を付けられ、参考資料検索と MCP を回す短いハーネスが入ります。
下書きは人が「項目に追加／更新」して初めてシートの正本になります。
共有ナレッジ MCP のヒットは参照で、参考資料への自動取込はしません。
記入済みシートは Markdown エディタの「ヒアリングシートから生成」で
テーマ「ヒアリングシート」を選んで読み込みます（hearing から generate-app は呼びません）。
読み込み後は設問ごとの材料ファイル（`01_設問名.md`）と、生成指示に基づく成果物
（`生成文書.md`）がプロジェクトに入ります。

## シート契約

先頭シートの契約です。

| セル | 内容 |
| --- | --- |
| `B1` | 種別マーカー `hearing-sheet`（情報化企画書の `systemplan` / `global` と同じ位置。旧 `navigation-sheet` も読む） |
| `A2` / `B2` | 見出し `項目` / `回答` |
| 3 行目以降 | 設問（A）と回答（B）。回答の改行はセル内改行 |
| A 列 `生成指示` の B | Markdown エディタが成果物 Markdown（`生成文書.md`）を書くための処理指示 |

画面では項目を構造化編集し、xlsx 書き出し時に 1 行 1 設問へします。
旧形式（A 列 `ナビゲーション` の B に Markdown 表）も読みます。
空雛形は本ページと `GET /template/hearing`（generate-app。`navigation` も可）から取得できます。
記入済みのダウンロード名は `ヒアリングシート_<ノート名>_YYYYMMDDHHMMSS.xlsx` です。

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
- 上限は `MAX_DOC_BYTES`（既定 20MB）
- 取込時に Markdown 見出し、または「第○条／様式」などの行で節分けする。無ければページ塊
- 生成・対話はキーワードと見出しの重なりで節を選ぶ（無関係な節は捨てる。Qdrant は使わない）。日本語は助詞で切って 2〜3 文字の重なりを見る
- スキャン PDF は本文が取れないページを RapidOCR で読む（doccheck と同じ系統。`NOTEBOOK_OCR=0` で無効。上限 `NOTEBOOK_OCR_MAX_PAGES`）

## 環境変数

| 変数 | 既定 | 用途 |
| --- | --- | --- |
| `NOTEBOOK_APP_URL` | `http://notebook-app:8017/invoke` | backend からの接続先（旧 `PROCURETECH_HEARING_APP_URL` も可） |
| `NOTEBOOK_PORT` | `8017` | 開発時のホスト公開ポート（旧 `PROCURETECH_HEARING_PORT` も可） |
| `HEARING_RETENTION_DAYS` | `30` | 作業の保持日数 |
| `MAX_DOC_BYTES` | `20971520` | 参考ファイルの上限 |
| `HEARING_LLM` | `1` | `0` で行ごと生成を無効化 |
| `PROCURETECH_MODEL` | `DEFAULT_MODEL` または `qwen2.5:7b` | 行ごと生成・対話ハーネスのモデル |
| `HEARING_LLM_MAX_TOKENS` | `8192` | 対話・行生成の応答上限。長い表が途中で切れるときは上げる |
| `KNOWLEDGE_MCP_URL` | `http://knowledge-mcp:8002/mcp` | 共有ナレッジ（共通チーム）を Dify 抜きで呼ぶ。空ならその MCP は未接続 |
| `NOTEBOOK_MCP_TIMEOUT` | `45` | リモート MCP 呼び出しの秒数 |
| `NOTEBOOK_OCR` | `1` | `0` でスキャン PDF の OCR を無効化 |
| `NOTEBOOK_OCR_MAX_PAGES` | `40` | 1 ファイルあたり OCR するページ数の上限 |

## 対話ハーネスとスキル

画面は Markdown エディタと同じく、上部タブです。

- **ノート一覧** — 作成・開く・削除
- **参考資料** — ファイル／ナレッジの取り込み。「参考資料を追加」内のボタンから、このノートで使う MCP の On/Off
- **対話** — バブル。調べた手順は回答の上に出す
- **項目** — シートの正本。記入済み xlsx のダウンロード

使い方はタブ上のボタンからモーダルで開きます。
AIタイプと MCP の接続管理もタブではなくモーダルです（作業の本体ではないため）。

参考資料へのナレッジ追加は、選んだ文書のコピーをノートに隔離します（項目の根拠）。
共有ナレッジ MCP は共通チームのナレッジを対話のその場で検索するだけで、ノートには入りません。

対話は短い tool loop（最大6ステップ、直近8往復）です。
モデルには OpenAI 互換の `tools` を渡します。ツール非対応のモデル向けに、
`{"tool":"...","arguments":{...}}` の JSON フォールバックもあります。

AIタイプはチャットのシステムプロンプトと同じく、**この対話の手順**です。
選ぶと以降の返信の書き方が変わります。
定義の追加・削除は「AIタイプとMCP」モーダル。対話ではAIタイプを選ぶだけです。
MCP の接続・切り離しと利用時プロンプトも同じモーダルです。ノートごとの On/Off は参考資料タブです。
ユーザーごとに保存し、初回一覧取得で次の例をシードします。最初の4つは議事録の例です。

| 例 | 作る下書き |
| --- | --- |
| 議事録係 | 決定事項・未決事項・TODO |
| 進行管理担当 | 担当・内容・期限・状態 |
| 秘書 | 結論、決定と影響、課題、お願いしたい判断 |
| 参謀 | 持ち越し論点と次回の論点案 |

ノートのコアツールと、接続かつこのノートで有効な MCP ツールを渡します。項目の確定はしません。
AIタイプは書き方を変え、コアツール（参考資料検索・項目確認）だけを絞ります。MCP はノートの有効／無効が優先です。

- `search_sources` — 人がノートへ足した参考資料だけを検索
- `list_items` — 採用済み項目と生成指示
- `knowledge_list_tags` / `knowledge_list_docs` / `knowledge_search` — 共有ナレッジ（参照）。`scope` はサーバ固定
- `get_current_time` / `get_weather` / `wikipedia_search` — サンプル MCP（時刻・天気・Wikipedia）。既定で接続。Wikipedia は百科事典のみで、ウェブ全体は検索しない

共有ナレッジのヒットは出典に「共有ナレッジ・未ソース」と付きます。項目の根拠にするには、人が「参考資料」タブで取り込んでください。
ハーネスはファイルやナレッジを勝手にノートへ入れません。日時・天気・Wikipedia の用語は、使える MCP を先に呼ぶよう促します。

行ごとの「生成」ボタンは従来どおりソースだけの grounded 生成です。
