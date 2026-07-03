"""プロンプトテンプレート・カタログ（6-(20)(21)(22)）。

- 標準テンプレート(6-21): `is_standard=1`。全ユーザーに表示。
- 個人テンプレート(6-20): 作成者本人のみ表示（`owner_user`）。
- 組織/グループ共有(6-22): `shared_groups` に含まれるグループの利用者に表示。

テンプレートを選ぶと、本文（変数置換後）を **チャット画面へ流し込むディープリンク**
（`/chat?content=... または systemContext=...`）を返す。源内は無改修
（既存のクエリパラメータ取り込み経路を利用）。

パス非依存の純関数（変数解析・置換・ディープリンク生成）はテスト対象。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from typing import Any
from urllib.parse import quote

PROMPT_DB_PATH = os.environ.get("PROMPT_DB_PATH", "/data/prompts.db")

# チャット流し込みディープリンク(/chat?content=...)の最大URL長(パス+クエリ)。
# URL クエリ(GET)に全文を載せるため、これを超える長文はリンクを出さず「コピー運用」に
# フォールバックする。日本語は URL エンコードで約9倍に膨らむ点に注意。dev サーバ/プロキシ
# のヘッダ上限(概ね8〜16KB)や古い環境の ~2KB を考慮した既定値。
DEEPLINK_MAX_URL = int(os.environ.get("PROMPT_DEEPLINK_MAX_URL", "8000"))

_VAR_RE = re.compile(r"\{\{\s*([^}]+?)\s*\}\}")


# ---------------------------------------------------------------------------
# 純関数: 変数解析・置換・ディープリンク
# ---------------------------------------------------------------------------
def parse_vars(text: str | None) -> dict[str, str]:
    """`キー: 値` または `キー=値` を1行ずつ解析して辞書にする。"""
    result: dict[str, str] = {}
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        if ":" in line:
            k, v = line.split(":", 1)
        elif "=" in line:
            k, v = line.split("=", 1)
        else:
            continue
        k = k.strip()
        if k:
            result[k] = v.strip()
    return result


def substitute(body: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    """本文中の {{キー}} を値で置換する。未指定のキーは残し、その一覧を返す。"""
    missing: list[str] = []

    def _repl(m: re.Match[str]) -> str:
        key = m.group(1).strip()
        if key in variables:
            return variables[key]
        if key not in missing:
            missing.append(key)
        return m.group(0)

    return _VAR_RE.sub(_repl, body or ""), missing


def template_variables(body: str) -> list[str]:
    """本文に含まれる {{キー}} の一覧（重複なし）。"""
    seen: list[str] = []
    for m in _VAR_RE.finditer(body or ""):
        k = m.group(1).strip()
        if k not in seen:
            seen.append(k)
    return seen


def build_deeplink(text: str, target: str = "content", auto_submit: bool = False) -> str:
    """チャットへ流し込むディープリンクを作る。target=system で systemContext に入れる。"""
    key = "systemContext" if target == "system" else "content"
    auto = "true" if auto_submit else "false"
    return f"/chat?{key}={quote(text or '')}&autoSubmit={auto}"


def deeplink_if_fits(
    text: str, target: str = "content", auto_submit: bool = False
) -> str | None:
    """URL長が上限(DEEPLINK_MAX_URL)以内ならディープリンクを返す。超過なら None。

    長文を GET クエリに載せると URL 長制限で壊れるため、超過時はリンクを出さず
    呼び出し側で「コピーして貼り付け」運用に誘導する。
    """
    link = build_deeplink(text, target, auto_submit)
    return link if len(link) <= DEEPLINK_MAX_URL else None


# ---------------------------------------------------------------------------
# SQLite カタログ
# ---------------------------------------------------------------------------
def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(PROMPT_DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(PROMPT_DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS templates ("
            " id TEXT PRIMARY KEY,"
            " title TEXT NOT NULL,"
            " body TEXT NOT NULL,"
            " target TEXT NOT NULL DEFAULT 'content',"
            " ownerUser TEXT NOT NULL DEFAULT '',"
            " sharedGroups TEXT NOT NULL DEFAULT '[]',"
            " isStandard INTEGER NOT NULL DEFAULT 0,"
            " createdDate TEXT NOT NULL,"
            " updatedDate TEXT NOT NULL)"
        )


def _now() -> str:
    return str(int(time.time() * 1000))


def create_template(
    *,
    title: str,
    body: str,
    owner_user: str,
    target: str = "content",
    shared_groups: list[str] | None = None,
    is_standard: bool = False,
    template_id: str | None = None,
) -> str:
    tid = template_id or uuid.uuid4().hex[:8]
    now = _now()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO templates (id, title, body, target, ownerUser, sharedGroups,"
            " isStandard, createdDate, updatedDate) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                tid,
                title,
                body,
                target if target in ("content", "system") else "content",
                owner_user,
                json.dumps(shared_groups or [], ensure_ascii=False),
                1 if is_standard else 0,
                now,
                now,
            ),
        )
    return tid


def _row_to_dict(r: sqlite3.Row) -> dict[str, Any]:
    try:
        groups = json.loads(r["sharedGroups"])
    except (json.JSONDecodeError, TypeError):
        groups = []
    return {
        "id": r["id"],
        "title": r["title"],
        "body": r["body"],
        "target": r["target"],
        "ownerUser": r["ownerUser"],
        "sharedGroups": groups,
        "isStandard": bool(r["isStandard"]),
    }


def get_template(template_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        r = conn.execute("SELECT * FROM templates WHERE id = ?", (template_id,)).fetchone()
    return _row_to_dict(r) if r else None


def list_visible(user_id: str, team_ids: list[str], is_admin: bool) -> list[dict[str, Any]]:
    """標準＋自分＋チーム共有＋全体公開のテンプレートを返す。

    共有先（列名は歴史的経緯で `sharedGroups` のままだが、意味は「共有先チームID」）と
    利用者の所属チーム(`team_ids`)の積集合で可視性を判定する。予約値 `public` は
    全利用者が暗黙保持し、全体公開を表す。
    """
    ut = set(team_ids or []) | {"public"}
    out: list[dict[str, Any]] = []
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM templates ORDER BY isStandard DESC, title").fetchall()
    for r in rows:
        t = _row_to_dict(r)
        visible = (
            is_admin
            or t["isStandard"]
            or (t["ownerUser"] and t["ownerUser"] == user_id)
            or bool(ut.intersection(t["sharedGroups"]))
        )
        if visible:
            out.append(t)
    return out


def can_delete(t: dict[str, Any], user_id: str, is_admin: bool) -> bool:
    if is_admin:
        return True
    if t.get("isStandard"):
        return False  # 標準は管理者のみ
    return bool(t.get("ownerUser") and t["ownerUser"] == user_id)


def delete_template(template_id: str) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM templates WHERE id = ?", (template_id,))


def count() -> int:
    with _connect() as conn:
        r = conn.execute("SELECT COUNT(*) AS c FROM templates").fetchone()
    return r["c"] if r else 0
