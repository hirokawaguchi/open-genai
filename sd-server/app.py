"""A1111 互換の最小 txt2img/img2img API（源内 /image 向け）。

PyTorch はベースイメージ（storage-manager/llm-router の cu130）を流用する。
既定モデルは SD-Turbo（数ステップ・guidance 0）。UI 既定の 50/7 はサーバ側で丸める。
"""

from __future__ import annotations

import base64
import io
import os
import threading
from typing import Any

import torch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from PIL import Image

MODEL_ID = os.environ.get("SD_MODEL_ID", "stabilityai/sd-turbo")
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32
IS_TURBO = "turbo" in MODEL_ID.lower() or "lcm" in MODEL_ID.lower()

app = FastAPI(title="Open GENAI SD Server", version="0.1.0")

_lock = threading.RLock()
_txt2img = None
_img2img = None
_load_error: str | None = None


def _get_txt2img():
    global _txt2img, _load_error
    if _txt2img is not None:
        return _txt2img
    with _lock:
        if _txt2img is not None:
            return _txt2img
        from diffusers import AutoPipelineForText2Image

        kwargs: dict[str, Any] = {
            "torch_dtype": DTYPE,
            "safety_checker": None,
        }
        if os.path.isdir(MODEL_ID):
            kwargs["local_files_only"] = True
        if DTYPE == torch.float16:
            kwargs["variant"] = "fp16"
        try:
            pipe = AutoPipelineForText2Image.from_pretrained(MODEL_ID, **kwargs)
        except Exception:
            kwargs.pop("variant", None)
            pipe = AutoPipelineForText2Image.from_pretrained(MODEL_ID, **kwargs)
        pipe.to(DEVICE)
        _txt2img = pipe
        _load_error = None
        return _txt2img


def _get_img2img():
    global _img2img
    txt = _get_txt2img()
    if _img2img is not None:
        return _img2img
    with _lock:
        if _img2img is not None:
            return _img2img
        from diffusers import AutoPipelineForImage2Image

        _img2img = AutoPipelineForImage2Image.from_pipe(txt)
        return _img2img


def _b64_to_image(data: str) -> Image.Image:
    raw = base64.b64decode(data.split(",", 1)[-1])
    return Image.open(io.BytesIO(raw)).convert("RGB")


def _image_to_b64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _resolve_steps_cfg(steps: int, cfg: float) -> tuple[int, float]:
    if IS_TURBO:
        return max(1, min(int(steps or 4), 4)), 0.0
    return max(1, int(steps or 20)), float(cfg if cfg is not None else 7)


def _prefetch_safe() -> None:
    global _load_error
    try:
        _get_txt2img()
    except Exception as exc:  # noqa: BLE001
        _load_error = str(exc)


@app.on_event("startup")
def _prefetch() -> None:
    if os.environ.get("SD_PREFETCH", "1").strip().lower() in ("0", "false", "off"):
        return
    threading.Thread(target=_prefetch_safe, name="sd-prefetch", daemon=True).start()


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL_ID,
        "device": DEVICE,
        "loaded": _txt2img is not None,
        "error": _load_error,
    }


@app.get("/sdapi/v1/sd-models")
def sd_models() -> list[dict[str, str]]:
    return [{"title": MODEL_ID, "model_name": MODEL_ID.split("/")[-1]}]


def _dim(value: Any, default: int = 512) -> int:
    n = int(value or default)
    n = max(64, min(n, 1024))
    return n - (n % 8)


@app.post("/sdapi/v1/txt2img")
def txt2img(body: dict[str, Any]) -> Any:
    try:
        steps, cfg = _resolve_steps_cfg(body.get("steps") or 20, body.get("cfg_scale") or 7)
        seed = int(body.get("seed") if body.get("seed") is not None else -1)
        generator = None
        if seed >= 0:
            generator = torch.Generator(device=DEVICE).manual_seed(seed)
        # Diffusers の pipe はスレッドセーフではない。UI は既定 3 枚並列なので直列化する。
        with _lock:
            pipe = _get_txt2img()
            image = pipe(
                prompt=body.get("prompt") or "",
                negative_prompt=body.get("negative_prompt") or None,
                width=_dim(body.get("width")),
                height=_dim(body.get("height")),
                num_inference_steps=steps,
                guidance_scale=cfg,
                generator=generator,
            ).images[0]
        return {"images": [_image_to_b64(image)], "info": f'{{"seed": {seed}, "steps": {steps}}}'}
    except Exception as exc:  # noqa: BLE001
        print(f"[sd-server] txt2img failed: {exc}")
        return JSONResponse(status_code=500, content={"error": str(exc)})


@app.post("/sdapi/v1/img2img")
def img2img(body: dict[str, Any]) -> Any:
    inits = body.get("init_images") or []
    if not inits:
        return JSONResponse(status_code=400, content={"error": "init_images required"})
    try:
        steps, cfg = _resolve_steps_cfg(body.get("steps") or 20, body.get("cfg_scale") or 7)
        seed = int(body.get("seed") if body.get("seed") is not None else -1)
        generator = None
        if seed >= 0:
            generator = torch.Generator(device=DEVICE).manual_seed(seed)
        with _lock:
            pipe = _get_img2img()
            image = pipe(
                prompt=body.get("prompt") or "",
                negative_prompt=body.get("negative_prompt") or None,
                image=_b64_to_image(inits[0]),
                strength=float(body.get("denoising_strength") or 0.35),
                num_inference_steps=steps,
                guidance_scale=cfg,
                generator=generator,
            ).images[0]
        return {"images": [_image_to_b64(image)], "info": f'{{"seed": {seed}, "steps": {steps}}}'}
    except Exception as exc:  # noqa: BLE001
        print(f"[sd-server] img2img failed: {exc}")
        return JSONResponse(status_code=500, content={"error": str(exc)})
