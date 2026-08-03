FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ビルドコンテキストはリポジトリルート（shared/ を共有するため）
COPY rag-app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 氏名・住所 NER（GiNZA）。未導入でも電話・マイナンバー・住所パターンは動作する。
ARG PII_INSTALL_NER=0
RUN if [ "$PII_INSTALL_NER" = "1" ]; then \
      pip install --no-cache-dir 'ginza>=5.1.3' 'ja-ginza>=5.1.3'; \
    fi

COPY shared ./shared
COPY rag-app/app ./app

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
