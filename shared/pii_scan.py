"""個人情報の検知（氏名・住所・電話番号・マイナンバー）。

- 検知のみ（匿名化・マスクは行わない）。
- 警告 UI 用に、検知箇所の短い抜粋（match / context）を返す。
- GiNZA が無い／失敗時は氏名をスキップし、住所は正規表現補助のみ。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

from shared.mynumber import find_valid_mynumbers

# 表示用ラベル（この集合以外は返さない）
CAT_NAME = "氏名"
CAT_ADDRESS = "住所"
CAT_PHONE = "電話番号"
CAT_MYNUMBER = "マイナンバー"
ALL_CATEGORIES = (CAT_NAME, CAT_ADDRESS, CAT_PHONE, CAT_MYNUMBER)

# 同期経路の NER 上限（文字）
DEFAULT_NER_MAX_CHARS = int(os.environ.get("PII_NER_MAX_CHARS", "8000"))
# 警告に載せる抜粋の最大件数（種別ごと）
MAX_HITS_PER_CATEGORY = int(os.environ.get("PII_MAX_HITS_PER_CATEGORY", "5"))
CONTEXT_RADIUS = 24

NGWORD_DB_PATH = os.environ.get("NGWORD_DB_PATH", "/data/ngwords.db")

# 国内電話（0 始まり、区切り任意）。短すぎる一致を避けるため桁数を見る。
_PHONE_RE = re.compile(
    r"(?<!\d)(?:0\d{1,4}[-−ー－]\d{1,4}[-−ー－]\d{3,4}|0[789]0[-−ー－]?\d{4}[-−ー－]?\d{4}|0\d{9,10})(?!\d)"
)

# 都道府県＋市区町村を含む住所っぽい並び（補助。NER と併用）
_ADDRESS_RE = re.compile(
    r"(?:東京都|北海道|(?:京都|大阪)府|"
    r"(?:青森|岩手|宮城|秋田|山形|福島|茨城|栃木|群馬|埼玉|千葉|神奈川|"
    r"新潟|富山|石川|福井|山梨|長野|岐阜|静岡|愛知|三重|滋賀|奈良|和歌山|"
    r"鳥取|島根|岡山|広島|山口|徳島|香川|愛媛|高知|福岡|佐賀|長崎|熊本|"
    r"大分|宮崎|鹿児島|沖縄)県)"
    r"[^\s\n　]{1,40}?(?:市|区|町|村)"
)

_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# 氏名 NER の明らかな誤検知を落とす
_CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]")
_PERSON_REJECT_RE = re.compile(
    r"(AI|OSPO|エージェント|モデル|システム|デジタル|サーバ|クラウド|メッシュ|"
    r"右中央|左中央|右上|左上|右下|左下|中央|吹き出し)",
    re.IGNORECASE,
)

_DEFAULT_SETTINGS: dict[str, Any] = {
    "warn_attachments": True,
    "scan_knowledge_pii": True,
    "check_pii_ner": True,
    "check_mynumber": True,
}

_nlp = None
_nlp_failed = False


def _mask_uuids(text: str) -> str:
    return _UUID_RE.sub("[UUID]", text)


def load_pii_settings() -> dict[str, Any]:
    """ngwords.db のルールから PII 関連フラグを読む（読取専用・失敗時は既定）。"""
    out = dict(_DEFAULT_SETTINGS)
    path = os.environ.get("NGWORD_DB_PATH", NGWORD_DB_PATH)
    if not os.path.exists(path):
        return out
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5)
        try:
            row = conn.execute("SELECT rules FROM ngword_rules WHERE id = 1").fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return out
        data = json.loads(row[0])
        if not isinstance(data, dict):
            return out
        for key in _DEFAULT_SETTINGS:
            if key in data:
                out[key] = bool(data[key])
        return out
    except Exception:  # noqa: BLE001
        return out


def _phone_digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _context(text: str, start: int, end: int, radius: int = CONTEXT_RADIUS) -> str:
    a = max(0, start - radius)
    b = min(len(text), end + radius)
    frag = text[a:b].replace("\n", " ").replace("\r", " ")
    frag = re.sub(r"\s+", " ", frag).strip()
    prefix = "…" if a > 0 else ""
    suffix = "…" if b < len(text) else ""
    return f"{prefix}{frag}{suffix}"


def _hit(category: str, match: str, context: str, start: int) -> dict[str, Any]:
    return {
        "category": category,
        "match": match.strip(),
        "context": context,
        "offset": start,
    }


def _looks_like_person_name(text: str) -> bool:
    """GiNZA Person の誤検知をある程度落とす。"""
    t = (text or "").strip()
    if not t or len(t) < 2 or len(t) > 20:
        return False
    if not _CJK_RE.search(t):
        return False  # 英数字のみ（OSPO 等）は除外
    if _PERSON_REJECT_RE.search(t):
        return False
    # 「生成AI・AI」のように記号・英字が混ざる複合語は除外
    if "・" in t or "/" in t:
        return False
    ascii_letters = sum(1 for c in t if ("A" <= c <= "Z") or ("a" <= c <= "z"))
    if ascii_letters >= 2:
        return False
    return True


def find_phone_hits(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not text:
        return out
    for m in _PHONE_RE.finditer(text):
        digits = _phone_digits(m.group(0))
        if len(digits) in (10, 11) and digits.startswith("0"):
            out.append(
                _hit(CAT_PHONE, m.group(0), _context(text, m.start(), m.end()), m.start())
            )
            if len(out) >= MAX_HITS_PER_CATEGORY:
                break
    return out


def find_address_hits(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not text:
        return out
    for m in _ADDRESS_RE.finditer(text):
        out.append(
            _hit(CAT_ADDRESS, m.group(0), _context(text, m.start(), m.end()), m.start())
        )
        if len(out) >= MAX_HITS_PER_CATEGORY:
            break
    return out


def find_mynumber_hits(text: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not text:
        return out
    for m in re.finditer(r"\d{12}", text):
        val = m.group(0)
        if val in find_valid_mynumbers(val):
            # 表示は一部マスク（アップロード者向けでも丸ごと出さない）
            masked = val[:4] + "****" + val[-4:]
            out.append(
                _hit(CAT_MYNUMBER, masked, _context(text, m.start(), m.end()), m.start())
            )
            if len(out) >= MAX_HITS_PER_CATEGORY:
                break
    return out


def _get_nlp():  # type: ignore[no-untyped-def]
    global _nlp, _nlp_failed
    if _nlp_failed:
        return None
    if _nlp is not None:
        return _nlp
    try:
        import spacy  # type: ignore

        # ginza 5.2 + spacy 3.8 で compound_splitter の split_mode=None が落ちるため除外
        load_kw = {"exclude": ["compound_splitter"]}
        try:
            _nlp = spacy.load("ja_ginza", **load_kw)
        except Exception:  # noqa: BLE001
            try:
                _nlp = spacy.load("ja_ginza_electra", **load_kw)
            except Exception:  # noqa: BLE001
                _nlp = spacy.load("ja_ginza")
        return _nlp
    except Exception as e:  # noqa: BLE001
        print(f"[pii_scan] GiNZA 読込失敗（氏名 NER は無効）: {e}")
        _nlp_failed = True
        return None


def _ner_hits(text: str, *, max_chars: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(氏名 hits, 住所 hits)。"""
    name_hits: list[dict[str, Any]] = []
    addr_hits: list[dict[str, Any]] = []
    if not text:
        return name_hits, addr_hits
    nlp = _get_nlp()
    if nlp is None:
        return name_hits, addr_hits
    sample = text if len(text) <= max_chars else text[:max_chars]
    try:
        disable = [p for p in nlp.pipe_names if p not in ("tok2vec", "ner")]
        with nlp.select_pipes(disable=disable):
            doc = nlp(sample)
    except Exception:  # noqa: BLE001
        try:
            doc = nlp(sample)
        except Exception:  # noqa: BLE001
            return name_hits, addr_hits

    for ent in doc.ents:
        label = (ent.label_ or "").upper()
        span = ent.text.strip()
        if label == "PERSON" or label.startswith("PERSON"):
            if not _looks_like_person_name(span):
                continue
            if len(name_hits) < MAX_HITS_PER_CATEGORY:
                name_hits.append(
                    _hit(
                        CAT_NAME,
                        span,
                        _context(sample, ent.start_char, ent.end_char),
                        ent.start_char,
                    )
                )
        elif label in (
            "GPE",
            "LOC",
            "LOCATION",
            "FACILITY",
            "CITY",
            "PROVINCE",
            "COUNTRY",
            "ADDRESS",
        ) or any(x in label for x in ("LOC", "GPE", "ADDRESS", "FACILITY", "CITY", "PROVINCE")):
            if len(addr_hits) < MAX_HITS_PER_CATEGORY and span:
                addr_hits.append(
                    _hit(
                        CAT_ADDRESS,
                        span,
                        _context(sample, ent.start_char, ent.end_char),
                        ent.start_char,
                    )
                )
    return name_hits, addr_hits


