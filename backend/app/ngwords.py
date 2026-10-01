"""禁止ワード/機密情報の入力制限（8-(8)）の読取・判定。

- ルールの書き込みは管理者限定 exApp（ngword-app）が担い、backend は
  **読み取り専用**で参照して推論前段（/predict 系・AIアプリ）で入力を検査する。
- ルール未設定/読取不可の場合は「制限なし（enabled=false）」として扱う。

ルール JSON:
    {
      "enabled": true,
      "case_sensitive": false,
      "check_mynumber": true,                 # 個人番号（検査数字一致）をブロック
      "words": ["禁止語1", "禁止語2"],         # 部分一致でブロック
      "patterns": ["\\\\d{3}-\\\\d{4}"]       # 正規表現(search)。\\d{12} 単体はマイナンバー検査に委譲
    }
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from typing import Any

from shared.mynumber import find_valid_mynumbers

NGWORD_DB_PATH = os.environ.get("NGWORD_DB_PATH", "/data/ngwords.db")
# 既定の棟。teams_store.DEFAULT_TENANT_ID と一致。
DEFAULT_TENANT_ID = os.environ.get(
    "DEFAULT_TENANT_ID", "00000000-0000-0000-0000-0000000000t1"
)

_DEFAULT: dict[str, Any] = {
    "enabled": False,
    "case_sensitive": False,
    "check_mynumber": True,
    "warn_attachments": True,
    "scan_knowledge_pii": True,
    "check_pii_ner": True,
    "words": [],
    "patterns": [],
}

# mtime ベースの簡易キャッシュ。棟（tenantId）ごとに rules/compiled を保持する。
_cache: dict[str, Any] = {"mtime": None, "by_tenant": {}}

# teamId 等の UUID をパターン／桁列検査から除外
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)

# 旧設定の「\\d{12}」はマイナンバー専用検査へ委譲（単純 12 桁一致はしない）
_DELEGATE_TO_MYNUMBER = frozenset(
    {
        r"\d{12}",
        r"[0-9]{12}",
        r"^\d{12}$",
        r"^[0-9]{12}$",
    }
)


def _mask_uuids(text: str) -> str:
    return _UUID_RE.sub("[UUID]", text)


def _is_mynumber_delegate_pattern(pattern: str) -> bool:
    return (pattern or "").strip() in _DELEGATE_TO_MYNUMBER


def _read_rules(tenant_id: str) -> dict[str, Any]:
    """棟別ルールを読む。行が無ければ制限なし（既定）。

    既定の棟だけは、未移行の旧・単一行（id=1）も後方互換で参照する。
    """
    if not os.path.exists(NGWORD_DB_PATH):
        return dict(_DEFAULT)
    try:
        conn = sqlite3.connect(f"file:{NGWORD_DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            row = None
            try:
                row = conn.execute(
                    "SELECT rules FROM ngword_rules_v2 WHERE tenantId = ?",
                    (tenant_id,),
                ).fetchone()
            except sqlite3.OperationalError:
                row = None  # v2 未作成（writer 未更新）。旧表へフォールバック。
            if (not row or not row[0]) and tenant_id == DEFAULT_TENANT_ID:
                try:
                    row = conn.execute(
                        "SELECT rules FROM ngword_rules WHERE id = 1"
                    ).fetchone()
                except sqlite3.OperationalError:
                    row = None
        finally:
            conn.close()
        if not row or not row[0]:
            return dict(_DEFAULT)
        data = json.loads(row[0])
        if not isinstance(data, dict):
            return dict(_DEFAULT)
        # 旧ルールにキーが無い場合は既定値を補完する
        for key, default in _DEFAULT.items():
            if key not in data:
                data[key] = default
        return data
    except Exception:  # noqa: BLE001 - 読取不可時は制限なし
        return dict(_DEFAULT)


def _load(tenant_id: str) -> tuple[dict[str, Any], list[re.Pattern[str]]]:
    tid = (tenant_id or "").strip() or DEFAULT_TENANT_ID
    try:
        mtime = os.path.getmtime(NGWORD_DB_PATH) if os.path.exists(NGWORD_DB_PATH) else None
    except OSError:
        mtime = None
    if mtime != _cache["mtime"]:
        _cache["mtime"] = mtime
        _cache["by_tenant"] = {}
    by_tenant = _cache["by_tenant"]
    if tid not in by_tenant:
        rules = _read_rules(tid)
        flags = 0 if rules.get("case_sensitive") else re.IGNORECASE
        compiled: list[re.Pattern[str]] = []
        for p in rules.get("patterns") or []:
            if _is_mynumber_delegate_pattern(str(p)):
                continue
            try:
                compiled.append(re.compile(p, flags))
            except re.error:
                continue  # 不正な正規表現は無視
        by_tenant[tid] = (rules, compiled)
    return by_tenant[tid]


def get_rules(tenant_id: str | None = None) -> dict[str, Any]:
    """指定した棟のルールを返す（管理画面の表示用・都度読取）。

    書き込みは ngword-app（単一ライター）が担うため、ここでは常に最新を読み取る。
    """
    return _read_rules((tenant_id or "").strip() or DEFAULT_TENANT_ID)


def check(text: str, tenant_id: str | None = None) -> tuple[bool, str | None]:
    """text が禁止語/機密パターンに該当するか。(blocked, 理由メッセージ)。

    判定は開いている棟（tenant_id）のルールで行う。
    """
    if not text:
        return False, None
    rules, compiled = _load((tenant_id or "").strip() or DEFAULT_TENANT_ID)
    if not rules.get("enabled"):
        return False, None

    case_sensitive = bool(rules.get("case_sensitive"))
    haystack = text if case_sensitive else text.lower()
    for w in rules.get("words") or []:
        if not w:
            continue
        needle = w if case_sensitive else w.lower()
        if needle in haystack:
            return True, f"禁止ワード「{w}」が含まれています。"

    pattern_text = _mask_uuids(text)

    # 個人番号: 12 桁かつ検査用数字が一致するものだけブロック
    if rules.get("check_mynumber", True):
        if find_valid_mynumbers(pattern_text):
            return True, "マイナンバー（個人番号）と推定される記載が含まれています。"

    for pat in compiled:
        if pat.search(pattern_text):
            return True, "機密情報とみなされる記載が含まれています。"
    return False, None
