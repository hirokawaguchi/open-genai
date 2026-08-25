"""回答添付のディスク保管。パスは UUID のみなのでディレクトリ横断しない。"""

from __future__ import annotations

import base64
import binascii
import os
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

MAX_UPLOAD_BYTES = int(os.environ.get("PATCHFORM_MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

FILE_MIMES = frozenset(
    {
        "application/pdf",
        "image/jpeg",
        "image/png",
        "image/gif",
        "image/webp",
        "text/plain",
        "text/csv",
        "application/json",
        "application/msword",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
SIGNATURE_MIMES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})

_EXT_MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".doc": "application/msword",
    ".xls": "application/vnd.ms-excel",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def files_root() -> Path:
    return Path(os.environ.get("PATCHFORM_FILES_DIR") or "/data/files")


def safe_filename(name: str) -> str:
    base = Path(name or "").name.replace("\x00", "").strip()
    return (base or "upload")[:200]


def _guess_mime(filename: str, header_mime: str) -> str:
    mime = (header_mime or "").split(";")[0].strip().lower()
    if mime and mime != "application/octet-stream":
        return mime
    return _EXT_MIME.get(Path(filename).suffix.lower(), mime or "application/octet-stream")


def decode_upload(data: str, *, filename: str, kind: str) -> tuple[bytes, str]:
    raw = (data or "").strip()
    header_mime = "application/octet-stream"
    if raw.startswith("data:"):
        header, _, b64 = raw.partition(",")
        header_mime = header[5:].split(";")[0] or header_mime
        raw = b64
    try:
        blob = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError("ファイルデータを解読できません") from e
    if not blob:
        raise ValueError("ファイルが空です")
    if len(blob) > MAX_UPLOAD_BYTES:
        raise ValueError(f"ファイルが大きすぎます（{MAX_UPLOAD_BYTES // (1024 * 1024)}MBまで）")
    mime = _guess_mime(filename, header_mime)
    allowed = SIGNATURE_MIMES if kind == "signature" else FILE_MIMES
    if mime not in allowed:
        raise ValueError("このファイル形式は添付できません")
    return blob, mime


def form_dir(form_id: str) -> Path:
    if not _UUID_RE.match(form_id or ""):
        raise ValueError("フォームIDが不正です")
    return files_root() / form_id


def stored_path(form_id: str, file_id: str) -> Path:
    if not _UUID_RE.match(file_id or ""):
        raise ValueError("ファイルIDが不正です")
    return form_dir(form_id) / file_id


def write_blob(form_id: str, file_id: str, blob: bytes) -> Path:
    dest = stored_path(form_id, file_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(blob)
    return dest


def remove_blob(form_id: str, file_id: str) -> None:
    try:
        path = stored_path(form_id, file_id)
    except ValueError:
        return
    if path.is_file():
        path.unlink()


def remove_form_dir(form_id: str) -> None:
    try:
        root = form_dir(form_id)
    except ValueError:
        return
    shutil.rmtree(root, ignore_errors=True)


def rename_form_dir(old_form_id: str, new_form_id: str) -> None:
    try:
        src = form_dir(old_form_id)
        dest = form_dir(new_form_id)
    except ValueError:
        return
    if not src.exists() or dest.exists():
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dest)


def content_disposition(filename: str) -> str:
    name = safe_filename(filename)
    ascii_name = name.encode("ascii", "replace").decode("ascii").replace('"', "")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


def public_meta(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "file_id": row["id"],
        "filename": row["filename"],
        "mime": row.get("mime") or "",
        "size": int(row.get("size") or 0),
    }
