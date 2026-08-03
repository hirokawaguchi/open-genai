"""共通 Retrieval ファサード（mode=auto|full|vector|tree|hybrid）。

UI の /invoke と機械向け /retrieve API の両方から利用する。
戻り値は節／チャンクの正規化リスト:
  {
    "nodes": [{id, title, text, source, doc_id?, pages?, score?, mode}],
    "trace": [...],
  }

mode=auto の選択方針:
  1. タグ付き候補の全文合計がコンテキスト予算内 → full
  2. 候補がすべて構造化 (index_kind=tree) → hybrid
  3. それ以外（非構造化を含む）→ vector
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from . import docstore, embeddings, vectorstore

# 1階層で二段化に切り替えるノード数
TREE_STAGE1_THRESHOLD = int(os.environ.get("TREE_STAGE1_THRESHOLD", "20"))
TREE_STAGE1_KEEP = int(os.environ.get("TREE_STAGE1_KEEP", "8"))
TREE_STAGE2_KEEP = int(os.environ.get("TREE_STAGE2_KEEP", "3"))
TREE_MAX_HOPS = int(os.environ.get("TREE_MAX_HOPS", "3"))
# 全文投入モードの文字数予算（プロンプト全体の余裕を見込んだ値）
FULL_CONTEXT_CHARS = int(os.environ.get("RAG_FULL_CONTEXT_CHARS", "24000"))


def _is_structured(doc: dict[str, Any]) -> bool:
    return (doc.get("index_kind") or "tree") == "tree"


def _tagged_docs(scope: str, tags: list[str] | None = None) -> list[dict[str, Any]]:
    return [
        d
        for d in docstore.list_docs(scope, tags)
        if not d.get("truncated") and (d.get("tags") or [])
    ]


def decide_retrieval_mode(
    docs: list[dict[str, Any]],
    *,
    legacy_count: int = 0,
    has_vector_candidates: bool = False,
    budget: int | None = None,
) -> tuple[str, dict[str, Any]]:
    """候補文書の状態から full / hybrid / vector を決める（純関数）。"""
    budget = FULL_CONTEXT_CHARS if budget is None else budget
    meta: dict[str, Any] = {
        "doc_count": len(docs),
        "legacy_count": legacy_count,
        "char_count": sum(int(d.get("char_count") or 0) for d in docs),
        "budget": budget,
    }

    if not docs and not has_vector_candidates:
        return "vector", {**meta, "reason": "no_candidates"}

    # 全文モード: docstore に全文があり、ベクトルのみのレガシーが無く、予算内
    if (
        docs
        and legacy_count == 0
        and all(int(d.get("char_count") or 0) > 0 for d in docs)
        and meta["char_count"] <= budget
    ):
        return "full", {**meta, "reason": "fits_context"}

    if docs and legacy_count == 0 and all(_is_structured(d) for d in docs):
        return "hybrid", {**meta, "reason": "all_structured"}

    return "vector", {**meta, "reason": "has_unstructured_or_oversized"}


async def resolve_retrieval_mode(
    scope: str, tags: list[str] | None = None
) -> tuple[str, dict[str, Any]]:
    """候補文書の状態から full / hybrid / vector を決める。"""
    docs = _tagged_docs(scope, tags)
    sources = await vectorstore.list_sources(scope, tags=tags)
    tagged_sources = [s for s in sources if s.get("tags")]
    doc_sources = {d["source"] for d in docs}
    legacy_count = sum(1 for s in tagged_sources if s["source"] not in doc_sources)
    return decide_retrieval_mode(
        docs,
        legacy_count=legacy_count,
        has_vector_candidates=bool(tagged_sources),
    )


def _parse_json_obj(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    # ```json ... ``` を許容
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        # 先頭 { から末尾 } までを拾う
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                return obj if isinstance(obj, dict) else None
            except json.JSONDecodeError:
                return None
    return None


def _keyword_score(query: str, title: str, summary: str) -> float:
    q = set(re.findall(r"[\w一-龥ぁ-んァ-ン]+", query.lower()))
    if not q:
        return 0.0
    blob = f"{title} {summary}".lower()
    hit = sum(1 for t in q if t in blob)
    return hit / max(len(q), 1)


async def _llm_select_nodes(
    question: str,
    candidates: list[dict[str, Any]],
    *,
    keep: int,
    stage: str,
) -> tuple[list[str], dict[str, Any]]:
    """候補ノードから関連 node_id を選ばせる。失敗時はキーワードフォールバック。"""
    lines = []
    for c in candidates:
        lines.append(
            f"- id={c['node_id']} | {c.get('title', '')} | {c.get('summary', '')}"
        )
    catalog = "\n".join(lines)
    prompt = (
        f"あなたは文書の目次から関連箇所を選ぶアシスタントです（{stage}）。\n"
        f"質問に関連する node_id を最大 {keep} 件、JSON のみで返してください。\n"
        "確信が低くても取りこぼしを避け、広めに選んで構いません。\n"
        '形式: {"selected":["id1","id2"],"confidence":"high|medium|low","reason":"..."}\n\n'
        f"# 質問\n{question}\n\n# 候補\n{catalog}\n"
    )
    try:
        raw = await embeddings.generate([{"role": "user", "content": prompt}])
        obj = _parse_json_obj(raw) or {}
        selected = [str(x) for x in (obj.get("selected") or []) if x]
        valid = {c["node_id"] for c in candidates}
        selected = [s for s in selected if s in valid][:keep]
        if selected:
            return selected, {
                "stage": stage,
                "selected": selected,
                "confidence": obj.get("confidence"),
                "reason": obj.get("reason"),
                "via": "llm",
            }
    except Exception as e:  # noqa: BLE001
        print(f"[rag-app] tree select LLM 失敗: {e}")

    scored = sorted(
        candidates,
        key=lambda c: _keyword_score(
            question, c.get("title") or "", c.get("summary") or ""
        ),
        reverse=True,
    )
    selected = [
        c["node_id"]
        for c in scored[:keep]
        if _keyword_score(question, c.get("title") or "", c.get("summary") or "") > 0
    ]
    if not selected and scored:
        selected = [scored[0]["node_id"]]
    return selected, {
        "stage": stage,
        "selected": selected,
        "via": "keyword_fallback",
    }


async def _tree_nav_doc(
    question: str, doc: dict[str, Any], top_k: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    doc_id = doc["doc_id"]
    source = doc["source"]
    trace: list[dict[str, Any]] = [{"doc_id": doc_id, "source": source, "steps": []}]
    steps = trace[0]["steps"]

    parent_id: str | None = None
    selected_ids: list[str] = []
    for hop in range(TREE_MAX_HOPS):
        children = docstore.get_children(doc_id, parent_id)
        if not children:
            break
        # 葉しか無い／子が選ばれた最終段
        if len(children) == 1 and hop > 0:
            selected_ids = [children[0]["node_id"]]
            steps.append({"hop": hop, "auto": children[0]["node_id"]})
            break

        if len(children) >= TREE_STAGE1_THRESHOLD:
            wide, t1 = await _llm_select_nodes(
                question, children, keep=TREE_STAGE1_KEEP, stage="recall"
            )
            steps.append(t1)
            cand = [c for c in children if c["node_id"] in set(wide)]
            if not cand:
                cand = children[:TREE_STAGE1_KEEP]
            narrow, t2 = await _llm_select_nodes(
                question, cand, keep=min(top_k, TREE_STAGE2_KEEP), stage="precision"
            )
            steps.append(t2)
            selected_ids = narrow
        else:
            selected_ids, t = await _llm_select_nodes(
                question, children, keep=min(top_k, TREE_STAGE2_KEEP), stage="select"
            )
            steps.append(t)

        if not selected_ids:
            break

        # 選ばれたノードに子がいればドリルダウン（先頭候補を辿る）
        next_parent = selected_ids[0]
        grandchildren = docstore.get_children(doc_id, next_parent)
        if not grandchildren:
            break
        parent_id = next_parent

    if not selected_ids:
        # ルート直下を全部のフォールバック（最大 top_k）
        roots = docstore.get_children(doc_id, None)
        selected_ids = [r["node_id"] for r in roots[:top_k]]

    bodies = docstore.get_nodes_with_text(doc_id, selected_ids[:top_k])
    nodes = [
        {
            "id": b["node_id"],
            "title": b.get("title") or b["node_id"],
            "text": b.get("text") or "",
            "source": source,
            "doc_id": doc_id,
            "page_start": b.get("page_start"),
            "page_end": b.get("page_end"),
            "score": None,
            "mode": "tree",
        }
        for b in bodies
        if (b.get("text") or "").strip()
    ]
    return nodes, trace


async def retrieve_vector(
    question: str,
    scope: str,
    top_k: int,
    tags: list[str] | None = None,
    *,
    source: str | None = None,
) -> dict[str, Any]:
    qvec = await embeddings.embed(question, is_query=True)
    # タグ未付与ドキュメントは RAG 対象外
    hits = await vectorstore.search(
        qvec,
        top_k,
        scope,
        tags or None,
        require_tags=True,
        source=(source or "").strip() or None,
    )
    nodes = []
    for h in hits:
        payload = h.get("payload") or {}
        src = payload.get("source") or "unknown"
        nodes.append(
            {
                "id": h.get("id"),
                "title": payload.get("title") or src or "chunk",
                "text": payload.get("text") or "",
                "source": src,
                "doc_id": payload.get("doc_id"),
                "page_start": payload.get("page_start") or payload.get("page"),
                "page_end": payload.get("page_end") or payload.get("page"),
                "score": h.get("score"),
                "mode": "vector",
            }
        )
    return {
        "nodes": nodes,
        "trace": [
            {
                "mode": "vector",
                "hit_count": len(nodes),
                "source": (source or "").strip() or None,
            }
        ],
    }


async def retrieve_tree(
    question: str,
    scope: str,
    top_k: int,
    tags: list[str] | None = None,
    doc_id: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    if doc_id:
        d = docstore.get_doc(doc_id, scope)
        if (
            d
            and not d.get("truncated")
            and (d.get("tags") or [])
            and _is_structured(d)
        ):
            docs = [d]
    elif source:
        d = docstore.get_doc_by_source(scope, source)
        if (
            d
            and not d.get("truncated")
            and (d.get("tags") or [])
            and _is_structured(d)
        ):
            docs = [d]
    else:
        docs = [d for d in _tagged_docs(scope, tags) if _is_structured(d)]

    if not docs:
        return {"nodes": [], "trace": [{"mode": "tree", "error": "no_structured_docs"}]}

    # 文書が複数ならタイトル＋要約で1件に絞る（PoC）
    if len(docs) > 1:
        catalog = [
            {
                "node_id": d["doc_id"],
                "title": d["source"],
                "summary": f"pages={d.get('page_count')} chars={d.get('char_count')}",
            }
            for d in docs
        ]
        chosen, t = await _llm_select_nodes(
            question, catalog, keep=min(3, len(docs)), stage="doc_select"
        )
        idset = set(chosen) if chosen else {docs[0]["doc_id"]}
        docs = [d for d in docs if d["doc_id"] in idset] or docs[:1]
        doc_trace = [t]
    else:
        doc_trace = []

    all_nodes: list[dict[str, Any]] = []
    all_trace: list[dict[str, Any]] = [{"mode": "tree", "doc_select": doc_trace}]
    per_doc_k = max(1, top_k // max(len(docs), 1))
    for d in docs:
        nodes, tr = await _tree_nav_doc(question, d, per_doc_k)
        all_nodes.extend(nodes)
        all_trace.extend(tr)

    return {"nodes": all_nodes[:top_k], "trace": all_trace}


async def retrieve_hybrid(
    question: str,
    scope: str,
    top_k: int,
    tags: list[str] | None = None,
    *,
    doc_id: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """ベクトルで文書候補 → 構造化ツリーで節特定。ツリーが無い文書はベクトルチャンクを使う。"""
    # 資料指定時はその文書だけを辿る（タグ内の他文書を混ぜない）
    if doc_id or source:
        docs: list[dict[str, Any]] = []
        if doc_id:
            d = docstore.get_doc(doc_id, scope)
            if d and not d.get("truncated") and (d.get("tags") or []):
                docs = [d]
        elif source:
            d = docstore.get_doc_by_source(scope, source)
            if d and not d.get("truncated") and (d.get("tags") or []):
                docs = [d]
        if docs and _is_structured(docs[0]):
            t_nodes, t_trace = await _tree_nav_doc(question, docs[0], top_k)
            for n in t_nodes:
                n["mode"] = "hybrid"
            return {
                "nodes": t_nodes[:top_k],
                "trace": [
                    {
                        "mode": "hybrid",
                        "scoped": True,
                        "doc_id": docs[0].get("doc_id"),
                        "source": docs[0].get("source"),
                    },
                    *t_trace,
                ],
            }
        src = (docs[0].get("source") if docs else None) or source
        vec = await retrieve_vector(
            question, scope, top_k, tags, source=(src or "").strip() or None
        )
        for n in vec.get("nodes") or []:
            n["mode"] = "hybrid"
        return {
            **vec,
            "trace": [{"mode": "hybrid", "scoped": True, "source": src}, *(vec.get("trace") or [])],
        }

    # 広めにベクトル候補を取る
    vec = await retrieve_vector(question, scope, max(top_k * 3, 8), tags)
    sources: list[str] = []
    for n in vec["nodes"]:
        s = n.get("source")
        if s and s not in sources:
            sources.append(s)

    nodes: list[dict[str, Any]] = []
    trace: list[dict[str, Any]] = [
        {"mode": "hybrid", "vector_sources": sources, "vector_trace": vec.get("trace")}
    ]

    for src_name in sources:
        doc = docstore.get_doc_by_source(scope, src_name)
        if (
            doc
            and not doc.get("truncated")
            and (doc.get("tags") or [])
            and _is_structured(doc)
        ):
            t_nodes, t_trace = await _tree_nav_doc(
                question, doc, max(1, top_k // max(len(sources), 1))
            )
            for n in t_nodes:
                n["mode"] = "hybrid"
            nodes.extend(t_nodes)
            trace.extend(t_trace)
        else:
            # 構造化索引が無い文書はベクトルヒットを採用
            for n in vec["nodes"]:
                if n.get("source") == src_name:
                    n = {**n, "mode": "hybrid"}
                    nodes.append(n)
                    if len([x for x in nodes if x.get("source") == src_name]) >= 2:
                        break

    if not nodes:
        return vec | {"trace": trace + [{"fallback": "vector_only"}]}

    return {"nodes": nodes[:top_k], "trace": trace}


async def retrieve_full(
    scope: str,
    tags: list[str] | None = None,
    *,
    doc_id: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    """タグ付き候補文書の全文をコンテキストとして返す。"""
    docs = _tagged_docs(scope, tags)
    if doc_id:
        docs = [d for d in docs if d.get("doc_id") == doc_id]
    elif source:
        from . import textnorm

        ns = textnorm.normalize_source(source)
        docs = [
            d for d in docs if textnorm.normalize_source(d.get("source")) == ns
        ]
    nodes: list[dict[str, Any]] = []
    for d in docs:
        pages = docstore.get_all_pages(d["doc_id"])
        text = "\n\n".join(
            (p.get("text") or "").strip() for p in pages if (p.get("text") or "").strip()
        )
        if not text:
            continue
        nodes.append(
            {
                "id": d["doc_id"],
                "title": d["source"],
                "text": text,
                "source": d["source"],
                "doc_id": d["doc_id"],
                "page_start": pages[0]["page"] if pages else None,
                "page_end": pages[-1]["page"] if pages else None,
                "score": 1.0,
                "mode": "full",
            }
        )
    return {
        "nodes": nodes,
        "trace": [
            {
                "mode": "full",
                "doc_count": len(nodes),
                "char_count": sum(len(n["text"]) for n in nodes),
            }
        ],
    }


def _resolve_source_filter(
    scope: str, doc_id: str | None, source: str | None
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    """doc_id / source を正規化し、対象文書（あれば）を返す。"""
    from . import textnorm

    did = (doc_id or "").strip() or None
    src = textnorm.normalize_source(source) or None
    doc: dict[str, Any] | None = None
    if did:
        doc = docstore.get_doc(did, scope)
        if doc and not src:
            src = textnorm.normalize_source(doc.get("source")) or None
    elif src:
        doc = docstore.get_doc_by_source(scope, src)
        if doc and not did:
            did = doc.get("doc_id")
        # 解決できた文書の正規化済み source を以降のフィルタに使う
        if doc:
            src = textnorm.normalize_source(doc.get("source")) or src
    return did, src, doc


async def retrieve(
    question: str,
    scope: str,
    *,
    mode: str = "auto",
    top_k: int = 4,
    tags: list[str] | None = None,
    doc_id: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    mode = (mode or "auto").strip().lower()
    chosen_meta: dict[str, Any] | None = None
    did, src, scoped_doc = _resolve_source_filter(scope, doc_id, source)

    if mode == "auto":
        if scoped_doc or src or did:
            # 資料指定時: 構造化なら tree（節・ページ）、なければ vector（該当チャンク）
            if scoped_doc and _is_structured(scoped_doc) and not scoped_doc.get("truncated"):
                mode = "tree"
            else:
                mode = "vector"
            chosen_meta = {
                "reason": "source_scoped",
                "doc_id": did,
                "source": src,
                "resolved_mode": mode,
            }
        else:
            mode, chosen_meta = await resolve_retrieval_mode(scope, tags)

    if mode == "full":
        result = await retrieve_full(scope, tags, doc_id=did, source=src)
    elif mode == "tree":
        result = await retrieve_tree(
            question, scope, top_k, tags, doc_id=did, source=src
        )
    elif mode == "hybrid":
        result = await retrieve_hybrid(
            question, scope, top_k, tags, doc_id=did, source=src
        )
    else:
        result = await retrieve_vector(question, scope, top_k, tags, source=src)

    if chosen_meta is not None:
        result = {
            **result,
            "resolved_mode": mode,
            "trace": [{"auto": chosen_meta, "resolved_mode": mode}]
            + list(result.get("trace") or []),
        }
    else:
        result = {**result, "resolved_mode": mode}
    return result


def nodes_to_hits(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """既存 _answer_with_hits 互換の hits 形式へ変換する。"""
    hits: list[dict[str, Any]] = []
    for n in nodes:
        score = n.get("score")
        if score is None:
            score = 1.0
        title = n.get("title") or ""
        text = n.get("text") or ""
        if title and n.get("mode") in ("tree", "hybrid", "full"):
            text = f"【{title}】\n{text}"
        hits.append(
            {
                "id": n.get("id"),
                "score": score,
                "payload": {
                    "text": text,
                    "source": n.get("source") or "unknown",
                    "doc_id": n.get("doc_id"),
                    "page_start": n.get("page_start"),
                    "page_end": n.get("page_end"),
                    "mode": n.get("mode"),
                },
            }
        )
    return hits
