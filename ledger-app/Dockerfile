FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY ledger-app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY ledger-app/app ./app

EXPOSE 8023

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8023"]
