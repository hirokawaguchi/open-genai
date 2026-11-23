FROM python:3.12-bookworm

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        chromium \
        chromium-l10n \
        xvfb \
        x11vnc \
        pulseaudio \
        pulseaudio-utils \
        fonts-noto-cjk \
        fonts-liberation \
        ca-certificates \
        locales \
    && sed -i 's/^# *\(ja_JP.UTF-8 UTF-8\)/\1/' /etc/locale.gen \
    && locale-gen ja_JP.UTF-8 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 --shell /bin/sh browser

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY policies/open-genai.json /opt/open-genai/browser-policy.json
COPY entrypoint.sh /entrypoint.sh
RUN chmod 755 /entrypoint.sh

EXPOSE 8024

ENTRYPOINT ["/entrypoint.sh"]
