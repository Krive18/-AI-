from dataclasses import dataclass
from enum import StrEnum

SUPPORTED_LOCALES = frozenset(
    {
        "en-US",
        "ja-JP",
        "ko-KR",
        "vi-VN",
        "ms-MY",
        "th-TH",
        "en-SG",
        "fil-PH",
        "de-DE",
        "fr-FR",
    }
)
YOUDAO_SUPPORTED_LOCALES = frozenset(
    {"en-US", "ja-JP", "ko-KR", "vi-VN", "ms-MY", "th-TH"}
)
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024
UPLOAD_SESSION_SECONDS = 24 * 60 * 60
ALLOWED_SUFFIXES = frozenset({".mp4", ".mov", ".mkv"})


class TranslationMode(StrEnum):
    PROFESSIONAL = "professional"
    YOUDAO = "youdao"
    SUBTITLE_OCR = "subtitle"


@dataclass(frozen=True, slots=True)
class UploadSession:
    token: str
    account_id: int
    filename: str
    content_type: str
    total_bytes: int
    object_key: str


@dataclass(frozen=True, slots=True)
class TaskSubtitles:
    source_text: str
    target_text: str
    segment_count: int
