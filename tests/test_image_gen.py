from __future__ import annotations

import asyncio
import json
import os

from conftest import load_service_module


def test_build_a1111_payload_text_to_image() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    payload = image_gen.build_a1111_payload(
        {
            "textPrompt": [
                {"text": "a cat", "weight": 1},
                {"text": "blurry", "weight": -1},
            ],
            "width": 512,
            "height": 768,
            "step": 25,
            "cfgScale": 8,
            "seed": 42,
            "stylePreset": "anime",
        }
    )
    assert payload["prompt"] == "a cat, anime style"
    assert payload["negative_prompt"] == "blurry"
    assert payload["width"] == 512
    assert payload["height"] == 768
    assert payload["steps"] == 25
    assert payload["cfg_scale"] == 8
    assert payload["seed"] == 42
    assert "init_images" not in payload


def test_build_a1111_payload_image_to_image() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    payload = image_gen.build_a1111_payload(
        {
            "textPrompt": [{"text": "a dog", "weight": 1}],
            "width": 512,
            "height": 512,
            "step": 20,
            "cfgScale": 7,
            "seed": 1,
            "initImage": "abc123",
            "imageStrength": 0.4,
        }
    )
    assert payload["init_images"] == ["abc123"]
    assert payload["denoising_strength"] == 0.4


def test_build_a1111_payload_requires_prompt() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    try:
        image_gen.build_a1111_payload({"textPrompt": []})
    except ValueError as exc:
        assert "プロンプト" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_build_fastsd_payload_text_to_image() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    payload = image_gen.build_fastsd_payload(
        {
            "textPrompt": [
                {"text": "a cat", "weight": 1},
                {"text": "blurry", "weight": -1},
            ],
            "width": 512,
            "height": 768,
            "step": 4,
            "cfgScale": 1,
            "seed": 42,
        }
    )
    assert payload["prompt"] == "a cat"
    assert payload["negative_prompt"] == "blurry"
    assert payload["image_width"] == 512
    assert payload["image_height"] == 768
    assert payload["inference_steps"] == 4
    assert payload["guidance_scale"] == 1
    assert payload["diffusion_task"] == "text_to_image"
    # seed>=0 のときは use_seed=True で固定される
    assert payload["seed"] == 42
    assert payload["use_seed"] is True
    assert "init_image" not in payload


def test_build_fastsd_payload_random_seed() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    payload = image_gen.build_fastsd_payload(
        {
            "textPrompt": [{"text": "a cat", "weight": 1}],
            "seed": -1,
        }
    )
    # 負値はランダム扱い（seed / use_seed を送らない）
    assert "seed" not in payload
    assert "use_seed" not in payload


def test_build_fastsd_payload_image_to_image() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    payload = image_gen.build_fastsd_payload(
        {
            "textPrompt": [{"text": "a dog", "weight": 1}],
            "step": 4,
            "cfgScale": 1,
            "seed": 1,
            "initImage": "abc123",
            "imageStrength": 0.4,
        }
    )
    assert payload["diffusion_task"] == "image_to_image"
    assert payload["init_image"] == "abc123"
    assert payload["strength"] == 0.4


def test_build_fastsd_payload_requires_prompt() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    try:
        image_gen.build_fastsd_payload({"textPrompt": []})
    except ValueError as exc:
        assert "プロンプト" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def _cat_params(**extra: object) -> dict:
    return {"textPrompt": [{"text": "a cat", "weight": 1}], **extra}


def test_openai_image_size_snaps_to_nearest_aspect() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    assert image_gen.openai_image_size("gpt-image-1", 512, 512) == "1024x1024"
    assert image_gen.openai_image_size("gpt-image-1", 1280, 768) == "1536x1024"
    assert image_gen.openai_image_size("gpt-image-1", 768, 1280) == "1024x1536"


def test_build_openai_images_payload_text_only() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    payload = image_gen.build_openai_images_payload(
        "gpt-image-1",
        _cat_params(
            textPrompt=[
                {"text": "a cat", "weight": 1},
                {"text": "blurry", "weight": -1},
            ],
            width=1280,
            height=768,
            step=50,
            cfgScale=7,
            seed=42,
            stylePreset="anime",
        ),
    )
    assert payload["model"] == "gpt-image-1"
    assert payload["prompt"] == "a cat, anime style Avoid: blurry"
    assert payload["size"] == "1536x1024"
    assert payload["n"] == 1
    assert "response_format" not in payload
    assert "seed" not in payload
    assert "steps" not in payload


def test_build_openai_images_payload_rejects_init_image() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    try:
        image_gen.build_openai_images_payload(
            "gpt-image-1", _cat_params(initImage="abc")
        )
    except image_gen.ImageGenError as exc:
        assert exc.status == 400
        assert exc.code == "unsupported_image_mode"
    else:
        raise AssertionError("expected ImageGenError")


def test_openai_edit_preserves_prompt_unless_style_set() -> None:
    import base64

    image_gen = load_service_module("backend/app/image_gen.py")
    raw = base64.b64encode(b"png-bytes").decode()
    fields, image = image_gen.build_openai_edit_fields(
        "gpt-image-1", _cat_params(initImage=raw)
    )
    assert fields["prompt"] == "a cat"
    assert "style" not in fields["prompt"]
    assert fields["input_fidelity"] == "high"
    assert image == b"png-bytes"

    styled, _ = image_gen.build_openai_edit_fields(
        "gpt-image-1", _cat_params(initImage=raw, stylePreset="anime")
    )
    assert styled["prompt"] == "a cat, anime style"
    assert styled["input_fidelity"] == "high"


