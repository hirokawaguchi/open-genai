"""OpenGENAI 手続きマスタ MCP サーバ（Streamable HTTP）。

patchform-app の公開済みカタログ（/catalog/*）を MCP ツールとして出す薄いラッパ。
下書き・提出本文・申請束トークンは出さない。書き込みもしない。
"""

from __future__ import annotations

import json
import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

PATCHFORM_BASE_URL = os.environ.get("PATCHFORM_BASE_URL", "http://patchform-app:8012").rstrip("/")
if PATCHFORM_BASE_URL.endswith("/invoke"):
    PATCHFORM_BASE_URL = PATCHFORM_BASE_URL[: -len("/invoke")].rstrip("/")
API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
HOST = os.environ.get("MCP_HOST", "0.0.0.0")
PORT = int(os.environ.get("MCP_PORT", "8013"))

mcp = FastMCP(
    "OpenGENAI Procedures",
    instructions=(
        "自治体が公開している手続きマスタを読む。"
        "list_procedures で一覧し、inspect_procedure で案内と対応表を見る。"
        "resolve_bundle に案内の答えを渡すと、足す様式の和集合をサーバー側で返す。"
        "下書きは出ない。提出や申請束の作成はできない。"
        "デジタル庁の行政手続等調査 MCP とは別物である。"
    ),
    host=HOST,
    port=PORT,
    streamable_http_path="/mcp",
    stateless_http=True,
    json_response=True,
)


def _headers() -> dict[str, str]:
    return {"x-api-key": API_KEY, "Content-Type": "application/json"}


def _as_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def parse_answers(raw: Any) -> Any:
    """LLM が JSON 文字列で渡した答えをオブジェクトに戻す。"""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw).strip()
    if not text:
        return {}
    if text.startswith("{") or text.startswith("["):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


async def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{PATCHFORM_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(url, headers=_headers(), params=params or {})
        r.raise_for_status()
        return r.json()


async def _post(path: str, body: dict[str, Any]) -> Any:
    url = f"{PATCHFORM_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


def _http_error(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            data = exc.response.json()
        except Exception:  # noqa: BLE001
            data = {"error": exc.response.text or str(exc)}
        return _as_json(data)
    return _as_json({"error": str(exc)})


@mcp.tool()
async def list_procedures(query: str = "") -> str:
    """公開中の手続き一覧。下書きは含まない。検索前に呼び、ID または名前を控えること。

    Args:
        query: 名前や説明の絞り込み（任意）。空なら全件。
    """
    try:
        data = await _get("/catalog/procedures", {"q": query} if query.strip() else None)
    except Exception as e:  # noqa: BLE001
        return _http_error(e)
    return _as_json(data)


@mcp.tool()
async def inspect_procedure(procedure: str) -> str:
    """公開中の手続きの中身。案内の選択肢、答えごとに足す様式、持ち物、注意。

    Args:
        procedure: 手続き ID または名前（list_procedures の値）。
    """
    ref = (procedure or "").strip()
    if not ref:
        return _as_json({"error": "procedure は必須です。先に list_procedures で確認してください。"})
    try:
        data = await _get("/catalog/procedure", {"ref": ref})
    except Exception as e:  # noqa: BLE001
        return _http_error(e)
    return _as_json(data)


@mcp.tool()
async def resolve_bundle(procedure: str, answers: str = "") -> str:
    """手続き ID（または名前）と案内の答えから、足す様式の和集合・解説・持ち物を返す。申請束は作らない。

    Args:
        procedure: 手続き ID または名前。
        answers: 案内の答え。JSON オブジェクト（例: {\"event\":\"転入\"}）または JSON 配列。
    """
    ref = (procedure or "").strip()
    if not ref:
        return _as_json({"error": "procedure は必須です。先に list_procedures で確認してください。"})
    try:
        data = await _post("/catalog/resolve", {"procedure": ref, "answers": parse_answers(answers)})
    except Exception as e:  # noqa: BLE001
        return _http_error(e)
    return _as_json(data)


def main() -> None:
    # Dify は Streamable HTTP のみ対応。エンドポイントは http://host:8013/mcp
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
