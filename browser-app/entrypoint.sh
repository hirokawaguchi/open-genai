#!/bin/sh
# Chromium の管理ポリシーを置いてから、非 root で API を起動する。
set -eu
for dir in /etc/chromium/policies/managed /etc/chromium-browser/policies/managed; do
  mkdir -p "$dir"
  cp /opt/open-genai/browser-policy.json "$dir/open-genai.json"
  chmod 644 "$dir/open-genai.json"
done
cd /app
exec su --preserve-environment -s /bin/sh browser -c \
  'exec uvicorn app.main:app --host 0.0.0.0 --port 8024'
