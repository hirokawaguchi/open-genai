"""dify-app の citation 抽出ヘルパ。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "dify-app" / "app" / "main.py"


def _load():
    # ホストに fastapi が無くてもヘルパを検証できるよう最小スタブを入れる
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
        responses.StreamingResponse = object  # type: ignore[attr-defined]
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

    # main.py の同ディレクトリ相対 import フォールバック用
    app_dir = str(MAIN.parent)
    if app_dir not in sys.path:
        sys.path.insert(0, app_dir)

    spec = importlib.util.spec_from_file_location("dify_app_main", MAIN)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["dify_app_main"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_citations_from_knowledge_search_json():
    mod = _load()
    payload = {
        "nodes": [
            {"ref": 2, "source": "spec.md", "text": "本文A"},
            {"ref": 3, "source": "spec.md", "text": "本文B"},
        ],
        "citation_artifacts": [
            {
                "display_name": "[2] spec.md",
                "text": "本文A",
                "mime_type": "text/x.open-genai.citation",
            }
        ],
    }
    arts = mod._citations_from_knowledge_search_payload(payload)
    assert len(arts) == 1
    assert arts[0]["display_name"] == "[2] spec.md"
    assert arts[0]["text"] == "本文A"
    assert arts[0]["mime_type"] == mod.CITATION_MIME


def test_citations_from_observation_string_with_prefix():
    mod = _load()
    obs = 'tool result:\n{"citation_artifacts":[{"display_name":"[1] a.md","text":"hello"}]}'
    arts = mod._citations_from_knowledge_search_payload(obs)
    assert len(arts) == 1
    assert arts[0]["display_name"] == "[1] a.md"


def test_citations_from_nodes_fallback():
    mod = _load()
    arts = mod._citations_from_knowledge_search_payload(
        {"nodes": [{"ref": 1, "source": "x.md", "text": "body"}]}
    )
    assert arts[0]["display_name"] == "[1] x.md"
    assert arts[0]["text"] == "body"


def test_citations_from_nodes_with_title_and_pages():
    mod = _load()
    arts = mod._citations_from_knowledge_search_payload(
        {
            "nodes": [
                {
                    "ref": 2,
                    "source": "規程.pdf",
                    "title": "第3章 運用",
                    "page_start": 10,
                    "page_end": 12,
                    "text": "節本文",
                }
            ]
        }
    )
    assert arts[0]["display_name"] == "[2] 規程.pdf / 第3章 運用 / p.10-12"


def test_scavenge_citations_from_agent_log_shape():
    mod = _load()
    payload = {
        "label": "CALL knowledge_search",
        "status": "success",
        "data": {
            "output": {
                "tool_call_name": "knowledge_search",
                "tool_response": (
                    'tool response: {"citation_artifacts":'
                    '[{"display_name":"[2] 04_shiyousho.pdf","text":"要件本文"}]}.'
                ),
            }
        },
    }
    out: list = []
    mod._scavenge_citations(payload, out)
    assert len(out) == 1
    assert out[0]["display_name"] == "[2] 04_shiyousho.pdf"
    assert "要件本文" in out[0]["text"]


def test_citations_from_tool_response_with_trailing_garbage():
    """実 Dify で見られた tool_response 末尾ゴミ付き形式。"""
    mod = _load()
    raw = (
        'tool response: {"citation_artifacts":[{"display_name":"[1] a.md",'
        '"text":"hello","mime_type":"text/x.open-genai.citation"}],'
        '"hit_count":1}\', stream=False).'
    )
    arts = mod._citations_from_knowledge_search_payload(raw)
    assert len(arts) == 1
    assert arts[0]["display_name"] == "[1] a.md"
    assert arts[0]["text"] == "hello"


def test_filter_citations_cited_in_answer():
    mod = _load()
    arts = [
        {"display_name": "[1] a.md", "text": "a", "mime_type": mod.CITATION_MIME},
        {"display_name": "[2] b.pdf", "text": "b", "mime_type": mod.CITATION_MIME},
        {"display_name": "[3] c.url", "text": "c", "mime_type": mod.CITATION_MIME},
    ]
    kept = mod._filter_citations_cited_in_answer("要点は次のとおりです[2]。", arts)
    assert [a["display_name"] for a in kept] == ["[2] b.pdf"]
    # 本文に参照が無いときは全部残す
    assert mod._filter_citations_cited_in_answer("参照なし", arts) == arts
