import pytest

from app.modules.media_runtime.subtitle_ocr import (
    CHANGED_PIXEL_THRESHOLD,
    FORCE_OCR_FRAME_INTERVAL,
    FRAME_BYTES,
    OcrSegmentBuilder,
    frames_differ,
    plan_ocr_indices,
    should_ocr_frame,
)

BLACK = bytes(FRAME_BYTES)
WHITE = bytes([255]) * FRAME_BYTES
GRAY = bytes([128]) * FRAME_BYTES


def _frame(base: int, tweaks: dict[int, int] | None = None) -> bytes:
    pixels = bytearray([base]) * FRAME_BYTES
    for index, value in (tweaks or {}).items():
        pixels[index] = value
    return bytes(pixels)


def test_identical_frames_do_not_differ() -> None:
    assert not frames_differ(GRAY, _frame(128, {10: 128 + 24}))


def test_large_pixel_shift_marks_frame_changed() -> None:
    tweaks = {index: 255 for index in range(CHANGED_PIXEL_THRESHOLD)}
    assert frames_differ(GRAY, _frame(128, tweaks))


def test_frame_diff_requires_exact_frame_size() -> None:
    with pytest.raises(ValueError):
        frames_differ(b"\x00" * 100, GRAY)


def test_first_frame_and_forced_cadence_are_always_planned() -> None:
    frames = [BLACK] * (FORCE_OCR_FRAME_INTERVAL + 2)
    planned = plan_ocr_indices(frames)
    assert planned == [0, FORCE_OCR_FRAME_INTERVAL]


def test_changed_frame_is_planned() -> None:
    frames = [BLACK, BLACK, WHITE, WHITE]
    assert plan_ocr_indices(frames) == [0, 2]


def test_should_ocr_frame_needs_previous_frame() -> None:
    assert should_ocr_frame(0, BLACK, BLACK)
    assert should_ocr_frame(3, BLACK, WHITE)


def test_builder_merges_consecutive_identical_text() -> None:
    builder = OcrSegmentBuilder(duration_ms=10_000)
    for index, text in [(0, "你好"), (1, "你好"), (2, "")]:
        builder.add(index, text)
    segments = builder.finish()
    assert [(s.start_ms, s.end_ms, s.text) for s in segments] == [
        (0, 2000, "你好")
    ]


def test_builder_starts_new_segment_on_text_change() -> None:
    builder = OcrSegmentBuilder(duration_ms=10_000)
    for index, text in [(0, "第一句"), (1, "第一句"), (2, "第二句"), (3, "第二句")]:
        builder.add(index, text)
    segments = builder.finish()
    assert [(s.start_ms, s.end_ms, s.text) for s in segments] == [
        (0, 2000, "第一句"),
        (2000, 4000, "第二句"),
    ]


def test_builder_bridges_gap_until_forced_ocr_read() -> None:
    # Frame 60 is forced even though frames 1-59 looked unchanged; if the
    # subtitle there still matches, the segment extends across the gap.
    builder = OcrSegmentBuilder(duration_ms=120_000)
    builder.add(0, "持续字幕")
    builder.add(FORCE_OCR_FRAME_INTERVAL, "持续字幕")
    segments = builder.finish()
    assert [(s.start_ms, s.end_ms, s.text) for s in segments] == [
        (0, 61_000, "持续字幕")
    ]


def test_builder_closes_open_segment_at_finish() -> None:
    builder = OcrSegmentBuilder(duration_ms=10_000)
    builder.add(0, "结尾字幕")
    segments = builder.finish()
    assert [(s.start_ms, s.end_ms, s.text) for s in segments] == [
        (0, 1000, "结尾字幕")
    ]


def test_builder_clamps_last_segment_to_source_duration() -> None:
    builder = OcrSegmentBuilder(duration_ms=2500)
    builder.add(0, "你好")
    builder.add(1, "你好")
    builder.add(2, "你好")
    segments = builder.finish()
    assert [(s.start_ms, s.end_ms) for s in segments] == [(0, 2500)]


def test_builder_without_subtitles_produces_nothing() -> None:
    builder = OcrSegmentBuilder(duration_ms=10_000)
    for index in range(4):
        builder.add(index, "")
    assert builder.finish() == []


def test_builder_extends_open_segment_through_unchanged_frames() -> None:
    # Frames 1 and 2 were skipped by frame-diffing (identical pixels), so an
    # open segment must persist through them until the next OCR read.
    builder = OcrSegmentBuilder(duration_ms=10_000)
    builder.add(0, "第一句")
    builder.note_unchanged(1)
    builder.note_unchanged(2)
    builder.add(3, "第二句")
    segments = builder.finish()
    assert [(s.start_ms, s.end_ms, s.text) for s in segments] == [
        (0, 3000, "第一句"),
        (3000, 4000, "第二句"),
    ]


def test_builder_note_unchanged_without_open_segment_is_noop() -> None:
    builder = OcrSegmentBuilder(duration_ms=10_000)
    builder.note_unchanged(0)
    builder.note_unchanged(1)
    builder.add(2, "你好")
    builder.note_unchanged(3)
    segments = builder.finish()
    assert [(s.start_ms, s.end_ms, s.text) for s in segments] == [
        (2000, 4000, "你好")
    ]
