#!/usr/bin/env bash
#
# 構造化 RAG（ツリー索引）の E2E 確認。
# 前提: docker compose 起動済み、ホスト Ollama に埋め込み/生成モデルがあること。
#
# 使い方:
#   scripts/e2e-tree-rag.sh
#   SKIP_LLM_ANSWER=1 scripts/e2e-tree-rag.sh   # retrieve まで（回答生成スキップ）
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

API_KEY="${RAG_API_KEY:-local-rag-key}"
SCOPE="${E2E_SCOPE:-00000000-0000-0000-0000-000000000000}"
USER_ID="${E2E_USER_ID:-e2e-user}"
GROUPS="${E2E_GROUPS:-SystemAdminGroup}"
SKIP_LLM_ANSWER="${SKIP_LLM_ANSWER:-0}"
RAG_CTR="${RAG_CTR:-open-genai-rag-app}"

PASS=0
FAIL=0

ok() { echo "  OK  $*"; PASS=$((PASS + 1)); }
ng() { echo "  NG  $*"; FAIL=$((FAIL + 1)); }

echo "=== E2E: structured (tree) RAG ==="
echo "container=$RAG_CTR scope=$SCOPE"

# ヘルス待ち
for i in $(seq 1 60); do
  if docker exec "$RAG_CTR" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/health')" >/dev/null 2>&1; then
    break
  fi
  sleep 1
  if [ "$i" -eq 60 ]; then
    echo "rag-app が起動しませんでした"
    exit 1
  fi
done
ok "rag-app /health"

# サンプル文書（Markdown 見出し付き・30k 超を意識した長文ではなく構造確認用）
DOC_B64="$(python3 - <<'PY'
import base64
text = """# 情報セキュリティ規程

## 第1条 目的
本規程は本市における情報資産の適切な管理を目的とする。

## 第2条 定義
本規程において「情報資産」とは、電子データおよび書類をいう。

## 第3条 管理者
情報セキュリティ管理者は、各課の課長とする。

# 附則
本規程は令和8年4月1日から施行する。
"""
print(base64.b64encode(text.encode()).decode())
PY
)"

# 構造化取込（API キーのみ）
INGEST_JSON="$(docker exec -i "$RAG_CTR" python - <<PY
import json, urllib.request
body = {
  "scope": "$SCOPE",
  "tags": ["e2e", "規程"],
  "also_vector": True,
  "files": [{
    "filename": "e2e-security-policy.md",
    "media_type": "text/markdown",
    "content": "$DOC_B64",
  }],
}
# 検索対象にするには tags を付与する（未付与でも登録自体は可）
req = urllib.request.Request(
  "http://127.0.0.1:8001/ingest_tree",
  data=json.dumps(body).encode(),
  headers={"Content-Type": "application/json", "x-api-key": "$API_KEY"},
  method="POST",
)
with urllib.request.urlopen(req, timeout=600) as res:
  print(res.read().decode())
PY
)"

echo "$INGEST_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); assert d.get('documents'), d; print(json.dumps(d['documents'][0], ensure_ascii=False, indent=2))"
DOC_ID="$(echo "$INGEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['documents'][0]['doc_id'])")"
NODE_COUNT="$(echo "$INGEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['documents'][0]['node_count'])")"
TRUNCATED="$(echo "$INGEST_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin)['documents'][0]['truncated'])")"

if [ "$TRUNCATED" = "False" ] || [ "$TRUNCATED" = "false" ]; then
  ok "ingest_tree truncated=false doc_id=$DOC_ID nodes=$NODE_COUNT"
else
  ng "ingest_tree truncated=$TRUNCATED"
fi
if [ "${NODE_COUNT:-0}" -ge 3 ]; then
  ok "tree has enough nodes ($NODE_COUNT)"
else
  ng "tree node_count too small: $NODE_COUNT"
fi

# 署名付き TOC / retrieve
run_signed() {
  local method="$1" path="$2" body="${3:-}"
  docker exec -i "$RAG_CTR" python - <<PY
import json, os, urllib.request
from app import intauth
scope = "$SCOPE"
user_id = "$USER_ID"
groups = "$GROUPS"
ts, sig = intauth.sign(user_id, groups, scope, "")
headers = {
  "Content-Type": "application/json",
  "x-api-key": "$API_KEY",
  "x-user-id": user_id,
  "x-user-groups": groups,
  "x-scope": scope,
  "x-user-ts": ts,
  "x-user-sig": sig,
  "x-user-tags": "",
}
data = None
method = "$method"
body = '''$body'''
if body.strip():
  data = body.encode()
req = urllib.request.Request(
  "http://127.0.0.1:8001$path",
  data=data,
  headers=headers,
  method=method,
)
with urllib.request.urlopen(req, timeout=600) as res:
  print(res.read().decode())
PY
}

