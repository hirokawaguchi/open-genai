"""源内 Web「画像を生成」ページ向けの /image/generate 実装。

クラウド版では Bedrock Lambda が担うエンドポイントを、ローカルでは画像生成サーバへ
プロキシする。バックエンドは `SD_BACKEND` で切り替える（既定は現行どおり A1111 互換）。

- `SD_BACKEND=a1111`（既定）: AUTOMATIC1111 互換 SD サーバ（GPU で自前運用する想定。
  Mac ホスト / Linux+NVIDIA コンテナ等）。`/sdapi/v1/txt2img` を叩く。
- `SD_BACKEND=fastsd`: FastSD CPU（CPU-only 環境向け・LCM）。A1111 非互換の独自 API
  `POST /api/generate`（LCMDiffusionSetting）を叩く。FastSD 本体は外部で
  `python src/app.py --api`（既定 :8000）として起動しておく。
"""

from __future__ import annotations

import os
from typing import Any

import httpx

# 画像生成バックエンド: a1111（既定）| fastsd
SD_BACKEND = (os.environ.get("SD_BACKEND") or "a1111").strip().lower()

# 接続先。既定は a1111=:7860 / fastsd=:8000（SD_API_URL を明示すればそれを優先）。
_DEFAULT_SD_URL = "http://host.docker.internal:8000" if SD_BACKEND == "fastsd" else "http://host.docker.internal:7860"
SD_API_URL = (os.environ.get("SD_API_URL") or _DEFAULT_SD_URL).rstrip("/")
SD_TIMEOUT = float(os.environ.get("SD_TIMEOUT", "600"))

LOCAL_SD_MODEL_ID = "local-sd"


def _envbool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


# FastSD は /api/generate ごとに diffusion 設定を丸ごと置き換えるため、モデル関連は毎回明示する。
# 未指定ならサーバ側 pydantic 既定（LCM 既定モデル・OpenVINO 無効）になる。
_FASTSD_MODEL_ID = (os.environ.get("SD_FASTSD_MODEL_ID") or "").strip()
_FASTSD_OPENVINO_MODEL_ID = (os.environ.get("SD_FASTSD_OPENVINO_MODEL_ID") or "").strip()
_FASTSD_USE_OPENVINO = _envbool("SD_FASTSD_USE_OPENVINO", False)
_FASTSD_USE_LCM_LORA = _envbool("SD_FASTSD_USE_LCM_LORA", False)
_FASTSD_USE_TINY_AUTO_ENCODER = _envbool("SD_FASTSD_USE_TINY_AUTO_ENCODER", False)
_FASTSD_USE_SAFETY_CHECKER = _envbool("SD_FASTSD_USE_SAFETY_CHECKER", False)


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


def _common_params(params: dict[str, Any]) -> dict[str, Any]:
    """GenerateImageParams から共通の生成パラメータを取り出す。"""
    positive, negative = _positive_negative_prompts(params.get("textPrompt") or [])
    if not positive:
        raise ValueError("プロンプトが空です。")
    positive = _apply_style_preset(positive, params.get("stylePreset"))

    return {
        "positive": positive,
        "negative": negative,
        "width": int(params.get("width") or 512),
        "height": int(params.get("height") or 512),
        "steps": int(params.get("step") or 20),
        "cfg_scale": float(params.get("cfgScale") or 7),
        "seed": int(params.get("seed") if params.get("seed") is not None else -1),
        "init_image": (params.get("initImage") or "").strip(),
        "image_strength": float(params.get("imageStrength") or 0.35),
    }


# --- AUTOMATIC1111 互換バックエンド ---------------------------------------


def build_a1111_payload(params: dict[str, Any]) -> dict[str, Any]:
    """GenerateImageParams 相当を A1111 txt2img / img2img 用 payload に変換する。"""
    c = _common_params(params)

    payload: dict[str, Any] = {
        "prompt": c["positive"],
        "negative_prompt": c["negative"],
        "steps": c["steps"],
        "width": c["width"],
        "height": c["height"],
        "cfg_scale": c["cfg_scale"],
        "seed": c["seed"],
    }
    if c["init_image"]:
        payload["init_images"] = [c["init_image"]]
        payload["denoising_strength"] = c["image_strength"]
    return payload


