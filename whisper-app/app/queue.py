"""文字起こしの直列待ち。ファイル名や利用者は持たない。

開始見込みは、前にいる音声の長さに処理倍率を掛けたもの。
結果を返す待ち（既定 60 分）に収まらない依頼は、列に入れない。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass

# 呼び出し側が結果を待つ上限。超える依頼は受け付けない。
ACCEPT_WINDOW_SECONDS = float(os.environ.get("WHISPER_ACCEPT_WINDOW", "3600"))
# 音声 1 秒あたりの処理秒。CPU の medium では実時間より少し長い。
SEC_PER_AUDIO_SEC = float(os.environ.get("WHISPER_SEC_PER_AUDIO_SEC", "1.2"))
# ビットレートが読めないときの仮定（低めに見て、待ちを長めに見積もる）。
FALLBACK_BITRATE = 128_000

_MPEG1_L3 = [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320]


@dataclass
class Slot:
    audio_seconds: float
    enqueued_at: float
    started_at: float | None = None


class TranscribeQueue:
    def __init__(self) -> None:
        self._slots: list[Slot] = []

    def reset(self) -> None:
        self._slots.clear()

    def forecast(self, audio_seconds: float, now: float | None = None) -> dict[str, object]:
        """この音声を今入れたときの順番。列には追加しない。"""
        moment = time.monotonic() if now is None else now
        ahead_seconds = self._remaining_seconds(moment)
        own = _process_seconds(audio_seconds)
        start = int(round(ahead_seconds))
        own_s = int(round(own))
        finish = start + own_s
        can_start = finish <= ACCEPT_WINDOW_SECONDS
        ahead = len(self._slots)
        view: dict[str, object] = {
            "ahead": ahead,
            "position": ahead + 1,
            "startInSeconds": start,
            "ownSeconds": own_s,
            "finishInSeconds": finish,
            "limitSeconds": int(ACCEPT_WINDOW_SECONDS),
            "canStart": can_start,
            "message": "",
        }
        view["message"] = describe(view)
        return view

    def try_reserve(self, audio_seconds: float) -> tuple[dict[str, object], Slot | None]:
        """収まるときだけ列の末尾に入れる。"""
        view = self.forecast(audio_seconds)
        if not view["canStart"]:
            return view, None
        slot = Slot(audio_seconds=max(0.0, audio_seconds), enqueued_at=time.monotonic())
        self._slots.append(slot)
        return view, slot

    def mark_started(self, slot: Slot) -> None:
        slot.started_at = time.monotonic()

    def release(self, slot: Slot) -> None:
        try:
            self._slots.remove(slot)
        except ValueError:
            return

    def _remaining_seconds(self, now: float) -> float:
        total = 0.0
        for slot in self._slots:
            cost = _process_seconds(slot.audio_seconds)
            if slot.started_at is None:
                total += cost
                continue
            total += max(0.0, cost - (now - slot.started_at))
        return total


def _process_seconds(audio_seconds: float) -> float:
    return max(0.0, audio_seconds) * SEC_PER_AUDIO_SEC


def describe(view: dict[str, object]) -> str:
    """画面に出す文。他の依頼の中身は含めない。"""
    ahead = int(view["ahead"])
    start = int(view["startInSeconds"])
    can_start = bool(view["canStart"])
    start_min = _minutes(start)
    if not can_start:
        if ahead <= 0:
            return (
                "この音声は、結果を返せる60分を超える見込みです。"
                "短く分割してから、再度実行してください。"
            )
        return (
            f"前に{ahead}件あります。開始見込みは約{start_min}分後で、"
            "結果が返る60分を超えます。今は受け付けできません。"
        )
    if ahead <= 0:
        return ""
    return (
        f"前に{ahead}件あります。開始見込みは約{start_min}分後です。"
        "このまま文字起こしを実行しますか？"
    )


def _minutes(seconds: int) -> int:
    if seconds <= 0:
        return 0
    return max(1, round(seconds / 60))


def estimate_audio_seconds(raw: bytes, *, total_bytes: int | None = None) -> float:
    """先頭のヘッダと全体のバイト数から、おおよその再生時間を返す。"""
    size = total_bytes if total_bytes is not None else len(raw)
    if size <= 0:
        return 0.0
    wav = _wav_seconds(raw, size)
    if wav is not None:
        return wav
    bitrate = _mp3_bitrate(raw)
    if bitrate is None:
        bitrate = FALLBACK_BITRATE
    return size * 8 / bitrate


def _wav_seconds(raw: bytes, size: int) -> float | None:
    if len(raw) < 44 or raw[:4] != b"RIFF":
        return None
    byte_rate = int.from_bytes(raw[28:32], "little")
    if byte_rate <= 0:
        return None
    return max(0.0, (size - 44) / byte_rate)


def _mp3_bitrate(raw: bytes) -> int | None:
    window = raw[:262144]
    for i in range(max(0, len(window) - 3)):
        b0, b1, b2 = window[i], window[i + 1], window[i + 2]
        if b0 != 0xFF or (b1 & 0xE0) != 0xE0:
            continue
        ver = (b1 >> 3) & 3
        layer = (b1 >> 1) & 3
        br_idx = (b2 >> 4) & 0xF
        sr_idx = (b2 >> 2) & 3
        if ver == 1 or layer != 1 or br_idx in (0, 15) or sr_idx == 3:
            continue
        if br_idx >= len(_MPEG1_L3):
            continue
        kbps = _MPEG1_L3[br_idx]
        if kbps:
            return kbps * 1000
    return None
