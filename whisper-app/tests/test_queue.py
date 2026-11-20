"""文字起こしの待ち見積もり。モデルは起動しない。"""

from app.queue import TranscribeQueue, estimate_audio_seconds, seconds_for_queue


def test_empty_queue_accepts_a_meeting() -> None:
    queue = TranscribeQueue()
    view = queue.forecast(49 * 60)
    assert view["canStart"] is True
    assert view["ahead"] == 0
    assert view["position"] == 1
    assert view["message"] == ""


def test_second_long_file_is_refused_and_not_queued() -> None:
    queue = TranscribeQueue()
    view, slot = queue.try_reserve(49 * 60)
    assert slot is not None
    assert view["canStart"] is True

    blocked, extra = queue.try_reserve(49 * 60)
    assert extra is None
    assert blocked["canStart"] is False
    assert blocked["ahead"] == 1
    assert "受け付けできません" in str(blocked["message"])
    assert queue.forecast(60)["ahead"] == 1


def test_short_job_waits_behind_a_short_job() -> None:
    queue = TranscribeQueue()
    _, first = queue.try_reserve(10 * 60)
    assert first is not None
    view = queue.forecast(10 * 60)
    assert view["canStart"] is True
    assert view["position"] == 2
    assert view["message"] == (
        "現在、別の文字起こしを1件処理中です。"
        "受付中の処理が終わり次第開始できます。"
        "開始見込みは約12分後です。"
        "このまま文字起こしを実行しますか？"
    )


def test_running_job_remaining_shrinks() -> None:
    queue = TranscribeQueue()
    _, slot = queue.try_reserve(10 * 60)
    assert slot is not None
    queue.mark_started(slot)
    slot.started_at = slot.started_at - 10 * 60 * 1.2  # type: ignore[operator]
    view = queue.forecast(60)
    assert view["startInSeconds"] == 0


def test_release_opens_the_queue() -> None:
    queue = TranscribeQueue()
    _, slot = queue.try_reserve(49 * 60)
    assert slot is not None
    queue.release(slot)
    assert queue.forecast(49 * 60)["canStart"] is True


def test_known_duration_overrides_a_large_video_estimate() -> None:
    huge = b"\x00" * 64
    assert seconds_for_queue(61, huge) == 61
    assert seconds_for_queue("61", huge) == 61
    assert seconds_for_queue(0, b"not audio") == estimate_audio_seconds(b"not audio")


def test_mp3_bitrate_changes_the_estimate() -> None:
    # MPEG1 Layer3, 192 kbps, 44.1 kHz, frame sync
    frame = bytes([0xFF, 0xFB, 0xB0, 0x00])
    slow = estimate_audio_seconds(b"not audio", total_bytes=192_000)
    fast = estimate_audio_seconds(frame, total_bytes=192_000)
    assert fast < slow
    assert 7 < fast < 9
