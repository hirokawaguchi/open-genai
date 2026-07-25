from __future__ import annotations

import asyncio

import pytest

from conftest import load_service_module


@pytest.fixture()
def docstore(tmp_path, monkeypatch: pytest.MonkeyPatch):
    mod = load_service_module("rag-app/app/docstore.py")
    db = tmp_path / "rag_meta.db"
    monkeypatch.setattr(mod, "DB_PATH", str(db))
    mod.init_db()
    return mod


@pytest.fixture()
def tree_builder(monkeypatch: pytest.MonkeyPatch):
    mod = load_service_module("rag-app/app/tree_builder.py")
    monkeypatch.setattr(mod, "TREE_USE_LLM_SUMMARY", False)
    return mod


def test_docstore_upsert_and_toc(docstore) -> None:
    pages = [
        {"page": 1, "text": "議題1 開会"},
        {"page": 2, "text": "議題2 予算案について議論した。"},
    ]
    nodes = [
        {
            "node_id": "root",
            "title": "文書全体",
            "summary": "議事録",
            "page_start": 1,
            "page_end": 2,
            "parent_id": None,
            "sort_order": 0,
        },
        {
            "node_id": "n1",
            "title": "議題2 予算案",
            "summary": "予算の議論",
            "page_start": 2,
            "page_end": 2,
            "parent_id": "root",
            "sort_order": 1,
        },
    ]
    doc_id = docstore.upsert_document(
        scope="team-a",
        source="minutes.md",
        pages=pages,
        nodes=nodes,
        tags=["議事録"],
        truncated=False,
        index_kind="tree",
    )
    docs = docstore.list_docs("team-a", ["議事録"])
    assert len(docs) == 1
    assert docs[0]["doc_id"] == doc_id
    assert docs[0]["truncated"] is False
    assert docs[0]["index_kind"] == "tree"

    toc = docstore.get_toc(doc_id)
    assert {n["node_id"] for n in toc} == {"root", "n1"}

    bodies = docstore.get_nodes_with_text(doc_id, ["n1"])
    assert len(bodies) == 1
    assert "予算案" in bodies[0]["text"]


def test_docstore_fulltext_kind(docstore) -> None:
    pages = [{"page": 1, "text": "全文A"}, {"page": 2, "text": "全文B"}]
    doc_id = docstore.upsert_document(
        scope="s",
        source="note.txt",
        pages=pages,
        nodes=[],
        tags=["メモ"],
        index_kind="fulltext",
    )
    d = docstore.get_doc(doc_id)
    assert d is not None
    assert d["index_kind"] == "fulltext"
    assert d["char_count"] == len("全文A") + len("全文B")
    all_pages = docstore.get_all_pages(doc_id)
    assert [p["text"] for p in all_pages] == ["全文A", "全文B"]


def test_decide_retrieval_mode() -> None:
    # retrieve.py は相対 import があるため、判定ロジックだけを複製せず
    # モジュールをパッケージ経由で読む。失敗時はスキップ相当にしないで明示 fail。
    # conftest が backend を path に入れるため、app は backend.app と衝突しうる。
    # rag-app を最前列にし、backend の app が既に載っていれば取り除く。
    import importlib
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    rag_app = str(root / "rag-app")
    backend = str(root / "backend")
    sys.path = [p for p in sys.path if p != backend]
    if rag_app in sys.path:
        sys.path.remove(rag_app)
    sys.path.insert(0, rag_app)
    sys.modules.pop("app", None)
    sys.modules.pop("app.retrieve", None)
    retrieve = importlib.import_module("app.retrieve")

    small = [{"index_kind": "fulltext", "char_count": 100, "tags": ["a"]}]
    mode, meta = retrieve.decide_retrieval_mode(small)
    assert mode == "full"
    assert meta["reason"] == "fits_context"

    trees = [
        {"index_kind": "tree", "char_count": 100_000, "tags": ["a"]},
        {"index_kind": "tree", "char_count": 100_000, "tags": ["a"]},
    ]
    mode, meta = retrieve.decide_retrieval_mode(trees, budget=1000)
    assert mode == "hybrid"
    assert meta["reason"] == "all_structured"

    mixed = [
        {"index_kind": "tree", "char_count": 100_000, "tags": ["a"]},
        {"index_kind": "fulltext", "char_count": 100_000, "tags": ["a"]},
    ]
    mode, meta = retrieve.decide_retrieval_mode(mixed, budget=1000)
    assert mode == "vector"
    assert meta["reason"] == "has_unstructured_or_oversized"

    mode, _ = retrieve.decide_retrieval_mode(
        [{"index_kind": "tree", "char_count": 10, "tags": ["a"]}],
        legacy_count=1,
        budget=1000,
    )
    assert mode == "vector"