def scan(
    text: str,
    *,
    enable_ner: bool = True,
    ner_max_chars: int | None = None,
    check_mynumber: bool = True,
) -> dict[str, Any]:
    """テキストを検査し、種別・件数・検知箇所の抜粋を返す。

    戻り値:
      {
        "categories": ["電話番号", ...],
        "counts": {"電話番号": 1, ...},
        "hits": [{"category","match","context","offset"}, ...],
      }
    """
    empty = {"categories": [], "counts": {}, "hits": []}
    if not text or not text.strip():
        return empty

    hay = _mask_uuids(text)
    hits: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    phone_hits = find_phone_hits(hay)
    if phone_hits:
        counts[CAT_PHONE] = len(phone_hits)
        hits.extend(phone_hits)

    if check_mynumber:
        myn_hits = find_mynumber_hits(hay)
        if myn_hits:
            # find_valid_mynumbers 全件に近い件数が欲しい場合もあるが、表示は上限付き
            all_myn = find_valid_mynumbers(hay)
            counts[CAT_MYNUMBER] = len(all_myn) if all_myn else len(myn_hits)
            hits.extend(myn_hits)

    addr_hits = find_address_hits(hay)
    name_hits: list[dict[str, Any]] = []
    if enable_ner:
        cap = DEFAULT_NER_MAX_CHARS if ner_max_chars is None else ner_max_chars
        ner_names, ner_addrs = _ner_hits(hay, max_chars=max(0, cap))
        name_hits = ner_names
        # 住所は正規表現と NER をマージ（match 重複除去）
        seen = {h["match"] for h in addr_hits}
        for h in ner_addrs:
            if h["match"] not in seen and len(addr_hits) < MAX_HITS_PER_CATEGORY:
                addr_hits.append(h)
                seen.add(h["match"])

    if name_hits:
        counts[CAT_NAME] = len(name_hits)
        hits.extend(name_hits)
    if addr_hits:
        counts[CAT_ADDRESS] = len(addr_hits)
        hits.extend(addr_hits)

    categories = [c for c in ALL_CATEGORIES if c in counts]
    # categories 順に hits を並べる
    order = {c: i for i, c in enumerate(ALL_CATEGORIES)}
    hits.sort(key=lambda h: (order.get(h["category"], 99), h.get("offset") or 0))
    return {"categories": categories, "counts": counts, "hits": hits}


def format_categories(categories: list[str]) -> str:
    """UI 向けの「A・B・C」連結。"""
    return "・".join(categories)


def format_warning_message(result: dict[str, Any]) -> str:
    """警告文（種別 + 検知例）。"""
    cats = list(result.get("categories") or [])
    if not cats:
        return ""
    lines = [f"個人情報の可能性: {format_categories(cats)}"]
    hits = list(result.get("hits") or [])
    # 種別ごとに最大2件の例
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for h in hits:
        by_cat.setdefault(h["category"], []).append(h)
    for cat in cats:
        examples = by_cat.get(cat) or []
        if not examples:
            continue
        shown = examples[:2]
        parts = []
        for h in shown:
            m = h.get("match") or ""
            ctx = h.get("context") or ""
            if ctx and m and m in ctx:
                parts.append(f"「{ctx}」")
            elif m:
                parts.append(f"「{m}」")
        if parts:
            lines.append(f"・{cat}: " + " / ".join(parts))
    return "\n".join(lines)
