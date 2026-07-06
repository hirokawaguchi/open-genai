#!/usr/bin/env bash
# 画像生成パイプラインの動作検証（mock SD または実 SD サーバ前提）
set -euo pipefail

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
echo "=== 2. backend /image/generate (Docker 内) ==="
IMG_RESULT=$(docker exec open-genai-backend python -c "
import asyncio, sys
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
if [ "$FAIL" -eq 0 ]; then
  echo "すべての検証に成功しました。"
  echo "源内 Web: http://localhost/image"
else
  echo "一部の検証に失敗しました。"
  exit 1
fi
