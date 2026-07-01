#!/usr/bin/env bash
# 閉域検証用の自己署名証明書を生成する（本番は組織のCA発行証明書を配置すること）。
#
# 使い方:
#   ./generate-selfsigned.sh genai.example.lg.jp
#
# 生成物（このディレクトリ）:
#   fullchain.pem  … 証明書（nginx の ssl_certificate）
#   privkey.pem    … 秘密鍵（nginx の ssl_certificate_key）
set -euo pipefail

CN="${1:-localhost}"
DIR="$(cd "$(dirname "$0")" && pwd)"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "${DIR}/privkey.pem" \
  -out "${DIR}/fullchain.pem" \
  -days 825 \
  -subj "/CN=${CN}" \
  -addext "subjectAltName=DNS:${CN}"

chmod 600 "${DIR}/privkey.pem"
echo "生成しました: ${DIR}/fullchain.pem, ${DIR}/privkey.pem (CN=${CN})"
echo "※ 自己署名のため、ブラウザ/クライアントに CA として信頼させる必要があります。"
