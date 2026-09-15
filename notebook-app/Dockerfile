FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        libjpeg62-turbo \
        libpng16-16 \
        zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY notebook-app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY notebook-app/app ./app

EXPOSE 8017

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8017"]