def test_build_dall_e_payload_requests_b64() -> None:
    image_gen = load_service_module("backend/app/image_gen.py")
    payload = image_gen.build_openai_images_payload("dall-e-3", _cat_params())
    assert payload["response_format"] == "b64_json"
    assert payload["size"] == "1024x1024"


def _load_image_gen(providers: str | None):
    if providers is None:
        os.environ.pop("IMAGE_PROVIDERS", None)
    else:
        os.environ["IMAGE_PROVIDERS"] = providers
    return load_service_module("backend/app/image_gen.py")


class _Resp:
    def __init__(self, status_code: int, payload: dict) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self) -> dict:
        return self._payload


class _ClientPatch:
    def __init__(self, image_gen, post) -> None:
        self.image_gen = image_gen
        self.post = post
        self.original = image_gen.httpx.AsyncClient

    def __enter__(self):
        post = self.post

        class _Client:
            def __init__(self, *args, **kwargs) -> None:
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, url, json=None, headers=None, params=None):
                return await post(url, json=json, headers=headers, params=params)

        self.image_gen.httpx.AsyncClient = _Client
        return self

    def __exit__(self, *args):
        self.image_gen.httpx.AsyncClient = self.original
        return False


def test_local_sd_still_posts_a1111_txt2img() -> None:
    image_gen = _load_image_gen(None)
    captured: dict = {}

    async def post(url, json=None, headers=None, params=None):
        captured["url"] = url
        captured["json"] = json
        return _Resp(200, {"images": ["QUJD"]})

    with _ClientPatch(image_gen, post):
        b64 = asyncio.run(
            image_gen.generate_image_base64(_cat_params(), {"modelId": "local-sd"})
        )
    assert b64 == "QUJD"
    assert captured["url"].endswith("/sdapi/v1/txt2img")
    assert captured["json"]["prompt"] == "a cat"


def test_gpt_image_posts_generations_and_returns_b64() -> None:
    os.environ["OPENAI_PROVIDER_API_KEY"] = "test-key"
    image_gen = _load_image_gen(
        json.dumps(
            [
                {
                    "name": "openai",
                    "protocol": "openai_images",
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_PROVIDER_API_KEY",
                    "models": ["gpt-image-1"],
                }
            ]
        )
    )
    captured: dict = {}

    async def post(url, json=None, headers=None, params=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Resp(200, {"data": [{"b64_json": "aGVsbG8="}]})

    try:
        with _ClientPatch(image_gen, post):
            b64 = asyncio.run(
                image_gen.generate_image_base64(
                    _cat_params(width=512, height=512),
                    {"modelId": "gpt-image-1"},
                )
            )
    finally:
        os.environ.pop("OPENAI_PROVIDER_API_KEY", None)
        os.environ.pop("IMAGE_PROVIDERS", None)
    assert b64 == "aGVsbG8="
    assert captured["url"] == "https://api.openai.com/v1/images/generations"
    assert captured["json"]["model"] == "gpt-image-1"
    assert captured["json"]["size"] == "1024x1024"
    assert captured["json"]["prompt"] == "a cat"
    assert captured["headers"]["Authorization"] == "Bearer test-key"


def test_unknown_model_and_protocol_fail() -> None:
    image_gen = _load_image_gen(
        json.dumps(
            [
                {
                    "name": "bedrock",
                    "protocol": "bedrock",
                    "base_url": "https://bedrock.example",
                    "models": ["amazon.nova-canvas-v1:0"],
                }
            ]
        )
    )
    try:
        try:
            asyncio.run(
                image_gen.generate_image_base64(_cat_params(), {"modelId": "no-such"})
            )
        except image_gen.ImageGenError as exc:
            assert exc.status == 400
            assert exc.code == "unknown_image_model"
        else:
            raise AssertionError("expected unknown model")

        try:
            asyncio.run(
                image_gen.generate_image_base64(
                    _cat_params(), {"modelId": "amazon.nova-canvas-v1:0"}
                )
            )
        except image_gen.ImageGenError as exc:
            assert exc.status == 400
            assert exc.code == "unsupported_image_protocol"
            assert "bedrock" in str(exc)
            assert "_PROTOCOLS" in str(exc)
        else:
            raise AssertionError("expected unsupported protocol")
    finally:
        os.environ.pop("IMAGE_PROVIDERS", None)


def test_image_available_when_provider_registered_even_if_sd_down() -> None:
    image_gen = _load_image_gen(
        json.dumps(
            [
                {
                    "name": "openai",
                    "protocol": "openai_images",
                    "base_url": "https://api.openai.com/v1",
                    "models": ["gpt-image-1"],
                }
            ]
        )
    )

    async def down() -> bool:
        return False

    image_gen.is_sd_up = down
    try:
        assert asyncio.run(image_gen.is_image_available()) is True
    finally:
        os.environ.pop("IMAGE_PROVIDERS", None)

    image_gen = _load_image_gen(None)
    image_gen.is_sd_up = down
    assert asyncio.run(image_gen.is_image_available()) is False


def test_local_sd_connection_error_hides_operator_detail() -> None:
    image_gen = _load_image_gen(None)

    async def post(url, json=None, headers=None, params=None):
        raise image_gen.httpx.ConnectError("refused at http://host.docker.internal:7860")

    with _ClientPatch(image_gen, post):
        try:
            asyncio.run(
                image_gen.generate_image_base64(_cat_params(), {"modelId": "local-sd"})
            )
        except image_gen.ImageGenError as exc:
            assert exc.status == 502
            assert exc.code == "local_sd_unavailable"
            text = str(exc)
            assert "接続できません" in text
            assert "host.docker" not in text
            assert "mock-sd" not in text
            assert "7860" not in text
        else:
            raise AssertionError("expected ImageGenError")
