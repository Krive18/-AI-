"""Locate the burned-in source-subtitle band of a video.

Short-form source videos place their Chinese subtitles at varying heights, so
the render step cannot mask a fixed band. This module samples grayscale frames
via FFmpeg, scores each row by horizontal edge energy (subtitle strokes are
dense horizontal edges compared with typical backgrounds), and merges the
strongest per-frame bands into one rectangle. Because static product or hand
close-ups can match the spatial profile of text, candidate rows must also show
temporal activity: real subtitle rows change whenever the cue switches, while
a static textured region stays constant across frames. A row only counts when
its edge energy is both strong in the frame and unstable over time. Pure-Python
on small downscaled frames; no extra dependencies.
"""

from __future__ import annotations

import statistics
import subprocess
from itertools import pairwise
from pathlib import Path

from app.modules.media_runtime.ffmpeg import MediaCommandError

ANALYSIS_WIDTH = 192
FRAME_SAMPLES = 16
SEARCH_TOP_FRACTION = 0.55
X_MARGIN_FRACTION = 0.08
MIN_BAND_FRACTION = 0.015
MAX_BAND_FRACTION = 0.30
MIN_ROW_SCORE = 6.0
SCORE_RATIO = 2.5
MIN_ROW_DELTA = 4.0
MIN_ROW_CHANGES = 2
MIN_BAND_ROWS = 4
GAP_TOLERANCE_ROWS = 2
PAD_FRACTION = 0.012


