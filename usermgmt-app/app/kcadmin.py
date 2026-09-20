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
    "givenname": "firstName",
    "given_name": "firstName",
    "名": "firstName",
    "lastname": "lastName",
    "last_name": "lastName",
    "familyname": "lastName",
    "family_name": "lastName",
    "姓": "lastName",
    "name": "name",
    "displayname": "name",
    "password": "password",
    "groups": "groups",
    "group": "groups",
    "enabled": "enabled",
    "temporary": "temporary",
    # 棟（テナント）。ID か棟名を書ける。解決・検証は backend 側で行う。
    "tenant": "tenant",
    "tenantid": "tenant",
    "tenant_id": "tenant",
    "tenantname": "tenant",
    "tenant_name": "tenant",
    "テナント": "tenant",
    "棟": "tenant",
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


def _split_japanese_name(name: str) -> tuple[str, str]:
    """表示名「姓 名」を Keycloak の lastName / firstName に分ける。1語なら姓側へ。"""
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    return (parts[0] if parts else ""), ""


def build_user_representation(row: dict[str, str]) -> dict[str, Any]:
    """Keycloak のユーザ表現(UserRepresentation) を組み立てる。

    - name のみ指定で firstName/lastName 未指定なら、空白区切りなら「姓 名」に分割する。
      1語のときは lastName（表示名の先頭＝姓側）に入れる。
    - password 指定時は credentials を付与（temporary は列で上書き可、既定 false）。
    """
    rep: dict[str, Any] = {
        "username": row["username"],
        "enabled": _to_bool(row.get("enabled"), True),
    }
    if row.get("email"):
        rep["email"] = row["email"]
        rep["emailVerified"] = True
    first = (row.get("firstName") or "").strip()
    last = (row.get("lastName") or "").strip()
    if not first and not last and row.get("name"):
        last, first = _split_japanese_name(row["name"])
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
                "email": row.get("email", ""),
                "action": action,
                "groups": parse_groups(row.get("groups")),
                # 棟は Keycloak には保存しない。backend が解決・付与するため素通しで返す。
                "tenant": (row.get("tenant") or "").strip(),
                "rep": build_user_representation(row) if action != "delete" and not err else None,
                "error": err,
            }
        )
    return planned
