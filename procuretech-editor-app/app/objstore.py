"""オブジェクトストレージ（S3 互換）連携（procuretech-editor 専用）。

OpenGENAI の思想（マネージドサービスに依存しない）に合わせ、案件フォルダ内の
生成文書（Markdown / Excel / 画像 / 変換済み Word など）を自前ホストの S3 互換
サーバ（SeaweedFS / MinIO 等）に保存する。接続は boto3 で抽象化し、`endpoint_url`
を差し替えるだけで別の S3 互換ストレージへ移行できる。

backend の `app/objstore.py` と同じ環境変数（`S3_*`）を共有しつつ、キーの接頭辞のみ
`EDITOR_S3_PREFIX`（既定 `procuretech-editor`）で分離する。オブジェクトキーは
`store.py` 側で `<prefix>/<user_hash>/<project_id>/<uuid>-<name>` の形で採番し、
本モジュールは与えられたキーに対する put/get/delete/copy/list/presign を提供する。

未設定時・boto3 不在時は無効（`is_configured()` が False）としてフォールバックする。
"""

from __future__ import annotations

import os
import re
from typing import Any
from urllib.parse import urlparse

S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "").rstrip("/")
S3_PUBLIC_ENDPOINT = (os.environ.get("S3_PUBLIC_ENDPOINT") or S3_ENDPOINT_URL).rstrip("/")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
S3_ADDRESSING_STYLE = os.environ.get("S3_ADDRESSING_STYLE", "path")
S3_PRESIGN_EXPIRY = int(os.environ.get("S3_PRESIGN_EXPIRY", str(24 * 3600)))
# editor 専用の接頭辞（backend の成果物 exapp/ と混在させない）
EDITOR_S3_PREFIX = os.environ.get("EDITOR_S3_PREFIX", "procuretech-editor").strip("/")


def is_configured() -> bool:
    return bool(S3_ENDPOINT_URL and S3_BUCKET and S3_ACCESS_KEY and S3_SECRET_KEY)


_SAFE_RE = re.compile(r"[^A-Za-z0-9._\-]+")


def sanitize_filename(name: str | None) -> str:
    """キー/表示に安全なファイル名へ整える（パス区切りは落とす）。"""
    base = (name or "").strip().replace("\\", "/").split("/")[-1]
    base = _SAFE_RE.sub("_", base).strip("._-")
    return base or "file"


def _client(endpoint: str) -> Any:
    """boto3 の S3 クライアントを作る（遅延 import）。"""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=S3_REGION,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": S3_ADDRESSING_STYLE},
        ),
    )


def _ensure_bucket(client: Any) -> None:
    try:
        client.head_bucket(Bucket=S3_BUCKET)
    except Exception:  # noqa: BLE001 - 無ければ作成を試みる
        try:
            client.create_bucket(Bucket=S3_BUCKET)
        except Exception as e:  # noqa: BLE001
            print(f"[editor-objstore] バケット作成に失敗（既存の可能性）: {e}")


def put_bytes(key: str, data: bytes, *, content_type: str | None = None) -> bool:
    """バイト列を指定キーへ保存する。成功で True。"""
    if not is_configured():
        return False
    try:
        c = _client(S3_ENDPOINT_URL)
        _ensure_bucket(c)
        c.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[editor-objstore] put 失敗 key={key}: {e}")
        return False


def get_bytes(key: str) -> bytes | None:
    """指定キーの内容を取得する。存在しなければ None。"""
    if not is_configured():
        return None
    try:
        c = _client(S3_ENDPOINT_URL)
        res = c.get_object(Bucket=S3_BUCKET, Key=key)
        return res["Body"].read()
    except Exception as e:  # noqa: BLE001
        print(f"[editor-objstore] get 失敗 key={key}: {e}")
        return None


def delete_key(key: str) -> bool:
    if not is_configured() or not key:
        return False
    try:
        c = _client(S3_ENDPOINT_URL)
        c.delete_object(Bucket=S3_BUCKET, Key=key)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[editor-objstore] delete 失敗 key={key}: {e}")
        return False


def delete_keys(keys: list[str]) -> int:
    """複数キーを削除し、削除できた件数を返す。"""
    n = 0
    for k in keys:
        if k and delete_key(k):
            n += 1
    return n


def copy_key(src_key: str, dst_key: str) -> bool:
    """S3 内でオブジェクトを複製する。"""
    if not is_configured():
        return False
    try:
        c = _client(S3_ENDPOINT_URL)
        c.copy_object(
            Bucket=S3_BUCKET,
            Key=dst_key,
            CopySource={"Bucket": S3_BUCKET, "Key": src_key},
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[editor-objstore] copy 失敗 {src_key}->{dst_key}: {e}")
        return False


def list_prefix(prefix: str) -> list[dict[str, Any]]:
    """接頭辞配下のオブジェクトを列挙する（key/size を返す）。"""
    if not is_configured():
        return []
    out: list[dict[str, Any]] = []
    try:
        c = _client(S3_ENDPOINT_URL)
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": S3_BUCKET, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            res = c.list_objects_v2(**kwargs)
            for obj in res.get("Contents", []) or []:
                out.append({"key": obj["Key"], "size": int(obj.get("Size", 0))})
            if res.get("IsTruncated"):
                token = res.get("NextContinuationToken")
            else:
                break
    except Exception as e:  # noqa: BLE001
        print(f"[editor-objstore] list 失敗 prefix={prefix}: {e}")
    return out


def presign_get(
    key: str, *, filename: str | None = None, expiry: int | None = None
) -> str | None:
    """指定キーの署名付き GET URL を公開エンドポイントで生成する。"""
    if not is_configured() or not key:
        return None
    exp = expiry or S3_PRESIGN_EXPIRY
    params: dict[str, Any] = {"Bucket": S3_BUCKET, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = (
            f'attachment; filename="{sanitize_filename(filename)}"'
        )
    try:
        signer = _client(S3_PUBLIC_ENDPOINT)
        url = signer.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=exp
        )
        # 内部と公開でホストが異なる場合、生成 URL のホストを公開側へ寄せる
        if S3_PUBLIC_ENDPOINT and S3_PUBLIC_ENDPOINT != S3_ENDPOINT_URL:
            pub = urlparse(S3_PUBLIC_ENDPOINT)
            gen = urlparse(url)
            url = gen._replace(scheme=pub.scheme, netloc=pub.netloc).geturl()
        return url
    except Exception as e:  # noqa: BLE001
        print(f"[editor-objstore] presign 失敗 key={key}: {e}")
        return None
