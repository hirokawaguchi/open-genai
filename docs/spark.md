# DGX Spark での構築メモ

NVIDIA DGX Spark（aarch64 / GB10 / CUDA 13）向けの現場メモです。
**画像生成と文字起こしの実装は環境ごとに異なる**ため、本家の既定 compose には載せません。
本家が持つのは接続口だけです。

| 機能 | 本家の接続口 | Spark 側の実装（このメモ） |
| --- | --- | --- |
| 文字起こし | `whisper-app` の `/invoke` `/health`。差替は `WHISPER_APP_URL` | CUDA 付き faster-whisper（CTranslate2 aarch64） |
| 画像生成 | `SD_BACKEND=a1111` + `SD_API_URL` | A1111 互換の最小 SD サーバ（SD-Turbo） |

サイト名称・公開 URL・管理コンソール許可 CIDR も `.env` と gitignore した overlay に置きます。コードへ自治体名やホスト IP を直書きしないこと。

## 起動

閉域 HTTP 検証（`docker-compose.verify.yml`）に、サイト用 overlay を足します。

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.verify.yml \
  -f docker-compose.spark.yml --env-file .env up -d
```

`docker-compose.spark.yml` は **gitignore**（`/docker-compose.spark.yml`）。
次の `up` で overlay を忘れると、Whisper が本家既定の CPU イメージで作り直されます。

TLS 本番にするときは `verify` を外し、`proxy/certs/` を置いて `docker-compose.prod.yml` + overlay にします。

## `.env` で足す値

本家の `.env.example` をコピーしたうえで、Spark では少なくとも次を上書きします。
値の例は構築時のものです。モデル名や公開 URL はサイトに合わせて変えてください。

```bash
# 画面名称（静的ビルドの web に埋め込まれる。変更後は web 再ビルド）
VITE_APP_TITLE=Open GENAI
# ゲスト HTML（日程調整・書類チェック・フォーム）は未設定なら VITE_APP_TITLE
# APP_TITLE=Open GENAI

# 文字起こし（GPU）
WHISPER_MODEL=large-v3
WHISPER_DEVICE=cuda
WHISPER_COMPUTE=float16

# 画像生成。サーバは overlay の sd-server（コンテナ名）
SD_BACKEND=a1111
SD_API_URL=http://sd-server:7860
SD_MODEL_ID=/models/sd-turbo
```

Qwen3.x / vLLM を使う場合、思考モードで `content` が空のまま待たされることがあります。
チャットは `LLM_PROVIDERS[].extra_body`、RAG / 日程調整は `RAG_EXTRA_BODY` / `CHOSEI_EXTRA_BODY`
（未設定時は本家側で `enable_thinking: false`）。

```json
{"chat_template_kwargs":{"enable_thinking":false}}
```

## 文字起こし（GPU Whisper）

本家の `whisper-app/Dockerfile` は `python:3.12-slim`（CPU）です。Spark では次が必要です。

- ベース: `nvidia/cuda:12.8.0-cudnn-runtime-ubuntu24.04`
- PyPI の aarch64 `ctranslate2` は CPU 専用。CUDA 本体は別バイナリを入れ、Python バインディングだけソースから入れる
- 構築時に使ったバイナリ:
  `https://github.com/assix/ctranslate2-aarch64-cuda13-binaries/releases/download/v4.6.0-cuda13-aarch64/ctranslate2-dgxspark-aarch64-cuda13.tar.gz`
  （CTranslate2 v4.6.0）
- ホストの cuBLAS 13 を実行時マウントする（コンテナイメージに CUDA 13 を全部入れない）
  - ホストパス: `/usr/local/cuda/targets/sbsa-linux/lib`
  - コンテナ: `/opt/cuda13/lib`
- `gpus: all` と NVIDIA Container Toolkit
- サイト用 Dockerfile は gitignore（`/whisper-app/Dockerfile.spark`）

overlay の要点:

```yaml
services:
  whisper-app:
    build:
      context: ./whisper-app
      dockerfile: Dockerfile.spark
    gpus: all
    environment:
      - WHISPER_DEVICE=${WHISPER_DEVICE:-cuda}
      - WHISPER_COMPUTE=${WHISPER_COMPUTE:-float16}
      - LD_LIBRARY_PATH=/opt/ctranslate2/lib:/opt/cuda13/lib:/usr/local/cuda/lib64
    volumes:
      - whisper_cache:/cache
      - /usr/local/cuda/targets/sbsa-linux/lib:/opt/cuda13/lib:ro
```

`WHISPER_APP_URL` は未設定なら `http://whisper-app:8002/invoke` のまま使えます。
別エンジンにするときだけ差し替え（`/invoke` と `/health` があれば可）。

## 画像生成（A1111 互換サーバ）

本家 backend は AUTOMATIC1111 互換 API（`/sdapi/v1/txt2img`）へプロキシします。
Spark では GB10 向け PyTorch イメージを流用した最小サーバを立てました。

- ベースイメージ例: 手元の `storage-manager/llm-router:2.0.1`（torch 2.12 + cu130）。
  公開レジストリの汎用イメージではない。**その環境で動く torch を流用する**
- 追加 pip: `diffusers` / `accelerate` / `pillow`（torch は再取得しない）
- 既定モデル: **SD-Turbo**（数ステップ、guidance 0）。UI 既定の 50/7 はサーバ側で丸める
- 重みはホストの `./sd-models/sd-turbo` を読み取り専用マウント（gitignore。約数 GB）
- サイト用コードは gitignore（`/sd-server/`）
- backend からの接続: `SD_API_URL=http://sd-server:7860`

overlay の要点:

```yaml
services:
  sd-server:
    build: ./sd-server
    container_name: open-genai-sd-server
    gpus: all
    environment:
      - HF_HOME=/models
      - SD_MODEL_ID=${SD_MODEL_ID:-/models/sd-turbo}
    volumes:
      - sd_models:/models
      - ./sd-models/sd-turbo:/models/sd-turbo:ro
```

AUTOMATIC1111 本体や FastSD に差し替える場合は、`SD_API_URL`（と必要なら `SD_BACKEND`）だけ変え、
この `sd-server` は起動しなくてよい。

## リポジトリに載せないもの

| 対象 | 置き場 |
| --- | --- |
| `.env` / 証明書 / DB | 既存の gitignore |
| `docker-compose.spark.yml` | サイト overlay |
| `whisper-app/Dockerfile.spark` | サイト用イメージ |
| `sd-server/` | サイト用 SD 実装 |
| `sd-models/` | 学習済み重み |
| `proxy/kc-admin-allow.d/10-local.conf` | 管理コンソール許可 CIDR |
| Tailscale 等の作業スクリプト | サイト用 |

Keycloak 管理コンソール（`/kc/admin`）は本家既定で deny-all です。
庁内網からだけ通すときは `10-local.conf` に `allow 10.0.0.0/8;` 等を書き、proxy を reload します。
`/kc/resources/` はログイン用 rate limit の対象外（管理画面の JS が 503 になるため）。

## 確認の目安

- `whisper-app` の `/health` が `"device":"cuda"`
- `/image` から生成でき、`sd-server` のログに txt2img が残る
- overlay 無しの `docker compose -f docker-compose.prod.yml config` に `sd-server` が出ない
- 画面タイトルは `.env` の `VITE_APP_TITLE` だけで変わる（コードにサイト名が無い）
