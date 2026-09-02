"""文字起こし「AI アプリ」マイクロサービス（faster-whisper / CUDA or CPU）。

源内の AI アプリ同期プロトコルに準拠:
- リクエスト: { "inputs": { "audio": ..., "language": "auto|ja|en", "files": [...] } }
  音声は inputs.files に base64 で入る（exApp のファイル入力仕様）。
- レスポンス: { "outputs": "<文字起こしテキスト(Markdown)>" }

Amazon Transcribe + S3 への依存を、ローカルの faster-whisper で置き換える。
"""

from __future__ import annotations

import base64
import os
import tempfile
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

API_KEY = os.environ.get("RAG_API_KEY", "local-rag-key")
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium")
WHISPER_COMPUTE = os.environ.get("WHISPER_COMPUTE", "int8")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")

app = FastAPI(title="Open GENAI Whisper App", version="0.1.0")

_model = None
_model_error: str | None = None


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


@app.post("/invoke")
async def invoke(request: Request, x_api_key: str | None = Header(default=None)) -> Any:
    err = _check_key(x_api_key)
    if err:
        return err

    body = await request.json()
    inputs = body.get("inputs", body)

    audio = _extract_audio(inputs)
    if not audio:
        return {"outputs": "音声ファイルが添付されていません。音声を添付してください。"}

    filename, raw = audio
    language = inputs.get("language") or "auto"
    lang_arg = None if language in ("auto", "", None) else language

    suffix = os.path.splitext(filename)[1] or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name

    try:
        model = _get_model()
    except Exception as e:  # noqa: BLE001
        return {"outputs": f"[文字起こしモデルの読み込みに失敗しました] {e}"}

    try:
        segments, info = model.transcribe(tmp_path, language=lang_arg, vad_filter=True)
        lines: list[str] = []
        for seg in segments:
            start = _fmt_ts(seg.start)
            end = _fmt_ts(seg.end)
            lines.append(f"[{start} - {end}] {seg.text.strip()}")
        transcript = "\n".join(lines) if lines else "（音声から文字を検出できませんでした）"
        detected = getattr(info, "language", lang_arg or "auto")
        outputs = f"**検出言語**: {detected}\n\n{transcript}"
        return {"outputs": outputs}
    except Exception as e:  # noqa: BLE001
        return {"outputs": f"[文字起こし中にエラーが発生しました] {e}"}
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _fmt_ts(seconds: float) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
