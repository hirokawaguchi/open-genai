"""教材の文字起こし。PDF はページ、動画は whisper の発話区間。アップロードの応答では待たない。"""

from __future__ import annotations

import base64
import os
import threading
from pathlib import Path

import httpx

from app import convert, storage, store

_busy: set[str] = set()
_busy_lock = threading.Lock()


def busy(material_id: str) -> bool:
    with _busy_lock:
        return material_id in _busy


def claim(material_id: str) -> bool:
    with _busy_lock:
        if material_id in _busy:
            return False
        _busy.add(material_id)
        return True


def release(material_id: str) -> None:
    with _busy_lock:
        _busy.discard(material_id)


def launch(tenant_id: str, material_id: str, token: str) -> None:
    def target() -> None:
        try:
            run_job(tenant_id, material_id, token)
        finally:
            release(material_id)

    if os.environ.get("LMS_TRANSCRIBE_SYNC") == "1":
        target()
        return
    threading.Thread(target=target, name=f"lms-transcript-{material_id[:8]}", daemon=True).start()


def run_job(tenant_id: str, material_id: str, token: str) -> None:
    try:
        material = store.load_material_for_job(tenant_id, material_id)
        if material is None:
            return
        data = storage.get_storage().get_bytes(str(material["original_key"]))
        if material["kind"] == "slides":
            from app import vision

            pages = convert.pdf_page_texts(data)
            count = max(int(material["slide_count"]), len(pages))
            while len(pages) < count:
                pages.append("")
            images: list[bytes] = []
            for key in material.get("slide_keys") or []:
                try:
                    images.append(storage.get_storage().get_bytes(str(key)))
                except storage.StorageError:
                    images.append(b"")
            pages, extra = vision.enrich_sparse_pages(
                pages,
                images,
                on_status=lambda text: store.note_transcript(tenant_id, material_id, token, text),
            )
            segments = [
                {"id": store._new_id(), "start": index, "end": index, "text": pages[index - 1]}
                for index in range(1, count + 1)
            ]
            if any(page.strip() for page in pages):
                notice = extra
            elif extra:
                notice = f"本文がありません。{extra}"
            else:
                notice = "本文がありません"
            store.finish_transcript(tenant_id, material_id, token, segments, notice)
            return
        filename = Path(str(material["original_key"])).name or "video.mp4"
        raw = transcribe_video(data, filename)
        segments = [
            {
                "id": store._new_id(),
                "start": round(float(item["start"]), 2),
                "end": round(float(item["end"]), 2),
                "text": str(item.get("text") or ""),
            }
            for item in raw
        ]
        notice = "" if any(item["text"].strip() for item in segments) else "本文がありません"
        store.finish_transcript(tenant_id, material_id, token, segments, notice)
    except store.LmsError as exc:
        store.fail_transcript(tenant_id, material_id, token, exc.message)
    except convert.ConvertError as exc:
        store.fail_transcript(tenant_id, material_id, token, exc.message)
    except storage.StorageError as exc:
        store.fail_transcript(tenant_id, material_id, token, exc.message)
    except Exception:
        store.fail_transcript(tenant_id, material_id, token, "文字起こしに失敗しました")


def transcribe_video(data: bytes, filename: str) -> list[dict]:
    limit = int(os.environ.get("LMS_TRANSCRIBE_MAX_BYTES", str(180 * 1024 * 1024)))
    if len(data) > limit:
        raise store.LmsError("動画が大きすぎて文字起こしできません。180MB までにしてください。")
    url = os.environ.get("WHISPER_APP_URL", "http://whisper-app:8002/invoke")
    key = os.environ.get("RAG_API_KEY", "local-rag-key")
    payload = {
        "inputs": {
            "format": "segments",
            "language": "ja",
            "files": [
                {
                    "files": [
                        {
                            "filename": filename,
                            "content": base64.b64encode(data).decode("ascii"),
                        }
                    ]
                }
            ],
        }
    }
    try:
        response = httpx.post(
            url,
            json=payload,
            headers={"x-api-key": key},
            timeout=httpx.Timeout(1800.0, connect=10.0),
        )
    except httpx.HTTPError as exc:
        raise store.LmsError("文字起こしサービスに接続できません") from exc
    if response.status_code == 401:
        raise store.LmsError("文字起こしサービスへの認証に失敗しました")
    if response.status_code >= 400:
        raise store.LmsError("文字起こしに失敗しました")
    body = response.json()
    outputs = body.get("outputs")
    if isinstance(outputs, str):
        text = outputs.strip()
        if text.startswith("["):
            raise store.LmsError(text)
        raise store.LmsError("文字起こしの結果を読めませんでした")
    if not isinstance(outputs, dict):
        raise store.LmsError("文字起こしの結果を読めませんでした")
    raw = outputs.get("segments") or []
    if not isinstance(raw, list):
        raise store.LmsError("文字起こしの結果を読めませんでした")
    segments: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            start = round(float(item.get("start")), 2)
            end = round(float(item.get("end")), 2)
        except (TypeError, ValueError):
            continue
        if start < 0 or end < start:
            continue
        segments.append({"start": start, "end": end, "text": str(item.get("text") or "").strip()})
    return segments
