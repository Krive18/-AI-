import base64
import hashlib
import io
import json
import tarfile
import wave
from base64 import urlsafe_b64encode
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider.service import RuntimeHealthChecker
from app.modules.provider_runtime.contracts import ProviderRequestError
from app.modules.provider_runtime.runtime import (
    ProviderRuntimeFactory,
    ProviderSelector,
)


def _cipher() -> ProviderSecretCipher:
    return ProviderSecretCipher(urlsafe_b64encode(b"a" * 32).decode())


def _version(
    code: str, capability: ProviderCapability, *, locales: list[str] | None = None
) -> tuple[ProviderConfig, ProviderVersion]:
    cipher = _cipher()
    config = ProviderConfig(
        provider_code=code,
        capability=int(capability),
        status=int(ProviderStatus.ENABLED),
        priority=10,
        supported_locales_json=locales,
    )
    version = ProviderVersion(
        model_name="model-x",
        endpoint_url="https://provider.invalid/api",
        timeout_ms=750,
        config_json=None,
        encrypted_secret=cipher.encrypt("secret-value"),
        status=int(ProviderStatus.ENABLED),
    )
    return config, version


class RecordingTransport:
    def __init__(self, response: dict[str, object]) -> None:
        self.response, self.calls = response, []

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append((url, headers, payload, timeout_seconds))
        return self.response

    def get_json(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append((url, headers, query, timeout_seconds))
        return {"status": "Success", "file_id": 42, "base_resp": {"status_code": 0}}

    def get_bytes(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> bytes:
        self.calls.append((url, headers, query, timeout_seconds))
        return b"ID3audio"


class RecordingWebSocketTransport:
    def __init__(self, messages: list[str]) -> None:
        self.messages = messages
        self.calls: list[tuple[str, bytes, int, float, float]] = []

    def exchange(
        self,
        url: str,
        audio: bytes,
        chunk_bytes: int,
        interval_seconds: float,
        timeout_seconds: float,
    ) -> list[str]:
        self.calls.append((url, audio, chunk_bytes, interval_seconds, timeout_seconds))
        return self.messages


def _minimax_archive(audio: bytes = b"ID3-test-audio") -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        member = tarfile.TarInfo("result/content.mp3")
        member.size = len(audio)
        archive.addfile(member, io.BytesIO(audio))
    return output.getvalue()


def test_selector_uses_enabled_locale_match_and_priority() -> None:
    first = _version("minimax", ProviderCapability.TTS, locales=["en-US"])
    second = _version("minimax", ProviderCapability.TTS, locales=["ja-JP"])
    second[0].priority = 1
    selected = ProviderSelector().select(
        ProviderCapability.TTS, "ja-JP", [first, second]
    )
    assert selected.config.provider_code == "minimax"


def test_factory_rejects_development_provider_codes() -> None:
    config, version = _version("mock_translation", ProviderCapability.TRANSLATION)
    with pytest.raises(ProviderRequestError, match="PROVIDER_UNSUPPORTED"):
        ProviderRuntimeFactory(_cipher()).build(config, version)


def test_doubao_health_check_submits_a_real_probe_request() -> None:
    config, version = _version("doubao_asr", ProviderCapability.ASR)
    version.endpoint_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    version.config_json = {
        "query_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
        "resource_id": "volc.seedasr.auc",
    }
    transport = RecordingTransport({})

    result = RuntimeHealthChecker(ProviderRuntimeFactory(_cipher(), transport)).check(
        config, version
    )

    assert result == "CONNECTED"
    url, headers, payload, _ = transport.calls[0]
    assert url.endswith("/api/v3/auc/bigmodel/submit")
    assert headers["X-Api-Key"] == "secret-value"
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers
    assert headers["X-Api-Resource-Id"] == "volc.seedasr.auc"
    assert payload["user"] == {"uid": headers["X-Api-Request-Id"]}
    audio = payload["audio"]
    assert isinstance(audio, dict) and isinstance(audio["data"], str)
    with wave.open(io.BytesIO(base64.b64decode(audio["data"])), "rb") as sample:
        assert sample.getframerate() == 16000
        assert sample.getnframes() == 16000
    request = payload["request"]
    assert isinstance(request, dict)
    assert request["enable_auto_lang"] is True


def test_doubao_auto_language_detection_can_be_disabled() -> None:
    config, version = _version("doubao_asr", ProviderCapability.ASR)
    version.endpoint_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    version.config_json = {
        "query_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
        "resource_id": "volc.seedasr.auc",
        "auto_lang": False,
    }
    transport = RecordingTransport({})

    RuntimeHealthChecker(ProviderRuntimeFactory(_cipher(), transport)).check(
        config, version
    )

    _url, _headers, payload, _timeout = transport.calls[0]
    assert payload["request"]["enable_auto_lang"] is False


class SilentProbeTransport(RecordingTransport):
    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        raise ProviderRequestError("PROVIDER_NO_SPEECH", "测试音频没有语音")


def test_doubao_silent_probe_still_confirms_api_key_connection() -> None:
    config, version = _version("doubao_asr", ProviderCapability.ASR)
    version.config_json = {
        "query_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
        "resource_id": "volc.seedasr.auc",
    }

    result = RuntimeHealthChecker(
        ProviderRuntimeFactory(_cipher(), SilentProbeTransport({}))
    ).check(config, version)

    assert result == "CONNECTED"


class DoubaoPollingTransport(RecordingTransport):
    def __init__(self, responses: list[dict[str, object]]) -> None:
        super().__init__({})
        self.responses = iter(responses)

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.calls.append((url, headers, payload, timeout_seconds))
        return next(self.responses)


def test_doubao_asr_keeps_polling_until_timeline_is_available(tmp_path) -> None:
    config, version = _version("doubao_asr", ProviderCapability.ASR)
    version.endpoint_url = "https://openspeech.bytedance.com/api/v3/auc/bigmodel/submit"
    version.config_json = {
        "query_url": "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
        "resource_id": "volc.seedasr.auc",
        "poll_interval_ms": 0,
        "max_poll_attempts": 3,
    }
    transport = DoubaoPollingTransport(
        [
            {},
            {"audio_info": {}, "result": {"text": ""}},
            {
                "audio_info": {"duration": 1200},
                "result": {
                    "text": "你好。",
                    "utterances": [
                        {"start_time": 100, "end_time": 900, "text": "你好。"}
                    ],
                },
            },
        ]
    )
    audio = tmp_path / "source.wav"
    audio.write_bytes(b"test-audio")

    result = (
        ProviderRuntimeFactory(_cipher(), transport)
        .build(config, version)
        .transcribe(str(audio))
    )

    assert [
        (segment.start_ms, segment.end_ms, segment.text) for segment in result.segments
    ] == [(100, 900, "你好。")]
    assert len(transport.calls) == 3


def test_ark_translation_sends_bearer_credential_and_normalizes_usage() -> None:
    config, version = _version("ark", ProviderCapability.TRANSLATION)
    transport = RecordingTransport(
        {
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }
    )
    result = (
        ProviderRuntimeFactory(_cipher(), transport)
        .build(config, version)
        .translate("你好", "en-US", 1200)
    )
    assert result.text == "hello"
    assert result.usage.input_units == 2 and result.usage.output_units == 1
    _, headers, payload, timeout = transport.calls[0]
    assert headers["Authorization"] == "Bearer secret-value"
    assert payload["model"] == "model-x" and timeout == 0.75
    assert "about 1.2 seconds" in payload["messages"][0]["content"]


def test_minimax_invalid_audio_is_a_safe_runtime_error() -> None:
    config, version = _version("minimax", ProviderCapability.TTS)
    runtime = ProviderRuntimeFactory(
        _cipher(), RecordingTransport({"data": {"audio": "!"}})
    ).build(config, version)
    with pytest.raises(ProviderRequestError, match="PROVIDER_RESPONSE_INVALID"):
        runtime.synthesize("hello", "en-US", "voice")


def test_minimax_async_tts_submits_polls_and_downloads_with_bearer_auth() -> None:
    config, version = _version("minimax", ProviderCapability.TTS)
    version.endpoint_url = "https://api.minimax.cn/v1/t2a_async_v2"
    version.config_json = {
        "poll_url": "https://api.minimax.cn/v1/query/t2a_async_query_v2",
        "download_url": "https://api.minimax.cn/v1/files/retrieve_content",
        "poll_interval_ms": 0,
    }
    transport = RecordingTransport({"task_id": 9, "base_resp": {"status_code": 0}})
    result = (
        ProviderRuntimeFactory(_cipher(), transport)
        .build(config, version)
        .synthesize("hello", "en-US", "voice")
    )
    assert result.audio == b"ID3audio" and result.usage.input_units == 5
    submit_url, headers, payload, _ = transport.calls[0]
    assert (
        submit_url.endswith("/t2a_async_v2")
        and headers["Authorization"] == "Bearer secret-value"
    )
    assert payload["voice_setting"] == {
        "voice_id": "voice",
        "speed": 1,
        "vol": 1,
        "pitch": 0,
    }
    assert transport.calls[1][2] == {"task_id": "9"} and transport.calls[2][2] == {
        "file_id": "42"
    }


def test_youdao_runtime_signs_stream_and_returns_target_timeline(
    tmp_path: Path,
) -> None:
    config, version = _version(
        "youdao_si", ProviderCapability.SIMULTANEOUS_INTERPRETATION
    )
    version.endpoint_url = "wss://openapi.youdao.com/stream-audio/stream-si"
    version.config_json = {"app_key": "application-id", "tts_sex": "female"}
    # The production API currently numbers segments from zero. The text-only
    # exchange no longer requests TTS audio, so segments carry empty audio.
    websocket = RecordingWebSocketTransport(
        [
            json.dumps({"action": "started", "errorCode": "0"}),
            json.dumps(
                {
                    "action": "recognition",
                    "errorCode": "0",
                    "isEnd": True,
                    "result": [
                        {
                            "segId": 0,
                            "st": {
                                "sentence": "你好",
                                "translation": "Xin chào",
                                "bg": 120,
                                "ed": 980,
                                "type": 0,
                                "partial": False,
                            },
                        }
                    ],
                }
            ),
        ]
    )
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFFsource-wav")

    result = (
        ProviderRuntimeFactory(_cipher(), websocket_transport=websocket)
        .build(config, version)
        .interpret_text(str(source), "vi-VN")
    )

    assert len(result.segments) == 1
    segment = result.segments[0]
    assert segment.sequence_no == 1
    assert segment.audio == b"" and segment.audio_format == ""
    assert (
        segment.source_text,
        segment.translated_text,
        segment.start_ms,
        segment.end_ms,
    ) == ("你好", "Xin chào", 120, 980)
    url, audio, chunk_bytes, interval_seconds, timeout_seconds = websocket.calls[0]
    query = parse_qs(urlparse(url).query)
    expected_sign = hashlib.sha256(
        (
            "application-id" + query["salt"][0] + query["curtime"][0] + "secret-value"
        ).encode()
    ).hexdigest()
    assert query["sign"] == [expected_sign]
    assert query["from"] == ["zh-CHS"] and query["to"] == ["vi"]
    assert query["ttsRequired"] == ["false"]
    assert "ttsSex" not in query
    assert audio == b"RIFFsource-wav"
    assert chunk_bytes == 6400 and interval_seconds == 0.2
    assert timeout_seconds == 0.75


def test_youdao_interpret_text_without_segments_is_no_speech(
    tmp_path: Path,
) -> None:
    config, version = _version(
        "youdao_si", ProviderCapability.SIMULTANEOUS_INTERPRETATION
    )
    version.config_json = {"app_key": "application-id", "tts_sex": "female"}
    websocket = RecordingWebSocketTransport(
        [
            json.dumps({"action": "started", "errorCode": "0"}),
            json.dumps({"action": "recognition", "errorCode": "0", "isEnd": True}),
        ]
    )
    runtime = ProviderRuntimeFactory(_cipher(), websocket_transport=websocket).build(
        config, version
    )
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFFsource-wav")

    with pytest.raises(ProviderRequestError) as caught:
        runtime.interpret_text(str(source), "en-US")

    assert caught.value.code == "PROVIDER_NO_SPEECH"


def test_youdao_runtime_normalizes_missing_service_permission(tmp_path: Path) -> None:
    config, version = _version(
        "youdao_si", ProviderCapability.SIMULTANEOUS_INTERPRETATION
    )
    version.config_json = {"app_key": "application-id", "tts_sex": "female"}
    websocket = RecordingWebSocketTransport(
        [json.dumps({"action": "error", "errorCode": "110"})]
    )
    runtime = ProviderRuntimeFactory(_cipher(), websocket_transport=websocket).build(
        config, version
    )
    source = tmp_path / "source.wav"
    source.write_bytes(b"RIFFsource-wav")

    with pytest.raises(ProviderRequestError) as caught:
        runtime.interpret_text(str(source), "en-US")

    assert caught.value.code == "PROVIDER_PERMISSION_DENIED"


class MiniMaxArchiveTransport(RecordingTransport):
    def __init__(self, *, download_failures: int = 0) -> None:
        super().__init__({"task_id": 9, "base_resp": {"status_code": 0}})
        self.download_failures = download_failures

    def get_bytes(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> bytes:
        self.calls.append((url, headers, query, timeout_seconds))
        if self.download_failures:
            self.download_failures -= 1
            raise ProviderRequestError("PROVIDER_TIMEOUT", "供应商请求超时或不可用")
        return _minimax_archive()


def _minimax_runtime(transport: RecordingTransport):
    config, version = _version("minimax", ProviderCapability.TTS)
    version.config_json = {
        "poll_url": "https://api.minimaxi.com/v1/query/t2a_async_query_v2",
        "download_url": "https://api.minimaxi.com/v1/files/retrieve_content",
        "poll_interval_ms": 0,
    }
    return ProviderRuntimeFactory(_cipher(), transport).build(config, version)


def test_minimax_async_tts_extracts_mp3_from_download_archive() -> None:
    result = _minimax_runtime(MiniMaxArchiveTransport()).synthesize(
        "hello", "en-US", "voice"
    )

    assert result.audio == b"ID3-test-audio"


def test_minimax_async_tts_retries_a_transient_download_timeout() -> None:
    transport = MiniMaxArchiveTransport(download_failures=1)

    result = _minimax_runtime(transport).synthesize("hello", "en-US", "voice")

    assert result.audio == b"ID3-test-audio"
    download_calls = [call for call in transport.calls if "retrieve_content" in call[0]]
    assert len(download_calls) == 2


def test_unknown_provider_is_a_safe_runtime_error() -> None:
    config, version = _version("unknown", ProviderCapability.ASR)
    with pytest.raises(ProviderRequestError, match="PROVIDER_UNSUPPORTED"):
        ProviderRuntimeFactory(_cipher()).build(config, version)


def test_invalid_encrypted_credential_is_normalized() -> None:
    config, version = _version("ark", ProviderCapability.TRANSLATION)
    version.encrypted_secret = b"x" * 13
    with pytest.raises(ProviderRequestError, match="PROVIDER_CREDENTIAL_INVALID"):
        ProviderRuntimeFactory(_cipher()).build(config, version)


def _ark_vision_runtime(transport: RecordingTransport):
    config, version = _version("ark_vision", ProviderCapability.SUBTITLE_OCR)
    return ProviderRuntimeFactory(_cipher(), transport).build(config, version)


def test_ark_vision_sends_image_url_and_returns_subtitle_text() -> None:
    transport = RecordingTransport(
        {
            "choices": [{"message": {"content": " 欢迎来到直播间 "}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 5},
        }
    )

    text = _ark_vision_runtime(transport).read_subtitle(b"\xff\xd8\xffjpeg")

    assert text == "欢迎来到直播间"
    url, headers, payload, timeout = transport.calls[0]
    assert url == "https://provider.invalid/api"
    assert headers["Authorization"] == "Bearer secret-value"
    assert timeout == 0.75
    assert payload["model"] == "model-x"
    message = payload["messages"][0]
    assert message["role"] == "user"
    parts = message["content"]
    assert isinstance(parts, list) and len(parts) == 2
    assert parts[0]["type"] == "text"
    assert "字幕" in parts[0]["text"] and "NONE" in parts[0]["text"]
    assert parts[1]["type"] == "image_url"
    image_url = parts[1]["image_url"]
    assert image_url["url"].startswith("data:image/jpeg;base64,")


def test_ark_vision_none_and_empty_responses_become_empty_text() -> None:
    none_transport = RecordingTransport(
        {"choices": [{"message": {"content": "NONE"}}]}
    )
    empty_transport = RecordingTransport(
        {"choices": [{"message": {"content": "   "}}]}
    )

    assert _ark_vision_runtime(none_transport).read_subtitle(b"jpeg") == ""
    assert _ark_vision_runtime(empty_transport).read_subtitle(b"jpeg") == ""


def test_ark_vision_probe_confirms_connection_with_blank_image() -> None:
    transport = RecordingTransport(
        {"choices": [{"message": {"content": "NONE"}}]}
    )
    config, version = _version("ark_vision", ProviderCapability.SUBTITLE_OCR)

    state = RuntimeHealthChecker(
        ProviderRuntimeFactory(_cipher(), transport)
    ).check(config, version)

    assert state == "CONNECTED"
    _url, _headers, payload, _timeout = transport.calls[0]
    parts = payload["messages"][0]["content"]
    image_url = parts[1]["image_url"]["url"]
    jpeg = base64.b64decode(image_url.removeprefix("data:image/jpeg;base64,"))
    assert jpeg.startswith(b"\xff\xd8")


def test_ark_vision_invalid_response_is_a_safe_runtime_error() -> None:
    runtime = _ark_vision_runtime(RecordingTransport({"choices": []}))

    with pytest.raises(ProviderRequestError, match="PROVIDER_RESPONSE_INVALID"):
        runtime.read_subtitle(b"jpeg")
