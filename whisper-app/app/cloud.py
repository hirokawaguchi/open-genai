"""ファイル文字起こしを OpenAI の gpt-transcribe へ送る。

モデルは読み込まない。24MB 以下なら1回、超える録音だけ無音の近くで割る。
"""

from __future__ import annotations

import io
from typing import Any

MODEL = "gpt-transcribe"
TRANSCRIBE_URL = "https://api.openai.com/v1/audio/transcriptions"
LIMIT_BYTES = 24 * 1024 * 1024
TARGET_SECONDS = 10 * 60
SEARCH_SECONDS = 20.0
SAMPLE_RATE = 16_000
BITRATE = 48_000
HOP_SECONDS = 0.2
PROMPT_CHARS = 200


class CloudTranscribeError(Exception):
    """利用者に見せてよいメッセージ。API キーは含めない。"""


def segment_ends(
    rms: list[float],
    *,
    hop_seconds: float,
    duration: float,
    target: float = TARGET_SECONDS,
    search: float = SEARCH_SECONDS,
) -> list[float]:
    """各区間の終了秒。最後は録音の終わり。目標付近で最も静かな位置を切る。"""
    if duration <= 0:
        return [0.0]
    if duration <= target * 1.25:
        return [duration]
    ends: list[float] = []
    cursor = 0.0
    while duration - cursor > target * 1.25:
        goal = cursor + target
        lo = max(cursor + 1.0, goal - search)
        hi = min(duration - 0.5, goal + search)
        best = min(duration, goal)
        best_rms = 1e9
        start_i = int(lo / hop_seconds) if hop_seconds > 0 else 0
        end_i = int(hi / hop_seconds) if hop_seconds > 0 else start_i
        for index in range(start_i, max(start_i + 1, end_i + 1)):
            if index >= len(rms):
                break
            if rms[index] < best_rms:
                best_rms = rms[index]
                best = min(duration, index * hop_seconds)
        if best <= cursor + 0.5:
            best = min(duration, cursor + target)
        ends.append(best)
        cursor = best
    ends.append(duration)
    return ends


def render_transcript(parts: list[dict[str, Any]]) -> str:
    """1本なら本文だけ。複数なら区間見出しを付けて結合する。"""
    usable = [part for part in parts if str(part.get("text") or "").strip() or part.get("language")]
    if not usable:
        return "**検出言語**: auto\n\n（音声から文字を検出できませんでした）"
    language = "auto"
    for part in usable:
        lang = str(part.get("language") or "").strip()
        if lang:
            language = lang
            break
    if len(parts) <= 1:
        text = str(parts[0].get("text") or "").strip() or "（音声から文字を検出できませんでした）"
        return f"**検出言語**: {language}\n\n{text}"
    lines = [f"**検出言語**: {language}", ""]
    for part in parts:
        start = _fmt_ts(float(part.get("start") or 0))
        end = _fmt_ts(float(part.get("end") or 0))
        text = str(part.get("text") or "").strip() or "（この区間から文字を検出できませんでした）"
        lines.append(f"**{start}–{end}**")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def prompt_tail(text: str) -> str:
    """次の区間へ渡す直前の末尾。"""
    body = text.strip()
    if len(body) <= PROMPT_CHARS:
        return body
    return body[-PROMPT_CHARS:]


def transcribe_file(raw: bytes, language: str | None, api_key: str) -> str:
    """音声バイト列を gpt-transcribe に送り、結合した Markdown を返す。"""
    key = (api_key or "").strip()
    if not key or key.lower() == "ollama":
        raise CloudTranscribeError("クラウドの文字起こしを利用できません。")
    pcm = _load_pcm(raw)
    pieces = _pieces(pcm)
    lang = None if language in (None, "", "auto") else language
    parts: list[dict[str, Any]] = []
    previous = ""
    for start, end, blob in pieces:
        text, detected = _post_audio(blob, lang, prompt_tail(previous), key)
        parts.append({"start": start, "end": end, "text": text, "language": detected})
        previous = text or previous
    return render_transcript(parts)


