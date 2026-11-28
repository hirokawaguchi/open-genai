#!/bin/sh
# ノート用 Hermes。共有の作業ディレクトリは作らない。
set -eu

HERMES_HOME="${HERMES_HOME:-/root/.hermes}"
export HERMES_HOME
mkdir -p "$HERMES_HOME/memories" "$HERMES_HOME/user-skills"
if [ -d /opt/hermes/installs ] && [ ! -e "$HERMES_HOME/installs" ]; then
  ln -sfn /opt/hermes/installs "$HERMES_HOME/installs"
fi
if [ -d /opt/hermes/tools ] && [ ! -e "$HERMES_HOME/tools" ]; then
  ln -sfn /opt/hermes/tools "$HERMES_HOME/tools"
fi

MODEL="${HERMES_LLM_MODEL:-glm-5.2:cloud}"
BASE="${HERMES_LLM_BASE:-http://host.docker.internal:11434/v1}"
case "$BASE" in
  */v1) ;;
  *) BASE="${BASE%/}/v1" ;;
esac
KEY="${HERMES_LLM_API_KEY:-ollama}"

cat > "$HERMES_HOME/config.yaml" << EOF
model:
  default: ${MODEL}
  provider: custom
  base_url: ${BASE}
  api_key: ${KEY}
  context_length: 65536
  ollama_num_ctx: 65536
terminal:
  backend: local
display:
  interface: cli
  compact: true
agent:
  # 0 は上限なし。文書は調べて書く手順が多く、途中で止めない。
  max_turns: 0
  disabled_toolsets:
    - terminal
    - file
    - code_execution
    - browser
    - web
    - skills
    - memory
    - delegation
    - computer_use
    - coding
    - cronjob
    - kanban
    - image_gen
    - video
    - video_gen
    - tts
    - connections
    - project
    - search
    - session_search
    - vision
EOF

cat > "$HERMES_HOME/SOUL.md" << 'EOF'
# Hermes

私はノートの中で動くエージェントです。応答は日本語です。
あいさつや雑談、文書を作る頼みが無い発言には、短く返すだけです。文書の話はこちらから始めません。
文書を作ってほしいと分かったときだけ、ノートの道具を使います。シェルやファイルの移動はしません。
利用者は道具の英語名を書きません。回答の本文にも英語の道具名は出しません。
文書の作成は、言い回しを整えてエディタで開くまで、同じ応答で終えます。
EOF

PY="$(python3 - << 'PY'
import json
from pathlib import Path
root = Path("/opt/hermes/installs")
for facts in root.glob("*/facts.json"):
    try:
        data = json.loads(facts.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        continue
    env = (data.get("packages") or {}).get("venv", {}).get("environment")
    if env:
        py = Path(env) / "bin" / "python"
        if py.is_file():
            print(py)
            break
PY
)"
if [ -z "$PY" ]; then
  echo "hermes python not found" >&2
  exit 1
fi
exec "$PY" /opt/notebook-acp/acp_gateway.py
