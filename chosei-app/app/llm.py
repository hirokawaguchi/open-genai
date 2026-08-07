"""OpenAI 互換 chat/completions 呼び出し（Ollama 等）。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import httpx

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434").rstrip(
    "/"
)
OPENAI_BASE_URL = (
    os.environ.get("OPENAI_BASE_URL") or f"{OLLAMA_BASE_URL}/v1"
).rstrip("/")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY") or "ollama"
CHOSEI_MODEL = os.environ.get("CHOSEI_MODEL") or os.environ.get("DEFAULT_MODEL") or "qwen2.5:7b"
REQUEST_TIMEOUT = float(os.environ.get("CHOSEI_LLM_TIMEOUT", "120"))
DEFAULT_MAX_TOKENS = int(os.environ.get("CHOSEI_LLM_MAX_TOKENS", "2048"))


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


async def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    model: str | None = None,
    max_tokens: int | None = None,
) -> str:
    payload: dict[str, Any] = {
        "model": model or CHOSEI_MODEL,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "max_tokens": max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        res = await client.post(
            f"{OPENAI_BASE_URL}/chat/completions",
            json=payload,
            headers=_headers(),
        )
        res.raise_for_status()
        data = res.json()
    choices = data.get("choices") or [{}]
    return ((choices[0].get("message") or {}).get("content") or "").strip()


def _strip_fences(raw: str) -> str:
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    return raw.strip()


def salvage_truncated_json(raw: str) -> Any | None:
    """途中で切れた JSON から、完成している配列要素だけを復元する。

    例: {"dates":[{...},{...不完全  →  完成分の dates だけ返す。
    """
    text = _strip_fences(raw)
    start = text.find("{")
    if start < 0:
        start = text.find("[")
    if start < 0:
        return None
    text = text[start:]

    # 完成オブジェクトを後ろから削って再パース
    for end in range(len(text), 0, -1):
        chunk = text[:end].rstrip()
        # 未閉じの文字列・配列・オブジェクトを雑に閉じる
        candidates = [chunk]
        # 末尾が不完全な文字列の途中なら、その要素ごと捨てて閉じる
        if '"' in chunk:
            # 奇数個の未エスケープ " なら文字列が開いたまま
            quotes = 0
            escaped = False
            for ch in chunk:
                if escaped:
                    escaped = False
                    continue
                if ch == "\\":
                    escaped = True
                    continue
                if ch == '"':
                    quotes += 1
            if quotes % 2 == 1:
                # 最後の " 以降（不完全値）を捨て、直前のオブジェクト区切りまで戻す
                last_quote = chunk.rfind('"')
                # 不完全キー/値ごと削除し、直前の , または [ まで
                cut = max(chunk.rfind(","), chunk.rfind("["), chunk.rfind("{"))
                if cut > 0:
                    trimmed = chunk[:cut]
                    # [ の直後で切った場合はそのまま
                    if chunk[cut] == ",":
                        trimmed = chunk[:cut]
                    candidates.insert(0, trimmed)
        for base in candidates:
            open_sq = base.count("[") - base.count("]")
            open_cu = base.count("{") - base.count("}")
            if open_sq < 0 or open_cu < 0:
                continue
            trial = base + ("]" * open_sq) + ("}" * open_cu)
            # 末尾の余分なカンマを除去
            trial = re.sub(r",\s*([\]}])", r"\1", trial)
            try:
                return json.loads(trial)
            except json.JSONDecodeError:
                continue

    # dates 配列の完成要素だけ正規表現で拾う（最終手段）
    objs = re.findall(
        r'\{\s*"start_time"\s*:\s*"[^"]+"\s*,\s*"end_time"\s*:\s*(?:null|"[^"]*")\s*,'
        r'\s*"is_all_day"\s*:\s*(?:true|false)\s*,\s*"label"\s*:\s*"[^"]*"\s*\}',
        text,
    )
    if objs:
        dates = []
        for o in objs:
            try:
                dates.append(json.loads(o))
            except json.JSONDecodeError:
                continue
        if dates:
            return {"dates": dates, "notes": "応答が途中で切れたため、取得できた候補のみ反映しました。"}
    return None


def extract_json(text: str) -> Any:
    """モデル出力から JSON を取り出す（```json 囲み・途中切れにも対応）。"""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("空の応答です")
    body = _strip_fences(raw)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start = body.find(open_c)
        end = body.rfind(close_c)
        if start >= 0 and end > start:
            try:
                return json.loads(body[start : end + 1])
            except json.JSONDecodeError:
                continue
    salvaged = salvage_truncated_json(raw)
    if salvaged is not None:
        return salvaged
    raise ValueError(f"JSON を解析できませんでした: {text[:240]}")
