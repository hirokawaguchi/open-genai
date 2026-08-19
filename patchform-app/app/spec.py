"""フォーム JSON 契約（opengenai-patchform/1）。

カタログに無い type、または enabled=False の type は定義にも回答にも使えない。
これで「エディタでは作れたが配信できない」を防ぐ。
"""

from __future__ import annotations

import re
from typing import Any

from app.lookup import corporate_check_digit_ok, yuucho_to_branch
from app.normalize import canonicalize

SPEC_VERSION = "opengenai-patchform/1"

# 公開面に出せない機微部品。visibility が internal 以外なら定義を拒否する。
SENSITIVE_TYPES = frozenset({"mynumber"})

STATUSES = ("draft", "published", "closed", "archived")
VISIBILITIES = ("internal", "public", "both")
IDENTITY_MODES = ("required", "optional", "anonymous")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_RE = re.compile(r"^[0-9+\-() ]{8,20}$")
_PIN_RE = re.compile(r"^\d{4}$")

# type -> {label, enabled, category, has_options, input}
# enabled=True のものだけビルダと配信で使う。
def _item(
    label: str,
    category: str,
    description: str,
    *,
    has_options: bool = False,
) -> dict[str, Any]:
    return {
        "label": label,
        "enabled": True,
        "category": category,
        "has_options": has_options,
        "description": description,
    }


CATALOG: dict[str, dict[str, Any]] = {
    "text": _item("テキスト", "basic", "1行の自由記入"),
    "textarea": _item("テキストエリア", "basic", "複数行の自由記入"),
    "email": _item("メールアドレス", "basic", "メール形式を確認する"),
    "phone": _item("電話番号", "basic", "電話番号を入力する"),
    "number": _item("数値", "basic", "数量や金額など"),
    "select": _item("セレクト", "selection", "一覧から1つ選ぶ", has_options=True),
    "radio": _item("ラジオ", "selection", "並んだ選択肢から1つ", has_options=True),
    "checkbox": _item("チェックボックス", "selection", "複数選べる", has_options=True),
    "slider": _item("スライダー", "selection", "目安の数値をバーで選ぶ"),
    "rating": _item("評価", "selection", "1〜5の満足度など"),
    "date": _item("日付", "datetime", "年月日を選ぶ"),
    "time": _item("時刻", "datetime", "時分を選ぶ"),
    "datetime-local": _item("日時", "datetime", "日付と時刻を一緒に"),
    "daterange": _item("期間", "datetime", "開始日と終了日"),
    "address_composite": _item("住所", "composite", "郵便番号・都道府県・市区町村など"),
    "user_info_composite": _item("氏名", "composite", "姓・名・フリガナ。性別と生年月日は表示を選べる"),
    "company_info_composite": _item("法人情報", "composite", "法人名・法人番号・代表者"),
    "financial_institution_composite": _item(
        "金融機関", "composite", "振込先。ゆうちょは記号番号から店番へ換算"
    ),
    "text_display": _item("説明文", "display", "回答ではなく案内文を出す"),
    "image_display": _item("画像表示", "display", "案内図などの画像を出す"),
    "divider": _item("区切り線", "display", "項目の区切り"),
    "page_break": _item("改ページ", "display", "次のページへ進む区切り。進捗と次へが出る"),
    "file": _item("ファイル", "advanced", "添付ファイルを受け取り、実ファイルを保管する"),
    "password": _item("パスワード", "advanced", "入力内容を隠す"),
    "calculated": _item("計算", "advanced", "他の数値からその場で自動計算する"),
    "mynumber": _item("マイナンバー", "advanced", "12桁。庁内専用・保存時暗号化"),
    "matrix_question": _item("マトリクス", "advanced", "行×列の表で選ぶ"),
    "signature_pad": _item("署名", "advanced", "署名画像を添付する"),
    "location": _item("位置情報", "advanced", "緯度経度または現在地"),
    "qr_scanner": _item("QR読取", "advanced", "QRの内容を入力・読取する"),
    "image_recognition": _item("画像認識", "ai", "画像から文字を読み取る"),
    "document_reader": _item("文書読取", "ai", "テキスト文書から内容を取り出す"),
}

DISPLAY_TYPES = frozenset(
    t for t, meta in CATALOG.items() if meta["category"] == "display"
)

