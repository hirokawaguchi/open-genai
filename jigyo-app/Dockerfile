FROM python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

COPY jigyo-app/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY jigyo-app/app ./app

EXPOSE 8020

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020"]
