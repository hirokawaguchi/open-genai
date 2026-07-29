# Dify × OpenGENAI ナレッジ連携（事例）

源内のナレッジを Dify から使うときの **事例中心ガイド**です。  
API 仕様の詳細は [knowledge-api.md](knowledge-api.md)、MCP 詳細は [knowledge-mcp.md](knowledge-mcp.md) を参照してください。

## どの経路を使うか

| 経路 | DSL | 向いていること |
| --- | --- | --- |
| **HTTP 固定 WF（入門・本丸）** | [`OpenGENAI-KnowledgeAgent.yml`](../dify-app/dsl/OpenGENAI-KnowledgeAgent.yml) | 質問＋タグ（任意 source）→ `/retrieve` → 根拠付き回答 |
| **Agent + MCP** | [`OpenGENAI-KnowledgeAgent.chatflow.yml`](../dify-app/dsl/OpenGENAI-KnowledgeAgent.chatflow.yml) | タグ確認・資料名解決を Agent に任せる対話 |
| **応用（業務分析）** | [`OpenGENAI-MinutesStance.yml`](../dify-app/dsl/OpenGENAI-MinutesStance.yml) | 議事録の発言者スタンス表など、固定プロンプトの業務 WF |

```
[源内 UI] → backend → dify-app → Dify
                              ├ HTTP ノード → rag-app /retrieve
                              └ Agent MCP → knowledge-mcp → rag-app
```

出典アコーディオン: 回答の `citation_artifacts`（または Agent のツール結果）を `dify-app` が拾い、源内 UI（`ExAppCitations`）に表示します。本文の `[n]` と対応させます。

---

## 共通準備

1. Open GENAI 側: `docker compose up -d rag-app`（Agent 利用時は `knowledge-mcp` も）
2. セルフホスト Dify の `.env` に SSRF 許可を追加し、`ssrf_proxy` を再起動:

```bash
SSRF_PROXY_ALLOW_PRIVATE_DOMAINS=host.docker.internal
```

3. 入門用サンプルを登録（タグ `規程`）:

```bash
DOC_B64="$(base64 < dify-app/dsl/samples/knowledge-qa-sample.md | tr -d '\n')"
docker compose exec rag-app sh -lc "curl -s -X POST http://localhost:8001/ingest_tree \
  -H 'x-api-key: local-rag-key' -H 'Content-Type: application/json' \
  -d \"{\\\"scope\\\":\\\"00000000-0000-0000-0000-000000000000\\\",\\\"tags\\\":[\\\"規程\\\"],\\\"also_vector\\\":true,\\\"files\\\":[{\\\"filename\\\":\\\"knowledge-qa-sample.md\\\",\\\"media_type\\\":\\\"text/markdown\\\",\\\"content\\\":\\\"$DOC_B64\\\"}]}\""
```

4. 疎通:

```bash
curl -s -X POST http://127.0.0.1:8001/retrieve \
  -H "x-api-key: local-rag-key" -H "Content-Type: application/json" \
  -d '{"question":"タグ未付与は検索対象か","mode":"auto","top_k":4,"scope":"00000000-0000-0000-0000-000000000000","tags":["規程"]}'
```

---

## 事例 1: HTTP 固定 WF（根拠付き Q&A）

**題材:** タグ付きナレッジを `/retrieve` で取り、LLM が `[n]` 付きで答える。任意で `source` を渡すと資料内検索になる。

### 手順

1. Dify Studio →「DSL から作成」→ [`OpenGENAI-KnowledgeAgent.yml`](../dify-app/dsl/OpenGENAI-KnowledgeAgent.yml) をインポート
2. **回答 LLM** ノードのモデルを、利用可能なものへ付け替え
3. 環境変数を確認:
   - `RAG_BASE_URL` = `http://host.docker.internal:8001`
   - `RAG_API_KEY` = Open GENAI の `RAG_API_KEY`
   - `RAG_SCOPE` = 対象チームの teamId（共通チームなら `00000000-0000-0000-0000-000000000000`）
4. 公開してテスト実行

| 入力 | タグ横断の例 | 資料指定の例 |
| --- | --- | --- |
| query | 出典の明示はどう書く？ | 第4章の資料内検索とは？ |
| tags | `規程` | `規程` |
| source | （空） | `knowledge-qa-sample.md` |

期待: 回答本文に `[1]` など。源内経由ならアコーディオンに節タイトル／ページ付き出典。

### 源内への登録（workflow）

