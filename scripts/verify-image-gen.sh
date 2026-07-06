#!/usr/bin/env bash
# 画像生成パイプラインの動作検証（mock SD または実 SD サーバ前提）
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SD_URL="${SD_API_URL:-http://localhost:7860}"
FAIL=0

pass() { echo "  OK  $*"; }
fail() { echo "  NG  $*"; FAIL=1; }

echo "=== 1. SD サーバ (${SD_URL}) ==="
if curl -sf "${SD_URL}/sdapi/v1/sd-models" >/dev/null; then
  pass "sd-models"
else
  fail "sd-models に到達できません。mock: python3 scripts/mock-sd-server.py"
fi

echo
echo "=== 2. sd-app (Docker) ==="
SD_HEALTH=$(docker exec open-genai-sd-app python -c "
import urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8003/health', timeout=5) as r:
        print(r.status, r.read().decode())
except Exception as e:
    print('ERR', e)
" 2>&1 || echo "ERR container")
if echo "$SD_HEALTH" | grep -q '"status"[[:space:]]*:[[:space:]]*"ok"'; then
  pass "sd-app /health -> $SD_HEALTH"
else
  fail "sd-app /health -> $SD_HEALTH"
fi

echo
echo "=== 3. backend /image/generate (Docker 内) ==="
IMG_RESULT=$(docker exec open-genai-backend python -c "
import asyncio, os, sys
sys.path.insert(0, '/app')
from app.image_gen import generate_image_base64

async def main():
    b64 = await generate_image_base64({
        'textPrompt': [{'text': 'a red square test', 'weight': 1}],
        'width': 64,
        'height': 64,
        'step': 1,
        'cfgScale': 7,
        'seed': 42,
    })
    print('LEN', len(b64))

asyncio.run(main())
" 2>&1 || echo "ERR backend")
if echo "$IMG_RESULT" | grep -q 'LEN'; then
  pass "generate_image_base64 -> $(echo "$IMG_RESULT" | tail -1)"
else
  fail "generate_image_base64 -> $IMG_RESULT"
fi

echo
echo "=== 4. sd-app /invoke (AI アプリ経由) ==="
INVOKE=$(docker exec open-genai-sd-app python -c "
import json, urllib.request
req = urllib.request.Request(
    'http://127.0.0.1:8003/invoke',
    data=json.dumps({'inputs': {'prompt': 'test cat', 'steps': 1, 'size': 64}}).encode(),
    headers={'Content-Type': 'application/json', 'x-api-key': 'local-rag-key'},
    method='POST',
)
with urllib.request.urlopen(req, timeout=30) as r:
    body = json.loads(r.read().decode())
    arts = body.get('artifacts') or []
    print('ARTIFACTS', len(arts))
" 2>&1 || echo "ERR invoke")
if echo "$INVOKE" | grep -q 'ARTIFACTS 1'; then
  pass "sd-app /invoke -> $INVOKE"
else
  fail "sd-app /invoke -> $INVOKE"
fi

echo
if [ "$FAIL" -eq 0 ]; then
  echo "すべての検証に成功しました。"
  echo "源内 Web: http://localhost/ → AIアプリ → 画像を生成"
else
  echo "一部の検証に失敗しました。"
  exit 1
fi
