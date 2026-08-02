"""エンドユーザ向けエラー分類。

プロバイダ（Dify / Azure OpenAI 等）の生メッセージはログ専用とし、
API レスポンスには固定の日本語メッセージと error_code のみを返す。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

ERROR_MESSAGES: dict[str, str] = {
    "RATE_LIMIT": (
        "現在リクエストが集中しています。"
        "しばらく時間をおいてから再度お試しください。"
    ),
    "UPLOAD_FAILED": (
        "ファイルのアップロードに失敗しました。"
        "形式・サイズを確認してから再度お試しください。"
    ),
    "CONNECTION": (
        "サービスに接続できませんでした。時間をおいて再度お試しください。"
    ),
    "INVALID_INPUT": "入力内容を確認してから再度お試しください。",
    "CONTEXT_TOO_LARGE": (
        "入力内容が大きすぎて処理できませんでした。"
        "指示を具体にするか、対象範囲を絞って再度お試しください。"
    ),
    "WORKFLOW_ERROR": (
        "処理中にエラーが発生しました。時間をおいて再度お試しください。"
        "解消しない場合は管理者にお問い合わせください。"
    ),
}

ERROR_STATUS: dict[str, int] = {
    "RATE_LIMIT": 429,
    "UPLOAD_FAILED": 502,
    "CONNECTION": 502,
    "INVALID_INPUT": 400,
    "CONTEXT_TOO_LARGE": 413,
    "WORKFLOW_ERROR": 502,
}


class AppInvokeError(Exception):
    """ユーザ向け固定文言を持つ invoke エラー。"""

    def __init__(self, code: str, detail: str = "") -> None:
        if code not in ERROR_MESSAGES:
            code = "WORKFLOW_ERROR"
        self.code = code
        self.message = ERROR_MESSAGES[code]
        self.status = ERROR_STATUS[code]
        self.detail = detail or ""
        super().__init__(self.message)


def classify_provider_error(
    raw: str,
    *,
    default_code: str = "WORKFLOW_ERROR",
    http_status: int | None = None,
) -> AppInvokeError:
    """生エラー文字列と HTTP status を分類し、固定文言の AppInvokeError を返す。

    判定順:
      1. レート制限（status 429 または本文の rate limit 表現）→ RATE_LIMIT
      2. コンテキスト超過（status 413 または本文の context length 表現）→ CONTEXT_TOO_LARGE
      3. その他 4xx → INVALID_INPUT（クライアント起因。接続失敗と混同しない）
      4. 5xx → CONNECTION（サーバ/接続側の問題。default より優先）
      5. status 不明・その他 → default_code（フォールバック）
    """
    text = (raw or "").lower()
    # 1. レート制限
    if http_status == 429 or (
        "429" in (raw or "")
        or "rate_limit" in text
        or "too_many_requests" in text
        or "rate limit" in text
    ):
        return AppInvokeError("RATE_LIMIT", detail=raw)
    # 2. コンテキスト超過（413 または本文表現）
    if http_status == 413 or (
        "context length" in text
        or "maximum context" in text
        or "exceeds model" in text
        or ("input length" in text and "exceed" in text)
        or "context_length_exceeded" in text
        or "string_above_max_length" in text
    ):
        return AppInvokeError("CONTEXT_TOO_LARGE", detail=raw)
    # 3. その他 4xx は入力不備として扱う（「接続できない」と誤表示しない）
    if http_status is not None and 400 <= http_status < 500:
        return AppInvokeError("INVALID_INPUT", detail=raw)
    # 4. 5xx はサーバ/接続側の問題として扱う
    if http_status is not None and 500 <= http_status < 600:
        return AppInvokeError("CONNECTION", detail=raw)
    # 5. status 不明・その他は呼び出し側の default にフォールバック
    if default_code not in ERROR_MESSAGES:
        default_code = "WORKFLOW_ERROR"
    return AppInvokeError(default_code, detail=raw)


def error_body(exc: AppInvokeError) -> dict[str, str]:
    """ユーザ向けレスポンス本文（detail は含めない）。"""
    logger.error("dify-app invoke error code=%s detail=%s", exc.code, exc.detail)
    return {"error": exc.message, "error_code": exc.code}


def error_response(exc: AppInvokeError) -> Any:
    """ユーザ向け JSONResponse を生成し、生 detail はログにだけ残す。"""
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=exc.status, content=error_body(exc))


def normalize_error_payload(
    error_code: Any,
    *,
    http_status: int | None = None,
) -> tuple[int, str, str]:
    """既知 code のみ信頼し、(status, message, code) を返す。"""
    code = str(error_code or "")
    if http_status == 429:
        code = "RATE_LIMIT"
    if code not in ERROR_MESSAGES:
        code = "WORKFLOW_ERROR"
    return ERROR_STATUS[code], ERROR_MESSAGES[code], code
