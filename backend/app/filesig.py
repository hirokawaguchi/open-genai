"""添付ファイル URL の短命 HMAC 署名。

`/files/{key}` は img タグ等のため Authorization ヘッダを付けられない。
代わりにクエリ `exp` / `sig` で method+key を署名し、漏洩した key だけでは
読み書きできないようにする。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from urllib.parse import unquote, urlencode

# 未設定時は APP_JWT_SECRET を流用（auth モジュールは重い依存のためここでは import しない）
FILES_URL_SECRET = os.environ.get("FILES_URL_SECRET") or os.environ.get(
    "APP_JWT_SECRET", "change-me-open-genai-secret"
)

TTL_PUT = int(os.environ.get("FILES_URL_TTL_PUT", "900"))  # 15 分
TTL_GET = int(os.environ.get("FILES_URL_TTL_GET", "3600"))  # 1 時間
TTL_DELETE = int(os.environ.get("FILES_URL_TTL_DELETE", "900"))

_METHOD_TTL = {
    "PUT": TTL_PUT,
    "GET": TTL_GET,
    "DELETE": TTL_DELETE,
}


def _sign_payload(method: str, key: str, exp: int) -> str:
    msg = f"{method.upper()}\n{key}\n{exp}".encode("utf-8")
    return hmac.new(FILES_URL_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()


def sign_query(method: str, key: str, ttl: int | None = None) -> dict[str, str]:
    """署名クエリ (exp, sig) を返す。"""
    method_u = method.upper()
    if ttl is None:
        ttl = _METHOD_TTL.get(method_u, TTL_GET)
    exp = int(time.time()) + max(1, int(ttl))
    return {"exp": str(exp), "sig": _sign_payload(method_u, key, exp)}


def build_signed_url(base_url: str, key: str, method: str, ttl: int | None = None) -> str:
    """`{base}/files/{key}?exp=...&sig=...` を組み立てる。"""
    q = urlencode(sign_query(method, key, ttl=ttl))
    return f"{base_url.rstrip('/')}/files/{key}?{q}"


def build_signed_path(key: str, method: str = "GET", ttl: int | None = None) -> str:
    """ホストを含まない `/api/files/{key}?exp&sig`。

    ページを開いたホストのまま取得する。絶対 URL にすると、別ホストの画面から
    そのホストへ直接取りにいってしまう。
    """
    return build_signed_url("/api", key, method, ttl=ttl)


def file_key_from_stored_url(url: str) -> str | None:
    """保存済みの files URL からオブジェクトキーを取り出す。

    `/api/files/<key>?exp&sig` と `https://host/api/files/<key>?...` の両方。
    """
    if not isinstance(url, str) or not url or url.startswith(("data:", "blob:")):
        return None
    path = url.split("?", 1)[0]
    marker = "/files/"
    idx = path.find(marker)
    if idx < 0:
        return None
    key = unquote(path[idx + len(marker) :])
    if not key or key.startswith(("/", "..")) or key != os.path.normpath(key):
        return None
    return key


def resign_stored_file_url(url: str, method: str = "GET", ttl: int | None = None) -> str:
    """期限切れの署名を、同じキーの新しい相対パスへ付け替える。"""
    key = file_key_from_stored_url(url)
    if not key:
        return url
    return build_signed_path(key, method, ttl=ttl)


IMAGE_RESULT_EXTRA_NAME = "open-genai-generated-image"


def refresh_image_result_urls(messages: list[dict]) -> list[dict]:
    """履歴表示用に、画像結果へ埋め込んだ署名 URL を付け直す。

    署名は短命なので、保存した URL をそのまま img に渡すと時間経過で 403 になる。
    DB は書き換えず、返す直前だけ新しい署名を付ける。
    """
    for message in messages:
        extra = message.get("extraData")
        if not isinstance(extra, list):
            continue
        for entry in extra:
            if not isinstance(entry, dict) or entry.get("name") != IMAGE_RESULT_EXTRA_NAME:
                continue
            source = entry.get("source")
            if not isinstance(source, dict) or source.get("type") != "json":
                continue
            raw = source.get("data")
            if not isinstance(raw, str) or not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            changed = False
            images = payload.get("images")
            if isinstance(images, list):
                for image in images:
                    if isinstance(image, dict) and isinstance(image.get("fileUrl"), str):
                        fresh = resign_stored_file_url(image["fileUrl"])
                        if fresh != image["fileUrl"]:
                            image["fileUrl"] = fresh
                            changed = True
            source_image = payload.get("sourceImage")
            if isinstance(source_image, dict) and isinstance(source_image.get("fileUrl"), str):
                fresh = resign_stored_file_url(source_image["fileUrl"])
                if fresh != source_image["fileUrl"]:
                    source_image["fileUrl"] = fresh
                    changed = True
            if changed:
                source["data"] = json.dumps(payload, ensure_ascii=False)
    return messages


def verify(method: str, key: str, exp: str | None, sig: str | None) -> bool:
    """署名と有効期限を検証する。"""
    if not exp or not sig:
        return False
    try:
        exp_i = int(exp)
    except (TypeError, ValueError):
        return False
    if exp_i < int(time.time()):
        return False
    expected = _sign_payload(method.upper(), key, exp_i)
    return hmac.compare_digest(expected, sig)
