"""外部 Word 変換 API 連携。

参照実装（procureTechMarkdownEditor）と同じ契約:

- POST `{EDITOR_CONVERT_URL}/api/convert-markdown`
  multipart: `file`=(`<project>.zip`, zip バイト列, application/zip)
  form: `username`, `allow_specification`, `allow_rfi`, `allow_quotation`,
        `allow_primaryexam`（"true"/"false"）
  応答: JSON（`request_id` を含む）

- GET `{EDITOR_CONVERT_URL}/api/conversion-status/{request_id}`
  応答: JSON（`status`, 成功時は `nextcloud_path` 等）

`EDITOR_CONVERT_URL` 未設定なら無効（`is_configured()` が False）。
"""

from __future__ import annotations

import os

import httpx

EDITOR_CONVERT_URL = os.environ.get("EDITOR_CONVERT_URL", "").rstrip("/")
TIMEOUT = float(os.environ.get("EDITOR_CONVERT_TIMEOUT", "120"))

# 変換対象の種別フラグ（フロントからの options キーと 1:1 対応）
OPTION_KEYS = (
    "allow_specification",
    "allow_rfi",
    "allow_quotation",
    "allow_primaryexam",
)


class ConvertError(RuntimeError):
    """利用者に提示してよい変換エラー。"""


def is_configured() -> bool:
    return bool(EDITOR_CONVERT_URL)


def _bool_str(v: object) -> str:
    return "true" if bool(v) else "false"


async def start_conversion(
    zip_bytes: bytes,
    *,
    project_name: str,
    username: str,
    options: dict[str, bool] | None = None,
) -> dict:
    """zip を送信して変換を開始し、応答 JSON（request_id 等）を返す。"""
    if not is_configured():
        raise ConvertError("Word 変換 API が未設定です（EDITOR_CONVERT_URL）。")
    opts = options or {}
    data = {"username": username or "user"}
    for key in OPTION_KEYS:
        data[key] = _bool_str(opts.get(key, True))
    files = {"file": (f"{project_name}.zip", zip_bytes, "application/zip")}
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.post(
                f"{EDITOR_CONVERT_URL}/api/convert-markdown", files=files, data=data
            )
        except httpx.HTTPError as e:
            raise ConvertError(f"外部サービスとの通信に失敗しました: {e}") from e
    if res.status_code != 200:
        try:
            msg = res.json().get("error") or "外部 API へのリクエストに失敗しました"
        except Exception:  # noqa: BLE001
            msg = "外部 API へのリクエストに失敗しました"
        raise ConvertError(msg)
    return res.json()


async def get_status(request_id: str) -> dict:
    """変換ステータスを取得して JSON を返す。"""
    if not is_configured():
        raise ConvertError("Word 変換 API が未設定です（EDITOR_CONVERT_URL）。")
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            res = await client.get(
                f"{EDITOR_CONVERT_URL}/api/conversion-status/{request_id}"
            )
        except httpx.HTTPError as e:
            raise ConvertError(f"外部サービスとの通信に失敗しました: {e}") from e
    if res.status_code != 200:
        raise ConvertError("変換状況の確認に失敗しました。")
    return res.json()
