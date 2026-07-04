#!/usr/bin/env bash
#
# Python 依存の既知脆弱性スキャン（pip-audit）。
#
# リリース前チェック:
#   scripts/audit-python-deps.sh
#
# 前提: pip-audit が PATH にあること（未インストール時は venv を自動作成）
#
# 終了コード: 0 = 脆弱性なし, 1 = 脆弱性あり, 2 = 実行エラー
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

INCLUDE_GENAI_AI_API=0
VENV_DIR="${ROOT_DIR}/.venv-pip-audit"

while [ $# -gt 0 ]; do
  case "$1" in
    --include-genai-ai-api) INCLUDE_GENAI_AI_API=1; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

ensure_pip_audit() {
  if command -v pip-audit >/dev/null 2>&1; then
    return
  fi
  if [ ! -d "$VENV_DIR" ]; then
    echo "pip-audit 用 venv を作成: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install -q pip-audit
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
}

find_requirements() {
  if [ "$INCLUDE_GENAI_AI_API" -eq 1 ]; then
    find . -name requirements.txt -not -path './genai-web/*' | sort
  else
    find . -maxdepth 2 -name requirements.txt | sort
  fi
}

ensure_pip_audit

failed=0
total=0

while IFS= read -r req; do
  [ -n "$req" ] || continue
  total=$((total + 1))
  echo "=== $req ==="
  if pip-audit -r "$req"; then
    echo
  else
    failed=1
    echo
  fi
done < <(find_requirements)

echo "スキャン対象: ${total} ファイル"

if [ "$failed" -ne 0 ]; then
  echo "既知の脆弱性が検出されました。requirements.txt を更新して再実行してください。" >&2
  exit 1
fi

echo "既知の脆弱性は検出されませんでした。"
