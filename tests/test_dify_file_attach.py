"""dify-app のファイル添付可否判定（features.file_attach）ヘルパ。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "dify-app" / "app" / "main.py"


def _load():
    # ホストに fastapi / httpx が無くてもヘルパを検証できるよう最小スタブを入れる
    if "fastapi" not in sys.modules:
        import types

        class _App:
            def __init__(self, *a, **k):
                pass

            def on_event(self, *a, **k):
                def deco(fn):
                    return fn

                return deco

            def get(self, *a, **k):
                def deco(fn):
                    return fn

                return deco

            def post(self, *a, **k):
                def deco(fn):
                    return fn

                return deco

        fastapi = types.ModuleType("fastapi")
        fastapi.FastAPI = _App  # type: ignore[attr-defined]
        fastapi.Header = lambda *a, **k: None  # type: ignore[attr-defined]
        fastapi.Request = object  # type: ignore[attr-defined]
        responses = types.ModuleType("fastapi.responses")
        responses.JSONResponse = dict  # type: ignore[attr-defined]
        sys.modules["fastapi"] = fastapi
        sys.modules["fastapi.responses"] = responses
    if "httpx" not in sys.modules:
        import types

        httpx = types.ModuleType("httpx")

        class _AsyncClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        httpx.AsyncClient = _AsyncClient  # type: ignore[attr-defined]
        sys.modules["httpx"] = httpx

    spec = importlib.util.spec_from_file_location("dify_app_main", MAIN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dify_app_main"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_config_flag_bool_and_string():
    mod = _load()
    assert mod._config_flag({}, "file_attach") is None
    assert mod._config_flag({"file_attach": True}, "file_attach") is True
    assert mod._config_flag({"file_attach": False}, "file_attach") is False
    assert mod._config_flag({"file_attach": "true"}, "file_attach") is True
    assert mod._config_flag({"file_attach": "off"}, "file_attach") is False
    # 解釈不能な値は None（未指定扱い）
    assert mod._config_flag({"file_attach": "maybe"}, "file_attach") is None


def test_file_attach_enabled_via_file_upload():
    mod = _load()
    params = {"user_input_form": [], "file_upload": {"enabled": True}}
    assert mod._file_attach_supported(params, {}) is True


def test_file_attach_enabled_via_file_input_variable():
    mod = _load()
    params = {
        "user_input_form": [
            {"file-list": {"variable": "upload_files", "type": "file-list"}}
        ],
        "file_upload": {"enabled": False},
    }
    assert mod._file_attach_supported(params, {}) is True


def test_file_attach_enabled_via_config_file_var():
    mod = _load()
    params = {"user_input_form": [], "file_upload": {"enabled": False}}
    assert mod._file_attach_supported(params, {"file_var": "docs"}) is True


def test_file_attach_config_false_overrides_params():
    mod = _load()
    # /parameters 上は添付可能でも、config.file_attach=false なら強制 OFF
    params = {"user_input_form": [], "file_upload": {"enabled": True}}
    assert mod._file_attach_supported(params, {"file_attach": False}) is False


def test_file_attach_disabled_for_knowledge_agent_shape():
    mod = _load()
    # ナレッジ検索エージェント相当: file_upload 無効・file 入力変数なし
    params = {
        "user_input_form": [
            {"text-input": {"variable": "scope", "type": "text-input"}}
        ],
        "file_upload": {"enabled": False},
    }
    assert mod._file_attach_supported(params, {}) is False


def test_file_attach_fail_closed_on_empty_params():
    mod = _load()
    # /parameters 取得失敗時（空 dict）は config の明示指定が無ければ False
    assert mod._file_attach_supported({}, {}) is False
    # 取得失敗でも config.file_attach=true は尊重
    assert mod._file_attach_supported({}, {"file_attach": True}) is True
