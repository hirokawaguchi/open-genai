"""CSV パースと Keycloak ユーザ表現の組み立て（純ロジック・テスト対象）。

ネットワーク非依存の関数のみを置き、Keycloak Admin API 呼び出し(main.py)から使う。
"""

from __future__ import annotations

import csv
import io
from typing import Any

VALID_ACTIONS = ("upsert", "create", "update", "delete")

# CSV 見出しの別名（小文字化して照合）
_ALIASES = {
    "action": "action",
    "username": "username",
    "user": "username",
    "email": "email",
    "mail": "email",
    "firstname": "firstName",
    "first_name": "firstName",
    "lastname": "lastName",
    "last_name": "lastName",
    "name": "name",
    "displayname": "name",
    "password": "password",
    "groups": "groups",
    "group": "groups",
    "enabled": "enabled",
    "temporary": "temporary",
}


def _to_bool(value: str | None, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() not in ("false", "0", "no", "off", "いいえ")


def parse_groups(value: str | None) -> list[str]:
    """';' または ',' 区切りのグループ名リスト。先頭 '/' は除去。"""
    if not value:
        return []
    parts: list[str] = []
    for chunk in value.replace(";", ",").split(","):
        g = chunk.strip().lstrip("/").strip()
        if g:
            parts.append(g)
    return parts


def parse_csv(text: str) -> list[dict[str, str]]:
    """CSV テキストを行辞書のリストに変換する（見出しは別名正規化）。"""
    text = text.lstrip("\ufeff")  # BOM 除去
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for raw in reader:
        row: dict[str, str] = {}
        for k, v in raw.items():
            if k is None:
                continue
            key = _ALIASES.get(k.strip().lower())
            if key:
                row[key] = (v or "").strip()
        if any(row.values()):
            rows.append(row)
    return rows


def validate_row(row: dict[str, str]) -> str | None:
    """行の妥当性を検査。問題があればエラーメッセージ、無ければ None。"""
    action = (row.get("action") or "upsert").strip().lower()
    if action not in VALID_ACTIONS:
        return f"不正な action: {action}（{'/'.join(VALID_ACTIONS)} のいずれか）"
    if not row.get("username"):
        return "username は必須です"
    if action in ("create", "upsert") and not row.get("email"):
        # email 未指定でも作成は可能だが、SAML 属性として推奨のため警告扱いにしない
        return None
    return None


def normalized_action(row: dict[str, str]) -> str:
    return (row.get("action") or "upsert").strip().lower()


def build_user_representation(row: dict[str, str]) -> dict[str, Any]:
    """Keycloak のユーザ表現(UserRepresentation) を組み立てる。

    - name のみ指定で firstName/lastName 未指定なら firstName に name を入れる。
    - password 指定時は credentials を付与（temporary は列で上書き可、既定 false）。
    """
    rep: dict[str, Any] = {
        "username": row["username"],
        "enabled": _to_bool(row.get("enabled"), True),
    }
    if row.get("email"):
        rep["email"] = row["email"]
        rep["emailVerified"] = True
    first = row.get("firstName")
    last = row.get("lastName")
    if not first and row.get("name"):
        first = row["name"]
    if first:
        rep["firstName"] = first
    if last:
        rep["lastName"] = last
    if row.get("password"):
        rep["credentials"] = [
            {
                "type": "password",
                "value": row["password"],
                "temporary": _to_bool(row.get("temporary"), False),
            }
        ]
    return rep


def plan_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """各行を (action, username, rep, groups, error) の計画に変換する。"""
    planned: list[dict[str, Any]] = []
    for row in rows:
        err = validate_row(row)
        action = normalized_action(row)
        planned.append(
            {
                "username": row.get("username", ""),
                "action": action,
                "groups": parse_groups(row.get("groups")),
                "rep": build_user_representation(row) if action != "delete" and not err else None,
                "error": err,
            }
        )
    return planned