COMPOSITE_SUBFIELDS: dict[str, list[str]] = {
    "address_composite": ["postal_code", "prefecture", "city", "street", "building"],
    "user_info_composite": [
        "last_name",
        "first_name",
        "last_name_kana",
        "first_name_kana",
        "gender",
        "birth_date",
    ],
    "company_info_composite": ["company_name", "corporate_number", "representative"],
    "financial_institution_composite": [
        "is_yuucho",
        "bank_code",
        "bank_name",
        "branch_code",
        "branch_name",
        "account_type",
        "account_number",
        "yuucho_symbol",
        "yuucho_number",
        "account_holder",
    ],
}

COMPOSITE_REQUIRED_SUBFIELDS: dict[str, list[str]] = {
    "address_composite": ["prefecture", "city", "street"],
    "user_info_composite": ["last_name", "first_name"],
    "company_info_composite": ["company_name"],
    "financial_institution_composite": ["account_holder"],
}

_CORP_RE = re.compile(r"^\d{13}$")
_POSTAL_RE = re.compile(r"^\d{3}-?\d{4}$")
_BANK_CODE_RE = re.compile(r"^\d{4}$")
_BRANCH_CODE_RE = re.compile(r"^\d{3}$")
_YUCHO_SYMBOL_RE = re.compile(r"^\d{3,5}$")
_YUCHO_NUMBER_RE = re.compile(r"^\d{1,8}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_GENDERS = frozenset({"男", "女", "その他", "回答しない"})
_FORMULA_RE = re.compile(r"^[0-9+\-*/().\s]+$")
_FIELD_REF_RE = re.compile(r"\{\{([a-zA-Z0-9_]+)\}\}")


def _truthy(value: Any) -> bool:
    if value is True or value == 1:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _prop_shown(comp: dict[str, Any], name: str) -> bool:
    props = comp.get("properties") if isinstance(comp.get("properties"), dict) else {}
    if name not in props:
        return True
    return _truthy(props.get(name))


def mynumber_check_digit_ok(digits: str) -> bool:
    """個人番号（12桁）の検査数字。"""
    if len(digits) != 12 or not digits.isdigit():
        return False
    total = 0
    for i in range(1, 12):
        p = int(digits[11 - i])
        q = i + 1 if i <= 6 else i - 5
        total += p * q
    c = total % 11
    check = 0 if c <= 1 else 11 - c
    return check == int(digits[11])


def enabled_types() -> list[str]:
    return [t for t, meta in CATALOG.items() if meta["enabled"]]


def catalog_public() -> list[dict[str, Any]]:
    return [
        {"type": t, **{k: v for k, v in meta.items()}}
        for t, meta in CATALOG.items()
        if meta["enabled"]
    ]


def empty_definition(title: str = "", description: str = "") -> dict[str, Any]:
    return {
        "$version": SPEC_VERSION,
        "metadata": {"title": title, "description": description},
        "components": [],
    }


def validate_pin(pin: str | None) -> str | None:
    if not pin:
        return None
    if not _PIN_RE.match(pin):
        return "暗証番号は4桁の数字である必要があります"
    return None


def _options_of(comp: dict[str, Any]) -> list[str]:
    raw = (comp.get("properties") or {}).get("options") or []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, dict) and (item.get("value") or item.get("label")):
            out.append(str(item.get("value") or item["label"]).strip())
    return out


