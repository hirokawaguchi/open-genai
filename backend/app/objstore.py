"""オブジェクトストレージ（S3 互換）連携。

OpenGENAI の思想（マネージドサービスを使わない）に合わせ、自前ホストの
**OSS S3 互換サーバ（SeaweedFS 等）** に成果物を保存し、**署名付き URL**で
利用者へ受け渡す。接続先は S3 API（boto3）で抽象化しており、SeaweedFS /
MinIO / その他 S3 互換に `endpoint_url` を向けるだけで差し替え可能。

配信経路の都合上、内部アップロード用エンドポイント（`S3_ENDPOINT_URL`）と、
利用者がアクセスする公開エンドポイント（`S3_PUBLIC_ENDPOINT`）を分離できる。

未設定時・boto3 不在時は無効（`is_configured()` が False）としてフォールバック。
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import unquote, urlparse

S3_ENDPOINT_URL = os.environ.get("S3_ENDPOINT_URL", "").rstrip("/")
# 署名付き URL 生成に使う公開エンドポイント（未指定なら内部と同じ）
S3_PUBLIC_ENDPOINT = (os.environ.get("S3_PUBLIC_ENDPOINT") or S3_ENDPOINT_URL).rstrip("/")
S3_REGION = os.environ.get("S3_REGION", "us-east-1")
S3_BUCKET = os.environ.get("S3_BUCKET", "")
S3_ACCESS_KEY = os.environ.get("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.environ.get("S3_SECRET_KEY", "")
# 署名付き URL の有効期限（秒）。既定 24 時間。
S3_PRESIGN_EXPIRY = int(os.environ.get("S3_PRESIGN_EXPIRY", str(24 * 3600)))
# SeaweedFS / MinIO は path-style が無難
S3_ADDRESSING_STYLE = os.environ.get("S3_ADDRESSING_STYLE", "path")
S3_KEY_PREFIX = os.environ.get("S3_KEY_PREFIX", "exapp")
# 成果物の保持日数（0 で自動削除を無効化）。超過分は日次パージで削除する。
S3_ARTIFACT_RETENTION_DAYS = int(os.environ.get("S3_ARTIFACT_RETENTION_DAYS", "30"))
S3_ARTIFACT_PURGE_INTERVAL = int(
    os.environ.get("S3_ARTIFACT_PURGE_INTERVAL", str(24 * 3600))
)


def is_configured() -> bool:
    return bool(S3_ENDPOINT_URL and S3_BUCKET and S3_ACCESS_KEY and S3_SECRET_KEY)


_SAFE_RE = re.compile(r"[^A-Za-z0-9._\-]+")


def sanitize_filename(name: str | None) -> str:
    """キー/表示に安全なファイル名へ整える。"""
    base = (name or "").strip().replace("\\", "/").split("/")[-1]
    base = _SAFE_RE.sub("_", base).strip("._-")
    return base or "file"


def _opaque_user_segment(user_id: str | None) -> str:
    """ユーザ ID をオブジェクトキー用の不可逆 ID に変換する（URL に PII を載せない）。"""
    uid = (user_id or "").strip()
    if not uid:
        return "anon"
    return hashlib.sha256(uid.encode("utf-8")).hexdigest()[:32]


def build_key(user_id: str | None, filename: str | None) -> str:
    """`<prefix>/<user_hash>/<uuid>/<filename>` のオブジェクトキーを作る。"""
    return "/".join(
        [
            S3_KEY_PREFIX,
            _opaque_user_segment(user_id),
            uuid.uuid4().hex,
            sanitize_filename(filename),
        ]
    )


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
            print(f"[objstore] バケット作成に失敗（既存の可能性）: {e}")


def put_and_presign(
    data: bytes,
    *,
    filename: str,
    content_type: str | None,
    user_id: str | None,
    expiry: int | None = None,
) -> tuple[str | None, str | None]:
    """バイト列を保存し、(公開エンドポイントの署名付き URL, オブジェクトキー) を返す。失敗時 (None, None)。"""
    if not is_configured():
        return None, None
    key = build_key(user_id, filename)
    exp = expiry or S3_PRESIGN_EXPIRY
    try:
        up = _client(S3_ENDPOINT_URL)
        _ensure_bucket(up)
        up.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )
        # 署名は公開エンドポイントのホストで生成（利用者はこの URL でアクセス）
        signer = up if S3_PUBLIC_ENDPOINT == S3_ENDPOINT_URL else _client(S3_PUBLIC_ENDPOINT)
        url = signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=exp,
        )
        return url, key
    except Exception as e:  # noqa: BLE001 - 失敗時はフォールバック（None）
        print(f"[objstore] アップロード/署名に失敗: {e}")
        return None, None


def _is_managed_key(key: str) -> bool:
    prefix = S3_KEY_PREFIX.rstrip("/") + "/"
    return bool(key) and key.startswith(prefix) and ".." not in key


def is_managed_key(key: str) -> bool:
    """自前ストレージの管理下オブジェクトキーかどうか。"""
    return _is_managed_key(key)


def owns_key(key: str, user_id: str | None) -> bool:
    """オブジェクトキーの所有者（`<prefix>/<user_hash>/...`）が当該ユーザーか判定する。"""
    parts = (key or "").split("/")
    if len(parts) < 2:
        return False
    return parts[1] == _opaque_user_segment(user_id)


def filename_from_key(key: str) -> str:
    """オブジェクトキー末尾の表示用ファイル名を返す。"""
    return (key or "").rstrip("/").split("/")[-1] or "file"


def presign_existing(key: str, expiry: int | None = None) -> str | None:
    """既存オブジェクトの署名付き URL を再発行する（存在しなければ None）。"""
    if not is_configured() or not _is_managed_key(key):
        return None
    exp = expiry or S3_PRESIGN_EXPIRY
    try:
        up = _client(S3_ENDPOINT_URL)
        up.head_object(Bucket=S3_BUCKET, Key=key)  # 存在確認
        signer = up if S3_PUBLIC_ENDPOINT == S3_ENDPOINT_URL else _client(S3_PUBLIC_ENDPOINT)
        return signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": S3_BUCKET, "Key": key},
            ExpiresIn=exp,
        )
    except Exception as e:  # noqa: BLE001 - 失敗時は None
        print(f"[objstore] 署名URLの再発行に失敗: {e}")
        return None


def key_from_url(url: str) -> str | None:
    """自前ストレージの署名付き URL からオブジェクトキーを抽出する（後方互換）。"""
    if not url:
        return None
    path = unquote(urlparse(url).path or "").lstrip("/")
    if not path:
        return None
    bucket_prefix = f"{S3_BUCKET}/"
    if path.startswith(bucket_prefix):
        key = path[len(bucket_prefix) :]
    elif path.startswith(S3_KEY_PREFIX + "/"):
        key = path
    else:
        return None
    return key if _is_managed_key(key) else None


def keys_from_artifacts(artifacts: Any) -> list[str]:
    """履歴 artifacts から削除対象のオブジェクトキーを収集する。"""
    found: list[str] = []
    for item in artifacts or []:
        if not isinstance(item, dict):
            continue
        key = str(item.get("object_key") or "").strip()
        if not key:
            key = key_from_url(str(item.get("file_url") or "")) or ""
        if key and _is_managed_key(key):
            found.append(key)
    return list(dict.fromkeys(found))


def delete_keys(keys: list[str]) -> int:
    """指定キーのオブジェクトを削除する。削除件数を返す。"""
    if not is_configured():
        return 0
    unique = [k for k in dict.fromkeys(keys) if _is_managed_key(k)]
    if not unique:
        return 0
    deleted = 0
    try:
        c = _client(S3_ENDPOINT_URL)
        for i in range(0, len(unique), 1000):
            batch = [{"Key": k} for k in unique[i : i + 1000]]
            resp = c.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": batch})
            deleted += len(resp.get("Deleted", []))
    except Exception as e:  # noqa: BLE001
        print(f"[objstore] オブジェクト削除に失敗: {e}")
    return deleted


def purge_objects_older_than(days: int) -> int:
    """保持日数を超えた成果物オブジェクトを削除する（孤児ファイルの掃除）。"""
    if not is_configured() or days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    prefix = S3_KEY_PREFIX.rstrip("/") + "/"
    deleted = 0
    try:
        c = _client(S3_ENDPOINT_URL)
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": S3_BUCKET, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            resp = c.list_objects_v2(**kwargs)
            stale = [
                {"Key": o["Key"]}
                for o in resp.get("Contents", [])
                if o.get("Key")
                and _is_managed_key(o["Key"])
                and o.get("LastModified") is not None
                and o["LastModified"] < cutoff
            ]
            if stale:
                for i in range(0, len(stale), 1000):
                    batch = stale[i : i + 1000]
                    out = c.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": batch})
                    deleted += len(out.get("Deleted", []))
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
    except Exception as e:  # noqa: BLE001
        print(f"[objstore] 期限切れ成果物のパージに失敗: {e}")
    return deleted


def purge_prefix(prefix: str | None = None) -> int:
    """指定プレフィックス（既定は全 exApp 成果物）を削除する。削除件数を返す。

    契約終了時のデータ削除（8-(7)）で使用。
    """
    if not is_configured():
        return 0
    pfx = prefix if prefix is not None else (S3_KEY_PREFIX + "/")
    deleted = 0
    try:
        c = _client(S3_ENDPOINT_URL)
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": S3_BUCKET, "Prefix": pfx}
            if token:
                kwargs["ContinuationToken"] = token
            resp = c.list_objects_v2(**kwargs)
            objs = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            if objs:
                c.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": objs})
                deleted += len(objs)
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
    except Exception as e:  # noqa: BLE001
        print(f"[objstore] パージに失敗: {e}")
    return deleted


def run_retention_purge() -> tuple[int, int, int]:
    """保持期間超過の成果物と実行履歴を削除する。(objects, histories, orphans)"""
    if not is_configured() or S3_ARTIFACT_RETENTION_DAYS <= 0:
        return 0, 0, 0
    from . import teams_store

    cutoff = str(
        int(time.time() * 1000) - S3_ARTIFACT_RETENTION_DAYS * 24 * 3600 * 1000
    )
    old_histories = teams_store.list_exapp_histories_older_than(cutoff)
    keys: list[str] = []
    for hist in old_histories:
        keys.extend(keys_from_artifacts(hist.get("artifacts")))
    deleted_objects = delete_keys(keys)
    deleted_histories = teams_store.delete_histories_older_than(cutoff)
    deleted_orphans = purge_objects_older_than(S3_ARTIFACT_RETENTION_DAYS)
    return deleted_objects, deleted_histories, deleted_orphans


_purge_started = False
_purge_lock = threading.Lock()


def _purge_loop() -> None:
    while True:
        try:
            objs, hists, orphans = run_retention_purge()
            if objs or hists or orphans:
                print(
                    f"[objstore] 保持期間超過を削除: objects={objs}, histories={hists}, orphans={orphans}"
                )
        except Exception as e:  # noqa: BLE001
            print(f"[objstore] 定期パージに失敗: {e}")
        time.sleep(S3_ARTIFACT_PURGE_INTERVAL)


def start_retention_scheduler() -> None:
    """成果物の保持期間パージをバックグラウンドで開始する。"""
    global _purge_started
    if _purge_started or not is_configured() or S3_ARTIFACT_RETENTION_DAYS <= 0:
        return
    with _purge_lock:
        if _purge_started:
            return
        t = threading.Thread(target=_purge_loop, name="objstore-purge", daemon=True)
        t.start()
        _purge_started = True
