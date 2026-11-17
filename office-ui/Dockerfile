# ibisOffice ブラウザー版（AGPL-3.0-only）。配布物はこのリポジトリに置かない。
# タグのソースを SHA-256 で照合し、開いたファイルを保存できる差分を当ててからビルドする。
# 差分は patches/keep-opened-source.patch。対応するソースはタグ v<版> とその差分。
# https://github.com/ibisjp/ibis-office/blob/v0.8.7/docs/web-embedding-ja.md

FROM node:22-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
      ca-certificates curl build-essential pkg-config python3 unzip patch git \
 && rm -rf /var/lib/apt/lists/*
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/usr/local/cargo \
    PATH=/usr/local/cargo/bin:$PATH \
    CARGO_TERM_COLOR=never
RUN curl -fsSL https://sh.rustup.rs | sh -s -- -y --default-toolchain none --profile minimal \
 && rustup toolchain install nightly-2026-09-17 --profile minimal --target wasm32-unknown-unknown \
 && rustup default nightly-2026-09-17 \
 && cargo install wasm-bindgen-cli --version 0.2.128 --locked

ARG IBIS_OFFICE_VERSION=0.8.7
ARG IBIS_OFFICE_SOURCE_SHA256=bcc4779588b5a3e5ec15cd831a98ef132f908c797d6851f054071397d34cad84
WORKDIR /src
COPY patches/keep-opened-source.patch /tmp/keep-opened-source.patch
RUN curl -fsSL -o source.tar.gz \
      "https://github.com/ibisjp/ibis-office/archive/refs/tags/v${IBIS_OFFICE_VERSION}.tar.gz" \
 && echo "${IBIS_OFFICE_SOURCE_SHA256}  source.tar.gz" | sha256sum -c - \
 && tar -xzf source.tar.gz \
 && cd "ibis-office-${IBIS_OFFICE_VERSION}" \
 && patch -p1 < /tmp/keep-opened-source.patch \
 && git config --global advice.detachedHead false \
 && checkout() { \
      name="$1"; sha="$2"; \
      rm -rf "forks/${name}"; \
      git init "forks/${name}"; \
      git -C "forks/${name}" remote add origin "https://github.com/ibisjp/${name}.git"; \
      git -C "forks/${name}" fetch --depth 1 origin "${sha}"; \
      git -C "forks/${name}" checkout FETCH_HEAD; \
    } \
 && checkout gpui-base ed9d080ab37254553b8d39fb56c95a4a8e54ec88 \
 && checkout gpui-component 941770cce5e71cc78d49205fcfa5c0b34766211b \
 && checkout gpui-pre 43e8a4881add309eadbb7b854e1160818767c168 \
 && checkout gpui-pre-apple 272edfce0b119f92e637d3d273625ac903dd0b0f \
 && checkout gpui-pre-linux 94a307ca7306fb1727b493695ffc632d47d01bc4 \
 && checkout gpui-pre-macos 0046e2477ae50fe2655a236b202f0d360da05e4e \
 && checkout gpui-pre-web 3fa569b684485f703b282debc240f840d6be4aaf \
 && checkout gpui-pre-wgpu c2eeca34ed99bac2033b2f5769ab72f6fdbb184f \
 && checkout gpui-pre-windows c1043b9c799ccfecd6011979a7170677df9ffcdb \
 && npm ci \
 && bash scripts/build-web.sh --release \
 && test -f www/index.html \
 && test -f www/main.js \
 && test -f www/license.md \
 && test -f www/pkg/ibis_office_app_bg.wasm

FROM nginx:1.27-alpine
ARG IBIS_OFFICE_VERSION=0.8.7
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /src/ibis-office-${IBIS_OFFICE_VERSION}/www /usr/share/nginx/html
COPY templates /usr/share/nginx/html/templates
COPY MODIFICATION.txt /usr/share/nginx/html/OPEN-GENAI-MODIFICATION.txt
EXPOSE 8080
