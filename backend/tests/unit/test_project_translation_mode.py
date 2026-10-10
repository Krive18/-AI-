import pytest
from pydantic import ValidationError

from app.modules.project.routes import ProjectCreateRequest
from app.modules.project.schemas import YOUDAO_SUPPORTED_LOCALES, TranslationMode


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": "越南市场成片",
        "uploadToken": "upload-token-123456",
        "targetLocales": ["vi-VN"],
    }
    payload.update(overrides)
    return payload


def test_project_create_defaults_to_professional_translation() -> None:
    request = ProjectCreateRequest.model_validate(_payload())

    assert request.translation_mode is TranslationMode.PROFESSIONAL


def test_project_create_accepts_youdao_translation() -> None:
    request = ProjectCreateRequest.model_validate(_payload(translationMode="youdao"))

    assert request.translation_mode is TranslationMode.YOUDAO


def test_youdao_translation_rejects_unsupported_filipino_locale() -> None:
    with pytest.raises(ValidationError):
        ProjectCreateRequest.model_validate(
            _payload(translationMode="youdao", targetLocales=["vi-VN", "fil-PH"])
        )


def test_youdao_supported_locales_match_first_release_scope() -> None:
    assert YOUDAO_SUPPORTED_LOCALES == {
        "en-US",
        "ja-JP",
        "ko-KR",
        "vi-VN",
        "ms-MY",
        "th-TH",
    }