def validate_definition(
    definition: Any,
    *,
    visibility: str = "internal",
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(definition, dict):
        return None, "フォーム定義はオブジェクトである必要があります"
    version = definition.get("$version") or SPEC_VERSION
    if version != SPEC_VERSION:
        return None, f"未対応の定義バージョンです: {version}"
    meta = definition.get("metadata") or {}
    if not isinstance(meta, dict):
        return None, "metadata の形式が不正です"
    comps = definition.get("components")
    if comps is None:
        comps = []
    if not isinstance(comps, list):
        return None, "components は配列である必要があります"
    ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for i, raw in enumerate(comps):
        if not isinstance(raw, dict):
            return None, f"部品 {i + 1} の形式が不正です"
        cid = str(raw.get("id") or "").strip()
        ctype = str(raw.get("type") or "").strip()
        label = str(raw.get("label") or "").strip()
        if not cid:
            return None, f"部品 {i + 1} に id がありません"
        if cid in ids:
            return None, f"部品 id が重複しています: {cid}"
        ids.add(cid)
        info = CATALOG.get(ctype)
        if not info:
            return None, f"未知の部品タイプです: {ctype}"
        if not info["enabled"]:
            return None, f"部品タイプ {ctype} はまだ利用できません"
        if ctype in SENSITIVE_TYPES and visibility != "internal":
            return None, f"{info['label']} は庁内専用フォームにのみ配置できます"
        if ctype not in DISPLAY_TYPES and not label:
            return None, f"部品 {cid} のラベルは必須です"
        props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
        if info.get("has_options") and not _options_of({"properties": props}):
            return None, f"部品 {label or cid} には選択肢が必要です"
        if ctype == "matrix_question":
            rows = props.get("rows") or []
            cols = props.get("columns") or []
            if not isinstance(rows, list) or not isinstance(cols, list) or not rows or not cols:
                return None, f"部品 {label or cid} には行と列が必要です"
        if ctype == "image_display":
            src = str(props.get("src") or "")
            if src and not _safe_image_src(src):
                return None, f"部品 {label or cid} の画像 URL が不正です"
        visible_when = raw.get("visibleWhen")
        if visible_when is not None and not isinstance(visible_when, (dict, list)):
            return None, f"部品 {cid} の visibleWhen が不正です"
        normalized.append(
            {
                "id": cid,
                "type": ctype,
                "label": label,
                "required": bool(raw.get("required")),
                "hide_label": bool(raw.get("hide_label")),
                "placeholder": str(raw.get("placeholder") or ""),
                "properties": props,
                "validation": raw.get("validation") if isinstance(raw.get("validation"), dict) else {},
                "visibleWhen": visible_when,
                "imi_type": str(raw.get("imi_type") or "").strip(),
                "imi_subfields": _imi_subfields(ctype, raw.get("imi_subfields")),
            }
        )
    return {
        "$version": SPEC_VERSION,
        "metadata": {
            "title": str(meta.get("title") or ""),
            "description": str(meta.get("description") or ""),
        },
        "components": normalized,
    }, None


def _imi_subfields(ctype: str, raw: Any) -> dict[str, str]:
    allowed = COMPOSITE_SUBFIELDS.get(ctype)
    if not allowed or not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key in allowed:
        val = str(raw.get(key) or "").strip()
        if val:
            out[key] = val
    return out


def _as_strings(value: Any) -> list[str]:
    if value is None or value == "":
        return [""]
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _is_visible(comp: dict[str, Any], answers: dict[str, Any]) -> bool:
    cond = comp.get("visibleWhen")
    if not cond:
        return True
    rules = cond if isinstance(cond, list) else [cond]
    for rule in rules:
        if not isinstance(rule, dict):
            return False
        field = str(rule.get("field") or "")
        got = _as_strings(answers.get(field))
        if "eq" in rule and str(rule["eq"]) not in got:
            return False
        if "in" in rule:
            allowed = rule["in"]
            if not isinstance(allowed, list) or not any(str(v) in got for v in allowed):
                return False
    return True


def validate_answers(
    definition: dict[str, Any],
    answers: Any,
    *,
    partial: bool = False,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(answers, dict):
        return None, "回答はオブジェクトである必要があります"
    cleaned: dict[str, Any] = {}
    for comp in definition.get("components") or []:
        cid = comp["id"]
        ctype = comp["type"]
        if ctype in DISPLAY_TYPES or ctype == "calculated":
            continue
        if not _is_visible(comp, answers):
            continue
        raw = answers.get(cid)
        if raw is None or raw == "" or raw == []:
            if comp.get("required") and not partial:
                return None, f"{comp['label']}は必須です"
            continue
        raw = canonicalize(comp, raw)
        err = _validate_value(comp, raw, partial=partial)
        if err:
            if partial and ("必須" in err or "不足" in err):
                cleaned[cid] = raw
                continue
            return None, err
        cleaned[cid] = _normalize_value(comp, raw)
    for comp in definition.get("components") or []:
        if comp["type"] != "calculated":
            continue
        if not _is_visible(comp, {**answers, **cleaned}):
            continue
        value, err = evaluate_formula(comp, cleaned)
        if err:
            if partial:
                continue
            return None, err
        cleaned[comp["id"]] = value
    return cleaned, None


def evaluate_formula(comp: dict[str, Any], answers: dict[str, Any]) -> tuple[float | None, str | None]:
    formula = str((comp.get("properties") or {}).get("formula") or "").strip()
    if not formula:
        return None, f"{comp['label']}の計算式がありません"
    expr = _FIELD_REF_RE.sub(
        lambda m: str(answers.get(m.group(1), "")),
        formula,
    )
    if not _FORMULA_RE.match(expr):
        return None, f"{comp['label']}の計算式が不正です"
    try:
        return float(eval(expr, {"__builtins__": {}}, {})), None  # noqa: S307
    except Exception:  # noqa: BLE001
        return None, f"{comp['label']}を計算できませんでした"


def _validate_value(comp: dict[str, Any], raw: Any, *, partial: bool = False) -> str | None:
    ctype = comp["type"]
    label = comp["label"]
    if ctype in ("text", "textarea", "phone", "email", "date", "time", "datetime-local", "password"):
        if not isinstance(raw, str):
            return f"{label}の形式が不正です"
        if ctype == "email" and not _EMAIL_RE.match(raw.strip()):
            return f"{label}はメールアドレスの形式で入力してください"
        if ctype == "phone" and not _PHONE_RE.match(raw.strip()):
            return f"{label}は電話番号の形式で入力してください"
        if ctype == "date" and not re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
            return f"{label}は日付（YYYY-MM-DD）で入力してください"
        if ctype == "time" and not re.match(r"^\d{2}:\d{2}$", raw):
            return f"{label}は時刻（HH:MM）で入力してください"
        if ctype == "datetime-local" and not re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", raw):
            return f"{label}は日時で入力してください"
        return None
    if ctype == "mynumber":
        if not isinstance(raw, str) or not re.match(r"^\d{12}$", raw.strip()):
            return f"{label}は12桁の数字で入力してください"
        if not mynumber_check_digit_ok(raw.strip()):
            return f"{label}の検査数字が正しくありません"
        return None
    if ctype == "daterange":
        if not isinstance(raw, dict) or not raw.get("start") or not raw.get("end"):
            return f"{label}は開始日と終了日が必要です"
        return None
    if ctype in ("slider", "rating"):
        try:
            n = float(raw)
        except (TypeError, ValueError):
            return f"{label}は数値で入力してください"
        if ctype == "rating" and not (1 <= n <= 5):
            return f"{label}は1〜5で入力してください"
        return None
    if ctype == "matrix_question":
        rows = [str(x) for x in (comp.get("properties") or {}).get("rows") or []]
        cols = [str(x) for x in (comp.get("properties") or {}).get("columns") or []]
        if not isinstance(raw, dict):
            return f"{label}の形式が不正です"
        for row, val in raw.items():
            if row not in rows:
                return f"{label}の行が不正です"
            if isinstance(val, list):
                if any(v not in cols for v in val):
                    return f"{label}の列が不正です"
            elif val not in cols:
                return f"{label}の列が不正です"
        return None
    if ctype == "signature_pad":
        if isinstance(raw, str) and raw.startswith("data:image"):
            return None
        if isinstance(raw, dict) and str(raw.get("file_id") or "").strip():
            return None
        return f"{label}の署名データが不正です"
    if ctype == "location":
        if not isinstance(raw, dict):
            return f"{label}の形式が不正です"
        try:
            lat = float(raw.get("lat"))
            lng = float(raw.get("lng"))
        except (TypeError, ValueError):
            return f"{label}は緯度・経度が必要です"
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return f"{label}の座標が不正です"
        return None
    if ctype == "qr_scanner":
        if not isinstance(raw, str) or not raw.strip():
            return f"{label}の形式が不正です"
        return None
    if ctype in ("image_recognition", "document_reader"):
        if isinstance(raw, str) and raw.strip():
            return None
        if isinstance(raw, dict) and (raw.get("filename") or raw.get("extracted")):
            return None
        return f"{label}のファイルまたは読取結果が必要です"
    if ctype == "number":
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            return f"{label}の形式が不正です"
        try:
            float(raw)
        except (TypeError, ValueError):
            return f"{label}は数値で入力してください"
        return None
    if ctype in ("select", "radio"):
        opts = _options_of(comp)
        if not isinstance(raw, str) or raw not in opts:
            return f"{label}の選択肢が不正です"
        return None
    if ctype == "checkbox":
        opts = _options_of(comp)
        if not isinstance(raw, list) or any(v not in opts for v in raw):
            return f"{label}の選択肢が不正です"
        return None
    if ctype == "file":
        if isinstance(raw, str) and raw.strip():
            return None
        if isinstance(raw, dict) and (raw.get("file_id") or raw.get("filename")):
            return None
        return f"{label}の形式が不正です"
    if ctype in COMPOSITE_SUBFIELDS:
        if not isinstance(raw, dict):
            return f"{label}の形式が不正です"
        keys = COMPOSITE_SUBFIELDS[ctype]
        required = list(COMPOSITE_REQUIRED_SUBFIELDS.get(ctype, []))
        if ctype == "financial_institution_composite":
            yuucho = _truthy(raw.get("is_yuucho"))
            if yuucho:
                required.extend(["yuucho_symbol", "yuucho_number"])
            else:
                required.extend(["bank_name", "account_number"])
        if not partial:
            for key in required:
                if not str(raw.get(key) or "").strip():
                    return f"{label}の必須項目が不足しています"
        if ctype == "address_composite":
            postal = str(raw.get("postal_code") or "").strip()
            if postal and not _POSTAL_RE.match(postal):
                return f"{label}の郵便番号が不正です"
        if ctype == "user_info_composite":
            if _prop_shown(comp, "show_gender"):
                gender = str(raw.get("gender") or "").strip()
                if gender and gender not in _GENDERS:
                    return f"{label}の性別が不正です"
            if _prop_shown(comp, "show_birth_date"):
                birth = str(raw.get("birth_date") or "").strip()
                if birth and not _DATE_RE.match(birth):
                    return f"{label}の生年月日が不正です"
        if ctype == "company_info_composite":
            corp = str(raw.get("corporate_number") or "").strip()
            if corp and not _CORP_RE.match(corp):
                return f"{label}の法人番号は13桁です"
            if corp and not corporate_check_digit_ok(corp):
                return f"{label}の法人番号の検査数字が正しくありません"
        if ctype == "financial_institution_composite":
            bank_code = str(raw.get("bank_code") or "").strip()
            branch_code = str(raw.get("branch_code") or "").strip()
            symbol = str(raw.get("yuucho_symbol") or "").strip()
            number = str(raw.get("yuucho_number") or "").strip()
            if bank_code and not _BANK_CODE_RE.match(bank_code):
                return f"{label}の金融機関コードは4桁です"
            if branch_code and not _BRANCH_CODE_RE.match(branch_code):
                return f"{label}の支店コードは3桁です"
            if symbol and not _YUCHO_SYMBOL_RE.match(symbol):
                return f"{label}の記号は3〜5桁です"
            if number and not _YUCHO_NUMBER_RE.match(number):
                return f"{label}の番号は数字8桁以内です"
        unknown = set(raw) - set(keys)
        if unknown:
            return f"{label}に未知の項目があります"
        return None
    if ctype == "calculated":
        return None
    return f"{label}は未対応の部品です"


def _safe_image_src(src: str) -> bool:
    return src.startswith(("https://", "http://", "data:image/"))


def _normalize_value(comp: dict[str, Any], raw: Any) -> Any:
    ctype = comp["type"]
    if ctype in ("slider", "rating"):
        return float(raw)
    if ctype == "location" and isinstance(raw, dict):
        return {"lat": float(raw["lat"]), "lng": float(raw["lng"])}
    if ctype in ("image_recognition", "document_reader"):
        if isinstance(raw, str):
            return {"filename": "", "extracted": raw.strip()}
        return {
            "filename": str(raw.get("filename") or ""),
            "extracted": str(raw.get("extracted") or ""),
        }
    if ctype == "qr_scanner":
        return str(raw).strip()
    if ctype == "file":
        if isinstance(raw, str):
            return {"filename": raw.strip()}
        return {
            "file_id": str(raw.get("file_id") or ""),
            "filename": str(raw.get("filename") or ""),
            "mime": str(raw.get("mime") or ""),
            "size": int(raw.get("size") or 0) if str(raw.get("size") or "0").isdigit() else 0,
        }
    if ctype == "signature_pad" and isinstance(raw, dict):
        return {
            "file_id": str(raw.get("file_id") or ""),
            "filename": str(raw.get("filename") or ""),
            "mime": str(raw.get("mime") or ""),
            "size": int(raw.get("size") or 0) if str(raw.get("size") or "0").isdigit() else 0,
        }
    if ctype == "user_info_composite" and isinstance(raw, dict):
        out = dict(raw)
        if not _prop_shown(comp, "show_gender"):
            out.pop("gender", None)
        if not _prop_shown(comp, "show_birth_date"):
            out.pop("birth_date", None)
        return out
    if ctype == "financial_institution_composite" and isinstance(raw, dict) and _truthy(
        raw.get("is_yuucho")
    ):
        converted = yuucho_to_branch(
            str(raw.get("yuucho_symbol") or ""),
            str(raw.get("yuucho_number") or ""),
        )
        out = dict(raw)
        for key, val in converted.items():
            if val and not str(out.get(key) or "").strip():
                out[key] = val
            elif key in ("bank_code", "bank_name") and val:
                out[key] = val
        if converted.get("branch_code"):
            out["branch_code"] = converted["branch_code"]
        if converted.get("account_number"):
            out["account_number"] = converted["account_number"]
        return out
    return raw
