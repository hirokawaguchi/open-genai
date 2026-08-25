"""procedure-mcp の答え整形ヘルパ。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MCP_MAIN = ROOT / "procedure-mcp" / "app" / "main.py"


def _load_mcp_main():
    spec = importlib.util.spec_from_file_location("procedure_mcp_main", MCP_MAIN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ModuleNotFoundError as e:
        if e.name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
            pytest.skip("mcp package not installed")
        raise
    return mod


def test_parse_answers_json_and_empty() -> None:
    mod = _load_mcp_main()
    assert mod.parse_answers("") == {}
    assert mod.parse_answers('{"event":"転入"}') == {"event": "転入"}
    assert mod.parse_answers({"event": "転居"}) == {"event": "転居"}
    assert mod.parse_answers("転入") == "転入"


def test_strips_invoke_suffix() -> None:
    mod = _load_mcp_main()
    assert not mod.PATCHFORM_BASE_URL.endswith("/invoke")
