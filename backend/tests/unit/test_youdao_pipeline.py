import pytest

from app.modules.provider_runtime.contracts import InterpretationSegment
from app.workers.pipeline import _validate_youdao_delivery


def _segment(
    sequence: int, start: int, end: int, translation: str
) -> InterpretationSegment:
    return InterpretationSegment(
        sequence_no=sequence,
        start_ms=start,
        end_ms=end,
        source_text="中文原文",
        translated_text=translation,
        audio=b"RIFFtarget-audio",
    )


def test_youdao_delivery_is_ordered_and_clamped_to_video_duration() -> None:
    result = _validate_youdao_delivery(
        [_segment(2, 1200, 2400, "Hai"), _segment(1, 100, 900, "Xin chào")],
        source_duration_ms=2000,
    )

    assert [(item.sequence_no, item.start_ms, item.end_ms) for item in result] == [
        (1, 100, 900),
        (2, 1200, 2000),
    ]
    assert [item.translated_text for item in result] == ["Xin chào", "Hai"]


def test_youdao_delivery_rejects_segments_outside_video_timeline() -> None:
    with pytest.raises(ValueError, match="timeline"):
        _validate_youdao_delivery(
            [_segment(1, 2000, 2400, "Xin chào")], source_duration_ms=2000
        )
