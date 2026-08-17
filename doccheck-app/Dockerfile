FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 0= RapidOCR のみ（arm64/開発向け既定）
# 1= 本家 PaddleOCR も追加（amd64 本番向け。イメージ肥大）
ARG INSTALL_PADDLEOCR=0

# RapidOCR (PP-OCR / ONNX) + Pillow 用のランタイム
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
        libpng16-16 \
        libgl1 \
        libglib2.0-0 \
        libxcb1 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
COPY requirements-paddleocr.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && if [ "$INSTALL_PADDLEOCR" = "1" ]; then \
         pip install --no-cache-dir -r requirements-paddleocr.txt; \
       fi

COPY app ./app
COPY public ./public
COPY samples ./samples

EXPOSE 8011

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8011"]
