"""内部サービス間認証（backend → exApp マイクロサービス）。

課題: exApp は同一 Docker ネットワーク内で API キー + `x-user-groups` を信頼する。
これらは内部到達できる攻撃者に偽装され得るため（管理者機能のバイパス）、backend が
「利用者ID・グループ・タグ・スコープ・時刻」に対して共有鍵で HMAC 署名を付与し、
exApp 側で検証する。

- `INTERNAL_SIGNING_SECRET` が未設定なら検証はスキップ（開発時の後方互換）。本番では
  必ず十分に長いランダム値を backend と全 exApp に同じ値で設定すること。
- 署名対象にタイムスタンプを含め、`INTERNAL_SIG_MAX_AGE` 秒を超えた署名は無効。
- `tags`（OpenGENAI 独自の共有タグ）も署名対象に含める。`x-user-tags` の偽装による
  タグ共有資産へのなりすまし閲覧を防ぐ。未使用時は空文字で全サービス整合。

本ファイルは各サービスの `app/intauth.py` に同一内容で配置する（各コンテナのビルド
コンテキストが異なり shared/ を共有できないため）。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

SECRET = os.environ.get("INTERNAL_SIGNING_SECRET", "")
MAX_AGE = int(os.environ.get("INTERNAL_SIG_MAX_AGE", "300"))


def _norm(values: str | None) -> str:
    # 順序非依存にするため正規化（空白除去・ソート・空要素除去）
    return ",".join(sorted(x.strip() for x in (values or "").split(",") if x.strip()))


def _canonical(
    user_id: str | None,
    groups: str | None,
    scope: str | None,
    ts: str,
    tags: str | None = None,
) -> str:
    return f"{user_id or ''}\n{_norm(groups)}\n{scope or ''}\n{_norm(tags)}\n{ts}"


def _compute(
    user_id: str | None,
    groups: str | None,
    scope: str | None,
    ts: str,
    tags: str | None = None,
) -> str:
    return hmac.new(
        SECRET.encode("utf-8"),
        _canonical(user_id, groups, scope, ts, tags).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def sign(
    user_id: str | None,
    groups: str | None,
    scope: str | None = "",
    tags: str | None = None,
) -> tuple[str, str]:
    """(ts, signature) を返す。SECRET 未設定でも ts/sig は返す（検証側で無視）。"""
    ts = str(int(time.time()))
    return ts, _compute(user_id, groups, scope, ts, tags)


def signed_headers(
    user_id: str | None,
    groups: str | None,
    scope: str | None = "",
    tags: str | None = None,
) -> dict[str, str]:
    ts, sig = sign(user_id, groups, scope, tags)
    return {"x-user-ts": ts, "x-user-sig": sig}


def verify(
    user_id: str | None,
    groups: str | None,
    scope: str | None,
    ts: str | None,
    sig: str | None,
    tags: str | None = None,
) -> bool:
    """署名を検証する。SECRET 未設定なら常に True（開発時）。

    scope も署名対象に含めるため、`x-scope` の改ざん（他チームへのなりすまし）も検知する。
    tags も署名対象に含めるため、`x-user-tags`（共有タグ）の改ざんも検知する。
    """
    if not SECRET:
        return True
    if not ts or not sig:
        return False
    try:
        if abs(int(time.time()) - int(ts)) > MAX_AGE:
            return False
    except ValueError:
        return False
    return hmac.compare_digest(_compute(user_id, groups, scope, ts, tags), sig)
