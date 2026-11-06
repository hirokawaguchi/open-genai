"""自治体予算ビュー（Open GENAI exApp / 専用ページ向け）。

令和6年度の市区町村・普通会計決算を返す。画面は genai-web の /budget。
Compose では profiles: ["budget"] でオプション起動する。
庁内は backend が JWT 検証後、HMAC 署名付きで /config と /data へプロキシする。
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Header
from fastapi.responses import JSONResponse

from . import intauth

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
DATA_PATH = Path(__file__).resolve().parent / "data" / "fy2024.json"

app = FastAPI(title="Open GENAI Budget App", version="0.1.0")


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


def _verify_internal(
    x_api_key: str | None,
    x_user_id: str | None,
    x_user_groups: str | None,
    x_scope: str | None,
    x_user_ts: str | None,
    x_user_sig: str | None,
    x_user_tags: str | None,
) -> JSONResponse | None:
    err = _check_key(x_api_key)
    if err:
        return err
    if not intauth.verify(
        x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    ):
        return JSONResponse(status_code=401, content={"error": "invalid internal signature"})
    if not x_user_id:
        return JSONResponse(status_code=401, content={"error": "認証が必要です"})
    return None


@lru_cache(maxsize=1)
def load_data() -> dict:
    return json.loads(DATA_PATH.read_text(encoding="utf-8"))


@app.get("/health")
def health() -> dict[str, str]:
    load_data()
    return {"status": "ok"}


@app.get("/config")
def get_config(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    data = load_data()
    return JSONResponse(
        content={
            "enabled": True,
            "year": data["year"],
            "label": data["label"],
            "basis": data["basis"],
            "source": data["source"],
            "sourceUrl": data["sourceUrl"],
            "municipalities": len(data["rows"]),
        }
    )


@app.get("/data")
def get_data(
    x_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_user_groups: str | None = Header(default=None),
    x_scope: str | None = Header(default=None),
    x_user_ts: str | None = Header(default=None),
    x_user_sig: str | None = Header(default=None),
    x_user_tags: str | None = Header(default=None),
) -> JSONResponse:
    err = _verify_internal(
        x_api_key, x_user_id, x_user_groups, x_scope, x_user_ts, x_user_sig, x_user_tags
    )
    if err:
        return err
    return JSONResponse(content=load_data())