def test_resolve_source_filter_normalizes(docstore) -> None:
    import importlib
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    rag_app = str(root / "rag-app")
    backend = str(root / "backend")
    sys.path = [p for p in sys.path if p != backend]
    if rag_app in sys.path:
        sys.path.remove(rag_app)
    sys.path.insert(0, rag_app)
    sys.modules.pop("app", None)
    sys.modules.pop("app.retrieve", None)
    sys.modules.pop("app.docstore", None)

    retrieve = importlib.import_module("app.retrieve")
    # retrieve が参照する docstore をテスト用 DB に差し替え
    retrieve.docstore = docstore

    scope = "scope-a"
    doc_id = docstore.upsert_document(
        scope=scope,
        source="policy.md",
        pages=[{"page": 1, "text": "本文"}],
        nodes=[
            {
                "node_id": "n1",
                "title": "条",
                "summary": "",
                "page_start": 1,
                "page_end": 1,
                "parent_id": None,
                "sort_order": 0,
            }
        ],
        tags=["規程"],
        index_kind="tree",
    )
    did, src, doc = retrieve._resolve_source_filter(scope, None, "policy.md")
    assert did == doc_id
    assert src == "policy.md"
    assert doc is not None

    did2, src2, _ = retrieve._resolve_source_filter(scope, doc_id, None)
    assert did2 == doc_id
    assert src2 == "policy.md"


def test_docstore_replace_same_source(docstore) -> None:
    pages1 = [{"page": 1, "text": "old"}]
    nodes1 = [
        {
            "node_id": "n1",
            "title": "old",
            "summary": "old",
            "page_start": 1,
            "page_end": 1,
            "parent_id": None,
            "sort_order": 0,
        }
    ]
    doc_id1 = docstore.upsert_document(
        scope="s", source="a.txt", pages=pages1, nodes=nodes1
    )
    pages2 = [{"page": 1, "text": "new content"}]
    nodes2 = [
        {
            "node_id": "n1",
            "title": "new",
            "summary": "new",
            "page_start": 1,
            "page_end": 1,
            "parent_id": None,
            "sort_order": 0,
        }
    ]
    doc_id2 = docstore.upsert_document(
        scope="s", source="a.txt", pages=pages2, nodes=nodes2
    )
    assert doc_id1 == doc_id2
    assert docstore.get_nodes_with_text(doc_id2, ["n1"])[0]["text"] == "new content"


def test_tree_builder_from_markdown(tree_builder) -> None:
    text = (
        "# 第1章 総則\n\nこの規程の目的を定める。\n\n"
        "## 第1条 目的\n\n本規程は業務の適正化を図る。\n\n"
        "## 第2条 定義\n\n用語の定義を行う。\n"
    )
    pages = [{"page": 1, "text": text}]
    nodes = asyncio.run(tree_builder.build_tree_nodes(pages))
    titles = [n["title"] for n in nodes]
    assert "第1章 総則" in titles
    assert "第1条 目的" in titles
    assert "第2条 定義" in titles
    # 条は章の子
    by_title = {n["title"]: n for n in nodes}
    parent = by_title["第1章 総則"]["node_id"]
    assert by_title["第1条 目的"]["parent_id"] == parent


def test_tree_builder_from_pages(tree_builder) -> None:
    pages = [
        {"page": 1, "text": "短い"},
        {"page": 2, "text": "これは十分に長いページ本文です。" * 5},
        {"page": 3, "text": "最終ページの議題まとめ。"},
    ]
    nodes = asyncio.run(tree_builder.build_tree_nodes(pages))
    assert any(n["node_id"] == "root" for n in nodes)
    assert len(nodes) >= 2
