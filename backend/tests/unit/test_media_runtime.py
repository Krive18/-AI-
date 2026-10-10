from pathlib import Path

import pytest

from app.modules.media_runtime.ffmpeg import FFmpeg, MediaCommandError


class RecordingRunner:
    def __init__(self, stdout: str = "") -> None:
        self.stdout, self.commands = stdout, []

    def run(self, command: list[str], timeout_seconds: float) -> str:
        self.commands.append((command, timeout_seconds))
        return self.stdout


def test_extract_audio_uses_argument_array_and_fixed_audio_format(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    output = tmp_path / "audio.wav"
    FFmpeg(runner).extract_audio(tmp_path / "source;bad.mp4", output)
    command, _ = runner.commands[0]
    assert command[0] == "ffmpeg" and any(
        part.endswith("source;bad.mp4") for part in command
    )
    assert "shell" not in " ".join(command)
    assert command[-1] == str(output)


def test_probe_rejects_malformed_output(tmp_path: Path) -> None:
    with pytest.raises(MediaCommandError, match="MEDIA_PROBE_INVALID"):
        FFmpeg(RecordingRunner("not-json")).probe(tmp_path / "source.mp4")


def test_probe_returns_source_video_dimensions(tmp_path: Path) -> None:
    payload = (
        '{"streams": [{"codec_type": "video", "codec_name": "h264", '
        '"width": 720, "height": 1280}, '
        '{"codec_type": "audio", "codec_name": "aac"}], '
        '"format": {"duration": "14.833", "format_name": "mp4"}}'
    )

    probe = FFmpeg(RecordingRunner(payload)).probe(tmp_path / "source.mp4")

    assert probe.width == 720
    assert probe.height == 1280


def test_compose_timeline_delays_each_voice_segment(tmp_path: Path) -> None:
    runner = RecordingRunner()
    first = tmp_path / "first.wav"
    second = tmp_path / "second.mp3"
    output = tmp_path / "dubbed.wav"

    FFmpeg(runner).compose_timeline(
        [(first, 0, 900), (second, 1200, 2400)],
        3000,
        output,
    )

    command, _ = runner.commands[0]
    filters = command[command.index("-filter_complex") + 1]
    assert command[:3] == ["ffmpeg", "-y", "-f"]
    assert str(first) in command and str(second) in command
    assert "adelay=0|0" in filters and "adelay=1200|1200" in filters
    assert command[-1] == str(output)


def test_compose_timeline_fits_complete_voice_into_its_video_window(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    voice = tmp_path / "voice.mp3"
    output = tmp_path / "dubbed.wav"

    FFmpeg(runner).compose_timeline(
        [(voice, 1000, 4000, 6000)],
        5000,
        output,
    )

    command, _ = runner.commands[0]
    filters = command[command.index("-filter_complex") + 1]
    assert "atempo=2" in filters
    assert filters.index("atempo=2") < filters.index("atrim=0:3.000")
    assert "apad=pad_dur=3.000" in filters


def test_mux_masks_source_subtitles_and_replaces_audio_without_burning_subtitles(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    source = tmp_path / "source.mp4"
    dubbed = tmp_path / "dubbed.wav"
    output = tmp_path / "translated.mp4"

    FFmpeg(runner).mux(
        source,
        dubbed,
        output,
        video_width=720,
        video_height=1280,
        mask_rect=(43, 1100, 634, 60),
        original_volume=0.0,
    )

    command, _ = runner.commands[0]
    filters = command[command.index("-filter_complex") + 1]
    assert "[0:a]" not in filters
    assert "[1:a]anull[aout]" in filters
    assert "delogo=x=43:y=1100:w=634:h=60:show=0" in filters
    assert "subtitles=filename=" not in filters
    assert "[masked]null[vout]" in filters
    assert command[command.index("-map") + 1] == "[vout]"
    assert command[command.index("-map", command.index("-map") + 1) + 1] == "[aout]"
    assert command[command.index("-crf") + 1] == "18"
    assert command[command.index("-movflags") + 1] == "+faststart"


def test_mux_without_mask_rect_skips_delogo(tmp_path: Path) -> None:
    runner = RecordingRunner()
    source = tmp_path / "source.mp4"
    dubbed = tmp_path / "dubbed.wav"
    output = tmp_path / "translated.mp4"

    FFmpeg(runner).mux(
        source,
        dubbed,
        output,
        video_width=720,
        video_height=1280,
        original_volume=0.0,
    )

    command, _ = runner.commands[0]
    filters = command[command.index("-filter_complex") + 1]
    assert "delogo=" not in filters
    assert "[0:v]null[vout]" in filters


def test_mux_clamps_mask_rect_to_frame_edges(tmp_path: Path) -> None:
    runner = RecordingRunner()
    source = tmp_path / "source.mp4"
    dubbed = tmp_path / "dubbed.wav"
    output = tmp_path / "translated.mp4"

    FFmpeg(runner).mux(
        source,
        dubbed,
        output,
        video_width=720,
        video_height=1280,
        mask_rect=(-50, 1270, 10000, 500),
        original_volume=0.0,
    )

    command, _ = runner.commands[0]
    filters = command[command.index("-filter_complex") + 1]
    assert "delogo=x=1:y=1270:w=718:h=9:show=0" in filters
