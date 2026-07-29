"""OpenAI 互換の埋め込みサイドカー（sentence-transformers）。

HF Text Embeddings Inference (TEI, CPU/ORT) は ruri-v3 系（ModernBERT-Ja, ONNX
非提供）を CPU で配信できないため、その代替として sentence-transformers で同等の
埋め込みを OpenAI 互換 API として提供する。

- POST /v1/embeddings  { "model": ..., "input": str | [str, ...] }
    -> { "object": "list", "data": [{"object":"embedding","index":i,"embedding":[...]}],
         "model": ..., "usage": {...} }
- GET  /health

入力への prefix（Ruri の「検索クエリ: 」「検索文書: 」）は呼び出し側(rag-app)で付与済み。
ここではそのままエンコードする。
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

MODEL_ID = os.environ.get("EMBED_MODEL", "cl-nagoya/ruri-v3-310m")
NORMALIZE = os.environ.get("EMBED_NORMALIZE", "true").lower() != "false"

app = FastAPI(title="open-genai embed sidecar")
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_ID, device="cpu")
    return _model


class EmbeddingsRequest(BaseModel):
    input: str | list[str]
    model: str | None = None


@app.on_event("startup")
def _warmup() -> None:
    # 起動時にモデルをロードして初回リクエストのレイテンシを避ける。
    _get_model()


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model": MODEL_ID}


@app.post("/v1/embeddings")
def embeddings(req: EmbeddingsRequest) -> dict[str, Any]:
    inputs = [req.input] if isinstance(req.input, str) else list(req.input)
    model = _get_model()
    vectors = model.encode(
        inputs,
        normalize_embeddings=NORMALIZE,
        convert_to_numpy=True,
    )
    data = [
        {"object": "embedding", "index": i, "embedding": vec.tolist()}
        for i, vec in enumerate(vectors)
    ]
    total_chars = sum(len(t) for t in inputs)
    return {
        "object": "list",
        "data": data,
        "model": req.model or MODEL_ID,
        "usage": {"prompt_tokens": total_chars, "total_tokens": total_chars},
    }
