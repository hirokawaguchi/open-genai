"""教材バイト列の置き場。本番は SeaweedFS。テストはメモリ。"""

from __future__ import annotations

import os
from typing import Protocol

PREFIX = os.environ.get("LMS_S3_PREFIX", "lms").strip("/") or "lms"


class StorageError(Exception):
    def __init__(self, message: str, status: int = 503) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class Storage(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None: ...

    def get_bytes(self, key: str) -> bytes: ...

    def presign(self, key: str) -> str: ...

    def delete(self, key: str) -> None: ...


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = (data, content_type)

    def get_bytes(self, key: str) -> bytes:
        item = self.objects.get(key)
        if not item:
            raise StorageError("教材が見つかりません", 404)
        return item[0]

    def presign(self, key: str) -> str:
        if key not in self.objects:
            raise StorageError("教材が見つかりません", 404)
        return f"http://localhost:8333/{key}"

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class S3Storage:
    def put_bytes(self, key: str, data: bytes, content_type: str) -> None:
        client = _client(os.environ.get("S3_ENDPOINT_URL", ""))
        bucket = _bucket()
        _ensure_bucket(client, bucket)
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type or "application/octet-stream",
        )

    def get_bytes(self, key: str) -> bytes:
        client = _client(os.environ.get("S3_ENDPOINT_URL", ""))
        try:
            obj = client.get_object(Bucket=_bucket(), Key=key)
            return obj["Body"].read()
        except Exception as e:
            raise StorageError("教材を読み出せません") from e

    def presign(self, key: str) -> str:
        internal = os.environ.get("S3_ENDPOINT_URL", "").rstrip("/")
        public = (os.environ.get("S3_PUBLIC_ENDPOINT") or internal).rstrip("/")
        bucket = _bucket()
        expiry = int(os.environ.get("S3_PRESIGN_EXPIRY", str(24 * 3600)))
        signer = _client(public or internal)
        return signer.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expiry,
        )

    def delete(self, key: str) -> None:
        client = _client(os.environ.get("S3_ENDPOINT_URL", ""))
        try:
            client.delete_object(Bucket=_bucket(), Key=key)
        except Exception as e:
            raise StorageError(f"教材を削除できません: {e}") from e


_current: Storage | None = None


def get_storage() -> Storage:
    global _current
    if _current is None:
        if os.environ.get("LMS_STORAGE") == "memory":
            _current = MemoryStorage()
        else:
            _current = S3Storage()
    return _current


def reset_storage() -> None:
    global _current
    _current = None


def _bucket() -> str:
    bucket = os.environ.get("S3_BUCKET", "")
    if not (
        os.environ.get("S3_ENDPOINT_URL")
        and bucket
        and os.environ.get("S3_ACCESS_KEY")
        and os.environ.get("S3_SECRET_KEY")
    ):
        raise StorageError("SeaweedFS が未設定です")
    return bucket


def _client(endpoint: str):
    try:
        import boto3
        from botocore.client import Config
    except ImportError as e:
        raise StorageError("boto3 がありません") from e
    if not endpoint:
        raise StorageError("SeaweedFS が未設定です")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY", ""),
        aws_secret_access_key=os.environ.get("S3_SECRET_KEY", ""),
        region_name=os.environ.get("S3_REGION", "us-east-1"),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "path")},
        ),
    )


def _ensure_bucket(client, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except Exception:
        try:
            client.create_bucket(Bucket=bucket)
        except Exception as e:
            raise StorageError(f"バケットを用意できません: {e}") from e
