"""源内 Web「画像を生成」ページ向けの /image/generate 実装。

モデル ID でバックエンドを振り分ける。

- `local-sd`（またはモデル未指定）: ローカル画像生成サーバ。`SD_BACKEND` で切り替える。
  - `a1111`（既定）: AUTOMATIC1111 互換（`/sdapi/v1/txt2img`）。
  - `fastsd`: FastSD CPU（`POST /api/generate`）。
- `IMAGE_PROVIDERS` に登録した modelId: `protocol` ごとのクラウド API。
  実装済みは `openai_images`（OpenAI 互換 `POST /images/generations`）のみ。
  別プロトコルは `_PROTOCOLS` に関数を足す。
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx

# 画像生成バックエンド: a1111（既定）| fastsd
SD_BACKEND = (os.environ.get("SD_BACKEND") or "a1111").strip().lower()

# 接続先。既定は a1111=:7860 / fastsd=:8000（SD_API_URL を明示すればそれを優先）。
_DEFAULT_SD_URL = "http://host.docker.internal:8000" if SD_BACKEND == "fastsd" else "http://host.docker.internal:7860"
SD_API_URL = (os.environ.get("SD_API_URL") or _DEFAULT_SD_URL).rstrip("/")
SD_TIMEOUT = float(os.environ.get("SD_TIMEOUT", "600"))

LOCAL_SD_MODEL_ID = "local-sd"
LOCAL_SD_UNAVAILABLE_MESSAGE = "ローカルの Stable Diffusion に接続できません。"
LOCAL_SD_UNAVAILABLE_CODE = "local_sd_unavailable"

# OpenAI Images の許可サイズ。未登録モデルは gpt-image-1 と同じ 3 サイズへ寄せる。
_OPENAI_IMAGE_SIZES: dict[str, tuple[tuple[int, int], ...]] = {
    "gpt-image-1": ((1024, 1024), (1536, 1024), (1024, 1536)),
    "dall-e-3": ((1024, 1024), (1792, 1024), (1024, 1792)),
    "dall-e-2": ((256, 256), (512, 512), (1024, 1024)),
}
_DEFAULT_OPENAI_IMAGE_SIZES = _OPENAI_IMAGE_SIZES["gpt-image-1"]


class ImageGenError(Exception):
    """画像生成の失敗。status / code を API 応答に載せる。"""

    def __init__(
        self, message: str, *, status: int = 502, code: str | None = None
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


@dataclass
class ImageProvider:
    """画像生成 API 1 系統ぶんの接続情報。"""

    name: str
    protocol: str
    base_url: str
    api_key: str | None = None
    auth_header: str = "Authorization"
    auth_prefix: str = "Bearer "
    query: dict[str, str] = field(default_factory=dict)
    models: list[str] = field(default_factory=list)

    def headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers[self.auth_header] = f"{self.auth_prefix}{self.api_key}"
        return headers


def load_image_providers() -> dict[str, ImageProvider]:
    """`IMAGE_PROVIDERS` を modelId → provider に読む。未設定・不正時は空。"""
    raw = os.environ.get("IMAGE_PROVIDERS", "").strip()
    if not raw:
        return {}
    try:
        entries = json.loads(raw)
    except (ValueError, TypeError) as exc:
        print(f"[image] IMAGE_PROVIDERS の解析に失敗: {exc}")
        return {}
    if not isinstance(entries, list):
        print("[image] IMAGE_PROVIDERS は JSON 配列である必要があります")
        return {}

    index: dict[str, ImageProvider] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("base_url"):
            continue
        protocol = str(entry.get("protocol") or "").strip()
        models = [str(m) for m in (entry.get("models") or []) if str(m).strip()]
        if not protocol or not models:
            print(f"[image] protocol または models が無いエントリを無視: {entry.get('name')}")
            continue
        key = None
        if entry.get("api_key_env"):
            key = os.environ.get(str(entry["api_key_env"])) or None
        elif entry.get("api_key"):
            key = str(entry["api_key"]) or None
        provider = ImageProvider(
            name=str(entry.get("name") or entry["base_url"]),
            protocol=protocol,
            base_url=str(entry["base_url"]).rstrip("/"),
            api_key=key,
            auth_header=str(entry.get("auth_header") or "Authorization"),
            auth_prefix=(
                entry["auth_prefix"]
                if entry.get("auth_prefix") is not None
                else "Bearer "
            ),
            query={str(k): str(v) for k, v in (entry.get("query") or {}).items()},
            models=models,
        )
        for model_id in provider.models:
            if model_id in index:
                print(
                    f"[image] モデルID重複 '{model_id}': '{index[model_id].name}' を優先し "
                    f"'{provider.name}' の割当は無視"
                )
                continue
            if model_id == LOCAL_SD_MODEL_ID:
                print("[image] local-sd はローカル SD 専用のため IMAGE_PROVIDERS では無視")
                continue
            index[model_id] = provider
    return index


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
        raise _local_sd_unavailable(exc) from exc

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
        raise _local_sd_unavailable(exc) from exc

    if res.status_code != 200:
        raise RuntimeError(f"画像生成に失敗しました (status: {res.status_code})")

    data = res.json()
    if data.get("error"):
        raise RuntimeError(f"画像生成に失敗しました: {data.get('error')}")
    images = data.get("images") or []
    if not images:
        raise RuntimeError("画像が生成されませんでした。")
    return _strip_data_uri(images[0])


# --- OpenAI 互換 Images API ------------------------------------------------


def openai_image_size(model_id: str, width: int, height: int) -> str:
    """幅・高さに近いアスペクトの許可サイズを返す。"""
    sizes = _OPENAI_IMAGE_SIZES.get(model_id, _DEFAULT_OPENAI_IMAGE_SIZES)
    safe_height = height if height > 0 else 1
    aspect = width / safe_height
    best = min(sizes, key=lambda wh: abs((wh[0] / wh[1]) - aspect))
    return f"{best[0]}x{best[1]}"


def _openai_prompt(common: dict[str, Any]) -> str:
    prompt = common["positive"]
    if common["negative"]:
        prompt = f"{prompt} Avoid: {common['negative']}"
    return prompt


def build_openai_edit_fields(
    model_id: str, params: dict[str, Any]
) -> tuple[dict[str, str], bytes]:
    """添付画像の加工用。雰囲気未指定ならスタイル文言は足さない。"""
    common = _common_params(params)
    if not common["init_image"]:
        raise ImageGenError(
            "加工する画像がありません。",
            status=400,
            code="missing_source_image",
        )
    try:
        raw = base64.b64decode(common["init_image"])
    except (ValueError, TypeError) as exc:
        raise ImageGenError("画像を読み込めませんでした。", status=400) from exc
    fields = {
        "model": model_id,
        "prompt": _openai_prompt(common),
        "n": "1",
        "size": openai_image_size(model_id, common["width"], common["height"]),
        "input_fidelity": "high",
    }
    return fields, raw


def build_openai_images_payload(model_id: str, params: dict[str, Any]) -> dict[str, Any]:
    """GenerateImageParams を OpenAI Images generations 用 payload に変換する。"""
    common = _common_params(params)
    if common["init_image"]:
        raise ImageGenError(
            "このモデルはテキストからの画像生成のみ対応しています。",
            status=400,
            code="unsupported_image_mode",
        )
    payload: dict[str, Any] = {
        "model": model_id,
        "prompt": _openai_prompt(common),
        "n": 1,
        "size": openai_image_size(model_id, common["width"], common["height"]),
    }
    # gpt-image 系は b64_json を既定で返す。dall-e は URL 既定のため明示する。
    if model_id.startswith("dall-e"):
        payload["response_format"] = "b64_json"
    return payload


def _auth_headers(provider: ImageProvider) -> dict[str, str]:
    if not provider.api_key:
        return {}
    return {provider.auth_header: f"{provider.auth_prefix}{provider.api_key}"}


async def _openai_images_edit(
    provider: ImageProvider, model_id: str, params: dict[str, Any]
) -> str:
    fields, raw = build_openai_edit_fields(model_id, params)
    try:
        async with httpx.AsyncClient(timeout=SD_TIMEOUT) as client:
            res = await client.post(
                f"{provider.base_url}/images/edits",
                data=fields,
                files={"image": ("image.png", raw, "image/png")},
                headers=_auth_headers(provider),
                params=provider.query or None,
            )
    except httpx.HTTPError as exc:
        print(f"[image] openai_images edit unreachable provider={provider.name}: {exc}")
        raise ImageGenError(
            "クラウドの画像生成サービスに接続できませんでした。",
            status=502,
            code="image_provider_unavailable",
        ) from exc
    return _openai_image_from_response(res, "edit")


def _openai_image_from_response(res: httpx.Response, kind: str) -> str:
    if res.status_code != 200:
        print(f"[image] openai_images {kind} status={res.status_code} body={res.text[:500]}")
        raise ImageGenError("画像生成に失敗しました。", status=502)
    data = res.json()
    images = data.get("data") or []
    b64 = images[0].get("b64_json") if images else None
    if not b64:
        raise ImageGenError("画像が生成されませんでした。", status=502)
    return _strip_data_uri(b64)


async def _openai_images_generate(
    provider: ImageProvider, model_id: str, params: dict[str, Any]
) -> str:
    if (params.get("initImage") or "").strip():
        return await _openai_images_edit(provider, model_id, params)
    payload = build_openai_images_payload(model_id, params)
    try:
        async with httpx.AsyncClient(timeout=SD_TIMEOUT) as client:
            res = await client.post(
                f"{provider.base_url}/images/generations",
                json=payload,
                headers=provider.headers(),
                params=provider.query or None,
            )
    except httpx.HTTPError as exc:
        print(f"[image] openai_images unreachable provider={provider.name}: {exc}")
        raise ImageGenError(
            "クラウドの画像生成サービスに接続できませんでした。",
            status=502,
            code="image_provider_unavailable",
        ) from exc

    return _openai_image_from_response(res, "generate")


ImageProtocol = Callable[
    [ImageProvider, str, dict[str, Any]], Awaitable[str]
]

# 新しいクラウド画像 API はここに関数を登録する。
_PROTOCOLS: dict[str, ImageProtocol] = {
    "openai_images": _openai_images_generate,
}


# --- 共通ディスパッチ -------------------------------------------------------


def _strip_data_uri(image: str) -> str:
    return image.split(",", 1)[1] if image.startswith("data:") else image


def _local_sd_unavailable(exc: BaseException) -> ImageGenError:
    print(f"[image] local SD unreachable url={SD_API_URL} backend={SD_BACKEND}: {exc}")
    return ImageGenError(
        LOCAL_SD_UNAVAILABLE_MESSAGE,
        status=502,
        code=LOCAL_SD_UNAVAILABLE_CODE,
    )


async def is_sd_up() -> bool:
    """ローカル画像生成サーバが起動・到達可能かを短時間で確認する。"""
    if SD_BACKEND == "fastsd":
        return await _fastsd_is_up()
    return await _a1111_is_up()


async def is_image_available() -> bool:
    """画像機能を出してよいか。ローカル SD か、クラウド画像プロバイダの登録がある。"""
    if load_image_providers():
        return True
    return await is_sd_up()


def _resolve_route(
    model: dict[str, Any] | None,
) -> tuple[str, ImageProvider | None]:
    model_id = ""
    if model and model.get("modelId"):
        model_id = str(model["modelId"]).strip()
    if not model_id or model_id == LOCAL_SD_MODEL_ID:
        return LOCAL_SD_MODEL_ID, None
    provider = load_image_providers().get(model_id)
    if provider is None:
        raise ImageGenError(
            f"未登録の画像生成モデルです: {model_id}",
            status=400,
            code="unknown_image_model",
        )
    return model_id, provider


async def generate_image_base64(
    params: dict[str, Any], model: dict[str, Any] | None = None
) -> str:
    """モデル指定に応じたバックエンドで画像を生成し、base64 文字列を返す。"""
    model_id, provider = _resolve_route(model)
    if provider is None:
        if SD_BACKEND == "fastsd":
            return await _fastsd_generate(params)
        return await _a1111_generate(params)
    handler = _PROTOCOLS.get(provider.protocol)
    if handler is None:
        raise ImageGenError(
            f"未対応の画像生成 protocol です: {provider.protocol}。"
            "backend/app/image_gen.py の _PROTOCOLS に関数を追加してください。",
            status=400,
            code="unsupported_image_protocol",
        )
    return await handler(provider, model_id, params)
