#!/usr/bin/env bash
#
# Open GENAI レイヤのリグレッションテスト。
#
# 実行内容:
#   1. Python ユニットテスト (pytest)
#   2. genai-web Open GENAI 向け Vitest（http 許可パッチ等）
#
# 使い方:
#   scripts/run-regression-tests.sh              # 両方実行（既定）
#   scripts/run-regression-tests.sh --python-only
#   scripts/run-regression-tests.sh --web-only
#   scripts/run-regression-tests.sh --web-all    # 上流 genai-web 全 Vitest
#
# 終了コード: 0 = 成功, 1 = テスト失敗, 2 = 実行エラー
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

RUN_PYTHON=1
RUN_WEB=1
WEB_ALL=0
VENV_DIR="${ROOT_DIR}/.venv-regression-tests"
WEB_TEST_TARGETS=(
  tests/features/team-apps/utils/endpointUrl.test.ts
  tests/hooks/useSyncUsecaseChatUrl.test.ts
  tests/utils/imageResultExtraData.test.ts
  tests/utils/ensureImagePersistTarget.test.ts
)

while [ $# -gt 0 ]; do
  case "$1" in
    --python-only) RUN_WEB=0; shift ;;
    --web-only) RUN_PYTHON=0; shift ;;
    --web-all) WEB_ALL=1; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

ensure_python_env() {
  if [ ! -d "$VENV_DIR" ]; then
    echo "pytest 用 venv を作成: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q -r tests/requirements.txt
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
}

run_python_tests() {
  echo "=== Python regression tests (pytest) ==="
  ensure_python_env
  pytest
}

run_web_tests() {
  if [ "$WEB_ALL" -eq 1 ]; then
    echo "=== genai-web regression tests (Vitest: full suite) ==="
  else
    echo "=== genai-web regression tests (Vitest: Open GENAI targets) ==="
    printf '  - %s\n' "${WEB_TEST_TARGETS[@]}"
  fi
  if [ ! -d genai-web/node_modules ]; then
    echo "npm ci を実行します..."
    (cd genai-web && npm ci)
  fi
  if [ "$WEB_ALL" -eq 1 ]; then
    (cd genai-web && npm run web:test)
  else
    (cd genai-web && npm run web:test -- "${WEB_TEST_TARGETS[@]}")
  fi
}

failed=0

if [ "$RUN_PYTHON" -eq 1 ]; then
  run_python_tests || failed=1
fi

if [ "$RUN_WEB" -eq 1 ]; then
  run_web_tests || failed=1
fi

if [ "$failed" -ne 0 ]; then
  echo "リグレッションテストに失敗しました。" >&2
  exit 1
fi

echo "リグレッションテストはすべて成功しました。"
