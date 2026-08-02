"""ユーザ向けエラー分類の単体テスト。"""

from __future__ import annotations

import unittest

from app.errors import (
    ERROR_MESSAGES,
    AppInvokeError,
    classify_provider_error,
    error_body,
    normalize_error_payload,
)


class ClassifyProviderErrorTest(unittest.TestCase):
    def test_rate_limit_hides_model_and_region(self) -> None:
        raw = (
            "[models] Rate Limit Error, Error code: 429 - "
            "{'error': {'message': 'Your requests to gpt-4.1 for gpt-4.1 in eastus "
            "have exceeded rate limit.', 'type': 'too_many_requests', "
            "'param': None, 'code': 'rate_limit_exceeded'}}"
        )
        err = classify_provider_error(raw)
        self.assertEqual(err.code, "RATE_LIMIT")
        self.assertEqual(err.message, ERROR_MESSAGES["RATE_LIMIT"])
        self.assertNotIn("gpt-4.1", err.message)
        self.assertNotIn("eastus", err.message)
        self.assertNotIn("rate_limit_exceeded", err.message)
        self.assertNotIn("{", err.message)
        # 生 detail は保持するがユーザ向け message とは分離
        self.assertIn("gpt-4.1", err.detail)

    def test_http_status_429(self) -> None:
        err = classify_provider_error("upstream busy", http_status=429)
        self.assertEqual(err.code, "RATE_LIMIT")

    def test_unknown_falls_back_to_fixed_workflow_error(self) -> None:
        raw = "Internal failure involving deployment gpt-4.1 in eastus"
        err = classify_provider_error(raw)
        self.assertEqual(err.code, "WORKFLOW_ERROR")
        self.assertEqual(err.message, ERROR_MESSAGES["WORKFLOW_ERROR"])
        self.assertNotIn("gpt-4.1", err.message)
        self.assertNotIn("eastus", err.message)

    def test_error_body_has_no_detail_field(self) -> None:
        exc = AppInvokeError("RATE_LIMIT", detail="secret gpt-4.1 eastus")
        body = error_body(exc)
        self.assertEqual(body["error"], ERROR_MESSAGES["RATE_LIMIT"])
        self.assertEqual(body["error_code"], "RATE_LIMIT")
        self.assertNotIn("detail", body)
        self.assertNotIn("gpt-4.1", body["error"])
        self.assertNotIn("eastus", body["error"])

    def test_normalize_error_payload_rejects_unknown_code(self) -> None:
        status, message, code = normalize_error_payload("NOT_A_CODE")
        self.assertEqual(code, "WORKFLOW_ERROR")
        self.assertEqual(message, ERROR_MESSAGES["WORKFLOW_ERROR"])
        self.assertEqual(status, 502)

    def test_context_too_large_hides_model_and_counts(self) -> None:
        raw = (
            'PluginInvokeError: {"args": {"description": "[models] Error: API request '
            'failed with status code 400: {\\"error\\": {\\"message\\": '
            '\\"Input length (169907) exceeds model\'s maximum context length (131072).\\", '
            '\\"type\\": \\"BadRequestError\\"}, \\"model\\": \\"gpt-oss-120b\\"}"}}'
        )
        err = classify_provider_error(raw)
        self.assertEqual(err.code, "CONTEXT_TOO_LARGE")
        self.assertEqual(err.message, ERROR_MESSAGES["CONTEXT_TOO_LARGE"])
        self.assertEqual(err.status, 413)
        self.assertNotIn("gpt-oss-120b", err.message)
        self.assertNotIn("169907", err.message)
        self.assertNotIn("131072", err.message)


if __name__ == "__main__":
    unittest.main()
