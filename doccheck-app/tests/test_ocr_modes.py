"""OCR モード分岐（ppocr / fallback / always）と不正値正規化のテスト。

Vision / PP-OCR の実 HTTP は呼ばず、エンジン関数を差し替えて
「どのモードで Vision を呼ぶ／呼ばない」「主候補と Vision 候補の格納」を検証する。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DOCCHECK_OCR_ENGINE", "hybrid")

from app import ocr, store  # noqa: E402

_DUMMY = Path("dummy.png")


class _Spy:
    def __init__(self) -> None:
        self.pp_calls = 0
        self.vision_calls = 0
        self.pp_result = ("PP", 0.9)
        self.vision_result = ("VIS", 0.55)

    def install(self) -> None:
        ocr.ENGINE = "hybrid"

        def fake_pp(path, prefer_official=True):  # noqa: ANN001, ARG001
            self.pp_calls += 1
            return self.pp_result

        def fake_vision(path, *, field_type="text", is_handwriting=True):  # noqa: ANN001, ARG001
            self.vision_calls += 1
            return self.vision_result

        ocr._ocr_ppocr = fake_pp  # type: ignore[assignment]
        ocr._ocr_vision = fake_vision  # type: ignore[assignment]


def test_ppocr_mode_never_calls_vision() -> None:
    spy = _Spy()
    spy.install()
    res = ocr.run_ocr_ex(_DUMMY, ocr_mode="ppocr")
    assert spy.vision_calls == 0
    assert res["text"] == "PP"
    assert res["vision_text"] == ""


def test_fallback_high_conf_skips_vision() -> None:
    spy = _Spy()
    spy.pp_result = ("PP", 0.9)
    spy.install()
    res = ocr.run_ocr_ex(_DUMMY, ocr_mode="fallback")
    assert spy.vision_calls == 0
    assert res["text"] == "PP"
    assert res["vision_text"] == ""


def test_fallback_low_conf_folds_vision_into_main() -> None:
    spy = _Spy()
    spy.pp_result = ("pp", 0.2)
    spy.install()
    res = ocr.run_ocr_ex(_DUMMY, ocr_mode="fallback")
    assert spy.vision_calls == 1
    # 低信頼なので主候補は Vision に昇格。fallback では別候補には出さない
    assert res["text"] == "VIS"
    assert res["vision_text"] == ""


def test_always_runs_both_and_keeps_pp_as_main() -> None:
    spy = _Spy()
    spy.pp_result = ("PP", 0.9)
    spy.install()
    res = ocr.run_ocr_ex(_DUMMY, ocr_mode="always")
    assert spy.pp_calls == 1
    assert spy.vision_calls == 1
    assert res["text"] == "PP"
    assert res["vision_text"] == "VIS"


def test_always_promotes_vision_when_pp_empty() -> None:
    spy = _Spy()
    spy.pp_result = ("", 0.0)
    spy.install()
    res = ocr.run_ocr_ex(_DUMMY, ocr_mode="always")
    assert res["text"] == "VIS"
    assert res["vision_text"] == "VIS"


def test_skip_vision_disables_vision_even_in_always() -> None:
    spy = _Spy()
    spy.pp_result = ("PP", 0.9)
    spy.install()
    res = ocr.run_ocr_ex(_DUMMY, ocr_mode="always", skip_vision=True)
    assert spy.vision_calls == 0
    assert res["vision_text"] == ""


def test_invalid_mode_falls_back() -> None:
    spy = _Spy()
    spy.pp_result = ("PP", 0.9)
    spy.install()
    res = ocr.run_ocr_ex(_DUMMY, ocr_mode="bogus")
    # 不正値は fallback 扱い（高信頼なので Vision は呼ばない）
    assert spy.vision_calls == 0
    assert res["text"] == "PP"


def test_normalize_ocr_mode() -> None:
    assert store.normalize_ocr_mode("always") == "always"
    assert store.normalize_ocr_mode("PPOCR") == "ppocr"
    assert store.normalize_ocr_mode("") == "fallback"
    assert store.normalize_ocr_mode(None) == "fallback"
    assert store.normalize_ocr_mode("bogus") == "fallback"


if __name__ == "__main__":
    test_ppocr_mode_never_calls_vision()
    test_fallback_high_conf_skips_vision()
    test_fallback_low_conf_folds_vision_into_main()
    test_always_runs_both_and_keeps_pp_as_main()
    test_always_promotes_vision_when_pp_empty()
    test_skip_vision_disables_vision_even_in_always()
    test_invalid_mode_falls_back()
    test_normalize_ocr_mode()
    print("ok")
