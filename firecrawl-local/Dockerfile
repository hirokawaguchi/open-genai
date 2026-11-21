# Firecrawl Local のサイドカー。compose ネットワーク内で v2 API を :3002 に出す。
# 検索は Firecrawl Cloud にクエリを出す（キーレスの無料枠、または FIRECRAWL_API_KEY）。
# scrape は手元で動き、JS が要るページは同梱の Chromium で描画する。
#
# インターネット接続環境でのみ profile websearch で起動する。閉域では使わない。
FROM rust:1-slim-bookworm AS build

# crates.io からローカル版をビルドする。C コンパイラが要る。
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential pkg-config libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN cargo install firecrawl-local

FROM debian:bookworm-slim

# JS ページの描画に使う Chromium と、ローカル版が使う実行時ライブラリ。
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /usr/local/cargo/bin/firecrawl-local /usr/local/bin/firecrawl-local

# ローカル版が同梱 Chromium を見つけられるようにする。
ENV CHROME_PATH=/usr/bin/chromium \
    FIRECRAWL_CHROME_PATH=/usr/bin/chromium

EXPOSE 3002

# v2 API を 0.0.0.0:3002 に出す。ローカルのルートは API キー不要。
CMD ["firecrawl-local", "serve", "--host", "0.0.0.0", "--port", "3002"]