TOC_JSON="$(run_signed GET "/knowledge/docs/${DOC_ID}/toc")"
TOC_TITLES="$(echo "$TOC_JSON" | python3 -c "import sys,json; print('|'.join(n['title'] for n in json.load(sys.stdin)['nodes']))")"
echo "  TOC: $TOC_TITLES"
if echo "$TOC_TITLES" | grep -q "第1条"; then
  ok "TOC contains 第1条"
else
  ng "TOC missing 第1条: $TOC_TITLES"
fi

LIST_JSON="$(run_signed GET "/knowledge/docs")"
LIST_HIT="$(echo "$LIST_JSON" | python3 -c "import sys,json; ids=[d['doc_id'] for d in json.load(sys.stdin)['documents']]; print('$DOC_ID' in ids)")"
if [ "$LIST_HIT" = "True" ]; then
  ok "list_docs includes ingested doc"
else
  ng "list_docs missing doc"
fi

RETRIEVE_BODY="$(python3 - <<PY
import json
print(json.dumps({
  "question": "情報セキュリティ管理者は誰ですか",
  "mode": "tree",
  "top_k": 3,
  "doc_id": "$DOC_ID",
}, ensure_ascii=False))
PY
)"
TREE_JSON="$(run_signed POST "/retrieve" "$RETRIEVE_BODY")"
TREE_TEXT="$(echo "$TREE_JSON" | python3 -c "import sys,json; ns=json.load(sys.stdin).get('nodes') or []; print('\\n'.join(n.get('text','') for n in ns))")"
echo "$TREE_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print('  tree nodes:', len(d.get('nodes') or []), 'mode sample:', (d.get('nodes') or [{}])[0].get('mode'))"
if echo "$TREE_TEXT" | grep -q "課長"; then
  ok "tree retrieve returned 第3条 context (課長)"
else
  ng "tree retrieve missed expected section text"
  echo "$TREE_TEXT" | head -c 500
  echo
fi

HYBRID_BODY="$(python3 - <<PY
import json
print(json.dumps({
  "question": "情報資産の定義は何ですか",
  "mode": "hybrid",
  "top_k": 3,
}, ensure_ascii=False))
PY
)"
HYBRID_JSON="$(run_signed POST "/retrieve" "$HYBRID_BODY")"
HYBRID_N="$(echo "$HYBRID_JSON" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('nodes') or []))")"
if [ "$HYBRID_N" -ge 1 ]; then
  ok "hybrid retrieve returned $HYBRID_N node(s)"
else
  ng "hybrid retrieve empty"
fi

if [ "$SKIP_LLM_ANSWER" != "1" ]; then
  ANSWER_JSON="$(docker exec -i "$RAG_CTR" python - <<PY
import json, urllib.request
from app import intauth
scope = "$SCOPE"
user_id = "$USER_ID"
groups = "$GROUPS"
ts, sig = intauth.sign(user_id, groups, scope, "")
body = {
  "inputs": {
    "action": "ask",
    "question": "情報セキュリティ管理者は誰ですか。規程の根拠を示してください。",
    "retrieval_mode": "tree",
    "top_k": 3,
    "doc_id": "$DOC_ID",
  }
}
req = urllib.request.Request(
  "http://127.0.0.1:8001/invoke",
  data=json.dumps(body).encode(),
  headers={
    "Content-Type": "application/json",
    "x-api-key": "$API_KEY",
    "x-user-id": user_id,
    "x-user-groups": groups,
    "x-scope": scope,
    "x-user-ts": ts,
    "x-user-sig": sig,
    "x-user-tags": "",
    "x-app-config": json.dumps({"rag_role": "search"}),
  },
  method="POST",
)
with urllib.request.urlopen(req, timeout=600) as res:
  print(res.read().decode())
PY
)"
  ANSWER="$(echo "$ANSWER_JSON" | python3 -c "import sys,json; print(json.load(sys.stdin).get('outputs','')[:800])")"
  echo "  answer preview:"
  echo "$ANSWER" | sed 's/^/    /'
  if echo "$ANSWER" | grep -Eq "課長|管理者"; then
    ok "invoke tree mode answered with manager role"
  else
    ng "invoke tree mode answer looks wrong"
  fi
else
  echo "  (SKIP_LLM_ANSWER=1: /invoke answer skipped)"
fi

# API health via proxy (optional)
if curl -sf "http://localhost/api/health" >/dev/null 2>&1; then
  ok "proxy /api/health reachable"
else
  echo "  --  proxy /api/health not reachable (ignored)"
fi

echo
echo "=== result: PASS=$PASS FAIL=$FAIL ==="
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
exit 0
