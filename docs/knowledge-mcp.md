# ナレッジ検索 MCP

Dify Agent（や MCP 対応クライアント）から OpenGENAI ナレッジを探すための薄いラッパです。  
内部では常に [`rag-app` の HTTP API](knowledge-api.md) を呼びます。

```
[Dify Agent] ──MCP──▶ knowledge-mcp (:8002/mcp) ──HTTP──▶ rag-app
[Dify HTTP ノード] ──────────────────────────────HTTP──▶ rag-app
```

Dify での利用手順（事例）は [dify-knowledge.md](dify-knowledge.md) を参照。

## 起動

```bash
docker compose up -d --build knowledge-mcp rag-app
```

| 項目 | 内容 |
| --- | --- |
| URL | `http://host.docker.internal:8002/mcp`（`KNOWLEDGE_MCP_PORT` で変更可） |
| 転送 | Streamable HTTP（Dify 1.6+） |
| 認証 | MCP 自体はキーなし。下流 `rag-app` へ渡す API キーは MCP コンテナ環境変数 |

## ツール

| ツール | 役割 |
| --- | --- |
| `knowledge_list_tags` | チーム（scope）内のタグ一覧。検索前に呼ぶ |
| `knowledge_list_docs` | タグで絞った文書一覧（`source` / `doc_id` 確認用） |
| `knowledge_search` | 検索（**tags 必須**）。任意で `source` / `doc_id` |

### `knowledge_search` の主な引数

| 引数 | 必須 | 説明 |
| --- | --- | --- |
| `query` | ○ | 検索クエリ |
| `tags` | ○ | タグ（例: `規程` または `規程,マニュアル`） |
| `scope` | − | teamId。空なら既定スコープ |
| `top_k` | − | 取得件数（既定 4） |
| `mode` | − | `auto` / `full` / `vector` / `tree` / `hybrid` |
| `source` | − | 対象ファイル名（資料内検索） |
| `doc_id` | − | 対象文書 ID（`list_docs` の値） |

`mode=auto` かつ `source` / `doc_id` 指定時は、構造化文書なら tree、なければ vector（API と同じ）。

### 戻り値

JSON 文字列。主なキー:

- `nodes` … ヒット（`ref`, `title`, `source`, `page_start` / `page_end`, `text`, `mode`）
- `citation_artifacts` … 源内アコーディオン用（`display_name`, `text`, `mime_type`）
- `resolved_mode` … 実際に使われた mode

出典表示名の例:

```text
[1] knowledge-qa-sample.md / 第3章 出典の明示 / p.1
```

## Dify への登録

1. Tools → MCP → URL `http://host.docker.internal:8002/mcp` を追加
2. **Server ID は `open_genai_knowledge`**（同梱 chatflow DSL がこの ID を参照）
3. プラグイン「Dify Agent Strategies」（`langgenius/agent`）が必要

別 ID で登録済みの場合は、Agent ノードの各ツール `provider_name` を合わせるか、MCP を作り直してください。

## 疎通確認（下流 API）

MCP は HTTP ラッパなので、まず `rag-app` が応答することを確認します。

```bash
curl -s "http://127.0.0.1:8001/knowledge/tags?scope=00000000-0000-0000-0000-000000000000" \
  -H "x-api-key: local-rag-key"
```

## SSRF（セルフホスト Dify）

Dify の `.env` に例えば次を追加し、`ssrf_proxy` を再起動:

```bash
SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal
```
