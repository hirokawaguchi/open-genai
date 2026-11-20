"""文字起こし「AI アプリ」マイクロサービス（faster-whisper / CUDA or CPU）。

源内の AI アプリ同期プロトコルに準拠:
- リクエスト: { "inputs": { "audio": ..., "language": "auto|ja|en", "files": [...] } }
  音声は inputs.files に base64 で入る（exApp のファイル入力仕様）。
- レスポンス: { "outputs": "<文字起こしテキスト(Markdown)>" }

Amazon Transcribe + S3 への依存を、ローカルの faster-whisper で置き換える。
"""

from __future__ import annotations

import asyncio
import base64
import os
import tempfile
from typing import Any

from .cloud import CloudTranscribeError, transcribe_file
from .queue import TranscribeQueue, estimate_audio_seconds, seconds_for_queue

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")

app = FastAPI(title="Open GENAI Whisper App", version="0.1.0")

_model = None
_model_error: str | None = None
# モデルと展開した音声でメモリを使うため、文字起こしは1本ずつ行う。
_transcribe_lock = asyncio.Lock()
# クラウド送信はモデルを使わない。ローカルの変換とは別の列にする。
_cloud_lock = asyncio.Lock()

# 受付順と開始見込み。変換ロックとは別に、列の更新だけを守る。
_queue = TranscribeQueue()
_queue_lock = asyncio.Lock()


def _get_model():
    """モデルは初回利用時に遅延ロード（起動を速く保つ）。"""
    global _model, _model_error
    if _model is not None:
        return _model
    try:
        import ctranslate2
        from faster_whisper import WhisperModel

        if WHISPER_DEVICE == "cuda" and ctranslate2.get_cuda_device_count() < 1:
            raise RuntimeError(
                "WHISPER_DEVICE=cuda ですが CUDA デバイスが見つかりません。"
                "コンテナに GPU が渡されているか確認してください。"
            )

        _model = WhisperModel(
            WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE
        )
        _model_error = None
    except Exception as e:  # noqa: BLE001
        _model_error = str(e)
        raise
    return _model


def _check_key(x_api_key: str | None) -> JSONResponse | None:
    if API_KEY and x_api_key != API_KEY:
        return JSONResponse(status_code=401, content={"error": "invalid api key"})
    return None


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": WHISPER_MODEL,
        "device": WHISPER_DEVICE,
        "compute": WHISPER_COMPUTE,
        "loaded": _model is not None,
    }


def _extract_audio(inputs: dict[str, Any]) -> tuple[str, bytes] | None:
    """inputs.files から最初の音声ファイル(filename, bytes)を取り出す。"""
    for entry in inputs.get("files") or []:
        for f in entry.get("files", []):
            content = f.get("content", "")
            if not content:
                continue
            try:
                raw = base64.b64decode(content)
            except Exception:  # noqa: BLE001
                continue
            return f.get("filename", "audio"), raw
    return None



def _queue_seconds(body: dict[str, Any]) -> float:
    """再生時間が渡されていればそれを使う。無ければバイト列から見積もる。"""
    try:
        given = float(body.get("audioSeconds") or 0)
    except (TypeError, ValueError):
        given = 0.0
    if given > 0:
        return given
    try:
        nbytes = int(body.get("nbytes") or 0)
    except (TypeError, ValueError):
        nbytes = 0
    head = b""
    encoded = body.get("headB64") or ""
    if encoded:
        try:
            head = base64.b64decode(encoded)
        except Exception:  # noqa: BLE001
            head = b""
    if nbytes <= 0:
        nbytes = len(head)
    return estimate_audio_seconds(head, total_bytes=nbytes)


@app.get("/queue")
async def queue_status(
    request: Request,
    x_api_key: str | None = Header(default=None),
    nbytes: int = 0,
    audioSeconds: float = 0,
) -> JSONResponse:
    err = _check_key(x_api_key)
    if err:
        return err
    async with _queue_lock:
        view = _queue.forecast(_queue_seconds({"nbytes": nbytes, "audioSeconds": audioSeconds}))
    return JSONResponse(content=view)


