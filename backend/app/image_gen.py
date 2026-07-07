"""源内 Web「画像を生成」ページ向けの /image/generate 実装。

クラウド版では Bedrock Lambda が担うエンドポイントを、
ローカルではホスト上の AUTOMATIC1111 互換 SD サーバへプロキシする。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

SD_API_URL = os.environ.get("SD_API_URL", "http://host.docker.internal:7860").rstrip("/")
SD_TIMEOUT = float(os.environ.get("SD_TIMEOUT", "600"))

LOCAL_SD_MODEL_ID = "local-sd"


def _positive_negative_prompts(text_prompt: list[dict[str, Any]]) -> tuple[str, str]:
    positive = ""
    negative = ""
    for item in text_prompt:
        text = (item.get("text") or "").strip()
        if not text:
            continue
        weight = item.get("weight", 1)
        if weight < 0:
            negative = text if not negative else f"{negative}, {text}"
        else:
            positive = text if not positive else f"{positive}, {text}"
    return positive, negative


def _apply_style_preset(prompt: str, style_preset: str | None) -> str:
    preset = (style_preset or "").strip()
    if not preset:
        return prompt
    return f"{prompt}, {preset} style"


def build_a1111_payload(params: dict[str, Any]) -> dict[str, Any]:
    """GenerateImageParams 相当を A1111 txt2img / img2img 用 payload に変換する。"""
    positive, negative = _positive_negative_prompts(params.get("textPrompt") or [])
    if not positive:
        raise ValueError("プロンプトが空です。")

    positive = _apply_style_preset(positive, params.get("stylePreset"))

    width = int(params.get("width") or 512)
    height = int(params.get("height") or 512)
    steps = int(params.get("step") or 20)
    cfg_scale = float(params.get("cfgScale") or 7)
    seed = int(params.get("seed") if params.get("seed") is not None else -1)

    payload: dict[str, Any] = {
        "prompt": positive,
        "negative_prompt": negative,
        "steps": steps,
        "width": width,
        "height": height,
        "cfg_scale": cfg_scale,
        "seed": seed,
    }

    init_image = (params.get("initImage") or "").strip()
    if init_image:
        payload["init_images"] = [init_image]
        payload["denoising_strength"] = float(params.get("imageStrength") or 0.35)

    return payload


async def is_sd_up() -> bool:
    """A1111 互換 SD サーバが起動・到達可能かを短時間で確認する。"""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{SD_API_URL}/sdapi/v1/sd-models")
        return res.status_code == 200
    except httpx.HTTPError:
        return False


async def generate_image_base64(params: dict[str, Any]) -> str:
    """A1111 互換 SD サーバで画像を生成し、base64 文字列を返す。"""
    payload = build_a1111_payload(params)
    init_image = (params.get("initImage") or "").strip()
    endpoint = "img2img" if init_image else "txt2img"

    try:
        async with httpx.AsyncClient(timeout=SD_TIMEOUT) as client:
            res = await client.post(
                f"{SD_API_URL}/sdapi/v1/{endpoint}",
                json=payload,
            )
    except httpx.HTTPError as exc:
        raise RuntimeError(
            "ホストの画像生成サーバ(A1111 互換)に接続できませんでした。"
            f"`{SD_API_URL}` で起動しているか確認してください: {exc} "
            "（検証用: ホストで `python3 scripts/mock-sd-server.py`）"
        ) from exc

    if res.status_code != 200:
        raise RuntimeError(f"画像生成に失敗しました (status: {res.status_code})")

    data = res.json()
    images = data.get("images") or []
    if not images:
        raise RuntimeError("画像が生成されませんでした。")

    image = images[0]
    if image.startswith("data:"):
        image = image.split(",", 1)[1]
    return image
