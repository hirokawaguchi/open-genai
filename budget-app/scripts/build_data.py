#!/usr/bin/env python3
"""令和6年度の市町村別決算状況調から、サンキー用のJSONを作る。

総務省の公表Excelは、歳入・目的別歳出・性質別歳出が別表である。
目的と性質を一本の帯でつなぐクロス表はこの資料にない。
各表の合計が概況の歳入総額・歳出総額と一致することを全市区町村で確認する。

金額の単位は千円。団体コードは6桁。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
OUT = ROOT / "app" / "data" / "fy2024.json"

BASE = "https://www.soumu.go.jp/main_content/"
FILES = {
    "city": {
        "overview": "001061669.xlsx",
        "rev": "001061670.xlsx",
        "purpose": "001061671.xlsx",
        "nature": "001061672.xlsx",
    },
    "town": {
        "overview": "001061674.xlsx",
        "rev": "001061675.xlsx",
        "purpose": "001061676.xlsx",
        "nature": "001061677.xlsx",
    },
}

# 歳入は款の合計列だけを取る。内訳列を足すと二重になる。
REVENUE = [
    (16, "地方税"),
    (23, "地方譲与税"),
    (24, "利子割交付金"),
    (25, "配当割交付金"),
    (26, "株式等譲渡所得割交付金"),
    (27, "分離課税所得割交付金"),
    (28, "地方消費税交付金"),
    (29, "ゴルフ場利用税交付金"),
    (30, "自動車取得税交付金"),
    (31, "軽油引取税交付金"),
    (32, "自動車税環境性能割交付金"),
    (33, "法人事業税交付金"),
    (34, "地方特例交付金等"),
    (38, "地方交付税"),
    (42, "交通安全対策特別交付金"),
    (43, "分担金及び負担金"),
    (46, "使用料"),
    (53, "手数料"),
    (56, "国庫支出金"),
    (77, "国有提供施設等所在市町村助成交付金"),
    (78, "都道府県支出金"),
    (96, "財産収入"),
    (99, "寄附金"),
    (103, "繰入金"),
    (104, "繰越金"),
    (107, "諸収入"),
    (115, "地方債"),
    (116, "特別区財政調整交付金"),
]

# 労働費と諸支出金は合計列がなく、項の合計が款になる。
PURPOSE = [
    ("議会費", [16]),
    ("総務費", [17]),
    ("民生費", [24]),
    ("衛生費", [30]),
    ("労働費", [35, 36]),
    ("農林水産業費", [37]),
    ("商工費", [43]),
    ("土木費", [44]),
    ("消防費", [56]),
    ("教育費", [57]),
    ("災害復旧費", [68]),
    ("公債費", [90]),
    ("諸支出金", [91, 92, 93]),
    ("前年度繰上充用金", [94]),
]

NATURE = [
    ("人件費", [16]),
    ("物件費", [135]),
    ("維持補修費", [143]),
    ("扶助費", [144]),
    ("補助費等", [145]),
    ("普通建設事業費", [150]),
    ("災害復旧事業費", [167]),
    ("失業対策事業費", [174]),
    ("公債費", [178]),
    ("積立金", [181]),
    ("投資及び出資金", [182]),
    ("貸付金", [183]),
    ("繰出金", [184]),
    ("前年度繰上充用金", [185]),
]

OVERVIEW_POP = 16
OVERVIEW_STRENGTH = 34
OVERVIEW_CURRENT = 29
OVERVIEW_REV = 39
OVERVIEW_EXP = 40
OVERVIEW_BALANCE = 41

DASHES = {"-", "－", "―", "ー", "–", "—", "…"}
SPACE_RE = re.compile(r"[\s\u3000]+")


def download(name: str) -> Path:
    dest = RAW / name
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = BASE + name
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    print(f"download {url}", file=sys.stderr)
    with urllib.request.urlopen(req, timeout=180) as resp:
        dest.write_bytes(resp.read())
    return dest


def num(value) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise ValueError(f"unexpected bool: {value!r}")
    if isinstance(value, (int, float)):
        return int(round(value))
    text = str(value).strip().replace(",", "").replace("，", "")
    if text in DASHES:
        return 0
    return int(round(float(text)))


def maybe_float(value):
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in DASHES:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def code_of(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, int):
        return f"{value:06d}"
    if isinstance(value, str) and value.strip().isdigit():
        return value.strip().zfill(6)
    return None


def clean_name(value) -> str:
    return SPACE_RE.sub("", str(value or "")).strip()


def cell(row, index):
    if index >= len(row):
        return None
    return row[index]


def grouped(row, spec) -> list[int]:
    return [sum(num(cell(row, index)) for index in indexes) for _, indexes in spec]


def plain(row, spec) -> list[int]:
    return [num(cell(row, index)) for index, _name in spec]


def load_rows(path: Path) -> dict[str, dict]:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    found: dict[str, dict] = {}
    pref = ""
    for row in ws.iter_rows(min_row=16, values_only=True):
        code = code_of(cell(row, 14))
        name = clean_name(cell(row, 15))
        if code is None:
            if name.endswith(("都", "道", "府", "県")) and "計" not in name:
                pref = name
            continue
        if code in found:
            raise SystemExit(f"duplicate code {code} in {path.name}")
        found[code] = {"name": name, "pref": pref, "row": row}
    wb.close()
    return found


def assert_header(path: Path, expected: str) -> None:
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = []
    for index, row in enumerate(ws.iter_rows(max_row=12, values_only=True)):
        rows.append(row)
        if index >= 11:
            break
    blob = " ".join(
        str(value or "")
        for row in rows
        for value in row
    )
    wb.close()
    if expected not in blob:
        raise SystemExit(f"{path.name} の見出しに {expected} がない: {blob!r}")


def build() -> dict:
    paths = {kind: {key: download(name) for key, name in files.items()} for kind, files in FILES.items()}
    for kind in paths.values():
        assert_header(kind["rev"], "地方税")
        assert_header(kind["purpose"], "議会費")
        assert_header(kind["nature"], "人件費")
        assert_header(kind["overview"], "歳入総額")

    rows = []
    errors = []
    for kind, files in paths.items():
        overview = load_rows(files["overview"])
        revenue = load_rows(files["rev"])
        purpose = load_rows(files["purpose"])
        nature = load_rows(files["nature"])
        codes = set(overview) & set(revenue) & set(purpose) & set(nature)
        missing = (set(overview) | set(revenue) | set(purpose) | set(nature)) - codes
        if missing:
            sample = ", ".join(sorted(missing)[:8])
            raise SystemExit(f"{kind}: 表のあいだで団体が揃わない ({len(missing)}): {sample}")
        for code in sorted(codes):
            ov = overview[code]["row"]
            rev_values = plain(revenue[code]["row"], REVENUE)
            purpose_values = grouped(purpose[code]["row"], PURPOSE)
            nature_values = grouped(nature[code]["row"], NATURE)
            rev_total = num(cell(ov, OVERVIEW_REV))
            exp_total = num(cell(ov, OVERVIEW_EXP))
            balance = num(cell(ov, OVERVIEW_BALANCE))
            rev_sum = sum(rev_values)
            purpose_sum = sum(purpose_values)
            nature_sum = sum(nature_values)
            # 公表表は千円単位で、科目合計と総額が1千円だけずれる団体がある。
            if (
                abs(rev_sum - rev_total) > 1
                or abs(purpose_sum - exp_total) > 1
                or abs(nature_sum - exp_total) > 1
                or abs(purpose_sum - nature_sum) > 1
            ):
                errors.append(
                    f"{code} {overview[code]['name']}: "
                    f"歳入 {rev_sum}/{rev_total} "
                    f"目的 {purpose_sum}/{exp_total} "
                    f"性質 {nature_sum}/{exp_total}"
                )
            if abs((rev_total - exp_total) - balance) > 1:
                errors.append(
                    f"{code} {overview[code]['name']}: 差引 {balance} != {rev_total - exp_total}"
                )
            rev_total = rev_sum
            exp_total = purpose_sum
            balance = rev_total - exp_total
            nature_gap = exp_total - nature_sum
            if nature_gap:
                largest = max(range(len(nature_values)), key=lambda index: nature_values[index])
                nature_values[largest] += nature_gap
            if not overview[code]["pref"]:
                errors.append(f"{code} {overview[code]['name']}: 都道府県が空")
            rows.append(
                {
                    "code": code,
                    "name": overview[code]["name"],
                    "pref": overview[code]["pref"],
                    "pop": num(cell(ov, OVERVIEW_POP)),
                    "revTotal": rev_total,
                    "expTotal": exp_total,
                    "balance": balance,
                    "strength": maybe_float(cell(ov, OVERVIEW_STRENGTH)),
                    "currentRatio": maybe_float(cell(ov, OVERVIEW_CURRENT)),
                    "rev": rev_values,
                    "purpose": purpose_values,
                    "nature": nature_values,
                }
            )
    if errors:
        print("\n".join(errors[:30]), file=sys.stderr)
        raise SystemExit(f"整合チェックに失敗: {len(errors)} 件")

    rows.sort(key=lambda row: row["code"])
    codes = [row["code"] for row in rows]
    if len(codes) != len(set(codes)):
        raise SystemExit("都市分と町村分で団体コードが重複している")
    sapporo = next(row for row in rows if row["code"] == "011002")
    if sapporo["name"] != "札幌市" or sapporo["pop"] != 1_955_678:
        raise SystemExit(f"札幌市の照合に失敗: {sapporo['name']} pop={sapporo['pop']}")
    if sapporo["revTotal"] != 1_239_448_780 or sapporo["expTotal"] != 1_229_157_420:
        raise SystemExit("札幌市の歳入・歳出が公表値と一致しない")
    if not any(row["code"] == "442011" and row["name"] == "大分市" for row in rows):
        raise SystemExit("大分市が見つからない")
    if not 1700 <= len(rows) <= 1800:
        raise SystemExit(f"団体数が想定外: {len(rows)}")

    return {
        "year": 2024,
        "label": "令和6年度",
        "basis": "普通会計・決算",
        "unit": "千円",
        "source": "総務省「令和6年度 市町村別決算状況調」",
        "sourceUrl": "https://www.soumu.go.jp/iken/zaisei/r06_shichouson.html",
        "revenue": [name for _, name in REVENUE],
        "purpose": [name for name, _ in PURPOSE],
        "nature": [name for name, _ in NATURE],
        "rows": rows,
    }


def main() -> None:
    payload = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {OUT} municipalities={len(payload['rows'])} bytes={OUT.stat().st_size}")


if __name__ == "__main__":
    main()