async def _a1111_is_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{SD_API_URL}/sdapi/v1/sd-models")
        return res.status_code == 200
    except httpx.HTTPError:
        return False


async def _a1111_generate(params: dict[str, Any]) -> str:
    payload = build_a1111_payload(params)
    endpoint = "img2img" if (params.get("initImage") or "").strip() else "txt2img"
    try:
        async with httpx.AsyncClient(timeout=SD_TIMEOUT) as client:
            res = await client.post(f"{SD_API_URL}/sdapi/v1/{endpoint}", json=payload)
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
    return _strip_data_uri(images[0])


# --- FastSD CPU バックエンド -----------------------------------------------


def build_fastsd_payload(params: dict[str, Any]) -> dict[str, Any]:
    """GenerateImageParams 相当を FastSD `/api/generate`(LCMDiffusionSetting) 用に変換する。"""
    c = _common_params(params)
    is_img2img = bool(c["init_image"])

    payload: dict[str, Any] = {
        "prompt": c["positive"],
        "negative_prompt": c["negative"],
        "image_width": c["width"],
        "image_height": c["height"],
        "inference_steps": c["steps"],
        "guidance_scale": c["cfg_scale"],
        "number_of_images": 1,
        "use_openvino": _FASTSD_USE_OPENVINO,
        "use_lcm_lora": _FASTSD_USE_LCM_LORA,
        "use_tiny_auto_encoder": _FASTSD_USE_TINY_AUTO_ENCODER,
        "use_safety_checker": _FASTSD_USE_SAFETY_CHECKER,
        "diffusion_task": "image_to_image" if is_img2img else "text_to_image",
    }

    # seed は use_seed=True のときだけ固定される。未指定/負値はランダム。
    if c["seed"] is not None and c["seed"] >= 0:
        payload["seed"] = c["seed"]
        payload["use_seed"] = True

    if _FASTSD_MODEL_ID:
        payload["lcm_model_id"] = _FASTSD_MODEL_ID
    if _FASTSD_OPENVINO_MODEL_ID:
        payload["openvino_lcm_model_id"] = _FASTSD_OPENVINO_MODEL_ID

    if is_img2img:
        payload["init_image"] = c["init_image"]
        payload["strength"] = c["image_strength"]

    return payload


async def _fastsd_is_up() -> bool:
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get(f"{SD_API_URL}/api/models")
        return res.status_code == 200
    except httpx.HTTPError:
        return False


async def _fastsd_generate(params: dict[str, Any]) -> str:
    payload = build_fastsd_payload(params)
    try:
        async with httpx.AsyncClient(timeout=SD_TIMEOUT) as client:
            res = await client.post(f"{SD_API_URL}/api/generate", json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(
            "画像生成サーバ(FastSD CPU)に接続できませんでした。"
            f"`{SD_API_URL}` で `python src/app.py --api`（既定 :8000）として "
            f"起動しているか確認してください: {exc}"
        ) from exc

    if res.status_code != 200:
        raise RuntimeError(f"画像生成に失敗しました (status: {res.status_code})")

    data = res.json()
    if data.get("error"):
        raise RuntimeError(f"画像生成に失敗しました: {data.get('error')}")
    images = data.get("images") or []
    if not images:
        raise RuntimeError("画像が生成されませんでした。")
    return _strip_data_uri(images[0])


# --- 共通ディスパッチ -------------------------------------------------------


def _strip_data_uri(image: str) -> str:
    return image.split(",", 1)[1] if image.startswith("data:") else image


async def is_sd_up() -> bool:
    """画像生成サーバが起動・到達可能かを短時間で確認する。"""
    if SD_BACKEND == "fastsd":
        return await _fastsd_is_up()
    return await _a1111_is_up()


async def generate_image_base64(params: dict[str, Any]) -> str:
    """設定されたバックエンドで画像を生成し、base64 文字列を返す。"""
    if SD_BACKEND == "fastsd":
        return await _fastsd_generate(params)
    return await _a1111_generate(params)