```json
{"dify_base_url":"http://host.docker.internal:8088/v1","dify_app_type":"workflow","response_field":"report"}
```

DeepResearch のように `depth` をユーザに触らせず既定のまま使う場合:

```json
{"dify_base_url":"http://host.docker.internal:8088/v1","dify_app_type":"workflow","response_field":"report","hide_inputs":["depth"],"default_inputs":{"depth":"3"}}
```

- endpoint: `http://dify-app:8004/invoke`
- APIキー: Dify のワークフロー用 `app-...`
- データ形式: 空のまま（自動フォーム）でも可。`hide_inputs` の変数は画面に出さず既定値を送る

フロー出力:

- `report` … 回答本文
- `citation_artifacts` … JSON 配列（源内がアコーディオン化）

---

## 事例 2: Agent + MCP（対話）

**題材:** Agent が `knowledge_list_tags` →（必要なら）`list_docs` → `knowledge_search` を選び、指定資料があれば `source` を渡す。

### 手順

1. `docker compose up -d --build knowledge-mcp rag-app`
2. Dify Tools → MCP → `http://host.docker.internal:8002/mcp`  
   - **Server ID: `open_genai_knowledge`**
3. プラグイン `langgenius/agent`（Agent Strategies）が入っていること
4. [`OpenGENAI-KnowledgeAgent.chatflow.yml`](../dify-app/dsl/OpenGENAI-KnowledgeAgent.chatflow.yml) をインポート
5. Agent のモデルを付け替え → 公開
6. 試す質問例:
   - 「利用できるタグは？」
   - 「規程タグで、出典の明示について教えて」
   - 「knowledge-qa-sample.md の第4章だけ見て」

Agent 指示のテキスト版: [`prompts/OpenGENAI-KnowledgeAgent-system.md`](../dify-app/dsl/prompts/OpenGENAI-KnowledgeAgent-system.md)

### 源内への登録（chat）

```json
{"dify_base_url":"http://host.docker.internal:8088/v1","dify_app_type":"chat","query_field":"query"}
```

`dify_base_url` は環境の Dify「APIアクセス」表示に合わせてください。

---

## 事例 3: 応用 — 議事録スタンス分析

入門ではなく **業務特化の固定 WF** です。議題を入力し、発言者ごとのスタンス表を出します。

| ファイル | 内容 |
| --- | --- |
| [`OpenGENAI-MinutesStance.yml`](../dify-app/dsl/OpenGENAI-MinutesStance.yml) | Retrieval → スタンス分析 |
| [`samples/minutes-stance-sample.md`](../dify-app/dsl/samples/minutes-stance-sample.md) | サンプル議事録 |

1. サンプルをタグ `議事録` で標準登録（`ingest_tree`）
2. DSL をインポートし、LLM モデルと `RAG_*` を設定
3. 議題例:「庁内AI利用ガイドライン案の採択」、タグ `議事録`

源内登録は事例 1 と同様（`response_field: report`）。

---

## 手動チェックリスト（リリース前）

- [ ] `GET /knowledge/tags` が API キーのみで応答する
- [ ] `POST /retrieve` タグ横断で nodes が返る
- [ ] `POST /retrieve` に `source` を付けると、構造化なら `resolved_mode=tree`
- [ ] HTTP WF: 回答に `[n]`、源内でアコーディオン表示
- [ ] MCP: Server ID `open_genai_knowledge` で chatflow がツール呼び出しできる
- [ ] 資料指定の会話で Agent が `source` を渡す
- [ ] Dify SSRF 許可（`host.docker.internal`）済み

---

## トラブルシュート（ナレッジ連携）

| 症状 | よくある原因 | 対処 |
| --- | --- | --- |
| retrieve が 0 件 | タグ未付与／タグ名不一致 | ドキュメント管理でタグ確認 |
| Dify HTTP が失敗 | SSRF 拒否 | `SSRF_PROXY_ALLOW_PRIVATE_DOMAINS` |
| Agent がツールを使えない | Agent Strategies 未導入／MCP ID 不一致 | プラグイン導入、Server ID を合わせる |
| 出典アコーディオンが出ない | `citation_artifacts` 未出力／本文に `[n]` なし | End 出力と回答の参照番号を確認 |
| 資料指定しても他文書が混ざる | `source` 未送信 | HTTP 入力または Agent 指示を確認 |

一般的な Dify 登録・成果物再ホストのトラブルは README「Dify 連携」を参照。
