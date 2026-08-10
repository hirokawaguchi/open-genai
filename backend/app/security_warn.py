"""本番向け: 既定のままの秘密情報が残っている場合に起動時警告を出す。"""

from __future__ import annotations

import os
import sys

# コード／example に現れる「未変更」とみなす値
_INSECURE_JWT = {
    "",
    "change-me-open-genai-secret",
    "please-change-to-a-long-random-secret",
}
_INSECURE_INTERNAL = {
    "",
    "please-change-to-a-long-random-secret",
    "change-me",
    "dev-internal-secret-change-me",
}
_INSECURE_KC_ADMIN_PW = {
    "",
    "admin",
    "password",
    "please-change-me",
}

_MIN_SECRET_LEN = 24


def _is_weak(value: str, insecure: set[str]) -> bool:
    v = (value or "").strip()
    if v in insecure:
        return True
    if v and len(v) < _MIN_SECRET_LEN:
        return True
    return False


def warn_insecure_defaults() -> None:
    """既定／弱い秘密情報が残っていれば stderr に設定ガイド付き警告を出す。起動は止めない。"""
    problems: list[str] = []

    jwt_secret = os.environ.get("APP_JWT_SECRET", "change-me-open-genai-secret")
    if _is_weak(jwt_secret, _INSECURE_JWT):
        problems.append(
            "APP_JWT_SECRET が未変更または短すぎます"
            "（JWT 偽造で全 API にアクセスされ得ます）"
        )

    internal = os.environ.get("INTERNAL_SIGNING_SECRET", "")
    if _is_weak(internal, _INSECURE_INTERNAL):
        problems.append(
            "INTERNAL_SIGNING_SECRET が未設定・未変更または短すぎます"
            "（exApp への x-user-* 偽装の余地）"
        )

    files_secret = os.environ.get("FILES_URL_SECRET", "")
    # 未設定なら APP_JWT_SECRET にフォールバックするため、JWT が弱いときだけ併記
    if files_secret and _is_weak(files_secret, _INSECURE_JWT | _INSECURE_INTERNAL):
        problems.append("FILES_URL_SECRET が未変更または短すぎます")

    kc_pw = os.environ.get("KEYCLOAK_ADMIN_PASSWORD", "")
    # 未設定（backend に渡していない）はスキップ。渡されていて既定なら警告。
    if kc_pw and _is_weak(kc_pw, _INSECURE_KC_ADMIN_PW):
        problems.append(
            "KEYCLOAK_ADMIN_PASSWORD が既定または短すぎます"
            "（/kc/ 管理コンソールが乗っ取られる可能性）"
        )

    if not problems:
        return

    lines = [
        "",
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
        "  [SECURITY] 既定のままの秘密情報が検出されました",
        "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
        "",
        "次を本番／閉域公開前に必ず変更してください:",
        "",
    ]
    for p in problems:
        lines.append(f"  - {p}")
    lines.extend(
        [
            "",
            "設定手順:",
            "  1. 乱数を生成:  openssl rand -hex 32",
            "  2. .env.prod（または .env）に設定:",
            "       APP_JWT_SECRET=<生成値>",
            "       INTERNAL_SIGNING_SECRET=<別の生成値>",
            "       KEYCLOAK_ADMIN_PASSWORD=<別の生成値>",
            "       # 任意: FILES_URL_SECRET=<別の生成値>",
            "  3. Keycloak 管理者パスワードは keycloak_data ボリューム",
            "     初回作成前に設定する（作成後は管理コンソールか",
            "     docker compose down -v で再作成が必要）。",
            "  4. realm 初期ユーザ (admin/password, user/password) を",
            "     無効化またはパスワード変更する。",
            "  詳細: README.md 「運用開始時（本番・閉域）— パスワード変更」",
            "",
            "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!",
            "",
        ]
    )
    print("\n".join(lines), file=sys.stderr, flush=True)
