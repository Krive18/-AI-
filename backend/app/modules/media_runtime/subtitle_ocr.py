"""Frame-diff-driven planning for burned-in subtitle OCR.

The pipeline samples a source video at one frame per second. Sending every
frame to a vision model is slow and expensive, so tiny 16x16 grayscale
frames are decoded locally first: only frames whose pixels actually changed
(or a periodic forced sample) are forwarded for OCR. This module holds the
pure planning and segment-merging logic so it can be unit-tested without
FFmpeg or a provider transport.
"""

from __future__ import annotations

from dataclasses import dataclass

DIFF_WIDTH = 16
DIFF_HEIGHT = 16
FRAME_BYTES = DIFF_WIDTH * DIFF_HEIGHT
# Gray delta per pixel above which the pixel counts as changed. JPEG noise
# and codec shimmer stay well under this on static content.
PIXEL_DELTA_TOLERANCE = 24
# Number of changed pixels (out of 256) that marks a frame as visually
# changed. At 16x16 a single subtitle line only touches a handful of cells
# (measured 4-8 on a 720p burn-in), while a static picture diffs at 0, so a
# low threshold still separates subtitles from noise; the periodic forced
# OCR bounds the cost of any false positives.
CHANGED_PIXEL_THRESHOLD = 4
# Re-OCR at least every N frames even without pixel changes, so a static
# shot whose subtitle changes mid-cue without visible motion still gets read.
FORCE_OCR_FRAME_INTERVAL = 60
# Frames are extracted at 1 fps; frame i covers [i*1000, (i+1)*1000) ms.
FRAME_INTERVAL_MS = 1000


def frames_differ(previous: bytes, current: bytes) -> bool:
    """Whether two 16x16 grayscale frames differ beyond codec noise."""
    if len(previous) != FRAME_BYTES or len(current) != FRAME_BYTES:
        raise ValueError("diff frame must be 16x16 grayscale")
    changed = sum(
        1
        for a, b in zip(previous, current, strict=True)
        if abs(a - b) > PIXEL_DELTA_TOLERANCE
    )
    return changed >= CHANGED_PIXEL_THRESHOLD


def should_ocr_frame(index: int, previous: bytes, current: bytes) -> bool:
    """Frame 0 is always read; later frames only on change or forced cadence."""
    if index == 0 or index % FORCE_OCR_FRAME_INTERVAL == 0:
        return True
    return frames_differ(previous, current)


def plan_ocr_indices(gray_frames: list[bytes]) -> list[int]:
    """Frames (0-based) that need an OCR call for a decoded gray frame list."""
    planned: list[int] = []
    for index in range(len(gray_frames)):
        if index == 0:
            planned.append(index)
            continue
        if should_ocr_frame(index, gray_frames[index - 1], gray_frames[index]):
            planned.append(index)
    return planned


@dataclass(frozen=True, slots=True)
class OcrSubtitleSegment:
    start_ms: int
    end_ms: int
    text: str


class OcrSegmentBuilder:
    """Merges per-frame OCR text into timeline segments.

    Consecutive frames whose OCR text is identical extend one segment; a
    frame without subtitles closes the open segment; different text starts a
    new one. Only frames that were actually sent to OCR are added.
    """

    def __init__(self, duration_ms: int | None = None) -> None:
        self._duration_ms = duration_ms if duration_ms and duration_ms > 0 else None
        self._segments: list[OcrSubtitleSegment] = []
        self._open_text: str | None = None
        self._open_start_ms = 0
        self._open_end_ms = 0

    def add(self, frame_index: int, text: str) -> None:
        cleaned = text.strip()
        start_ms = frame_index * FRAME_INTERVAL_MS
        end_ms = start_ms + FRAME_INTERVAL_MS
        if not cleaned:
            self._close()
            return
        if self._open_text == cleaned:
            self._open_end_ms = end_ms
            return
        self._close()
        self._open_text = cleaned
        self._open_start_ms = start_ms
        self._open_end_ms = end_ms

    def note_unchanged(self, frame_index: int) -> None:
        """Advance an open segment through a frame that was not OCR'd.

        Skipping OCR for a frame is only allowed when the frame is
        pixel-identical to its predecessor, so an open subtitle is assumed
        to persist; the forced OCR cadence re-confirms the text regularly.
        """
        if self._open_text is None:
            return
        self._open_end_ms = (frame_index + 1) * FRAME_INTERVAL_MS

    def _close(self) -> None:
        if self._open_text is None:
            return
        end_ms = self._open_end_ms
        if self._duration_ms is not None:
            end_ms = min(end_ms, self._duration_ms)
        if end_ms > self._open_start_ms:
            self._segments.append(
                OcrSubtitleSegment(self._open_start_ms, end_ms, self._open_text)
            )
        self._open_text = None

    def finish(self) -> list[OcrSubtitleSegment]:
        self._close()
        return list(self._segments)
