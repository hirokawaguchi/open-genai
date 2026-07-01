#!/usr/bin/env bash
#
# 契約終了時のデータ完全削除＋削除報告書の生成（本サービス仕様書 8-(7) 対応）。
#
# 委託者の情報・アップロードファイル・チャット履歴・監査ログ・RAG(Qdrant)・
# フォルダ権限・Keycloak ユーザ・Dify セッション等は、すべて Docker の名前付き
# ボリュームに保存される。本スクリプトはそれらを **物理削除** し、実施内容の
# 報告書（委託者提出用）を生成する。
#
# 使い方:
#   scripts/purge-and-report.sh [--prod] [--yes] [--report <path>]
#     --prod            docker-compose.prod.yml を対象にする（既定は docker-compose.yml）
#     --yes             確認プロンプトを省略（非対話実行）
#     --report <path>   報告書の出力先（既定 ./deletion-report-<日時>.txt）
#
# 注意: この操作は取り消せません。実行前にバックアップの要否を確認してください。
set -euo pipefail

COMPOSE_FILE="docker-compose.yml"
ASSUME_YES=0
REPORT=""

while [ $# -gt 0 ]; do
  case "$1" in
    --prod) COMPOSE_FILE="docker-compose.prod.yml"; shift ;;
    --yes) ASSUME_YES=1; shift ;;
    --report) REPORT="${2:-}"; shift 2 ;;
    -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不明な引数: $1" >&2; exit 2 ;;
  esac
done

# リポジトリルートへ移動（このスクリプトの1つ上）
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -f "$COMPOSE_FILE" ]; then
  echo "compose ファイルが見つかりません: $COMPOSE_FILE" >&2
  exit 1
fi

TS="$(date +%Y%m%d-%H%M%S)"
REPORT="${REPORT:-${ROOT_DIR}/deletion-report-${TS}.txt}"

COMPOSE=(docker compose -f "$COMPOSE_FILE")

# プロジェクト名（ボリューム接頭辞）。未設定なら compose の既定（ディレクトリ名）。
PROJECT="$(${COMPOSE[@]} config --format json 2>/dev/null \
  | sed -n 's/.*"name": *"\([^"]*\)".*/\1/p' | head -n1 || true)"
if [ -z "${PROJECT}" ]; then
  PROJECT="$(basename "$ROOT_DIR" | tr '[:upper:]' '[:lower:]' | tr -cd 'a-z0-9_-')"
fi

# 対象ボリューム（compose 定義名）
VOLUMES="$(${COMPOSE[@]} config --volumes 2>/dev/null || true)"

echo "==============================================================="
echo " 契約終了データ削除（完全削除）"
echo "  compose : $COMPOSE_FILE"
echo "  project : $PROJECT"
echo "  報告書  : $REPORT"
echo "  対象ボリューム:"
echo "$VOLUMES" | sed 's/^/    - /'
echo "==============================================================="
echo " この操作は取り消せません（全データが物理削除されます）。"

if [ "$ASSUME_YES" -ne 1 ]; then
  printf 'すべてのデータを完全に削除します。よろしいですか？ [yes/NO]: '
  read -r ans
  if [ "$ans" != "yes" ]; then
    echo "中止しました。"
    exit 0
  fi
fi

# ---- 削除前インベントリ（ベストエフォート）----
{
  echo "# データ削除報告書（Open GENAI）"
  echo
  echo "- 実施日時: $(date '+%Y-%m-%d %H:%M:%S %z')"
  echo "- 実施ホスト: $(hostname)"
  echo "- 実施ユーザ: ${USER:-unknown}"
  echo "- 対象 compose: $COMPOSE_FILE"
  echo "- プロジェクト名: $PROJECT"
  echo
  echo "## 削除前インベントリ（ベストエフォート）"
  echo
  echo "### 対象ボリューム（定義）"
  echo "$VOLUMES" | sed 's/^/- /'
  echo
  echo "### 実在ボリュームと使用量"
  docker system df -v 2>/dev/null \
    | awk -v p="^${PROJECT}_" '/VOLUME NAME/{f=1} f && ($1 ~ p){print "- " $1 "  " $NF}' \
    || echo "- （取得できませんでした）"
} > "$REPORT"

# ---- 削除実行（コンテナ停止＋ボリューム削除）----
echo
echo ">> コンテナ停止・ボリューム削除を実行します..."
"${COMPOSE[@]}" down -v --remove-orphans

# ---- 検証（プロジェクトのボリュームが残っていないか）----
REMAINING="$(docker volume ls --format '{{.Name}}' 2>/dev/null | grep -E "^${PROJECT}_" || true)"

{
  echo
  echo "## 削除実行"
  echo
  echo "- コマンド: docker compose -f $COMPOSE_FILE down -v --remove-orphans"
  echo
  echo "## 検証結果"
  echo
  if [ -z "$REMAINING" ]; then
    echo "- プロジェクト（${PROJECT}_*）のボリューム残存: **なし**（完全削除を確認）"
  else
    echo "- 残存ボリュームあり（要確認）:"
    echo "$REMAINING" | sed 's/^/  - /'
  fi
  echo
  echo "## 補足"
  echo
  echo "- 本削除により、チャット履歴・アップロードファイル・監査ログ・RAG(Qdrant)・"
  echo "  フォルダ権限・Keycloak ユーザ・Dify セッション等の委託者データを物理削除しました。"
  echo "- ホスト上の TLS 証明書(proxy/certs/*.pem)や .env 等の設定ファイルは本スクリプトの"
  echo "  対象外です。必要に応じて別途削除してください。"
} >> "$REPORT"

echo
echo ">> 完了しました。報告書: $REPORT"
if [ -n "$REMAINING" ]; then
  echo "!! 残存ボリュームがあります。報告書を確認してください。" >&2
  exit 1
fi