def _load_pcm(raw: bytes):
    import av
    import numpy as np

    try:
        container = av.open(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise CloudTranscribeError("音声を読み取れませんでした。") from exc
    stream = next((item for item in container.streams if item.type == "audio"), None)
    if stream is None:
        raise CloudTranscribeError("音声トラックが見つかりませんでした。")
    resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
    chunks: list[Any] = []
    try:
        for frame in container.decode(stream):
            chunks.extend(_as_frames(resampler.resample(frame)))
        chunks.extend(_as_frames(resampler.resample(None)))
    except Exception as exc:  # noqa: BLE001
        raise CloudTranscribeError("音声を読み取れませんでした。") from exc
    if not chunks:
        raise CloudTranscribeError("音声を読み取れませんでした。")
    arrays = [frame.to_ndarray().reshape(-1) for frame in chunks]
    return np.concatenate(arrays)


def _as_frames(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _pieces(pcm) -> list[tuple[float, float, bytes]]:
    import numpy as np

    duration = len(pcm) / SAMPLE_RATE if len(pcm) else 0.0
    whole = _encode_mp3(pcm)
    if len(whole) <= LIMIT_BYTES:
        return [(0.0, duration, whole)]
    hop = int(SAMPLE_RATE * HOP_SECONDS)
    rms: list[float] = []
    for offset in range(0, len(pcm), hop):
        window = pcm[offset : offset + hop].astype(np.float32)
        if len(window) == 0:
            break
        rms.append(float(np.sqrt(np.mean(window * window)) / 32768.0))
    ends = segment_ends(rms, hop_seconds=HOP_SECONDS, duration=duration)
    pieces: list[tuple[float, float, bytes]] = []
    cursor = 0.0
    for end in ends:
        start_i = int(cursor * SAMPLE_RATE)
        end_i = int(end * SAMPLE_RATE)
        blob = _encode_mp3(pcm[start_i:end_i])
        pieces.append((cursor, end, blob))
        cursor = end
    return pieces


def _encode_mp3(pcm) -> bytes:
    import av

    if len(pcm) == 0:
        raise CloudTranscribeError("音声を読み取れませんでした。")
    buf = io.BytesIO()
    container = av.open(buf, mode="w", format="mp3")
    stream = container.add_stream("libmp3lame", rate=SAMPLE_RATE)
    stream.layout = "mono"
    stream.bit_rate = BITRATE
    offset = 0
    step = SAMPLE_RATE
    pts = 0
    while offset < len(pcm):
        piece = pcm[offset : offset + step]
        frame = av.AudioFrame.from_ndarray(piece.reshape(1, -1), format="s16", layout="mono")
        frame.sample_rate = SAMPLE_RATE
        frame.pts = pts
        for packet in stream.encode(frame):
            container.mux(packet)
        pts += len(piece)
        offset += step
    for packet in stream.encode(None):
        container.mux(packet)
    container.close()
    return buf.getvalue()


def _post_audio(blob: bytes, language: str | None, prompt: str, api_key: str) -> tuple[str, str]:
    import requests

    data: dict[str, str] = {"model": MODEL, "response_format": "json"}
    if language:
        data["language"] = language
    if prompt:
        data["prompt"] = prompt
    try:
        response = requests.post(
            TRANSCRIBE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            files={"file": ("audio.mp3", blob, "audio/mpeg")},
            data=data,
            timeout=600,
        )
    except requests.RequestException as exc:
        raise CloudTranscribeError("クラウドの文字起こしに接続できませんでした。") from exc
    if response.status_code != 200:
        raise CloudTranscribeError("クラウドの文字起こしに失敗しました。")
    try:
        body = response.json()
    except ValueError as exc:
        raise CloudTranscribeError("クラウドの文字起こしに失敗しました。") from exc
    text = str(body.get("text") or "").strip()
    detected = ""
    languages = body.get("languages")
    if isinstance(languages, list) and languages:
        first = languages[0]
        if isinstance(first, dict):
            detected = str(first.get("code") or "").strip()
    return text, detected or (language or "")


def _fmt_ts(seconds: float) -> str:
    whole = max(0, int(seconds))
    minutes, secs = divmod(whole, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"
