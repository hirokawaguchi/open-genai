"""画像認識・文書読取。テキストはローカル、画像は Vision LLM。"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from . import llm

MAX_BYTES = 4 * 1024 * 1024
MAX_CHARS = 20_000

_IMAGE_PROMPT = (
    "画像に書かれている文字や内容を日本語で読み取ってください。"
    "読み取った内容だけを返し、説明や前置きは不要です。"
    "読めない場合は空文字だけを返してください。"
)


def decode_payload(data: str) -> tuple[bytes, str]:
    raw = (data or "").strip()
    mime = "application/octet-stream"
    if raw.startswith("data:"):
        header, _, b64 = raw.partition(",")
        mime = header[5:].split(";")[0] or mime
        raw = b64
    try:
        blob = base64.b64decode(raw, validate=False)
    except (binascii.Error, ValueError) as e:
        raise ValueError("ファイルデータを解読できません") from e
    if not blob:
        raise ValueError("ファイルが空です")
    if len(blob) > MAX_BYTES:
        raise ValueError("ファイルが大きすぎます（4MBまで）")
    return blob, mime


def extract_text_bytes(blob: bytes, filename: str, mime: str) -> str | None:
    name = (filename or "").lower()
    if (
        mime.startswith("text/")
        or name.endswith((".txt", ".csv", ".md", ".json"))
        or mime in ("application/json", "text/csv")
    ):
        return blob.decode("utf-8", errors="replace")
    if blob[:4] != b"%PDF":
        sample = blob[:800]
        if b"\x00" not in sample:
            try:
                text = blob.decode("utf-8")
            except UnicodeDecodeError:
                return None
            if text.strip():
                return text
    return None


async def extract_payload(
    *,
    kind: str,
    filename: str,
    data: str,
) -> dict[str, Any]:
    kind = (kind or "").strip()
    if kind not in ("image", "document"):
        raise ValueError("kind は image または document です")
    blob, mime = decode_payload(data)
    name = filename or "upload"

    if kind == "document":
        text = extract_text_bytes(blob, name, mime)
        if text is not None:
            return {
                "extracted": text.strip()[:MAX_CHARS],
                "source": "text",
                "filename": name,
            }
        return {
            "extracted": "",
            "source": "unavailable",
            "filename": name,
            "notes": "この文書は自動読取できません。内容を手入力してください。",
        }

    data_url = data if data.startswith("data:image/") else f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"
    if not data_url.startswith("data:image/"):
        data_url = f"data:image/png;base64,{base64.b64encode(blob).decode('ascii')}"
    try:
        text = await llm.chat_vision(_IMAGE_PROMPT, data_url)
    except Exception as e:  # noqa: BLE001
        return {
            "extracted": "",
            "source": "unavailable",
            "filename": name,
            "notes": f"画像の自動読取に失敗しました。内容を手入力してください（{e}）。",
        }
    return {
        "extracted": (text or "").strip()[:MAX_CHARS],
        "source": "llm",
        "filename": name,
        "model": llm.PATCHFORM_VISION_MODEL,
    }
