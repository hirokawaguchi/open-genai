# 手元の llm-router イメージ（torch 2.12+cu130 / GB10 動作確認済み）を流用。
# PyTorch を再取得しない。足りないのは diffusers / accelerate / pillow のみ。
FROM storage-manager/llm-router:2.0.1

WORKDIR /sd

ENV PYTHONUNBUFFERED=1 \
    HF_HOME=/models \
    PIP_BREAK_SYSTEM_PACKAGES=1

COPY requirements.txt ./
RUN --mount=type=cache,target=/root/.cache/pip \
    python3 -m pip install --default-timeout=600 --retries 20 -r requirements.txt

COPY app.py ./

EXPOSE 7860

CMD ["python3", "-m", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
