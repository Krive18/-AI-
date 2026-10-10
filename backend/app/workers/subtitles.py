from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    sequence_no: int
    start_ms: int
    end_ms: int
    text: str


def _timestamp(milliseconds: int) -> str:
    if milliseconds < 0:
        raise ValueError("subtitle timestamp cannot be negative")
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def render_srt(cues: Iterable[SubtitleCue]) -> bytes:
    blocks: list[str] = []
    previous_end = 0
    for cue in cues:
        text = cue.text.strip()
        if (
            cue.sequence_no < 1
            or cue.start_ms < previous_end
            or cue.end_ms <= cue.start_ms
            or not text
        ):
            raise ValueError("subtitle cue is invalid or out of order")
        blocks.append(
            f"{cue.sequence_no}\n{_timestamp(cue.start_ms)} --> "
            f"{_timestamp(cue.end_ms)}\n{text}"
        )
        previous_end = cue.end_ms
    return ("\n\n".join(blocks) + "\n").encode("utf-8-sig")
