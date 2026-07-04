#!/usr/bin/env bash
#
# リリース前チェック（依存脆弱性スキャン + リグレッションテスト）。
#
# 使い方:
#   scripts/pre-release-check.sh
#   scripts/pre-release-check.sh --python-only   # pytest のみ
#   scripts/pre-release-check.sh --web-only      # Vitest のみ
#
# 終了コード: 0 = 成功, 1 = いずれかのチェック失敗, 2 = 実行エラー
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== 1/2 Python dependency audit ==="
bash "$SCRIPT_DIR/audit-python-deps.sh"

echo
echo "=== 2/2 Regression tests ==="
bash "$SCRIPT_DIR/run-regression-tests.sh" "$@"

echo
echo "リリース前チェックはすべて成功しました。"
