"""knowledge-mcp のタグ／クエリ整形ヘルパと、rag-app 機械向け tags API の単体寄り確認。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MCP_MAIN = ROOT / "knowledge-mcp" / "app" / "main.py"


def _load_mcp_main():
    spec = importlib.util.spec_from_file_location("knowledge_mcp_main", MCP_MAIN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # mcp 未インストール環境ではスキップ
    try:
        spec.loader.exec_module(mod)
    except ModuleNotFoundError as e:
        if e.name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
            pytest.skip("mcp package not installed")
        raise
    return mod


def test_parse_tags_variants():
    mod = _load_mcp_main()
    assert mod._parse_tags("議事録") == ["議事録"]
    assert mod._parse_tags("議事録,規程") == ["議事録", "規程"]
    assert mod._parse_tags('["議事録","規程"]') == ["議事録", "規程"]
    assert mod._parse_tags(["a", " b "]) == ["a", "b"]
    assert mod._parse_tags("") == []


def test_resolve_scope_default():
    mod = _load_mcp_main()
    assert mod._resolve_scope("") == mod.DEFAULT_SCOPE
    assert mod._resolve_scope("  team-1  ") == "team-1"


def test_citation_label_with_title_and_pages():
    mod = _load_mcp_main()
    label = mod._citation_label(
        {
            "source": "規程.pdf",
            "title": "第3章 運用",
            "page_start": 10,
            "page_end": 12,
        }
    )
    assert label == "規程.pdf / 第3章 運用 / p.10-12"


def test_citation_label_source_only():
    mod = _load_mcp_main()
    assert mod._citation_label({"source": "a.md", "title": "a.md"}) == "a.md"
