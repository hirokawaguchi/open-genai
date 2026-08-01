# ナレッジ Retrieval API（機械向け）

人間向け Q&A は源内の「ナレッジ検索」exApp（`POST /invoke`）です。  
Dify や他サービスから **節／チャンク単位で取り出す**ときは、本 API を使います。

検索の正本は常に `rag-app` です。MCP（`knowledge-mcp`）も内部で同じ API を呼びます。

関連:

- [Dify 連携（事例）](dify-knowledge.md)
- [ナレッジ検索 MCP](knowledge-mcp.md)

## 前提

| 項目 | 内容 |
| --- | --- |
| サービス | `rag-app`（`docker compose up -d rag-app`） |
| ホスト公開 | 開発時 `:8001`（`RAG_APP_PORT` で変更可） |
| Dify からの到達 | `http://host.docker.internal:8001` |
| API キー | `.env` の `RAG_API_KEY`（開発既定 `local-rag-key`） |
| スコープ | チーム ID（`teamId`）。ナレッジはチーム単位で分離 |

**タグ未付与の文書は検索対象外**です。登録時にタグを付けてください。

## 認証

| ヘッダ | 用途 |
| --- | --- |
| `x-api-key` | RAG API キー（必須） |
| `x-scope` | ナレッジスコープ（= `teamId`） |
| `x-user-*` / `x-user-sig` | backend 経由の内部署名（本番） |

- **取込系**（`/ingest`, `/ingest_tree`）: 原則 `x-api-key` のみ
- **`POST /retrieve`** / **`GET /knowledge/tags`** / **`GET /knowledge/docs`**:
  - backend 経由: API キー ＋ 内部署名
  - **Dify / MCP 等の機械クライアント**: API キーのみ（署名ヘッダなし）。`scope` は JSON body・クエリまたは `x-scope`
- **TOC / nodes 等**: API キー ＋ 内部署名（本番）

## エンドポイント一覧

| メソッド | パス | 説明 |
| --- | --- | --- |
| `GET` | `/health` | ヘルスチェック |
| `POST` | `/ingest` | テキスト一括登録（全文＋ベクトル） |
| `POST` | `/ingest_tree` | ファイルの構造化取込（ツリー＋ベクトル） |
| `GET` | `/knowledge/tags` | タグ一覧（クエリ `scope`） |
| `GET` | `/knowledge/docs` | 文書一覧（任意クエリ `tags` / `scope`） |
| `GET` | `/knowledge/docs/{doc_id}/toc` | TOC |
| `POST` | `/knowledge/docs/{doc_id}/nodes` | 指定節の本文（body: `{"node_ids":[...]}`） |
| `POST` | `/retrieve` | 共通 Retrieval |
| `POST` | `/invoke` | 源内 exApp 用 Q&A |
| `POST` | `/knowledge/tags` | タグ作成（専用ページ用） |
| `POST` | `/knowledge/tags/rename` | タグ名変更 |
| `POST` | `/knowledge/tags/delete` | タグ削除（未使用のみ） |
| `POST` | `/knowledge/register` | ファイル登録（`mode=tree\|fulltext`、`files=base64`） |
| `POST` | `/knowledge/urls` | URL 登録 |
| `POST` | `/knowledge/urls/delete` | URL 削除 |
| `POST` | `/knowledge/urls/refresh` | URL 再取得（管理者） |
| `POST` | `/knowledge/docs/delete` | 文書削除（body: `{"source": ...}`） |
| `POST` | `/knowledge/docs/retag` | 文書のタグ付け替え |
| `POST` | `/knowledge/clear` | スコープ内の全消去（管理者） |

## ナレッジ管理 REST（専用ページ用・書込）

専用ページ `/knowledge` はこれらの書込 REST を使います。すべて **backend の認可付きプロキシ
（`/knowledge/*`）経由**で呼ばれ、rag-app 側は **API キー ＋ 内部署名**を要求します（機械クライアントの
署名なし直叩きは書込不可）。スコープ（`x-scope`）は署名対象で、改ざんできません。

認可（backend 側）:

| 操作 | 共有ナレッジ（common） | チームスコープ |
| --- | --- | --- |
| 読取（`GET /knowledge/tags`・`/docs`） | 全認証ユーザー | メンバー or 管理者 |
| 書込（タグ CRUD・登録・削除・retag・URL） | **システム管理者のみ** | メンバー or 管理者 |
| `urls/refresh`・`clear` | システム管理者のみ | **システム管理者のみ** |

- rag-app 側でも `_can_manage(scope, is_admin)`（共有は管理者のみ／チームはメンバー可）で二重にゲートします。
- `POST /knowledge/register` の `files` は `[{ "filename", "content"(base64), "media_type" }]`、`mode` は
  `tree`（構造化）/ `fulltext`（全文）。対応拡張子は `.pdf,.docx,.xlsx,.txt,.md,.csv,.html,.json`。
