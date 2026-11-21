# Web 検索（Firecrawl Local）

チャットのスイッチと、ノートブックの MCP から、ウェブ全体を検索・取得します。
検索は [Firecrawl Local](https://github.com/firecrawl/firecrawl) のサイドカーを経由します。

```
[チャット] ──POST /web-search──▶ backend ──HTTP──▶ firecrawl-local (:3002) ──▶ Firecrawl Cloud（検索）
[ノート]   ──MCP firecrawl_*──▶ notebook-app ──HTTP──▶ firecrawl-local (:3002)
```

> **重要（出口）:** scrape（ページ本文の取得）は firecrawl-local の手元で動きますが、
> **search（検索）はクエリが Firecrawl Cloud に出ます**（キーレスの無料枠、または `FIRECRAWL_API_KEY`）。
> インターネットに出られない閉域（LGWAN 等）では、この機能を **使わない**でください。

## 出し分け

`FIRECRAWL_URL` が空なら機能ごと無効です。

| 状態 | チャットのスイッチ | ノートブックの Web 検索 MCP |
| --- | --- | --- |
| `FIRECRAWL_URL` 未設定（既定） | 出ない | 非接続（セッションで On にできない） |
| `FIRECRAWL_URL` 設定あり | 出る（既定オフ） | 接続可 |

- 閉域では `FIRECRAWL_URL` を空のままにし、サイドカーも起動しないでください。
- インターネット接続環境でだけ、`websearch` プロファイルと `FIRECRAWL_URL` を設定します。

## 起動

インターネット接続環境でのみ起動します。ホストにはポートを公開しません（compose 内から到達）。

```bash
# .env
FIRECRAWL_URL=http://firecrawl-local:3002
# 任意: アカウントの鍵を使う場合（公開リポジトリには置かず overlay に置く）
# FIRECRAWL_API_KEY=fc-...

docker compose --profile websearch up -d --build firecrawl-local
```

`firecrawl-local` の起動後、`backend` と `notebook-app` は内部 DNS `http://firecrawl-local:3002` で到達します。

## チャット

- 入力欄の「Web検索」スイッチをオンにして送信すると、送信前に発話をクエリに検索します。
- 検索で得た抜粋（タイトル・URL・本文）だけをモデルの入力に足します（画面の発言本文には混ぜません）。
- モデルには、抜粋と URL だけを根拠にし、回答の末尾に出典（タイトルと URL）を書くよう指示します。
- 外部へ出す前に、入力制限（禁止ワード／機密情報）の判定と個人情報のマスクを通します。クエリは監査ログに残ります。
- 再送（リトライ）でも、スイッチがオンなら直前の発話で検索し直します。

| エンドポイント | 役割 |
| --- | --- |
| `GET /web-search/config` | スイッチを出すか（`{ "enabled": true }`） |
| `POST /web-search` | `{ "query": "..." }` を検索し、`{ "passages": [{title, url, text}] }` を返す |

## ノートブック MCP

カタログに「Web検索」（`catalog_id: firecrawl`）を足しています。`FIRECRAWL_URL` が空なら非接続です。

| ツール | 役割 |
| --- | --- |
| `firecrawl_search` | ウェブ全体を検索する（`query`、任意 `limit`。既定5・最大8） |
| `firecrawl_scrape` | 指定した URL の本文を Markdown で取得する（`url`） |

ウェブの最新情報や公式サイトが要るときに `firecrawl_search`、検索結果だけで足りなければ
その URL を `firecrawl_scrape` に渡して読みます。日本語 Wikipedia 検索（`wikipedia_search`）は
百科事典用として別に残しています。得た情報は参照です。項目の根拠にするには、
参考資料タブから資料を追加してください。
