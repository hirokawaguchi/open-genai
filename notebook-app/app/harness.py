"""対話用の短い tool loop。OpenAI 互換 tools と JSON フォールバック。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from . import activity, hermes_client, hermes_mcp, llm, retrieve, store, tools

HISTORY_LIMIT = 8
MAX_ANSWER_REFS = 5
ANSWER_REF_CHARS = 4000
_ANSWER_REF = re.compile(r"\[\[回答\s*(\d+)\]\]")


def _catalog_for_prompt(
    catalog: list[dict[str, Any]],
    source_ids: list[str],
) -> list[dict[str, Any]]:
    if not source_ids:
        return catalog
    wanted = set(source_ids)
    return [s for s in catalog if str(s.get("id") or "") in wanted]


def _system_prompt(
    instruction: str,
    enabled_mcps: list[dict[str, Any]],
    *,
    source_labels: list[str],
    catalog: list[dict[str, Any]],
    designated: list[dict[str, Any]] | None = None,
    manuscript: dict[str, Any] | None = None,
) -> str:
    lines = [
        "あなたはノートの中で動くエージェントです。日本語で答えてください。",
        "対話の文に [1] のような引用番号は書かない。出所は Open-Meteo や資料名のように、名前で書く。",
        "参考資料にも MCP にも無いことは断定せず、『資料から判断できない』と述べてください。",
        "あいさつ、雑談、文書を作る頼みが無い発言には、短く返すだけにしてください。道具は呼ばず、文書の話をこちらから始めません。",
        "短い資料の質問には、調べて答えるだけにしてください。ゴールも項目も、エディタへの渡しも不要です。",
        "文書を作ってほしいと分かった発言だけを、一文のゴールにします。",
        "文書かスライドかがその発言に無ければ、ask_user で一度だけ聞いて止めてください。",
        "形が分かったら list_items でクリップを見ます。クリップの文を優先し、その行は書き換えません。足りない事実だけ資料と MCP で補います。",
        "write_manuscript で原稿を書きます。文書は見出しと段落、スライドは見出しごとの短い箇条書きです。",
        "原稿の主張を資料に照らして fact_check を呼びます。食い違うか、資料に無い断定があれば、そこで止まります。",
        "すべて資料と合うときだけ revise_manuscript を呼びます。見出しは変えず足さず、言い回しと章の形だけ変えます。新しい事実は足しません。",
        "そのあと deliver を呼びます。原稿をプロジェクトへ書き出します。画面は開きません。",
        "人が直すと答えたら、食い違った箇所だけ資料に合わせて write_manuscript をやり直し、fact_check から同じ順です。",
        "人がこのまま書き出すと答えたら open_draft を呼びます。推敲はしません。画面は開きません。",
        "利用者は道具の英語名を書きません。日本語の依頼から、呼ぶ道具を自分で決めてください。",
        "回答の本文には道具の英語名を書かないでください。",
        "文書を作る依頼は、事実がすべて合うところまで進んだら、言い回しを整えて書き出すまで同じ応答で終えます。残りの手順を利用者に頼んで止めません。",
        "回答では、原稿を書き出したことだけ短く書いてください。プロジェクト名と開き方は画面が案内するので、書かないでください。",
        "言い回しを整える、という日本語は原稿の書き直しではありません。今の見出しを保ったまま言い回しだけ変えてから書き出します。",
        "そのほかの ask_user は、資料が矛盾しているときか、決まったゴールに必要な事実が資料に無いときだけです。",
        "原稿を書き出すと、画面が文書なら docx、スライドなら pptx を合成して文書台帳の下書きに置きます。スライドは整理済みの見出しをそのまま1枚にします。モデルから合成や台帳は呼び出しません。",
        "日程を調整してほしいときは propose_schedule だけを呼び、そこで止まります。タイトルと、YYYY-MM-DD または YYYY-MM-DDTHH:MM の候補日が決まっていなければ、呼ばずに ask_user で一度だけ聞いて止まります。案件の作成、招待、削除はしません。作るかは画面のボタンが案内します。回答では、確認してほしい候補だけ短く書きます。",
        "回答では、原稿を書き出したことだけ短く書いてください。台帳に置いたファイルは画面が案内するので、書かないでください。",
        "ナレッジへの投入は、検索のためだけです。成果物の保管先にはしません。",
        "接続中の MCP は、資料や質問に関係するときだけ呼んでください。あいさつや雑談では呼びません。",
        "推測で日時・天気・Wikipedia にある用語を埋めないでください。",
        "参考資料だけで足りないときは、使える MCP を当たってから答えてください。",
        "共有ナレッジ MCP が有効なとき、共通チームの資料はすべてこの対話の対象です。knowledge_search の結果も、参考資料と同じ根拠にしてください。",
    ]
    extra = (instruction or "").strip()
    if extra:
        lines.append(f"\n# ゴール\n{extra}")
        lines.append("この文が文書のゴールです。原稿はこの内容に沿って書きます。")
        lines.append("この発言があいさつや雑談なら、ゴールも項目も変えず、短く返してください。")
    lines.extend(_manuscript_lines(manuscript))
    if enabled_mcps:
        lines.append("\n# このノートで有効な MCP")
        for mcp in enabled_mcps:
            name = str(mcp.get("name") or "").strip() or "MCP"
            prompt = str(mcp.get("prompt") or "").strip()
            tool_names = "、".join(str(t) for t in (mcp.get("tools") or []) if t)
            lines.append(f"\n## {name}")
            if tool_names:
                lines.append(f"ツール: {tool_names}")
            if prompt:
                lines.append(prompt)
    lines.append("\n# この送信の資料範囲")
    knowledge_on = any("knowledge_search" in (mcp.get("tools") or []) for mcp in enabled_mcps)
    if source_labels:
        lines.append("指定された資料だけを検索する: " + "、".join(source_labels))
    else:
        lines.append("未指定のため、ノートの参考資料すべてを検索する。")
    if knowledge_on:
        lines.append(
            "共有ナレッジ MCP が On のため、共通チームの資料もすべて対象です。"
            "調べるときは knowledge_search を使い、その結果も根拠にしてください。"
        )
    lines.append("\n# 資料と見出し")
    if not catalog:
        lines.append(
            "ノートに写した参考資料はまだありません。共有ナレッジは対象です。"
            if knowledge_on
            else "参考資料はまだありません。"
        )
    else:
        shown = catalog[:20]
        for src in shown:
            heads = [str(h).strip() for h in (src.get("outline") or []) if str(h).strip()][:8]
            head = "、".join(heads) if heads else "見出しなし"
            lines.append(f"- {src.get('name')}: {head}")
        rest = len(catalog) - len(shown)
        if rest > 0:
            lines.append(f"- ほか {rest} 件")
    lines.append(
        "資料について聞かれているのに、資料名・節・項目のどれも質問が指しておらず、"
        "search_sources が本文を返さないときは、見出しを示してどの節かを1つだけ聞く。"
        "そのときは下書きしない。"
    )
    if designated:
        lines.append("\n" + _designated_section(designated))
    return "\n".join(lines)


def _manuscript_lines(manuscript: dict[str, Any] | None) -> list[str]:
    """今の原稿の見出しを、利用者に聞き直さず使える形で渡す。"""
    data = manuscript if isinstance(manuscript, dict) else {}
    labels = [
        str(chapter.get("label") or "").strip()
        for chapter in (data.get("chapters") or [])
        if isinstance(chapter, dict) and str(chapter.get("label") or "").strip()
    ]
    if not labels:
        return []
    form = "スライド" if data.get("form") == "slides" else "文書"
    fact = {"clean": "資料と合っている", "hold": "食い違いがある"}.get(
        str(data.get("fact") or ""),
        "まだ確かめていない",
    )
    revised = "整え済み" if data.get("revised") else "まだ整えていない"
    return [
        "\n# 今の原稿",
        f"形は{form}です。事実は{fact}。言い回しは{revised}。",
        "見出しは次のとおりです。この順と文言を保ってください。",
        "、".join(labels),
    ]


def answer_ref_numbers(text: str) -> list[int]:
    """質問文中の [[回答 N]] を、出てきた順・重複なしで返す。"""
    seen: list[int] = []
    for match in _ANSWER_REF.finditer(text or ""):
        n = int(match.group(1))
        if n not in seen:
            seen.append(n)
    return seen


def numbered_assistant_answers(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """アシスタント回答を出てきた順に 1 始まりで番号付けする。空文は数えない。"""
    numbered: list[dict[str, Any]] = []
    prompt = ""
    n = 0
    for message in messages:
        role = str(message.get("role") or "")
        content = str(message.get("content") or "")
        if role == "user":
            if content.strip():
                prompt = content.strip()
            continue
        if role != "assistant" or not content.strip():
            continue
        n += 1
        names: list[str] = []
        cites = message.get("citations")
        if isinstance(cites, list):
            for cite in cites:
                if not isinstance(cite, dict):
                    continue
                name = str(cite.get("display_name") or "").strip()
                if name and name not in names:
                    names.append(name)
        numbered.append(
            {
                "n": n,
                "id": str(message.get("id") or ""),
                "content": content,
                "prompt": prompt,
                "sources": names[:8],
            }
        )
    return numbered


def resolve_answer_refs(
    question: str, messages: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], str | None]:
    wanted = answer_ref_numbers(question)
    if not wanted:
        return [], None
    if len(wanted) > MAX_ANSWER_REFS:
        return [], "指定できる過去の回答は5件までです"
    by_n = {item["n"]: item for item in numbered_assistant_answers(messages)}
    missing = [n for n in wanted if n not in by_n]
    if missing:
        labels = "、".join(f"回答 {n}" for n in missing)
        return [], f"{labels} はこのノートにありません"
    return [by_n[n] for n in wanted], None


def _one_line(text: str, limit: int = 80) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    line = re.sub(r"\s+", " ", raw.splitlines()[0].strip())
    if len(line) <= limit:
        return line
    return line[:limit] + "…"


def _clip_answer(text: str) -> str:
    body = (text or "").strip()
    if len(body) <= ANSWER_REF_CHARS:
        return body
    return body[:ANSWER_REF_CHARS] + "\n（以下略）"


def _designated_section(answers: list[dict[str, Any]]) -> str:
    lines = [
        "# この送信で指定した過去の回答",
        "次の指示は、ここで挙げる回答を対象にする。",
        "『これ』『その回答』は、履歴全体ではなく、この番号を指す。",
        "指定が複数のときは、指示がどれかを言っていなければすべてを対象にする。",
        "指定に無い事実を、指定回答の内容であるかのように扱わない。",
    ]
    for answer in answers:
        lines.append(f"\n## 回答 {answer['n']}")
        prompt = _one_line(str(answer.get("prompt") or ""))
        if prompt:
            lines.append(f"きっかけ: {prompt}")
        sources = [str(s) for s in (answer.get("sources") or []) if str(s).strip()]
        if sources:
            lines.append("出典: " + "、".join(sources))
        lines.append(_clip_answer(str(answer.get("content") or "")))
    return "\n".join(lines)


def _history(
    messages: list[dict[str, Any]],
    designated: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    by_id = {
        str(item.get("id") or ""): int(item["n"])
        for item in (designated or [])
        if str(item.get("id") or "")
    }
    usable = [
        m
        for m in messages
        if m.get("role") in ("user", "assistant") and str(m.get("content") or "").strip()
    ]
    clipped = usable[-HISTORY_LIMIT * 2 :]
    out: list[dict[str, Any]] = []
    for message in clipped:
        content = str(message.get("content") or "")
        mid = str(message.get("id") or "")
        if message.get("role") == "assistant" and mid in by_id:
            content = (
                f"（回答 {by_id[mid]}。全文は「この送信で指定した過去の回答」を参照）"
            )
        out.append({"role": str(message["role"]), "content": content})
    return out


def _json_objects(text: str) -> list[str]:
    """本文に埋まった JSON オブジェクトを、入れ子を含めて切り出す。"""
    out: list[str] = []
    i = 0
    n = len(text or "")
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        escape = False
        start = i
        for j in range(i, n):
            ch = text[j]
            if in_str:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    out.append(text[start : j + 1])
                    i = j + 1
                    break
        else:
            break
    return out


def _prompt_for_hermes(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        role = str(message.get("role") or "")
        if role == "system":
            parts.append(content)
        elif role == "assistant":
            parts.append(f"エージェント:\n{content}")
        else:
            parts.append(f"利用者:\n{content}")
    return "\n\n".join(parts)


def _parse_json_tool(text: str, allowed: list[str]) -> dict[str, Any] | None:
    for raw in _json_objects(text or ""):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        name = str(data.get("tool") or "").strip()
        if name not in allowed:
            continue
        args = data.get("arguments")
        if args is None:
            args = {k: v for k, v in data.items() if k != "tool"}
        return {"name": name, "arguments": args if isinstance(args, dict) else {}}
    return None


async def run(
    *,
    session_id: str,
    user_id: str,
    scope: str,
    question: str,
    history: list[dict[str, Any]],
    instruction: str = "",
    skill: dict[str, Any] | None = None,
    enabled_mcps: list[dict[str, Any]] | None = None,
    source_ids: list[str] | None = None,
    source_labels: list[str] | None = None,
    designated_answers: list[dict[str, Any]] | None = None,
    forward_headers: dict[str, str] | None = None,
) -> tuple[str, list[dict[str, Any]], list[dict[str, str]], list[dict[str, Any]], bool]:
    mcps = enabled_mcps
    if mcps is None:
        mcps = store.enabled_session_mcps(session_id, user_id)
    allowed, extra_specs = tools.allowed_from_mcps(skill, mcps)
    if not allowed:
        allowed = list(tools.CORE_TOOL_NAMES)
    scoped = [str(s).strip() for s in (source_ids or []) if str(s).strip()]
    labels = [str(s).strip() for s in (source_labels or []) if str(s).strip()]
    designated = list(designated_answers or [])
    catalog = _catalog_for_prompt(store.list_source_index(session_id, user_id) or [], scoped)
    ctx = tools.ToolContext(
        session_id=session_id,
        user_id=user_id,
        scope=scope,
        remote_mcps=[m for m in mcps if m.get("kind") == "remote" and m.get("url")],
        source_ids=scoped,
        forward_headers=dict(forward_headers or {}),
    )
    traces: list[dict[str, str]] = []
    openai_tools = tools.openai_tools(allowed, extra_specs)
    model_question = question
    notes: list[str] = []
    if labels:
        notes.append("この発言で指定した資料: " + "、".join(labels))
    if designated:
        notes.append(
            "この発言で指定した過去の回答: "
            + "、".join(f"回答 {item['n']}" for item in designated)
        )
    if notes:
        model_question = f"{question}\n\n（{'。'.join(notes)}）"
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": _system_prompt(
                instruction,
                mcps,
                source_labels=labels,
                catalog=catalog,
                designated=designated,
                manuscript=(store.get_session(session_id, user_id) or {}).get("manuscript"),
            ),
        },
        *_history(history, designated),
        {"role": "user", "content": model_question},
    ]
    fallback_hint = (
        "ツールを使うときは次の JSON だけを返す。"
        '{"tool":"search_sources","arguments":{"query":"..."}}'
        " 使わないときは通常の日本語で答える。"
        " 日時・天気・Wikipedia にある用語は推測せず、使えるツールを先に呼ぶ。"
    )

    hermes_url = os.environ.get("NOTEBOOK_HERMES_URL", "").strip().rstrip("/")
    if hermes_url:
        token = hermes_mcp.open_turn(ctx, allowed, extra_specs)
        try:
            text, traces = await hermes_client.complete(
                hermes_url,
                token,
                _prompt_for_hermes(messages),
                on_tool=lambda name: activity.note(session_id, name),
            )
        finally:
            hermes_mcp.close_turn(token)
        if ctx.ask_text:
            return ctx.ask_text, [], traces, [], False
        if not text.strip():
            raise ValueError("Hermes の応答本文が空です")
        cites = retrieve.filter_used_citations(text, ctx.citations)
        return text, cites, traces, list(ctx.drafts), ctx.open_editor

    while True:
        try:
            reply = await llm.chat_completion(messages, tools=openai_tools or None)
        except Exception:  # noqa: BLE001
            reply = await llm.chat_completion(
                [
                    *messages,
                    {"role": "system", "content": fallback_hint},
                ]
            )
        tool_calls = reply.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            messages.append(llm.without_meta(reply))
            for call in tool_calls:
                fn = call.get("function") if isinstance(call, dict) else None
                if not isinstance(fn, dict):
                    continue
                name = str(fn.get("name") or "")
                if name not in allowed:
                    result = json.dumps(
                        {"error": f"このノートでは {name} を使えません"},
                        ensure_ascii=False,
                    )
                else:
                    result = await tools.dispatch(name, fn.get("arguments"), ctx)
                traces.append({"name": name, "result": result[:1200]})
                activity.note(session_id, name)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": str(call.get("id") or name),
                        "content": result,
                    }
                )
            if ctx.ask_text:
                return ctx.ask_text, [], traces, [], False
            continue

        text = llm.message_text(reply)
        parsed = _parse_json_tool(text, allowed)
        if parsed:
            result = await tools.dispatch(parsed["name"], parsed["arguments"], ctx)
            traces.append({"name": parsed["name"], "result": result[:1200]})
            activity.note(session_id, parsed["name"])
            if ctx.ask_text:
                return ctx.ask_text, [], traces, [], False
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": f"# ツール結果\n{result}"})
            continue

        if not text.strip():
            raise ValueError("モデルの応答本文が空です")
        text = await llm.continue_if_length(messages, reply)
        cites = retrieve.filter_used_citations(text, ctx.citations)
        return text, cites, traces, list(ctx.drafts), ctx.open_editor
