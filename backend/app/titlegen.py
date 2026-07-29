"""チャットタイトル生成の純粋ロジック。

FastAPI アプリ本体に依存しないため、単体テストしやすい。
- clean_title: LLM 出力からタイトルを整形（拒否文・空は "" を返す）
- fallback_title_from_prompt: LLM を使わずプロンプトのユーザー発話から題名を作る
"""

from __future__ import annotations

import json
import re

# LLM がタイトル生成を断ったときの定型文（日本語 / 英語）だけを狭くマッチする。
# タイトルは短文のため過検出しにくいが、"できません" 単独のような汎用語は避ける。
TITLE_REFUSAL_RE = re.compile(
    r"(申し訳|ごめんなさい|お答えでき(ず|ません)|回答でき(ず|ません)|"
    r"お手伝いでき(ず|ません)|対応でき(ず|ません)|生成でき(ず|ません)|"
    r"i['’]?m\s+sorry|i\s+am\s+sorry|i\s+cannot|i\s+can['’]?t|as\s+an\s+ai)",
    re.IGNORECASE,
)


def clean_title(text: str) -> str:
    """LLM 出力を 1 行のタイトルに整形する。空・拒否文なら "" を返す。"""
    if not text or not text.strip():
        return ""
    # <output> 等の XML/HTML タグを除去
    cleaned = re.sub(r"<[^>]+>", "", text)
    # 1 行目だけ採用し、前後の引用符・空白を除去
    first_line = cleaned.strip().splitlines()[0] if cleaned.strip() else ""
    first_line = first_line.strip().strip('"').strip("'").strip("「」").strip()
    first_line = first_line[:50]
    if not first_line or TITLE_REFUSAL_RE.search(first_line):
        return ""
    return first_line


def fallback_title_from_prompt(prompt: str) -> str:
    """タイトル LLM を使わず、プロンプト中のユーザー発話から短い題名を作る。"""
    if not prompt:
        return "無題"
    # 構造化タグがあればその中身のみを使う。空でも生プロンプトには落とさない
    # （タグ文字列自体が題名になるのを防ぐ）。
    m = re.search(
        r"<user-messages>\s*([\s\S]*?)\s*</user-messages>", prompt, re.IGNORECASE
    )
    if m:
        raw = m.group(1).strip()
    else:
        m2 = re.search(
            r"<conversation>\s*([\s\S]*?)\s*</conversation>", prompt, re.IGNORECASE
        )
        raw = (m2.group(1) if m2 else prompt).strip()
    # JSON 会話ダンプから最初の user content を拾う
    if raw.startswith("[") or '"role"' in raw[:80]:
        try:
            data = json.loads(raw if raw.startswith("[") else prompt)
            if isinstance(data, list):
                for item in data:
                    if (
                        isinstance(item, dict)
                        and item.get("role") == "user"
                        and isinstance(item.get("content"), str)
                    ):
                        raw = item["content"].strip()
                        break
        except Exception:
            pass
    raw = re.sub(r"\s+", " ", raw).strip()
    if not raw:
        return "無題"
    return raw[:30]
