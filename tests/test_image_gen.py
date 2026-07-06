from __future__ import annotations

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
