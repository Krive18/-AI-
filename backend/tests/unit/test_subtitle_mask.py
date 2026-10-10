from app.modules.media_runtime.subtitle_mask import (
    MIN_ROW_DELTA,
    _frame_band,
    _merge_rows,
    _row_scores,
    _row_temporal_changes,
    merge_frame_bands,
)

WIDTH = 192
HEIGHT = 341  # 1080x1920 downscaled to 192 wide


def _frame(band: tuple[int, int] | None, background: int = 200) -> bytes:
    pixels = bytearray([background] * (WIDTH * HEIGHT))
    if band is not None:
        y0, y1 = band
        for y in range(y0, y1 + 1):
            for x in range(int(WIDTH * 0.2), int(WIDTH * 0.8)):
                # Stroke-like alternating pattern: dense horizontal edges.
                pixels[y * WIDTH + x] = 40 if (x // 3) % 2 == 0 else 230
    return bytes(pixels)


def test_frame_band_finds_text_rows() -> None:
    band = (300, 312)
    scores = _row_scores(WIDTH, HEIGHT, _frame(band))

    detected = _frame_band(scores, HEIGHT)

    assert detected is not None
    assert abs(detected[0] - band[0]) <= 1
    assert abs(detected[1] - band[1]) <= 1


def test_frame_band_returns_none_for_clean_frame() -> None:
    scores = _row_scores(WIDTH, HEIGHT, _frame(None))

    assert _frame_band(scores, HEIGHT) is None


def test_frame_band_ignores_noise_below_threshold() -> None:
    pixels = bytearray([200] * (WIDTH * HEIGHT))
    pixels[320 * WIDTH + 96] = 0  # single stray pixel
    scores = _row_scores(WIDTH, HEIGHT, bytes(pixels))

    assert _frame_band(scores, HEIGHT) is None


def test_merge_rows_groups_contiguous_rows() -> None:
    assert _merge_rows([10, 11, 12, 20, 21, 40], 2) == [(10, 12), (20, 21), (40, 40)]


def test_merge_frame_bands_unions_and_pads() -> None:
    merged = merge_frame_bands([(300, 312), (296, 320)], HEIGHT)

    assert merged is not None
    y0, y1 = merged
    assert y0 < 300 and y1 > 320
    assert y1 - y0 < HEIGHT * 0.30


def test_merge_frame_bands_rejects_oversized_band() -> None:
    assert merge_frame_bands([(200, 320)], HEIGHT) is None


def test_merge_frame_bands_rejects_empty() -> None:
    assert merge_frame_bands([], HEIGHT) is None


def test_consensus_band_ignores_lone_false_positive() -> None:
    from app.modules.media_runtime.subtitle_mask import _consensus_band

    bands = [(312, 320)] * 4 + [(120, 140)]

    merged = _consensus_band(bands, HEIGHT)

    assert merged is not None
    assert abs(merged[0] - 312) <= 4
    assert abs(merged[1] - 320) <= 4


def test_consensus_band_rejects_single_frame_detection() -> None:
    from app.modules.media_runtime.subtitle_mask import _consensus_band

    assert _consensus_band([(312, 320)], HEIGHT) is None
    assert _consensus_band([(100, 120), (250, 270)], HEIGHT) is None


def _score_series(
    band: tuple[int, int] | None,
    frames: int,
    *,
    band_score: float = 40.0,
    background: int = 200,
) -> list[dict[int, float]]:
    """Per-frame row-score dicts; the band energy reappears every other frame."""
    series: list[dict[int, float]] = []
    for frame in range(frames):
        scores = dict(_row_scores(WIDTH, HEIGHT, _frame(None, background)))
        if band is not None and frame % 2 == 0:
            y0, y1 = band
            for y in range(y0, y1 + 1):
                scores[y] = band_score
        series.append(scores)
    return series


def test_temporal_changes_count_cue_switches() -> None:
    series = _score_series((300, 312), frames=6)

    changes = _row_temporal_changes(series)

    assert changes[300] == 5  # energy toggles on every frame boundary
    assert changes[306] == 5
    assert changes[250] == 0  # background never changes


def test_temporal_changes_ignore_small_jitter() -> None:
    series = _score_series((300, 312), frames=6)
    for index, frame in enumerate(series):  # ±jitter below MIN_ROW_DELTA
        if index % 2 == 0:
            frame[250] = MIN_ROW_DELTA / 2

    changes = _row_temporal_changes(series)

    assert changes[250] == 0  # jitter below MIN_ROW_DELTA is not a change
    assert changes[300] == 5


def test_frame_band_rejects_static_textured_rows() -> None:
    # Same dense-edge rows in every frame: strong spatially, zero temporal
    # activity, like a static product close-up.
    series = _score_series((300, 312), frames=6)
    for frame in series:  # make the band static across all frames
        for y in range(300, 313):
            frame[y] = 40.0
    scores = [(y, value) for y, value in series[0].items()]
    changes = _row_temporal_changes(series)

    assert _frame_band(scores, HEIGHT, changes) is None


def test_frame_band_keeps_rows_with_cue_changes() -> None:
    series = _score_series((300, 312), frames=6)
    scores = [(y, value) for y, value in series[0].items()]
    changes = _row_temporal_changes(series)

    detected = _frame_band(scores, HEIGHT, changes)

    assert detected is not None
    assert abs(detected[0] - 300) <= 1
    assert abs(detected[1] - 312) <= 1


def test_frame_band_without_temporal_keeps_legacy_behavior() -> None:
    series = _score_series((300, 312), frames=6)
    for frame in series:  # static band, would be rejected with temporal gating
        for y in range(300, 313):
            frame[y] = 40.0
    scores = [(y, value) for y, value in series[0].items()]

    detected = _frame_band(scores, HEIGHT)

    assert detected is not None
    assert abs(detected[0] - 300) <= 1
    assert abs(detected[1] - 312) <= 1