def extract_gray_frame(
    source: Path, timestamp_seconds: float, width: int = ANALYSIS_WIDTH
) -> tuple[int, int, bytes]:
    """Decode one downscaled grayscale frame. Returns (width, height, pixels)."""
    command = [
        "ffmpeg",
        "-v",
        "error",
        "-ss",
        f"{timestamp_seconds:.3f}",
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-vf",
        f"scale={width}:-2",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    try:
        completed = subprocess.run(
            command, shell=False, check=True, capture_output=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        raise MediaCommandError("MEDIA_COMMAND_TIMEOUT", "字幕区域采样超时") from None
    except (OSError, subprocess.CalledProcessError):
        raise MediaCommandError("MEDIA_COMMAND_FAILED", "字幕区域采样失败") from None
    data = completed.stdout
    height, remainder = divmod(len(data), width)
    if height <= 0 or remainder:
        raise MediaCommandError("MEDIA_PROBE_INVALID", "字幕区域采样为空")
    return width, height, data


def _row_scores(
    frame_width: int, frame_height: int, pixels: bytes
) -> list[tuple[int, float]]:
    """Per-row mean horizontal edge strength inside the bottom search area."""
    x0 = int(frame_width * X_MARGIN_FRACTION)
    x1 = int(frame_width * (1 - X_MARGIN_FRACTION))
    y0 = int(frame_height * SEARCH_TOP_FRACTION)
    span = max(1, x1 - 1 - x0)
    scores: list[tuple[int, float]] = []
    for y in range(y0, frame_height):
        row = pixels[y * frame_width : (y + 1) * frame_width]
        total = 0
        for x in range(x0, x1 - 1):
            total += abs(row[x + 1] - row[x])
        scores.append((y, total / span))
    return scores


def _merge_rows(rows: list[int], gap: int) -> list[tuple[int, int]]:
    bands: list[tuple[int, int]] = []
    start = previous = rows[0]
    for y in rows[1:]:
        if y - previous <= gap + 1:
            previous = y
        else:
            bands.append((start, previous))
            start = previous = y
    bands.append((start, previous))
    return bands


def _row_temporal_changes(
    frame_scores: list[dict[int, float]],
) -> dict[int, int]:
    """Per-row count of frame-to-frame edge-energy jumps across sampled frames.

    Subtitle cues replace their text when switching, so rows inside the band
    swing strongly several times over the clip. Static textures (product or
    hand close-ups) stay constant and never reach MIN_ROW_DELTA.
    """
    if len(frame_scores) < 2:
        return {}
    rows = frame_scores[0].keys()
    changes: dict[int, int] = {}
    for y in rows:
        count = 0
        for previous, current in pairwise(frame_scores):
            if abs(current.get(y, 0.0) - previous.get(y, 0.0)) >= MIN_ROW_DELTA:
                count += 1
        changes[y] = count
    return changes


def _frame_band(
    scores: list[tuple[int, float]],
    frame_height: int,
    temporal_changes: dict[int, int] | None = None,
) -> tuple[int, int] | None:
    """Strongest contiguous text-like band in one frame, or None.

    Rows must pass the spatial threshold; when temporal_changes is given they
    must also have changed often enough across sampled frames, which rejects
    static textured regions that merely look like dense horizontal edges.
    """
    if not scores:
        return None
    threshold = max(
        MIN_ROW_SCORE, statistics.median(value for _, value in scores) * SCORE_RATIO
    )
    if temporal_changes is None:
        rows = [y for y, value in scores if value >= threshold]
    else:
        rows = [
            y
            for y, value in scores
            if value >= threshold and temporal_changes.get(y, 0) >= MIN_ROW_CHANGES
        ]
    if not rows:
        return None
    bands = [
        band
        for band in _merge_rows(rows, GAP_TOLERANCE_ROWS)
        if band[1] - band[0] + 1 >= MIN_BAND_ROWS
    ]
    if not bands:
        return None
    by_row = dict(scores)
    strongest = max(
        bands, key=lambda band: sum(by_row[y] for y in range(band[0], band[1] + 1))
    )
    return strongest


def merge_frame_bands(
    bands: list[tuple[int, int]], frame_height: int
) -> tuple[int, int] | None:
    """Union per-frame bands into one rectangle with padding and sanity limits."""
    if not bands:
        return None
    y0 = min(band[0] for band in bands)
    y1 = max(band[1] for band in bands)
    pad = max(2, round(frame_height * PAD_FRACTION))
    y0 = max(1, y0 - pad)
    y1 = min(frame_height - 2, y1 + pad)
    height = y1 - y0 + 1
    if height < frame_height * MIN_BAND_FRACTION:
        return None
    if height > frame_height * MAX_BAND_FRACTION:
        return None
    return y0, y1


def _consensus_band(
    bands: list[tuple[int, int]], frame_height: int
) -> tuple[int, int] | None:
    """Cluster per-frame bands and keep the cluster most frames agree on.

    Busy backgrounds can produce a strong false-positive band in one or two
    frames, so a global union would over-expand and get rejected. Subtitles
    recur at the same position across cues, which is what consensus exploits.
    """
    if not bands:
        return None
    clusters: list[list[tuple[int, int]]] = []
    for band in sorted(bands):
        for cluster in clusters:
            y0 = min(item[0] for item in cluster)
            y1 = max(item[1] for item in cluster)
            if (
                band[0] <= y1 + GAP_TOLERANCE_ROWS
                and band[1] >= y0 - GAP_TOLERANCE_ROWS
            ):
                cluster.append(band)
                break
        else:
            clusters.append([band])
    best = max(
        clusters,
        key=lambda cluster: (
            len(cluster),
            -min(item[0] for item in cluster),
        ),
    )
    if len(best) < 2:
        return None
    return merge_frame_bands(best, frame_height)


def detect_subtitle_band(
    source: Path, duration_ms: int, source_height: int
) -> tuple[int, int] | None:
    """Subtitle rectangle (y0, y1) in source pixels, or None when undetected."""
    duration_seconds = max(1.0, duration_ms / 1000)
    step = duration_seconds / (FRAME_SAMPLES + 1)
    per_frame: list[list[tuple[int, float]]] = []
    frame_height = 0
    for index in range(1, FRAME_SAMPLES + 1):
        _, frame_height, pixels = extract_gray_frame(source, step * index)
        per_frame.append(_row_scores(ANALYSIS_WIDTH, frame_height, pixels))
    if frame_height == 0:
        return None
    temporal_changes = _row_temporal_changes([dict(scores) for scores in per_frame])
    bands: list[tuple[int, int]] = []
    for scores in per_frame:
        band = _frame_band(scores, frame_height, temporal_changes)
        if band is not None:
            bands.append(band)
    if not bands:
        return None
    band = _consensus_band(bands, frame_height)
    if band is None or source_height <= 0:
        return None
    scale = source_height / frame_height
    return round(band[0] * scale), round(band[1] * scale)
