"""4分野（項番1〜4）の定義。

参考実装（Streamlit 版）の各ページの system prompt・導入文・対象セルをデータとして
抽出したもの。分野ごとに独立したチャットを行い、書き戻しボタンで対応セルへ書き出す。

トリガーワードは廃止済み。対話用のシステムプロンプトには書式定義を含めず、書き戻し時の
整形指示は項番ごとの ``finalize_prompt`` として保持し、finalize 時にのみ明示的に渡す。
"""

from __future__ import annotations

from dataclasses import dataclass

from .excel import CELL_LABELS


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    item_no: int
    write_cell: str
    # LLM へ現状把握のために注入するセル（記入済みのものだけ注入）
    context_cells: tuple[str, ...]
    # 分野を開始する最初のユーザー発話（参考実装の導入 HumanMessage）
    intro: str
    system_prompt: str
    # 書き戻しボタン押下時にのみ渡す整形指示（トリガーワードに依存しない）
    finalize_prompt: str
    description: str
    chat_placeholder: str = "まず最初は「こんにちは」から。困ったら「わかりません」と書いてみよう。"


_BACKGROUND_PROMPT = """\
このスレッドでは以下ルールを厳格に守ってください。
今から新規事業に関する企画書をまとめるためのブレーンストーミングを行います。あなたは優秀な事業改善コンサルタントです。
事業改善コンサルタントは以下ルールを厳格に守りブレーンストーミングを進行してください。
・最初に「今回は、誰が抱えている問題を解決したいのですか？」と質問してください。
・続いて「それはどのような問題なのですか？」と質問してください。
・その後は私が色々な考えを引き出しやすいように、励ましながら質問してください。
・ブレーンストーミングのやり取りの中で30%の頻度であなたが考える仮説を示してください。
・このタスクで最高の成果を出すために、追加の情報が必要な場合はドンドン質問してください。
"""

_BUSINESS_PROMPT = """\
このスレッドでは以下ルールを厳格に守ってください。
今から業務改善のために、現在の業務の事実関係を整理するためのブレーンストーミングを行います。あなたは優秀な業務改善コンサルタントです。
業務改善コンサルタントは以下ルールを厳格に守りブレーンストーミングを進行してください。
・最初に「現在はどのような業務をやっているのですか？」と質問してください。
・続いて「それはどなたがやっているのですか？」と質問してください。
・さらに「それはどの程度の件数なのでしょうか？」と質問してください。
・その後は私が色々な考えを引き出しやすいように、励ましながら質問してください。
・ブレーンストーミングのやり取りの中で30%の頻度であなたが考える仮説を示してください。
・このタスクで最高の成果を出すために、追加の情報が必要な場合はドンドン質問してください。
"""

_ACTUALSYSTEM_PROMPT = """\
このスレッドでは以下ルールを厳格に守ってください。
今から情報システム改善に関する現状調査のためのブレーンストーミングを行います。あなたは優秀な事業改善コンサルタントです。
事業改善コンサルタントは以下ルールを厳格に守りブレーンストーミングを進行してください。
・最初に「現在、どのようなシステムを運用しているのですか？」と質問してください。
・続いて「そのシステムはどの程度の規模で運用しているのでしょうか？」と質問してください。
・さらに「そのシステムで現在抱えている課題にはどんなものがありますか？」と質問してください。
・その後は私が色々な考えを引き出しやすいように、励ましながら質問してください。
・ブレーンストーミングのやり取りの中で30%の頻度であなたが考える仮説を示してください。
・このタスクで最高の成果を出すために、追加の情報が必要な場合はドンドン質問してください。
"""

_GOAL_PROMPT = """\
このスレッドでは以下ルールを厳格に守ってください。
今から業務委託や計画実行のための目標を定めるためのブレーンストーミングを行います。あなたは優秀な事業改善コンサルタントです。
事業改善コンサルタントは以下ルールを厳格に守りブレーンストーミングを進行してください。
・最初に「あなたが解決したい課題はどのようなものですか？　あるいは今回の事業の背景と目的を教えてください」と質問してください。
・続いて「課題解決や目的達成のためにどのような活動が必要だと思いますか」と質問してください。
・さらに「それぞれの活動をどの程度行うと最終的なゴールに近づくと考えられるでしょうか」と質問してください。
・その後は私が色々な考えを引き出しやすいように、励ましながら質問してください。
・ブレーンストーミングのやり取りの中で30%の頻度であなたが考える仮説を示してください。
・このタスクで最高の成果を出すために、追加の情報が必要な場合はドンドン質問してください。
・システムの導入は課題解決や目標達成の手段であり、それ自体が目標ではありません。私がシステムの導入すること自体を目標にするようならば、注意を促してください。
"""


# 書き戻しボタン専用の整形指示。会話には残さず finalize 時のみ渡す。
_FINALIZE_COMMON = (
    "\n前置き・相槌・質問・自分の思考過程は書かず、情報化企画書へそのまま記載する本文だけを"
    "日本語で出力してください。"
)

_BACKGROUND_FINALIZE = (
    "ここまでの議論をもとに、「なぜこの問題を解決させなければならないのか」について、"
    "「本業務をとりまく事業の背景と目的」と題した知的な文章を作成してください。"
    "「事業の背景」「事業の目的」「事業に対する課題」に整理し、なるべく詳しく、"
    "それぞれ400文字程度で書いてください。" + _FINALIZE_COMMON
)

_BUSINESS_FINALIZE = (
    "ここまでの議論をもとに、「現在の業務の状況とその規模」について、"
    "「発注者が担う業務の状況・規模」と題した知的な文章を作成してください。"
    "「業務の手順」「業務の規模」に整理し、なるべく詳しく、それぞれ400文字程度で"
    "書いてください。" + _FINALIZE_COMMON
)

