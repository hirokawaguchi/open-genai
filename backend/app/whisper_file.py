"""ファイル文字起こしの方式。クラウドは棟が明示したときだけ。"""

from __future__ import annotations

from typing import Any

CLOUD = "cloud"
LOCAL = "local"


def file_engine(inputs: dict[str, Any] | None) -> str:
    """送られてきた方式。クラウド以外はローカル。"""
    if not isinstance(inputs, dict):
        return LOCAL
    raw = str(inputs.get("engine") or "").strip()
    if raw == CLOUD:
        return CLOUD
    return LOCAL


def cloud_allowed(features: dict[str, Any] | None, api_key: str | None) -> bool:
    """未設定は不可。キーが true で、OpenAI のキーがあるときだけ可。"""
    if not api_key:
        return False
    if not isinstance(features, dict):
        return False
    return features.get("whisper-cloud") is True
