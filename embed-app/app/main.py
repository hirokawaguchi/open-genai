"""OpenAI 互換の埋め込みサイドカー（sentence-transformers）。

任意の sentence-transformers 対応モデルを CPU で配信し、OpenAI 互換の
`/v1/embeddings` として提供する汎用サイドカー。埋め込みモデルは EMBED_MODEL で
差し替え可能（本プロジェクトの「どのモデルでも適用可能」という思想に沿う）。

HF Text Embeddings Inference (TEI, CPU/ORT) が配信できないモデル（例: ruri-v3 系＝
ModernBERT-Ja, ONNX 非提供）の受け皿としても使える。

- POST /v1/embeddings  { "model": ..., "input": str | [str, ...] }
    -> { "object": "list", "data": [{"object":"embedding","index":i,"embedding":[...]}],
         "model": ..., "usage": {...} }
- GET  /health

検索クエリ/文書への prefix（モデル依存: 例 Ruri の「検索クエリ: 」「検索文書: 」）は
呼び出し側(rag-app)で付与済みのため、ここではそのままエンコードする。
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
