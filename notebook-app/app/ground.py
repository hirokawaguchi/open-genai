"""同じソース集合で行生成と対話をする。"""

from __future__ import annotations

from typing import Any

from . import llm, retrieve, store


async def answer_from_sources(
    session_id: str,
    user_id: str,
    question: str,
    *,
    instruction: str = "",
) -> tuple[str, list[dict[str, str]]]:
    nodes = store.list_material_nodes(session_id, user_id)
    if nodes is None:
        raise KeyError("session")
    picked = retrieve.select_nodes(question, nodes)
    if not picked:
        raise ValueError("読める参考資料がありません")
    material, cites = retrieve.format_material(picked)
    extra = (instruction or "").strip()
    system = (
        "あなたは資料だけを根拠にするアシスタントです。"
        "以下の「参考情報」だけを使い、日本語で答えてください。"
        "参照した箇所には [1] のように番号を付けてください。"
        "参考情報に答えが無い場合は、推測せず『資料から判断できない』と述べてください。"
    )
    if extra:
        system += f"\n\n# ノートの指示\n{extra}"
    answer = await llm.chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": f"# 参考情報\n{material}\n\n# 質問\n{question}"},
        ]
    )
    return answer, retrieve.filter_used_citations(answer, cites)


async def enrich_briefing(filename: str, briefing: dict[str, Any], sample: str) -> dict[str, Any]:
    if not llm.LLM_ENABLED or not (sample or "").strip():
        return briefing
    try:
        raw = await llm.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "資料の案内を JSON だけ返す。"
                        '{"summary":"2文以内","terms":["用語",...]}'
                        "本文に無いことを書かない。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"# ファイル\n{filename}\n\n# 抜粋\n{sample[:4000]}",
                },
            ]
        )
    except Exception:  # noqa: BLE001
        return briefing
    text = (raw or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return briefing
    import json

    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return briefing
    out = dict(briefing)
    if isinstance(parsed.get("summary"), str) and parsed["summary"].strip():
        out["summary"] = parsed["summary"].strip()
    if isinstance(parsed.get("terms"), list):
        terms = [str(t).strip() for t in parsed["terms"] if str(t).strip()]
        if terms:
            out["terms"] = terms[:16]
    return out
