from __future__ import annotations

import json
import math
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class MediaCommandError(RuntimeError):
    def __init__(self, code: str, message: str = "媒体处理失败") -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class CommandRunner(Protocol):
    def run(self, command: list[str], timeout_seconds: float) -> str: ...


class SubprocessRunner:
    def run(self, command: list[str], timeout_seconds: float) -> str:
        try:
            completed = subprocess.run(
                command,
                shell=False,
                check=True,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            raise MediaCommandError("MEDIA_COMMAND_TIMEOUT", "媒体处理超时") from None
        except (OSError, subprocess.CalledProcessError):
            raise MediaCommandError("MEDIA_COMMAND_FAILED") from None
        return completed.stdout


@dataclass(frozen=True)
class MediaProbe:
    duration_ms: int
    container: str | None
    video_codec: str | None
    audio_codec: str | None
    width: int | None
    height: int | None


class FFmpeg:
    def __init__(
        self, runner: CommandRunner | None = None, *, timeout_seconds: float = 900.0
    ) -> None:
        self._runner, self._timeout = runner or SubprocessRunner(), timeout_seconds

    def check_available(self) -> None:
        self._runner.run(["ffmpeg", "-version"], 15)
        self._runner.run(["ffprobe", "-version"], 15)

    def probe(self, source: Path) -> MediaProbe:
        output = self._runner.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_format",
                "-show_streams",
                "-of",
                "json",
                str(source),
            ],
            self._timeout,
        )
        try:
            data = json.loads(output)
            streams = data["streams"]
            duration_ms = round(float(data["format"]["duration"]) * 1000)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise MediaCommandError("MEDIA_PROBE_INVALID", "媒体探测结果无效") from None
        if not isinstance(streams, list) or duration_ms < 0:
            raise MediaCommandError("MEDIA_PROBE_INVALID", "媒体探测结果无效")
        video_stream = next(
            (
                stream
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "video"
            ),
            None,
        )
        video = video_stream.get("codec_name") if video_stream is not None else None
        width = video_stream.get("width") if video_stream is not None else None
        height = video_stream.get("height") if video_stream is not None else None
        audio = next(
            (
                stream.get("codec_name")
                for stream in streams
                if isinstance(stream, dict) and stream.get("codec_type") == "audio"
            ),
            None,
        )
        container = (
            data.get("format", {}).get("format_name")
            if isinstance(data.get("format"), dict)
            else None
        )
        return MediaProbe(
            duration_ms,
            container if isinstance(container, str) else None,
            video if isinstance(video, str) else None,
            audio if isinstance(audio, str) else None,
            width if isinstance(width, int) and width > 0 else None,
            height if isinstance(height, int) and height > 0 else None,
        )

    def extract_audio(self, source: Path, destination: Path) -> None:
        self._runner.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ],
            self._timeout,
        )

    def extract_subtitle_frames(
        self, source: Path, jpg_directory: Path, gray_path: Path
    ) -> int:
        """Extract 1 fps frames: 640px-wide JPEGs plus one 16x16 gray rawvideo.

        The JPEGs feed the vision OCR model; the concatenated grayscale
        frames feed local frame-diff planning. Returns the frame count.
        """
        jpg_directory.mkdir(parents=True, exist_ok=True)
        self._runner.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source),
                "-filter_complex",
                (
                    "[0:v]fps=1,split=2[ocr][diff];"
                    "[ocr]scale=640:-2[ocr_out];"
                    "[diff]scale=16:16,format=gray[diff_out]"
                ),
                "-map",
                "[ocr_out]",
                "-q:v",
                "3",
                str(jpg_directory / "frame-%06d.jpg"),
                "-map",
                "[diff_out]",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "gray",
                str(gray_path),
            ],
            self._timeout,
        )
        try:
            gray = gray_path.read_bytes()
        except OSError:
            raise MediaCommandError("MEDIA_COMMAND_FAILED", "字幕帧采样失败") from None
        frame_count, remainder = divmod(len(gray), 256)
        if frame_count <= 0 or remainder:
            raise MediaCommandError("MEDIA_PROBE_INVALID", "字幕帧采样为空")
        return frame_count

    def compose_timeline(
        self,
        segments: Sequence[tuple[Path, int, int] | tuple[Path, int, int, int]],
        duration_ms: int,
        destination: Path,
    ) -> None:
        if duration_ms <= 0 or not segments:
            raise MediaCommandError("MEDIA_TIMELINE_INVALID", "配音时间轴无效")
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=44100:cl=stereo:d={duration_ms / 1000:.3f}",
        ]
        filters: list[str] = []
        mixed_inputs = ["[0:a]"]
        for index, segment in enumerate(segments, 1):
            source, start_ms, end_ms = segment[:3]
            source_duration_ms = segment[3] if len(segment) == 4 else None
            if start_ms < 0 or end_ms <= start_ms or end_ms > duration_ms:
                raise MediaCommandError("MEDIA_TIMELINE_INVALID", "配音时间轴无效")
            if source_duration_ms is not None and source_duration_ms <= 0:
                raise MediaCommandError("MEDIA_TIMELINE_INVALID", "配音时长无效")
            command.extend(["-i", str(source)])
            target_duration_ms = end_ms - start_ms
            maximum_seconds = target_duration_ms / 1000
            audio_filters = [f"[{index}:a]aresample=44100", "asetpts=PTS-STARTPTS"]
            if (
                source_duration_ms is not None
                and source_duration_ms > target_duration_ms
            ):
                tempo = source_duration_ms / target_duration_ms
                factor_count = math.ceil(math.log2(tempo))
                factor = tempo ** (1 / factor_count)
                formatted = f"{factor:.5f}".rstrip("0").rstrip(".")
                audio_filters.extend(f"atempo={formatted}" for _ in range(factor_count))
            audio_filters.extend(
                [
                    f"atrim=0:{maximum_seconds:.3f}",
                    f"apad=pad_dur={maximum_seconds:.3f}",
                    f"atrim=0:{maximum_seconds:.3f}",
                    f"adelay={start_ms}|{start_ms}[voice{index}]",
                ]
            )
            filters.append(",".join(audio_filters))
            mixed_inputs.append(f"[voice{index}]")
        filters.append(
            f"{''.join(mixed_inputs)}amix=inputs={len(mixed_inputs)}:"
            "duration=first:normalize=0[aout]"
        )
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[aout]",
                "-c:a",
                "pcm_s16le",
                str(destination),
            ]
        )
        self._runner.run(command, self._timeout)

    def mux(
        self,
        source_video: Path,
        dubbed_audio: Path,
        destination: Path,
        *,
        video_width: int | None = None,
        video_height: int | None = None,
        mask_rect: tuple[int, int, int, int] | None = None,
        original_volume: float = 0.0,
    ) -> None:
        if not 0 <= original_volume <= 1:
            raise MediaCommandError("MEDIA_MIX_INVALID", "原声音量无效")
        if mask_rect is not None and (
            not video_width or not video_height or video_width <= 0 or video_height <= 0
        ):
            raise MediaCommandError("MEDIA_SUBTITLE_INVALID", "视频尺寸无效")

        filters: list[str] = []
        video_input = "[0:v]"
        if mask_rect is not None:
            assert video_width is not None and video_height is not None
            # delogo samples pixels around the rectangle, so keep it off the edges.
            mask_x, mask_y, mask_width, mask_height = mask_rect
            mask_x = min(max(1, mask_x), video_width - 2)
            mask_y = min(max(1, mask_y), video_height - 2)
            mask_width = min(mask_width, video_width - mask_x - 1)
            mask_height = min(mask_height, video_height - mask_y - 1)
            if mask_width >= 8 and mask_height >= 4:
                filters.append(
                    f"{video_input}delogo=x={mask_x}:y={mask_y}:w={mask_width}:"
                    f"h={mask_height}:show=0[masked]"
                )
                video_input = "[masked]"
        filters.append(f"{video_input}null[vout]")

        if original_volume == 0:
            filters.append("[1:a]anull[aout]")
        else:
            filters.append(
                f"[0:a]volume={original_volume}[original];"
                "[original][1:a]amix=inputs=2:duration=first[aout]"
            )
        self._runner.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(source_video),
                "-i",
                str(dubbed_audio),
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[vout]",
                "-map",
                "[aout]",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "18",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-movflags",
                "+faststart",
                "-shortest",
                str(destination),
            ],
            self._timeout,
        )