- 削除・タグ付け替えのキーは **`source`**（ファイル名 or URL）です。
- `GET /knowledge/scopes`（backend）: 操作可能なスコープ一覧（共有 + 所属チーム、`canManage` 付き）を返します。

## `POST /retrieve`

### リクエスト

| フィールド | 必須 | 説明 |
| --- | --- | --- |
| `question` または `query` | ○ | 検索クエリ |
| `mode` | − | `auto`（既定）/ `full` / `vector` / `tree` / `hybrid` |
| `top_k` | − | 参照件数（既定 4） |
| `tags` | − | タグ絞り込み（配列または区切り文字列）。検索では実質必須に近い |
| `scope` | − | スコープ（ヘッダ `x-scope` でも可） |
| `doc_id` / `source` | − | 特定資料に絞る（全 mode で有効） |

### `mode=auto` の選択方針

1. **`doc_id` / `source` 指定時** … 構造化文書なら **tree**（節・ページ）、なければ **vector**（該当チャンク）
2. **full** … タグ付き候補の全文合計がコンテキスト予算内（既定 24000 文字）
3. **hybrid** … 候補がすべて構造化（標準登録）済み
4. **vector** … 非構造化を含む、または全文が予算超え

| mode | 挙動 |
| --- | --- |
| `vector` | Qdrant の類似チャンク検索（`source` 指定時はその文書のみ） |
| `tree` | 目次ツリーを辿り、節本文を返す |
| `hybrid` | ベクトルで文書候補 → 構造化で節特定 |
| `full` | 候補文書の全文を返す |
| `auto` | 上記を候補の状態から自動選択 |

### レスポンス例

```json
{
  "nodes": [
    {
      "id": "...",
      "title": "第3章 出典の明示",
      "text": "...",
      "source": "knowledge-qa-sample.md",
      "doc_id": "...",
      "page_start": 1,
      "page_end": 1,
      "score": null,
      "mode": "tree"
    }
  ],
  "resolved_mode": "tree",
  "trace": []
}
```

## curl 事例

共通の環境変数（ホストから叩く例）:

```bash
export RAG_URL=http://127.0.0.1:8001
export RAG_KEY=local-rag-key
export SCOPE=00000000-0000-0000-0000-000000000000
```

### 1. タグ一覧

```bash
curl -s "$RAG_URL/knowledge/tags?scope=$SCOPE" -H "x-api-key: $RAG_KEY"
```

### 2. 文書一覧（タグで絞る）

```bash
curl -s "$RAG_URL/knowledge/docs?scope=$SCOPE&tags=規程" -H "x-api-key: $RAG_KEY"
```

### 3. タグ横断検索

```bash
curl -s -X POST "$RAG_URL/retrieve" \
  -H "x-api-key: $RAG_KEY" -H "Content-Type: application/json" \
  -d "{\"question\":\"タグ未付与の文書は検索対象か\",\"mode\":\"auto\",\"top_k\":4,\"scope\":\"$SCOPE\",\"tags\":[\"規程\"]}"
```

### 4. 資料指定検索（`source`）

構造化文書なら `resolved_mode` が `tree` になり、節タイトル・ページ付きの node が返ります。

```bash
curl -s -X POST "$RAG_URL/retrieve" \
  -H "x-api-key: $RAG_KEY" -H "Content-Type: application/json" \
  -d "{\"question\":\"出典の明示について\",\"mode\":\"auto\",\"top_k\":4,\"scope\":\"$SCOPE\",\"tags\":[\"規程\"],\"source\":\"knowledge-qa-sample.md\"}"
```

### 5. サンプル文書の登録（入門用）

```bash
DOC_B64="$(base64 < dify-app/dsl/samples/knowledge-qa-sample.md | tr -d '\n')"
docker compose exec rag-app sh -lc "curl -s -X POST http://localhost:8001/ingest_tree \
  -H 'x-api-key: local-rag-key' -H 'Content-Type: application/json' \
  -d \"{\\\"scope\\\":\\\"00000000-0000-0000-0000-000000000000\\\",\\\"tags\\\":[\\\"規程\\\"],\\\"also_vector\\\":true,\\\"files\\\":[{\\\"filename\\\":\\\"knowledge-qa-sample.md\\\",\\\"media_type\\\":\\\"text/markdown\\\",\\\"content\\\":\\\"$DOC_B64\\\"}]}\""
```

## 補足

- 埋め込み: Ollama `mxbai-embed-large`
- ベクトル DB: Qdrant
- 構造化／全文メタ: SQLite（`RAG_META_DB_PATH`）
- E2E スクリプト: `scripts/e2e-tree-rag.sh`
