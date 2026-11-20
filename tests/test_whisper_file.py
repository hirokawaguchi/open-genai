"""ファイル文字起こしの方式判定。"""

from app.whisper_file import cloud_allowed, file_engine


def test_missing_engine_stays_local() -> None:
    assert file_engine({}) == "local"
    assert file_engine({"engine": "live"}) == "local"


def test_cloud_engine_is_explicit() -> None:
    assert file_engine({"engine": "cloud"}) == "cloud"


def test_cloud_requires_explicit_flag_and_key() -> None:
    assert cloud_allowed(None, "sk-test") is False
    assert cloud_allowed({}, "sk-test") is False
    assert cloud_allowed({"whisper-cloud": False}, "sk-test") is False
    assert cloud_allowed({"whisper-cloud": True}, None) is False
    assert cloud_allowed({"whisper-cloud": True}, "sk-test") is True
