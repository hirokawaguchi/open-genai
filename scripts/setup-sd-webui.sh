#!/usr/bin/env bash
# AUTOMATIC1111 stable-diffusion-webui をホストにセットアップ（macOS Apple Silicon 向け）
set -euo pipefail

INSTALL_DIR="${SD_WEBUI_DIR:-$HOME/stable-diffusion-webui}"
REPO="https://github.com/AUTOMATIC1111/stable-diffusion-webui.git"

if [ -d "$INSTALL_DIR/.git" ]; then
  echo "既存: $INSTALL_DIR"
else
  echo "clone -> $INSTALL_DIR"
  git clone "$REPO" "$INSTALL_DIR"
fi

cat <<EOF

セットアップ完了。初回起動はモデル取得のため 15〜30 分以上かかることがあります。

起動コマンド（Stability-AI 公式 repo 削除対策のミラー URL 付き）:
  cd "$INSTALL_DIR"
  export PYTORCH_ENABLE_MPS_FALLBACK=1
  export STABLE_DIFFUSION_REPO="https://github.com/w-e-w/stablediffusion.git"
  export STABLE_DIFFUSION_XL_REPO="https://github.com/w-e-w/generative-models.git"
  ./webui.sh --api --listen --port 7860 --skip-torch-cuda-test

CLIP インストール失敗時（pip 26 等）:
  ./venv/bin/pip install 'pip<26' 'setuptools<81' wheel
  ./venv/bin/pip install --no-build-isolation \\
    'https://github.com/openai/CLIP/archive/d50d76daa670286dd6cacf3bcd80b5e4823fc8e1.zip'

起動後、別ターミナルで検証:
  cd $(cd "$(dirname "$0")/.." && pwd)
  bash scripts/verify-image-gen.sh

EOF
