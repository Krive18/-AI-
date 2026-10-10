from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ProviderRequestError(RuntimeError):
    """Safe provider failure suitable for workflow events; never contains credentials."""

    def __init__(self, code: str, message: str = "供应商调用失败") -> None:
        self.code, self.message = code, message
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class ProviderUsage:
    input_units: int = 0
    output_units: int = 0
    audio_seconds: float = 0.0
    metadata: dict[str, int | float | str] = field(default_factory=dict)


@dataclass(frozen=True)
class AsrSegment:
    start_ms: int
    end_ms: int
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class AsrResult:
    segments: list[AsrSegment]
    usage: ProviderUsage


@dataclass(frozen=True)
class TranslationResult:
    text: str
    usage: ProviderUsage


@dataclass(frozen=True)
class TtsResult:
    audio: bytes
    content_type: str
    usage: ProviderUsage


@dataclass(frozen=True)
class InterpretationSegment:
    sequence_no: int
    start_ms: int
    end_ms: int
    source_text: str
    translated_text: str
    audio: bytes
    audio_format: str = "wav"


@dataclass(frozen=True)
class InterpretationResult:
    segments: list[InterpretationSegment]
    usage: ProviderUsage


@dataclass(frozen=True)
class ImageGenResult:
    image: bytes
    content_type: str
    usage: ProviderUsage


@dataclass(frozen=True)
class VideoGenResult:
    video: bytes
    content_type: str
    usage: ProviderUsage


class ProviderRuntime(Protocol):
    def probe(self) -> None: ...

    def transcribe(self, audio_path: str) -> AsrResult: ...

    def translate(
        self, text: str, target_locale: str, duration_ms: int | None = None
    ) -> TranslationResult: ...

    def synthesize(self, text: str, target_locale: str, voice_id: str) -> TtsResult: ...

    def interpret(
        self, audio_path: str, target_locale: str
    ) -> InterpretationResult: ...

    def interpret_text(
        self, audio_path: str, target_locale: str
    ) -> InterpretationResult: ...

    def generate(
        self, prompt: str, size: str, image_data_uris: list[str]
    ) -> ImageGenResult: ...

    def generate_video(
        self,
        prompt: str,
        reference_image_data_uri: str,
        resolution: str,
        duration_seconds: int,
        tier: int,
    ) -> VideoGenResult: ...

    def read_subtitle(self, frame_jpg: bytes) -> str: ...


class JsonTransport(Protocol):
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]: ...

    def get_json(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]: ...

    def get_bytes(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> bytes: ...

    def delete_json(
        self,
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]: ...


class WebSocketTransport(Protocol):
    def exchange(
        self,
        url: str,
        audio: bytes,
        chunk_bytes: int,
        interval_seconds: float,
        timeout_seconds: float,
    ) -> list[str]: ...
