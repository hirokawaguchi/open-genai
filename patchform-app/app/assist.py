"""フォーム作成・修正の LLM アシスト。失敗時はカタログ制約付きテンプレートにフォールバック。"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from . import llm, spec

# ナビ（申請区分などの設問）抽出は推論モデルの応答が揺れるため、複数回試して
# 最も設問が取れた結果を採用する。十分な件数が取れたら早めに打ち切る。
NAV_ATTEMPTS = max(1, int(os.environ.get("PATCHFORM_NAV_ATTEMPTS", "2")))
NAV_ENOUGH_QUESTIONS = max(1, int(os.environ.get("PATCHFORM_NAV_ENOUGH", "3")))

_HEADING_MARK = re.compile(r"^#{1,6}\s*")
_TOC_MARK = re.compile(r"[［\[\s]*目次[］\]\s]*")
# 見出しの区切りに使われるダッシュ類のみ潰す。片仮名の長音符「ー」は語の一部なので除く。
_DASH_RUN = re.compile(r"[－—―‐\-]{1,}")
_SPACES = re.compile(r"\s+")


def clean_heading(text: str) -> str:
    """手引きの見出し記号や「目次」を落として、短い手続き名にする。"""
    s = _HEADING_MARK.sub("", (text or "").strip())
    s = _TOC_MARK.sub(" ", s)
    s = _DASH_RUN.sub(" ", s)
    s = _SPACES.sub(" ", s).strip(" ・")
    if s.endswith("の手続きの手続き"):
        s = s[: -len("の手続き")]
    return s[:80]


def _option_label(opt: Any) -> str:
    if isinstance(opt, dict):
        return str(opt.get("label") or opt.get("value") or "").strip()
    raw = str(opt or "").strip()
    return raw.split("|", 1)[0].strip()


def guide_has_choice(guide: Any) -> bool:
    comps = guide.get("components") if isinstance(guide, dict) else None
    return any(
        isinstance(c, dict) and c.get("type") in ("select", "radio", "checkbox") for c in (comps or [])
    )


def catalog_for_prompt() -> list[dict[str, Any]]:
    return [
        {
            "type": t,
            "label": meta["label"],
            "has_options": meta.get("has_options", False),
            "category": meta["category"],
            "description": meta.get("description") or "",
        }
        for t, meta in spec.CATALOG.items()
        if meta["enabled"]
    ]


def fallback_definition(text: str) -> dict[str, Any]:
    """LLM なしでも動く自治体向け下書き。"""
    q = (text or "").strip()
    title = q[:40] or "申請フォーム"
    if any(k in q for k in ("医療", "子ども", "小児", "助成")):
        title = title if "フォーム" in title else "子ども医療費助成の申請"
        comps = [
            _c("applicant", "user_info_composite", "申請者", True),
            _c("addr", "address_composite", "住所", True),
            _c("child_name", "text", "お子さまの氏名", True),
            _c("birth", "date", "生年月日", True),
            _c("hospital", "text", "受診医療機関"),
            _c("bank", "financial_institution_composite", "振込先"),
            _c("note", "textarea", "備考"),
        ]
    elif any(k in q for k in ("法人", "事業者", "会社")):
        title = title if len(q) > 8 else "事業者届出"
        comps = [
            _c("company", "company_info_composite", "法人情報", True),
            _c("addr", "address_composite", "所在地", True),
            _c("contact", "user_info_composite", "担当者", True),
            _c("mail", "email", "メールアドレス", True),
            _c("tel", "phone", "電話番号", True),
        ]
    elif any(k in q for k in ("口座", "振込", "補助金", "給付")):
        title = title if len(q) > 8 else "補助金申請"
        comps = [
            _c("applicant", "user_info_composite", "申請者", True),
            _c("addr", "address_composite", "住所", True),
            _c("amount", "number", "申請額", True),
            _c("bank", "financial_institution_composite", "振込先", True),
            _c("reason", "textarea", "申請理由", True),
        ]
    elif any(k in q for k in ("アンケート", "調査", "意見")):
        title = title if len(q) > 8 else "アンケート"
        comps = [
            _c("name", "text", "お名前"),
            _c(
                "satisfy",
                "radio",
                "満足度",
                True,
                options=["とても満足", "満足", "普通", "不満"],
            ),
            _c("comment", "textarea", "ご意見"),
        ]
    else:
        comps = [
            _c("applicant", "user_info_composite", "氏名", True),
            _c("addr", "address_composite", "住所", True),
            _c("mail", "email", "メールアドレス"),
            _c("tel", "phone", "電話番号"),
            _c("note", "textarea", "内容"),
        ]
    return {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": title, "description": q},
        "components": comps,
    }


def _c(
    cid: str,
    ctype: str,
    label: str,
    required: bool = False,
    *,
    options: list[str] | None = None,
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    if options:
        props["options"] = options
    return spec.fill_default_imi(
        {
            "id": cid,
            "type": ctype,
            "label": label,
            "required": required,
            "placeholder": "",
            "properties": props,
        }
    )


def merge_definition(
    current: dict[str, Any] | None,
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """既存 id をできるだけ維持して差し替える。"""
    if not current:
        return incoming
    used = {c.get("id") for c in current.get("components") or []}
    by_label = {
        str(c.get("label") or ""): c for c in current.get("components") or [] if c.get("label")
    }
    merged: list[dict[str, Any]] = []
    for raw in incoming.get("components") or []:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "")
        old = by_label.get(label)
        cid = str(raw.get("id") or "")
        if old and old.get("type") == raw.get("type"):
            cid = old["id"]
        elif cid in used and (not old or old.get("id") != cid):
            cid = f"c_{int(time.time() * 1000)}_{len(merged)}"
        used.add(cid)
        item = dict(raw)
        item["id"] = cid
        if old and old.get("type") == raw.get("type"):
            if not str(item.get("imi_type") or "").strip() and old.get("imi_type"):
                item["imi_type"] = old["imi_type"]
            old_subs = old.get("imi_subfields") if isinstance(old.get("imi_subfields"), dict) else {}
            new_subs = item.get("imi_subfields") if isinstance(item.get("imi_subfields"), dict) else {}
            if old_subs or new_subs:
                item["imi_subfields"] = {**old_subs, **new_subs}
        merged.append(item)
    meta = {
        **(current.get("metadata") or {}),
        **(incoming.get("metadata") or {}),
    }
    return {
        "$version": spec.SPEC_VERSION,
        "metadata": {
            "title": str(meta.get("title") or ""),
            "description": str(meta.get("description") or ""),
        },
        "components": merged,
    }


def apply_generated(
    raw: Any,
    *,
    visibility: str,
    current: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "生成結果の形式が不正です"
    incoming = raw.get("definition") if isinstance(raw.get("definition"), dict) else raw
    if current:
        incoming = merge_definition(current, incoming)
    comps = incoming.get("components") if isinstance(incoming, dict) else None
    if isinstance(incoming, dict) and isinstance(comps, list):
        incoming = {
            **incoming,
            "components": [
                spec.fill_default_imi(c) if isinstance(c, dict) else c for c in comps
            ],
        }
    return spec.validate_definition(incoming, visibility=visibility)


def fallback_invite(title: str, public_url: str, tone: str = "丁寧") -> dict[str, str]:
    polite = tone != "カジュアル"
    if polite:
        subject = f"【ご案内】{title}のご回答のお願い"
        body = (
            f"{title}へのご回答をお願いいたします。\n\n"
            f"回答用URL:\n{public_url}\n\n"
            "ご不明点があれば作成者までお問い合わせください。"
        )
    else:
        subject = f"{title}の回答をお願いします"
        body = f"{title}の回答フォームです。\n{public_url}\n"
    return {"subject": subject, "body": body}


async def generate_form(
    text: str,
    *,
    visibility: str = "internal",
    current: dict[str, Any] | None = None,
) -> dict[str, Any]:
    q = (text or "").strip()
    if not q:
        raise ValueError("指示文は必須です")
    allowed = json.dumps(catalog_for_prompt(), ensure_ascii=False)
    system = (
        "あなたは日本の自治体向けオンラインフォーム設計者です。"
        "必ず JSON オブジェクトだけを返してください。"
        "キーは $version, metadata{title,description}, components です。"
        f"$version は {spec.SPEC_VERSION}。"
        "components の各要素は id, type, label, required, properties を持ちます。"
        "imi_type と imi_subfields は省略してよい（サーバーが型の既定語彙を補う）。"
        f"type は次のカタログに含まれるものだけ使ってください: {allowed}。"
        "select/radio/checkbox には properties.options 配列が必要です。"
        "説明文やコードフェンス以外は出力しないでください。"
    )
    user = f"次の要件でフォームを作成してください。\n{q}"
    if current:
        user += "\n\n既存定義を尊重し、可能な限り id を維持して修正してください。\n"
        user += json.dumps(current, ensure_ascii=False)
    try:
        raw = await llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}]
        )
        parsed = llm.extract_json(raw)
        definition, err = apply_generated(parsed, visibility=visibility, current=current)
        if err or definition is None:
            raise ValueError(err or "検証に失敗しました")
        return {
            "source": "llm",
            "definition": definition,
            "notes": "AI が生成した定義です。保存前に内容を確認してください。",
            "model": llm.PATCHFORM_MODEL,
        }
    except Exception as e:  # noqa: BLE001
        base = fallback_definition(q)
        if current:
            base = merge_definition(current, base)
        base = {
            **base,
            "components": [
                spec.fill_default_imi(c) if isinstance(c, dict) else c
                for c in (base.get("components") or [])
            ],
        }
        definition, err = spec.validate_definition(base, visibility=visibility)
        if err or definition is None:
            raise ValueError(err or "テンプレートの検証に失敗しました") from e
        return {
            "source": "template",
            "definition": definition,
            "notes": f"LLM を使えなかったためテンプレートを使いました（{e}）。",
            "model": llm.PATCHFORM_MODEL,
        }


async def draft_invite(title: str, public_url: str, tone: str = "丁寧") -> dict[str, Any]:
    fallback = fallback_invite(title, public_url, tone)
    messages = [
        {
            "role": "system",
            "content": (
                "あなたは自治体の案内文作成者です。JSON のみ返してください。"
                "キー: subject, body。本文は日本語。"
            ),
        },
        {
            "role": "user",
            "content": f"トーン:{tone}\nタイトル:{title}\nURL:{public_url}",
        },
    ]
    try:
        raw = await llm.chat(messages)
        parsed = llm.extract_json(raw)
        if not isinstance(parsed, dict) or not parsed.get("subject") or not parsed.get("body"):
            raise ValueError("案内文の形式が不正です")
        return {**fallback, **{k: parsed[k] for k in ("subject", "body")}, "source": "llm"}
    except Exception as e:  # noqa: BLE001
        return {**fallback, "source": "template", "notes": str(e)}


MAX_PROCEDURE_FORMS = 24
MAX_PROCEDURE_TEXT = 12_000
MAX_SELECT_CHAPTERS = 8
MAX_LLM_CHAPTERS = 4
MAX_CHAPTER_CHARS = 2_500
ALL_FORMS_OPTION = "一覧の様式をすべて出す"
_CHAPTER_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_CHAPTER_HINTS: tuple[tuple[str, int], ...] = (
    ("様式一覧", 6),
    ("提出書類", 6),
    ("必要書類", 5),
    ("申請書類", 4),
    ("添付", 4),
    ("様式", 3),
    ("指定申請", 3),
    ("持ち物", 3),
    ("対象", 2),
    ("要件", 2),
    ("手続き", 2),
    ("申請", 2),
)
_FORM_MARK = re.compile(
    r"(?:別記|別紙)?様式\s*第\s*[0-9０-９一二三四五六七八九十百]+\s*号(?:の[0-9０-９]+)?"
)
_QUOTED_FORM = re.compile(
    r"「([^」]{2,40}(?:申請書|届出書|申出書|報告書|調書|誓約書|同意書|請求書|届|台帳))」"
)
_LIST_PREFIX = re.compile(r"^[0-9０-９]+[\.．、.\s]+")
_ZEN_DIGIT = str.maketrans("０１２３４５６７８９", "0123456789")

# 様式名のゴミ取り（決定的な整形のみ。意味の判断はしない）。
_FILE_META = re.compile(
    r"[（(][^（()）]*(?:ファイル|Excel|EXCEL|PDF|Word|WORD|KB|MB|ダウンロード)[^（()）]*[）)]"
)
_NOTE_TAIL = re.compile(r"[（(]\s*注.*$")
_RECAP = re.compile(r"[（(]\s*(?:再掲|表|裏)\s*[）)]")
_ONLY_NUM_CELL = re.compile(r"^[0-9０-９()（）.\-\s]+$")
_NUM_ONLY = re.compile(
    r"^(?:別記|別紙)?(?:様式)?第?\s*[0-9０-９一二三四五六七八九十]+号(?:の[0-9０-９]+)?$"
)
# 表の要否・注記セル（要 / 不要 / 省略可 / 注3 / 要 注3 など）
_DROP_CELL = re.compile(r"(?:要|不要|省略可)(?:\s*注\s*[0-9０-９]+)?|注\s*[0-9０-９]+")
_CELL_META_KEYS = ("ファイル", "KB", "MB", "ダウンロード", "Excel", "PDF", "Word")


def _form_title_cell(line: str) -> str:
    """様式名の行を整える。

    markdown 表なら説明的なセルを選び、ファイルサイズ・注記凡例・要否（要/不要/省略可）
    などの定型的なゴミを落とす。分岐や区分の判断はしない（それは人とモデルに任せる）。
    """
    s = line
    if "|" in s:
        picks: list[str] = []
        for cell in (c.strip() for c in s.split("|")):
            cell = _RECAP.sub("", cell).strip()
            if not cell or _ONLY_NUM_CELL.match(cell):
                continue
            if _DROP_CELL.fullmatch(cell) or _NUM_ONLY.match(cell):
                continue
            if any(k in cell for k in _CELL_META_KEYS):
                continue
            picks.append(cell)
        s = " ".join(picks)
    s = _FILE_META.sub("", s)
    s = _NOTE_TAIL.sub("", s)
    s = _RECAP.sub("", s)
    s = s.split("※", 1)[0]
    # 余った開き括弧・区切りだけを落とす（閉じ括弧は名前の一部なので残す）
    return _SPACES.sub(" ", s).strip(" ・|（(")


def _line_at(text: str, index: int) -> str:
    start = text.rfind("\n", 0, index) + 1
    end = text.find("\n", index)
    return text[start : end if end >= 0 else None].strip()


def _norm_title(text: str) -> str:
    return clean_heading(text).translate(_ZEN_DIGIT).replace(" ", "")


def extract_form_titles(text: str, *, limit: int = MAX_PROCEDURE_FORMS) -> list[str]:
    """手引き本文から様式名だけを拾う。中身は見ない。"""
    q = text or ""
    by_mark: dict[str, str] = {}
    extras: list[str] = []
    for match in _FORM_MARK.finditer(q):
        mark = re.sub(r"\s+", "", match.group(0))
        line = _LIST_PREFIX.sub("", clean_heading(_form_title_cell(_line_at(q, match.start()))))
        titled = line
        wrapped = re.search(
            rf"^(.+?)[（(]\s*{re.escape(match.group(0))}\s*[）)]\s*$", line
        )
        if wrapped:
            titled = f"{mark} {wrapped.group(1).strip()}"
        elif mark not in line.replace(" ", ""):
            titled = f"{mark} {line}".strip()
        titled = re.sub(r"[・…．.\s]+\d{1,3}\s*$", "", titled).strip()
        if titled == mark or not titled:
            continue
        key = mark.translate(_ZEN_DIGIT)
        prev = by_mark.get(key, "")
        if len(titled) > len(prev):
            by_mark[key] = titled
    known = {_norm_title(v) for v in by_mark.values()}
    for match in _QUOTED_FORM.finditer(q):
        title = clean_heading(match.group(1))
        if not title or _norm_title(title) in known:
            continue
        extras.append(title)
        known.add(_norm_title(title))
    out = list(by_mark.values()) + extras
    # 同じ題名を落とす
    uniq: list[str] = []
    seen: set[str] = set()
    for title in out:
        key = _norm_title(title)
        if not key or key in seen:
            continue
        seen.add(key)
        uniq.append(title[:80])
        if len(uniq) >= limit:
            break
    return uniq


# 手続き名になりにくい行（組織名・連絡先・受付案内など）を弾く。
_ORG_TAIL = re.compile(r"(?:部|課|室|係|センター|事務所|支所|局)$")
_NAME_HINT = re.compile(r"(?:許可申請|申請|届出|認可|手続|しおり|手引き|手引|の案内|ガイド)")
_VERSION_PAREN = re.compile(r"[（(][^）)]*(?:改訂|改定|版|令和|平成|年\s*\d|第\s*\d+\s*版)[^）)]*[）)]")


def _tidy_procedure_name(name: str) -> str:
    """「◯◯のしおり／手引き」を「◯◯の手続き」に寄せる。"""
    name = _VERSION_PAREN.sub("", name).strip(" 　・")
    for suf in ("のしおり", "の手引き", "の手引", "の手びき"):
        if name.endswith(suf):
            return name[: -len(suf)] + "の手続き"
    if name.endswith("しおり"):
        return name[: -len("しおり")].strip("　 ・") + "の手続き"
    return name


def procedure_name_from_text(text: str) -> str:
    lines = (text or "").splitlines()
    # 1) 冒頭（目次より前）の本文行から、手続き名らしい行を優先して拾う。
    #    表紙の「◯◯申請のしおり」等は無印テキストのことが多く、見出し優先だと
    #    組織名を拾ってしまうため、まず本文行を見る。
    for raw in lines[:40]:
        s = clean_heading(raw)
        if not s or "目次" in s or "目 次" in s:
            continue
        s = _VERSION_PAREN.sub("", s).strip(" 　・")
        if len(s) < 4 or len(s) > 60:
            continue
        if _ORG_TAIL.search(s):
            continue
        if _NAME_HINT.search(s):
            return _tidy_procedure_name(s)[:80]
    # 2) 見出しから拾う（組織名だけの見出しは避ける）。
    for match in re.finditer(r"^#{1,6}\s+(.+)$", text or "", re.MULTILINE):
        name = clean_heading(match.group(1))
        if name and "目次" not in name and not _ORG_TAIL.search(name):
            return _tidy_procedure_name(name)
    first = clean_heading(lines[0] if lines else "")
    if first and "目次" not in first:
        return _tidy_procedure_name(first)
    return "手続き（仮）"


def split_guide_chapters(text: str) -> list[dict[str, Any]]:
    """見出しから章立てを切る。目次は kind=toc。"""
    q = text or ""
    matches = list(_CHAPTER_HEADING.finditer(q))
    chapters: list[dict[str, Any]] = []
    if not matches:
        body = q.strip()
        if body:
            chapters.append(
                {"id": "ch1", "title": "本文", "body": body, "kind": "body", "index": 1}
            )
        return chapters
    preface = q[: matches[0].start()].strip()
    if preface:
        chapters.append(
            {"id": "ch0", "title": "前文", "body": preface, "kind": "body", "index": 0}
        )
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(q)
        raw_title = match.group(2).strip()
        title = clean_heading(raw_title) or raw_title
        body = q[match.end() : end].strip()
        kind = "toc" if "目次" in raw_title else "body"
        chapters.append(
            {
                "id": f"ch{i + 1}",
                "title": title,
                "body": body,
                "kind": kind,
                "index": i + 1,
            }
        )
    return chapters


def score_chapter(chapter: dict[str, Any]) -> int:
    title = str(chapter.get("title") or "")
    body = str(chapter.get("body") or "")
    if chapter.get("kind") == "toc":
        return 2 if _FORM_MARK.search(body) else 1
    score = 0
    blob = f"{title}\n{body[:1200]}"
    weak_body = {"様式", "申請", "手続き"}
    for hint, weight in _CHAPTER_HINTS:
        if hint in title:
            score += weight * 2
        elif hint in blob and hint not in weak_body:
            score += weight
    if _FORM_MARK.search(body):
        score += 5
    return score


def select_guide_chapters(
    chapters: list[dict[str, Any]], *, limit: int = MAX_SELECT_CHAPTERS
) -> list[dict[str, Any]]:
    """目次は必ず残し、様式・提出に効く章を点数で選ぶ。"""
    toc = [c for c in chapters if c.get("kind") == "toc"]
    ranked = sorted(
        (c for c in chapters if c.get("kind") != "toc"),
        key=score_chapter,
        reverse=True,
    )
    chosen: list[dict[str, Any]] = []
    for chapter in ranked:
        if score_chapter(chapter) <= 0:
            continue
        chosen.append(chapter)
        if len(chosen) >= limit:
            break
    return toc + chosen


def analyze_chapter(chapter: dict[str, Any]) -> dict[str, Any]:
    """1章を機械的に読む。様式名だけ拾う。"""
    titles = extract_form_titles(str(chapter.get("body") or ""))
    return {
        "id": chapter.get("id"),
        "title": chapter.get("title"),
        "kind": chapter.get("kind"),
        "titles": titles,
    }


def _match_form_keys(want: list[str], forms: list[dict[str, Any]]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for title in want:
        need = _norm_title(title)
        if not need:
            continue
        for item in forms:
            definition = item.get("definition") if isinstance(item.get("definition"), dict) else {}
            meta = definition.get("metadata") if isinstance(definition.get("metadata"), dict) else {}
            have = _norm_title(str(meta.get("title") or item.get("title") or ""))
            key = str(item.get("key") or "")
            if not key or key in seen:
                continue
            if need == have or need in have or have in need:
                keys.append(key)
                seen.add(key)
                break
    return keys


def draft_from_form_titles(
    name: str,
    titles: list[str],
    *,
    conditions: list[dict[str, Any]] | None = None,
    navigation: dict[str, Any] | None = None,
    missing: list[str] | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """様式名だけの下書き。中身は空。一覧はまず全部必要とする。

    navigation（手引きから読み取った申請区分などの設問と分岐）があれば、
    案内フォームに設問を足し、選択肢ごとの準備物・様式の目安をルールにする。
    """
    forms = []
    keys: list[str] = []
    for i, title in enumerate(titles[:MAX_PROCEDURE_FORMS]):
        key = f"form{i + 1}"
        keys.append(key)
        forms.append(
            {
                "key": key,
                "definition": _simple_form(
                    title,
                    "手引きの様式名から作りました。記入済みファイルの添付で提出できます。"
                    "オンライン記入にする場合は項目を足してください。",
                    # 部品0だと公開（受付開始）できないため、既定で「様式ファイルの添付」枠を1つ置く。
                    # 作業台の前提（様式は記入でも添付でも可）に合わせた最小構成。
                    [_c("attachment", "file", "様式ファイル（記入済み）を添付", False)],
                ),
            }
        )
    components: list[dict[str, Any]] = []
    rules: list[dict[str, Any]] = []
    # 1) まず「全部出す」を既定にする様式選択の設問。
    event_options = [ALL_FORMS_OPTION]
    if keys:
        rules.append(
            {
                "component_id": "event",
                "option": ALL_FORMS_OPTION,
                "form_keys": keys,
                "notes": "様式一覧に出ていた用紙を、まず全部出す前提にしています。",
                "prepare": [],
            }
        )
    for item in conditions or []:
        if not isinstance(item, dict):
            continue
        when = clean_heading(str(item.get("when") or item.get("option") or ""))
        if not when or when == ALL_FORMS_OPTION:
            continue
        mapped = _match_form_keys(_title_list(item.get("form_titles") or item.get("titles") or []), forms)
        if not mapped:
            continue
        event_options.append(when[:40])
        rules.append(
            {
                "component_id": "event",
                "option": when[:40],
                "form_keys": mapped,
                "notes": str(item.get("notes") or "章の記載から仮に分けました。").strip(),
                "prepare": [],
            }
        )
    if keys:
        components.append(
            _c("event", "radio", "この手続きで出す様式", True, options=event_options)
        )
    # 2) 手引きから読み取った申請区分などの設問と分岐。
    nav_questions = (navigation or {}).get("questions") or []
    label_to_cid: dict[str, str] = {}
    for j, q in enumerate(nav_questions):
        if not isinstance(q, dict):
            continue
        label = clean_heading(str(q.get("label") or ""))
        opts = []
        seen_opt: set[str] = set()
        for opt in q.get("options") or []:
            text = _option_label(opt)
            key_opt = _norm_title(text)
            if not text or key_opt in seen_opt:
                continue
            seen_opt.add(key_opt)
            opts.append(text[:60])
        if not label or len(opts) < 2:
            continue
        cid = f"q{j + 1}"
        label_to_cid[_norm_title(label)] = cid
        components.append(_c(cid, "radio", label[:60], True, options=opts[:12]))
    for r in (navigation or {}).get("rules") or []:
        if not isinstance(r, dict):
            continue
        cid = label_to_cid.get(_norm_title(str(r.get("question") or r.get("label") or "")))
        option = str(r.get("option") or "").strip()
        if not cid or not option:
            continue
        mapped = _match_form_keys(_title_list(r.get("form_titles") or r.get("titles") or []), forms)
        prepare = r.get("prepare") or []
        if isinstance(prepare, str):
            prepare = [p.strip() for p in prepare.splitlines() if p.strip()]
        rules.append(
            {
                "component_id": cid,
                "option": option[:40],
                "form_keys": mapped,
                "notes": str(r.get("notes") or "").strip(),
                "prepare": [str(p).strip() for p in prepare if str(p).strip()],
            }
        )
    has_nav = bool(nav_questions)
    guide = _simple_form(
        f"{name}の案内",
        (
            "申請区分などの設問を手引きから読み取りました。選択肢ごとの準備物・様式は目安です。"
            if has_nav
            else "一覧にある様式は、まず全部必要としています。条件で変わる場合はあとから分けてください。"
        ),
        components,
    )
    return {
        "name": name,
        "description": "様式の中身は作っていません。条件がある場合は、この仮の選択肢を分けてください。",
        "guide": guide,
        "forms": forms,
        "rules": rules,
        "missing": missing
        or ["条件で様式が変わる場合は、あとから選択肢を分けてください"],
        "notes": notes
        or "様式名を文書から拾いました。中身は空です。一覧の様式は、まず全部必要としています。",
    }


def _simple_form(title: str, description: str, comps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "$version": spec.SPEC_VERSION,
        "metadata": {"title": title, "description": description},
        "components": comps,
    }


def fallback_procedure_draft(text: str) -> dict[str, Any]:
    """LLM なしでも手続き第1版を組めるテンプレート。公開はしない。"""
    q = (text or "").strip()
    titles = extract_form_titles(q)
    if titles:
        return draft_from_form_titles(procedure_name_from_text(q), titles)
    if any(k in q for k in ("転入", "転居", "引越", "引っ越し")):
        name = "転入・転居の手続き"
        guide_opts = ["転入", "転居"]
        forms = [
            {
                "key": "move_in",
                "definition": _simple_form(
                    "転入届",
                    "転入の届出",
                    [
                        _c("applicant", "user_info_composite", "届出人", True),
                        _c("addr", "address_composite", "新しい住所", True),
                    ],
                ),
            },
            {
                "key": "attach",
                "definition": _simple_form(
                    "添付台紙",
                    "持ち物の提出",
                    [_c("files", "file", "添付", True)],
                ),
            },
        ]
        rules = [
            {
                "component_id": "event",
                "option": "転入",
                "form_keys": ["move_in", "attach"],
                "notes": "転入届と添付を出してください。",
                "prepare": ["本人確認書類", "在留カード（該当する人）"],
            },
            {
                "component_id": "event",
                "option": "転居",
                "form_keys": ["attach"],
                "notes": "転居の場合は添付を確認してください。",
                "prepare": ["本人確認書類"],
            },
        ]
        missing = ["文書に無い分岐は足していません"]
    elif any(k in q for k in ("医療", "子ども", "小児", "助成")):
        name = "子ども医療費の手続き"
        guide_opts = ["新たに申請する", "内容を変更する"]
        forms = [
            {
                "key": "apply",
                "definition": _simple_form(
                    "医療費助成の申請",
                    "",
                    [
                        _c("applicant", "user_info_composite", "保護者", True),
                        _c("child", "text", "お子さまの氏名", True),
                        _c("bank", "financial_institution_composite", "振込先", True),
                    ],
                ),
            }
        ]
        rules = [
            {
                "component_id": "event",
                "option": "新たに申請する",
                "form_keys": ["apply"],
                "notes": "申請書を出してください。",
                "prepare": ["保険証", "振込先が分かるもの"],
            },
            {
                "component_id": "event",
                "option": "内容を変更する",
                "form_keys": ["apply"],
                "notes": "変更内容を申請書に書いてください。",
                "prepare": ["保険証"],
            },
        ]
        missing = ["審査基準はマスタに載せていません"]
    else:
        name = clean_heading(q.splitlines()[0] if q else "") or "手続き（仮）"
        guide_opts = []
        forms = []
        rules = []
        missing = ["文書から様式も分岐も読み取れませんでした"]

    if guide_opts:
        guide = _simple_form(
            f"{name}の案内",
            "状況を選んでください。",
            [
                _c("event", "radio", "該当するもの", True, options=guide_opts),
            ],
        )
    else:
        guide = _simple_form(f"{name}の案内", "", [])
    return {
        "name": name,
        "description": q[:400] or None,
        "guide": guide,
        "forms": forms,
        "rules": rules,
        "missing": missing,
        "notes": "テンプレートによる候補です。読み取れたものだけを選んで反映してください。",
    }


def _definition_from_part(raw: Any, title: str, visibility: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        raw = {}
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    incoming = {
        "$version": spec.SPEC_VERSION,
        "metadata": {
            "title": str(raw.get("title") or meta.get("title") or title),
            "description": str(raw.get("description") or meta.get("description") or ""),
        },
        "components": raw.get("components") if isinstance(raw.get("components"), list) else [],
    }
    return apply_generated(incoming, visibility=visibility)


def normalize_procedure_draft(
    raw: Any, *, visibility: str = "internal"
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(raw, dict):
        return None, "手続き案の形式が不正です"
    name = clean_heading(str(raw.get("name") or raw.get("title") or ""))
    if not name:
        name = "手続き（仮）"
    guide, gerr = _definition_from_part(raw.get("guide") or {}, f"{name}の案内", visibility)
    if gerr or guide is None:
        return None, gerr or "案内フォームの生成に失敗しました"
    gmeta = guide.get("metadata") if isinstance(guide.get("metadata"), dict) else {}
    guide["metadata"] = {
        **gmeta,
        "title": clean_heading(str(gmeta.get("title") or f"{name}の案内")) or f"{name}の案内",
    }
    forms_out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for i, item in enumerate(raw.get("forms") or []):
        if len(forms_out) >= MAX_PROCEDURE_FORMS:
            break
        if not isinstance(item, dict):
            continue
        key = str(item.get("key") or f"form{i + 1}").strip() or f"form{i + 1}"
        if key in seen:
            continue
        seen.add(key)
        incoming = item.get("definition") if isinstance(item.get("definition"), dict) else item
        incoming_meta = incoming.get("metadata") if isinstance(incoming, dict) and isinstance(incoming.get("metadata"), dict) else {}
        title = clean_heading(
            str(
                item.get("title")
                or incoming_meta.get("title")
                or (item.get("metadata") or {}).get("title")
                or f"様式{i + 1}"
            )
        ) or f"様式{i + 1}"
        definition, ferr = _definition_from_part(incoming if isinstance(incoming, dict) else item, title, visibility)
        if ferr or definition is None:
            return None, ferr or f"様式「{title}」の生成に失敗しました"
        fmeta = definition.get("metadata") if isinstance(definition.get("metadata"), dict) else {}
        definition["metadata"] = {**fmeta, "title": title}
        forms_out.append({"key": key, "definition": definition})
    keys = {f["key"] for f in forms_out}
    rules: list[dict[str, Any]] = []
    for item in raw.get("rules") or []:
        if not isinstance(item, dict):
            continue
        component_id = str(item.get("component_id") or "").strip()
        option = str(item.get("option") or "").strip()
        form_keys = [
            str(k).strip()
            for k in (item.get("form_keys") or item.get("form_ids") or [])
            if str(k).strip() in keys
        ]
        if not component_id or not option:
            continue
        prepare = item.get("prepare") or []
        if isinstance(prepare, str):
            prepare = [p.strip() for p in prepare.splitlines() if p.strip()]
        rules.append(
            {
                "component_id": component_id,
                "option": option,
                "form_keys": form_keys,
                "notes": str(item.get("notes") or "").strip(),
                "prepare": [str(p).strip() for p in prepare if str(p).strip()],
            }
        )
    missing = raw.get("missing") or []
    if isinstance(missing, str):
        missing = [missing]
    notes = str(raw.get("notes") or "").strip()
    return {
        "name": name,
        "description": str(raw.get("description") or "").strip() or None,
        "guide": guide,
        "forms": forms_out,
        "rules": rules,
        "missing": [str(m).strip() for m in missing if str(m).strip()],
        "notes": notes,
    }, None


def preview_procedure_draft(draft: dict[str, Any]) -> dict[str, Any]:
    """職員が反映対象を選ぶための要約。まだ何も作らない。"""
    name = str((draft or {}).get("name") or "")
    guide = draft.get("guide") if isinstance(draft.get("guide"), dict) else {}
    questions: list[dict[str, Any]] = []
    for comp in guide.get("components") or []:
        if not isinstance(comp, dict) or comp.get("type") not in ("select", "radio", "checkbox"):
            continue
        props = comp.get("properties") if isinstance(comp.get("properties"), dict) else {}
        questions.append(
            {
                "label": str(comp.get("label") or ""),
                "options": [_option_label(opt) for opt in (props.get("options") or []) if _option_label(opt)],
            }
        )
    warnings: list[str] = []
    if not name or name == "手続き（仮）":
        warnings.append("手続き名を読み取れませんでした。案内に反映する前に付けてください。")
    if not questions:
        warnings.append("手続きの選択肢（ラジオ・セレクト）は読み取れていません。")
    if not (draft.get("forms") or []):
        warnings.append("様式は読み取れていません。")
    for item in draft.get("missing") or []:
        text = str(item).strip()
        if text:
            warnings.append(text)
    forms = []
    for item in draft.get("forms") or []:
        if not isinstance(item, dict):
            continue
        definition = item.get("definition") if isinstance(item.get("definition"), dict) else {}
        meta = definition.get("metadata") if isinstance(definition.get("metadata"), dict) else {}
        field_count = len(definition.get("components") or [])
        forms.append(
            {
                "key": str(item.get("key") or ""),
                "title": str(meta.get("title") or item.get("title") or item.get("key") or "様式"),
                "field_count": field_count,
                "title_only": field_count == 0,
            }
        )
    desc = str(draft.get("description") or "").strip()
    return {
        "name": name,
        "warnings": warnings,
        "navigation": {
            "found": bool(questions),
            "title": str((guide.get("metadata") or {}).get("title") or ""),
            "questions": questions,
        },
        "forms": forms,
        "notice": {
            "name": name,
            "description": desc[:240],
            "rule_count": len(draft.get("rules") or []),
            "missing": [str(m).strip() for m in (draft.get("missing") or []) if str(m).strip()],
        },
    }


def pack_procedure_preview(generated: dict[str, Any]) -> dict[str, Any]:
    draft = generated.get("draft") if isinstance(generated.get("draft"), dict) else {}
    preview = preview_procedure_draft(draft)
    if isinstance(generated.get("outline"), dict):
        preview["outline"] = generated["outline"]
    return {
        "source": generated.get("source"),
        "notes": generated.get("notes"),
        "model": generated.get("model"),
        "draft": draft,
        "preview": preview,
    }


def _title_list(raw: Any) -> list[str]:
    items = raw if isinstance(raw, list) else []
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            title = clean_heading(item)
        elif isinstance(item, dict):
            title = clean_heading(str(item.get("title") or item.get("name") or ""))
        else:
            title = ""
        if title:
            out.append(title[:80])
    return out


def merge_form_titles(*groups: list[str]) -> list[str]:
    uniq: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for title in group:
            key = _norm_title(title)
            if not key or key in seen:
                continue
            seen.add(key)
            uniq.append(title[:80])
            if len(uniq) >= MAX_PROCEDURE_FORMS:
                return uniq
    return uniq


async def select_chapters_llm(chapters: list[dict[str, Any]]) -> list[str] | None:
    """目次から、様式・提出に効く章だけを選ぶ。失敗したら None。"""
    if len(chapters) <= 2:
        return None
    lines = [f"- {c['id']}: {c.get('title') or ''} ({c.get('kind')})" for c in chapters[:40]]
    raw = await llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "あなたは手引きの目次から関連章を選ぶアシスタントです。"
                    "JSON オブジェクトだけを返してください。"
                    '形式: {"selected":["ch1","ch2"]}'
                    "様式一覧・提出書類・対象・要件など、手続きの作成に効く章だけを選んでください。"
                    "目次そのものは selected に入れないでください。"
                ),
            },
            {
                "role": "user",
                "content": "次の目次から関連章の id を選んでください。\n" + "\n".join(lines),
            },
        ],
        temperature=0,
        max_tokens=512,
        think=False,
    )
    parsed = llm.extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    valid = {c["id"] for c in chapters}
    selected = [str(x) for x in (parsed.get("selected") or []) if str(x) in valid]
    return selected or None


async def refine_chapter_llm(
    chapter: dict[str, Any], known_titles: list[str]
) -> tuple[list[str], list[dict[str, Any]]]:
    """1章だけ読んで、様式名と条件を足す。"""
    if chapter.get("kind") == "toc":
        return [], []
    body = str(chapter.get("body") or "").strip()[:MAX_CHAPTER_CHARS]
    if not body:
        return [], []
    raw = await llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "あなたは日本の自治体向け手続き設計者です。"
                    "この章だけを読み、JSON オブジェクトだけを返してください。"
                    "フォーム定義は作らないでください。文書に無い様式名は足さないでください。"
                    "キー: form_titles, conditions。"
                    "form_titles は文字列の配列。"
                    'conditions は {"when":"法人の場合","form_titles":["様式第3号 誓約書"]} の配列。'
                    "条件が無ければ conditions は空配列です。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"章: {chapter.get('title')}\n"
                    f"既に拾った様式名:\n"
                    + ("\n".join(f"- {t}" for t in known_titles) or "（なし）")
                    +                     f"\n\n# 本文\n{body}"
                ),
            },
        ],
        temperature=0,
        max_tokens=4_096,
        think=False,
    )
    parsed = llm.extract_json(raw)
    if not isinstance(parsed, dict):
        raise ValueError("章の解析結果の形式が不正です")
    titles = _title_list(parsed.get("form_titles") or parsed.get("titles") or [])
    conditions: list[dict[str, Any]] = []
    for item in parsed.get("conditions") or []:
        if not isinstance(item, dict):
            continue
        when = clean_heading(str(item.get("when") or ""))
        cond_titles = _title_list(item.get("form_titles") or item.get("titles") or [])
        if when and cond_titles:
            conditions.append({"when": when, "form_titles": cond_titles})
    return titles, conditions


NAV_CONTEXT_CHARS = 9_000
NAV_CHAPTER_CHARS = 2_400
MAX_NAV_CHAPTERS = 6
# 申請区分・許可区分・要否など、分岐に効く章の見出し語。
_NAV_TITLE_HINTS: tuple[str, ...] = (
    "区分",
    "申請区分",
    "対象",
    "要件",
    "必要な書類",
    "提出書類",
    "申請書類",
    "流れ",
    "Ｑ＆Ａ",
    "Q&A",
    "有効期間",
    "手続き",
    "許可",
)


def select_nav_chapters(
    chapters: list[dict[str, Any]], *, limit: int = MAX_NAV_CHAPTERS
) -> list[dict[str, Any]]:
    """申請区分・要件など、分岐の判断に効く章を見出しから選ぶ。

    PDF 由来の見出しは「許 可 の 区 分」のように文字間へ空白が入ることがある。
    空白を潰してからヒント語を照合する。
    """
    picks: list[dict[str, Any]] = []
    for chapter in chapters:
        if chapter.get("kind") == "toc":
            continue
        body = str(chapter.get("body") or "")
        if not body.strip():
            continue
        flat = _SPACES.sub("", str(chapter.get("title") or ""))
        if any(_SPACES.sub("", hint) in flat for hint in _NAV_TITLE_HINTS):
            picks.append(chapter)
        if len(picks) >= limit:
            break
    return picks


async def draft_navigation_llm(
    chapters: list[dict[str, Any]], form_titles: list[str]
) -> dict[str, Any] | None:
    """手引きから申請区分などの設問（ナビ）と分岐ルールを読み取る。

    フォーム定義は作らない。返すのは設問（ラベルと選択肢）と、選択肢ごとの
    準備物・関連様式名・注意のみ。失敗したら None。
    """
    picks = select_nav_chapters(chapters)
    if not picks:
        return None
    buf: list[str] = []
    total = 0
    for chapter in picks:
        body = str(chapter.get("body") or "").strip()
        if not body:
            continue
        seg = f"## {chapter.get('title')}\n{body[:NAV_CHAPTER_CHARS]}"
        if total + len(seg) > NAV_CONTEXT_CHARS:
            seg = seg[: max(0, NAV_CONTEXT_CHARS - total)]
        if not seg:
            break
        buf.append(seg)
        total += len(seg)
        if total >= NAV_CONTEXT_CHARS:
            break
    context = "\n\n".join(buf).strip()
    if not context:
        return None
    titles_block = "\n".join(f"- {t}" for t in form_titles[:40]) or "（なし）"
    raw = await llm.chat(
        [
            {
                "role": "system",
                "content": (
                    "あなたは日本の自治体手続きの設計者です。"
                    "手引きを読み、申請者が最初に答えるべき設問（申請区分・許可区分・"
                    "法人/個人など、提出物が変わる分かれ目）を読み取ってください。"
                    "JSON オブジェクトだけを返します。"
                    'キーは questions と rules。'
                    'questions は [{"label":"設問文","options":["選択肢1","選択肢2"]}] の配列。'
                    "選択肢は2つ以上。文書から読み取れる分かれ目だけにし、推測で増やさない。"
                    'rules は [{"question":"設問文","option":"選択肢",'
                    '"form_titles":["様式一覧に載っている名称"],"prepare":["準備物"],'
                    '"notes":"補足"}] の配列。'
                    "form_titles は与えた様式一覧の名称のみを使い、無ければ空配列。"
                    "分岐が読み取れなければ questions は空配列。説明文やコードフェンスは出力しない。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"# 様式一覧（この名称だけを form_titles に使う）\n{titles_block}\n\n"
                    f"# 手引き抜粋\n{context}"
                ),
            },
        ],
        temperature=0,
        max_tokens=8_192,
        think=False,
    )
    parsed = llm.extract_json(raw)
    if not isinstance(parsed, dict):
        return None
    questions: list[dict[str, Any]] = []
    label_seen: set[str] = set()
    for item in parsed.get("questions") or []:
        if not isinstance(item, dict):
            continue
        label = clean_heading(
            str(item.get("label") or item.get("question") or item.get("text") or item.get("title") or "")
        )
        options = [_option_label(o) for o in (item.get("options") or []) if _option_label(o)]
        key = _norm_title(label)
        if not label or len(options) < 2 or key in label_seen:
            continue
        label_seen.add(key)
        questions.append({"label": label[:60], "options": options})
    if not questions:
        return None
    valid_labels = {_norm_title(q["label"]) for q in questions}
    rules: list[dict[str, Any]] = []
    for item in parsed.get("rules") or []:
        if not isinstance(item, dict):
            continue
        question = clean_heading(str(item.get("question") or item.get("label") or ""))
        option = _option_label(item.get("option"))
        if _norm_title(question) not in valid_labels or not option:
            continue
        rules.append(
            {
                "question": question,
                "option": option,
                "form_titles": _title_list(item.get("form_titles") or item.get("titles") or []),
                "prepare": [
                    str(p).strip()
                    for p in (item.get("prepare") or [])
                    if str(p).strip()
                ],
                "notes": str(item.get("notes") or "").strip(),
            }
        )
    return {"questions": questions, "rules": rules}


async def draft_procedure(text: str, *, visibility: str = "internal") -> dict[str, Any]:
    full = (text or "").strip()
    if not full:
        raise ValueError("手引きや案内の本文は必須です")
    chapters = split_guide_chapters(full)
    selected = select_guide_chapters(chapters)
    llm_error = ""
    try:
        picked = await select_chapters_llm(chapters)
        if picked:
            by_id = {c["id"]: c for c in chapters}
            extra = [by_id[i] for i in picked if i in by_id]
            seen = {c["id"] for c in selected}
            for chapter in extra:
                if chapter["id"] not in seen:
                    selected.append(chapter)
                    seen.add(chapter["id"])
    except Exception as e:  # noqa: BLE001
        llm_error = str(e)

    found: list[str] = []
    read: list[dict[str, Any]] = []
    for chapter in selected:
        local = analyze_chapter(chapter)
        found = merge_form_titles(found, local["titles"])
        read.append(
            {
                "id": local["id"],
                "title": local["title"],
                "kind": local["kind"],
                "form_count": len(local["titles"]),
            }
        )
    found = merge_form_titles(found, extract_form_titles(full))

    llm_titles: list[str] = []
    conditions: list[dict[str, Any]] = []
    llm_targets = [c for c in selected if c.get("kind") != "toc"][:MAX_LLM_CHAPTERS]
    if not llm_error:
        for chapter in llm_targets:
            try:
                extra_titles, extra_conds = await refine_chapter_llm(chapter, found)
                llm_titles = merge_form_titles(llm_titles, extra_titles)
                conditions.extend(extra_conds)
            except Exception as e:  # noqa: BLE001
                llm_error = str(e)
                break

    titles = merge_form_titles(found, llm_titles)
    name = procedure_name_from_text(full)

    # ナビ（申請区分などの設問）抽出は章解析の失敗とは独立に試みる。
    # 推論モデルの応答は揺れるので複数回試し、設問が最も取れた結果を採用する。
    navigation: dict[str, Any] | None = None
    nav_error = ""
    for _ in range(NAV_ATTEMPTS):
        try:
            candidate = await draft_navigation_llm(chapters, titles)
        except Exception as e:  # noqa: BLE001
            nav_error = str(e)
            candidate = None
        if candidate:
            cur = len((navigation or {}).get("questions") or [])
            if len(candidate.get("questions") or []) > cur:
                navigation = candidate
                nav_error = ""
        if navigation and len(navigation.get("questions") or []) >= NAV_ENOUGH_QUESTIONS:
            break

    nav_count = len((navigation or {}).get("questions") or [])
    outline = {
        "chapter_count": len(chapters),
        "read": read,
        "navigation_questions": nav_count,
    }
    if titles:
        notes = (
            f"目次から{len(chapters)}章を切り、様式・提出に関する{len(selected)}章を読みました。"
            "様式名を拾い、一覧の様式はまず全部必要としています。中身は空です。"
        )
        if nav_count:
            notes += f" 申請区分などの設問を{nav_count}件読み取りました（分岐と準備物は目安です）。"
        elif nav_error:
            notes += f" 申請区分の設問は読み取れませんでした（{nav_error}）。"
        if llm_error:
            notes += f" 一部の章の LLM は使えませんでした（{llm_error}）。"
        raw_draft = draft_from_form_titles(
            name,
            titles,
            conditions=conditions,
            navigation=navigation,
            notes=notes,
        )
        source = "llm" if (not llm_error or nav_count) else "template"
    else:
        raw_draft = fallback_procedure_draft(full)
        source = "template"
        if llm_error:
            raw_draft["notes"] = (
                f"LLM を使えなかったためテンプレートを使いました（{llm_error}）。"
                "読み取れた候補だけを選んでください。"
            )
    draft, err = normalize_procedure_draft(raw_draft, visibility=visibility)
    if err or draft is None:
        raise ValueError(err or "手続き案の検証に失敗しました")
    return {
        "source": source,
        "draft": draft,
        "notes": draft.get("notes") or raw_draft.get("notes"),
        "model": llm.PATCHFORM_MODEL,
        "outline": outline,
    }
