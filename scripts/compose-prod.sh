#!/usr/bin/env bash
# 本番 compose の入口。ホストシェルの PUBLIC_URL / S3_PUBLIC_ENDPOINT /
# VITE_APP_MODEL_IDS などが --env-file .env.prod より優先されるのを防ぐ。
#
#   ./scripts/compose-prod.sh
#   ./scripts/compose-prod.sh up -d --no-deps --force-recreate backend
#   ./scripts/compose-prod.sh build web
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE=docker-compose.prod.yml
ENV_FILE=.env.prod

unset \
  PUBLIC_URL \
  PUBLIC_BASE_URL \
  FRONTEND_URL \
  SAML_SP_ENTITY_ID \
  SAML_SP_ACS_URL \
  SAML_SP_SLS_URL \
  S3_PUBLIC_ENDPOINT \
  KC_HOSTNAME \
  OPERATOR_LOGIN_HOSTS \
  OPERATOR_USERS \
  CHOSEI_PUBLIC_ENDPOINT \
  VITE_APP_TITLE \
  VITE_APP_NAV_LAYOUT \
  VITE_APP_IMAGE_DEFAULT_STEP \
  VITE_APP_IMAGE_DEFAULT_CFG \
  VITE_APP_MODEL_IDS \
  APP_TITLE \
  PROXY_BIND_IP

if [[ ! -f "${ROOT}/${COMPOSE_FILE}" || ! -f "${ROOT}/${ENV_FILE}" ]]; then
  echo "ERROR: ${ROOT}/${COMPOSE_FILE} または ${ENV_FILE} がありません" >&2
  exit 1
fi

if [[ $# -eq 0 ]]; then
  set -- up -d
fi

echo "[compose-prod] ${ROOT}  ${COMPOSE_FILE} + ${ENV_FILE}  (host env は無視)" >&2
cd "${ROOT}"
exec docker compose \
  -f "${COMPOSE_FILE}" \
  --env-file "${ENV_FILE}" \
  "$@"
