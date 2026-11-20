"""クラウド文字起こしの分割と結合。API とモデルは呼ばない。"""

from app.cloud import prompt_tail, render_transcript, segment_ends


def test_short_audio_is_one_segment() -> None:
    assert segment_ends([0.1, 0.1], hop_seconds=0.2, duration=30) == [30]


def test_cut_prefers_the_quiet_window() -> None:
    rms = [0.5] * 8000
    # 10分の少し前（2900 * 0.2秒 = 580秒）を無音にする。
    rms[2900] = 0.0
    ends = segment_ends(rms, hop_seconds=0.2, duration=25 * 60)
    assert ends[-1] == 25 * 60
    assert abs(ends[0] - 580) < 1


def test_render_single_part_has_no_range_heading() -> None:
    text = render_transcript([{"start": 0, "end": 12, "text": "こんにちは", "language": "ja"}])
    assert text.startswith("**検出言語**: ja")
    assert "こんにちは" in text
    assert "–" not in text


def test_render_joins_parts_in_order() -> None:
    text = render_transcript(
        [
            {"start": 0, "end": 600, "text": "前半", "language": "ja"},
            {"start": 600, "end": 900, "text": "後半", "language": ""},
        ]
    )
    assert text.index("前半") < text.index("後半")
    assert "**10:00–15:00**" in text


def test_prompt_tail_keeps_the_end() -> None:
    assert prompt_tail("あ" * 50) == "あ" * 50
    assert prompt_tail("あ" * 250) == "あ" * 200