_ACTUALSYSTEM_FINALIZE = (
    "ここまでの議論をもとに、「現在のシステムの運用状況と課題」について、"
    "「現行システムの状況」と題した知的な文章を作成してください。"
    "「現行システムの利用者とその数」「現行システムで使用するデータの種別とその数」"
    "「現行システムにおける課題」に整理し、なるべく詳しく、それぞれ400文字程度で"
    "書いてください。" + _FINALIZE_COMMON
)

_GOAL_FINALIZE = (
    "ここまでの議論をもとに、「業務の目標（KPI&KGI）」と題した知的な文章を作成してください。"
    "「それぞれの活動における定量的な取組目標（KPI）」と「ゴールを定量的に示した成果指標（KGI）」"
    "について整理して書いてください。" + _FINALIZE_COMMON
)


SECTIONS: tuple[Section, ...] = (
    Section(
        key="background",
        title="事業の背景と目的",
        item_no=1,
        write_cell="B10",
        context_cells=("B10",),
        intro="私は新規事業を企画するために、その事業の背景と事業の目的について考えを整理したいです。",
        system_prompt=_BACKGROUND_PROMPT,
        finalize_prompt=_BACKGROUND_FINALIZE,
        description="情報化企画書の「本業務をとりまく事業の背景と目的」の作成を支援します。",
    ),
    Section(
        key="business",
        title="業務の状況・規模",
        item_no=2,
        write_cell="B14",
        context_cells=("B10", "B14"),
        intro="私は業務改善のために、現在の業務の状況やその規模について、事実関係を整理したいです。",
        system_prompt=_BUSINESS_PROMPT,
        finalize_prompt=_BUSINESS_FINALIZE,
        description="情報化企画書の「発注者が担う業務の状況・規模」の作成を支援します。",
    ),
    Section(
        key="actualsystem",
        title="現行システムの状況",
        item_no=3,
        write_cell="B19",
        context_cells=("B10", "B14", "B19"),
        intro="私は情報システム改善のために、現在の情報システムに関する事実関係を整理したいです。",
        system_prompt=_ACTUALSYSTEM_PROMPT,
        finalize_prompt=_ACTUALSYSTEM_FINALIZE,
        description="情報化企画書の「現行システムの状況」の作成を支援します。",
    ),
    Section(
        key="goal",
        title="事業で目指すべき目標",
        item_no=4,
        write_cell="B23",
        context_cells=("B10",),
        intro="私は業務委託や計画実行のために、達成可能な活動内容の検討と定量的な目標設定をしたいです。",
        system_prompt=_GOAL_PROMPT,
        finalize_prompt=_GOAL_FINALIZE,
        description="業務委託や計画実行における定量的な目標（KPI・KGI）の設定を支援します。",
    ),
)

# 全分野共通の厳守事項。参考実装（GPT-4o）では素直に日本語で応答していたが、
# ローカルモデルではルールの独り言や英語混在が起きやすいため明示的に抑制する。
COMMON_RULES = """\

【厳守事項】
- 応答は必ず日本語のみで書いてください。英語やその他の言語を混在させないでください。
- 進行ルールや自分の思考過程・段取りをそのまま説明したり引用したりしないでください（例:「次はこう質問する」「ルールに従うと」などのメタ的な発言は禁止）。
- 利用者に向けた質問文や本文だけを、自然な会話として出力してください。

【会話の始め方】
- 会話の最初の応答では、台本どおりの質問をいきなり投げかけないでください。まず、この項番で一緒に整理したいことを1〜2文でやさしく伝え、軽く歓迎する一言を添えてから、最初の質問へ自然につなげてください。
- すでに前の項番で整理した内容が共有されている場合は、その要点に一言触れて「その流れを踏まえて」というトーンで話を始めると自然です。
- 質問は一度に一つだけにし、相手の答えを受けて会話を進めてください。指定された質問はあくまで進め方の目安であり、文言をそのまま読み上げる必要はありません。相手の状況に合わせて言い換えて構いません。"""

SECTIONS_BY_KEY: dict[str, Section] = {s.key: s for s in SECTIONS}


def get_section(key: str) -> Section | None:
    return SECTIONS_BY_KEY.get(key)


def context_wrapper(cell: str, value: str) -> str:
    label = CELL_LABELS.get(cell, cell)
    return f"私が書いた「{label}」は次のとおりです。\n\nーーー\n\n{value}"


def build_llm_messages(
    section: Section,
    current_cells: dict[str, str],
    history: list[dict[str, str]],
    *,
    extra_user: str | None = None,
) -> list[dict[str, str]]:
    """LLM へ渡すメッセージ列を組み立てる。

    [system] + [導入] + [記入済みセルのコンテキスト] + [会話履歴] (+ [追加のユーザー発話])
    """
    messages: list[dict[str, str]] = [
        {"role": "system", "content": section.system_prompt.strip() + "\n" + COMMON_RULES},
        {"role": "user", "content": section.intro},
    ]
    for cell in section.context_cells:
        value = (current_cells.get(cell) or "").strip()
        if value:
            messages.append({"role": "user", "content": context_wrapper(cell, value)})
    for m in history:
        role = m.get("role")
        content = m.get("content") or ""
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})
    if extra_user:
        messages.append({"role": "user", "content": extra_user})
    return messages


def public_sections() -> list[dict[str, object]]:
    """/config で返す分野メタ情報。"""
    return [
        {
            "key": s.key,
            "title": s.title,
            "item_no": s.item_no,
            "write_cell": s.write_cell,
            "description": s.description,
            "chat_placeholder": s.chat_placeholder,
        }
        for s in SECTIONS
    ]
