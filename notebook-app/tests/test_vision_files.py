from app import extract, vision


def test_image_names_are_accepted():
    assert extract.is_image_name("図.png")
    assert extract.allowed_name("図.png")
    assert not extract.is_image_name("原稿.md")


def test_vision_off_skips_description(monkeypatch):
    monkeypatch.setenv("NOTEBOOK_VISION_MODEL", "off")
    assert vision.enabled() is False
    assert vision.description_name("画像-手続き.png") == "画像-手続き-説明.md"