@app.post("/queue")
async def queue_preview(request: Request, x_api_key: str | None = Header(default=None)) -> JSONResponse:
    err = _check_key(x_api_key)
    if err:
        return err
    body = await request.json()
    if not isinstance(body, dict):
        body = {}
    async with _queue_lock:
        view = _queue.forecast(_queue_seconds(body))
    return JSONResponse(content=view)


@app.post("/invoke")
async def invoke(request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err

    body = await request.json()
    inputs = body.get("inputs", body)

    audio = _extract_audio(inputs)
    if not audio:
        return {"outputs": "音声または動画ファイルが添付されていません。ファイルを添付してください。"}

    filename, raw = audio
    language = inputs.get("language") or "auto"
    lang_arg = None if language in ("auto", "", None) else language
    audio_seconds = seconds_for_queue(inputs.get("audioSeconds"), raw)

    async with _queue_lock:
        view, slot = _queue.try_reserve(audio_seconds)
    if slot is None:
        return JSONResponse(status_code=409, content={"error": view["message"], "error_code": "WHISPER_QUEUE", **view})

    suffix = os.path.splitext(filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    del raw

    as_segments = str(inputs.get("format") or "") == "segments"
    try:
        async with _transcribe_lock:
            async with _queue_lock:
                _queue.mark_started(slot)
            outputs = await asyncio.to_thread(_transcribe_file, tmp_path, lang_arg, as_segments)
            return {"outputs": outputs}
    finally:
        async with _queue_lock:
            _queue.release(slot)
        try:
            os.remove(tmp_path)
        except OSError:
            pass


@app.post("/invoke-cloud")
async def invoke_cloud(request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    """gpt-transcribe。モデルは読み込まず、ローカルの待ち列にも入れない。"""
    err = _check_key(x_api_key)
    if err:
        return err
    openai_key = request.headers.get("x-openai-key") or ""
    body = await request.json()
    inputs = body.get("inputs", body)
    if not isinstance(inputs, dict):
        inputs = {}
    audio = _extract_audio(inputs)
    if not audio:
        return {"outputs": "音声または動画ファイルが添付されていません。ファイルを添付してください。"}
    raw = audio[1]
    language = inputs.get("language") or "auto"
    async with _cloud_lock:
        try:
            outputs = await asyncio.to_thread(transcribe_file, raw, language, openai_key)
        except CloudTranscribeError as exc:
            return JSONResponse(status_code=502, content={"error": str(exc)})
        except Exception:  # noqa: BLE001
            return JSONResponse(
                status_code=502,
                content={"error": "クラウドの文字起こしに失敗しました。"},
            )
    return {"outputs": outputs}


def _transcribe_file(tmp_path: str, lang_arg: str | None, as_segments: bool = False) -> Any:
    """同期の文字起こし。イベントループを止めないようスレッドから呼ぶ。

    format=segments のときは発話ごとの開始秒・終了秒を返す。通常は Markdown の文字列。
    """
    try:
        model = _get_model()
    except Exception as e:  # noqa: BLE001
        return f"[文字起こしモデルの読み込みに失敗しました] {e}"

    try:
        segments, info = model.transcribe(tmp_path, language=lang_arg, vad_filter=True)
        detected = getattr(info, "language", lang_arg or "auto")
        if as_segments:
            rows = []
            for seg in segments:
                rows.append(
                    {
                        "start": round(float(seg.start), 2),
                        "end": round(float(seg.end), 2),
                        "text": seg.text.strip(),
                    }
                )
            return {"language": detected, "segments": rows}
        lines: list[str] = []
        for seg in segments:
            start = _fmt_ts(seg.start)
            end = _fmt_ts(seg.end)
            lines.append(f"[{start} - {end}] {seg.text.strip()}")
        transcript = "\n".join(lines) if lines else "（音声から文字を検出できませんでした）"
        return f"**検出言語**: {detected}\n\n{transcript}"
    except Exception as e:  # noqa: BLE001
        return f"[文字起こし中にエラーが発生しました] {e}"


def _fmt_ts(seconds: float) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
