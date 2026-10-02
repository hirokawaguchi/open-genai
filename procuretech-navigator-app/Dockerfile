FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# ビルドコンテキストはリポジトリルート（shared/llm_fallback を共有するため）
COPY procuretech-navigator-app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY procuretech-navigator-app/app ./app
COPY procuretech-navigator-app/materials ./materials

EXPOSE 8014

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8014"]
