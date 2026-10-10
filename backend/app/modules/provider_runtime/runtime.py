from __future__ import annotations

import base64
import hashlib
import io
import json
import tarfile
import time
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, cast
from urllib.parse import urlencode
from uuid import uuid4

from cryptography.exceptions import InvalidTag

from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider_runtime.contracts import (
    AsrResult,
    AsrSegment,
    ImageGenResult,
    InterpretationResult,
    InterpretationSegment,
    JsonTransport,
    ProviderRequestError,
    ProviderRuntime,
    ProviderUsage,
    TranslationResult,
    TtsResult,
    VideoGenResult,
    WebSocketTransport,
)
from app.modules.provider_runtime.http import UrlLibJsonTransport
from app.modules.provider_runtime.websocket import SyncWebSocketTransport


@dataclass(frozen=True)
class SelectedProvider:
    config: ProviderConfig
    version: ProviderVersion


class ProviderSelector:
    def select(
        self,
        capability: ProviderCapability,
        target_locale: str | None,
        candidates: list[tuple[ProviderConfig, ProviderVersion]],
    ) -> SelectedProvider:
        matching = [
            SelectedProvider(config, version)
            for config, version in candidates
            if config.capability == int(capability)
            and config.status == int(ProviderStatus.ENABLED)
            and version.status == int(ProviderStatus.ENABLED)
            and (
                target_locale is None
                or not config.supported_locales_json
                or target_locale in config.supported_locales_json
            )
        ]
        if not matching:
            raise ProviderRequestError("PROVIDER_NOT_AVAILABLE", "没有可用的供应商配置")
        return min(
            matching, key=lambda item: (item.config.priority, item.config.id or 0)
        )


class _BaseRuntime:
    def __init__(
        self,
        version: ProviderVersion,
        credential: str,
        transport: JsonTransport,
        websocket_transport: WebSocketTransport | None = None,
    ) -> None:
        self._version, self._credential, self._transport, self._websocket = (
            version,
            credential,
            transport,
            websocket_transport,
        )

    @property
    def _timeout(self) -> float:
        return max(0.001, self._version.timeout_ms / 1000)

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        return self._transport.post_json(
            self._version.endpoint_url,
            {"Authorization": f"Bearer {self._credential}"},
            payload,
            self._timeout,
        )

    def probe(self) -> None:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持连接检查"
        )

    def transcribe(self, audio_path: str) -> AsrResult:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持语音识别"
        )

    def translate(
        self, text: str, target_locale: str, duration_ms: int | None = None
    ) -> TranslationResult:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持文本翻译"
        )

    def synthesize(self, text: str, target_locale: str, voice_id: str) -> TtsResult:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持语音合成"
        )

    def interpret(self, audio_path: str, target_locale: str) -> InterpretationResult:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持同声传译"
        )

    def interpret_text(
        self, audio_path: str, target_locale: str
    ) -> InterpretationResult:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持同声传译"
        )

    def generate(
        self, prompt: str, size: str, image_data_uris: list[str]
    ) -> ImageGenResult:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持图片生成"
        )

    def generate_video(
        self,
        prompt: str,
        reference_image_data_uri: str,
        resolution: str,
        duration_seconds: int,
        tier: int,
    ) -> VideoGenResult:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持视频生成"
        )

    def read_subtitle(self, frame_jpg: bytes) -> str:
        raise ProviderRequestError(
            "PROVIDER_CAPABILITY_MISMATCH", "供应商不支持字幕识别"
        )


class DoubaoAsrRuntime(_BaseRuntime):
    def probe(self) -> None:
        output = io.BytesIO()
        with wave.open(output, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * 16000)
        self._submit(base64.b64encode(output.getvalue()).decode("ascii"))

    def transcribe(self, audio_path: str) -> AsrResult:
        source = Path(audio_path)
        try:
            encoded_audio = base64.b64encode(source.read_bytes()).decode("ascii")
        except OSError:
            raise ProviderRequestError(
                "MEDIA_INPUT_UNAVAILABLE", "识别音频不可用"
            ) from None
        headers, _payload = self._submit(encoded_audio)
        options = self._version.config_json or {}
        query_url = _string_option(options, "query_url", "")
        attempts = _int_option(options, "max_poll_attempts", 120)
        interval = _int_option(options, "poll_interval_ms", 1000) / 1000
        response: dict[str, object] | None = None
        for attempt in range(attempts):
            candidate = self._transport.post_json(query_url, headers, {}, self._timeout)
            candidate_result = candidate.get("result")
            candidate_segments = (
                candidate_result.get("utterances", candidate_result.get("segments"))
                if isinstance(candidate_result, dict)
                else candidate.get("segments")
            )
            if isinstance(candidate_segments, list):
                response = candidate
                break
            if attempt + 1 < attempts and interval:
                time.sleep(interval)
        if response is None:
            raise ProviderRequestError("PROVIDER_TIMEOUT", "识别任务轮询超时")
        raw_result = response.get("result")
        raw_segments = (
            raw_result.get("utterances", raw_result.get("segments"))
            if isinstance(raw_result, dict)
            else response.get("segments")
        )
        if not isinstance(raw_segments, list):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "识别响应缺少时间轴"
            )
        segments = [_segment(value) for value in raw_segments]
        usage = _usage(
            response,
            audio_seconds=sum(max(0, item.end_ms - item.start_ms) for item in segments)
            / 1000,
        )
        return AsrResult(segments, usage)

    def _submit(self, encoded_audio: str) -> tuple[dict[str, str], dict[str, object]]:
        options = self._version.config_json or {}
        query_url = _string_option(options, "query_url", "")
        if not query_url:
            raise ProviderRequestError(
                "PROVIDER_CONFIG_INVALID", "识别供应商缺少查询地址"
            )
        request_id = str(uuid4())
        # New Doubao Speech console authentication:
        # https://www.volcengine.com/docs/6561/1631584?lang=zh
        headers = {
            "X-Api-Key": self._credential,
            "X-Api-Resource-Id": _string_option(
                options, "resource_id", "volc.seedasr.auc"
            ),
            "X-Api-Request-Id": request_id,
            "X-Api-Sequence": "-1",
        }
        payload: dict[str, object] = {
            "user": {"uid": request_id},
            "audio": {"data": encoded_audio},
            "request": {
                "model_name": self._version.model_name,
                "enable_auto_lang": _bool_option(options, "auto_lang", True),
            },
        }
        self._transport.post_json(
            self._version.endpoint_url, headers, payload, self._timeout
        )
        return headers, payload


class ArkTranslationRuntime(_BaseRuntime):
    def probe(self) -> None:
        self.translate("你好", "en-US")

    def translate(
        self, text: str, target_locale: str, duration_ms: int | None = None
    ) -> TranslationResult:
        timing = ""
        if duration_ms is not None and duration_ms > 0:
            timing = (
                " The spoken translation must fit naturally within about "
                f"{duration_ms / 1000:.1f} seconds; keep it concise without "
                "losing the main meaning."
            )
        response = self._post(
            {
                "model": self._version.model_name,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            f"Translate into {target_locale} for video subtitles and dubbing."
                            f"{timing} Return only the target-language translation; "
                            "do not include labels, explanations, or source-language text."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
            }
        )
        choices = response.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "翻译响应无效")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "翻译响应无效")
        return TranslationResult(content, _usage(response, input_units=len(text)))


class MiniMaxTtsRuntime(_BaseRuntime):
    def probe(self) -> None:
        options = self._version.config_json or {}
        voice_id = _string_option(options, "default_voice_id", "")
        if not voice_id:
            raise ProviderRequestError(
                "PROVIDER_CONFIG_INVALID", "语音供应商缺少默认音色"
            )
        self.synthesize("连接测试", "zh-CN", voice_id)

    def synthesize(self, text: str, target_locale: str, voice_id: str) -> TtsResult:
        options = self._version.config_json or {}
        try:
            response = self._post(
                {
                    "model": self._version.model_name,
                    "text": text,
                    "language_boost": _string_option(options, "language_boost", "auto"),
                    "voice_setting": {
                        "voice_id": voice_id,
                        "speed": 1,
                        "vol": 1,
                        "pitch": 0,
                    },
                    "audio_setting": {
                        "audio_sample_rate": 32000,
                        "bitrate": 128000,
                        "format": "mp3",
                        "channel": 1,
                    },
                }
            )
        except ProviderRequestError as error:
            raise ProviderRequestError(
                error.code, f"配音任务提交失败：{error.message}"
            ) from None
        task_id = response.get("task_id")
        if not isinstance(task_id, int):
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "语音任务响应无效")
        poll_url = _string_option(options, "poll_url", "")
        download_url = _string_option(options, "download_url", "")
        if not poll_url or not download_url:
            raise ProviderRequestError(
                "PROVIDER_CONFIG_INVALID", "语音供应商缺少轮询或下载地址"
            )
        attempts = _int_option(options, "max_poll_attempts", 120)
        interval = _int_option(options, "poll_interval_ms", 1000) / 1000
        headers = {"Authorization": f"Bearer {self._credential}"}
        for attempt in range(attempts):
            status = self._get_json_with_retry(
                poll_url,
                headers,
                {"task_id": str(task_id)},
                options,
                "任务状态查询",
            )
            state = status.get("status")
            if isinstance(state, str) and state.casefold() == "success":
                file_id = status.get("file_id")
                if not isinstance(file_id, int):
                    raise ProviderRequestError(
                        "PROVIDER_RESPONSE_INVALID", "语音任务缺少文件标识"
                    )
                archive = self._get_bytes_with_retry(
                    download_url,
                    headers,
                    {"file_id": str(file_id)},
                    options,
                    "音频下载",
                )
                audio = _extract_minimax_audio(archive)
                return TtsResult(
                    audio, "audio/mpeg", ProviderUsage(input_units=len(text))
                )
            if isinstance(state, str) and state.casefold() in {"failed", "expired"}:
                raise ProviderRequestError(
                    "PROVIDER_JOB_FAILED", "语音任务失败或已过期"
                )
            if attempt + 1 < attempts and interval:
                time.sleep(interval)
        raise ProviderRequestError("PROVIDER_TIMEOUT", "语音任务轮询超时")

    def _get_json_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        options: dict[str, object],
        stage: str,
    ) -> dict[str, object]:
        attempts = _int_option(options, "network_retry_attempts", 2)
        for attempt in range(attempts):
            try:
                return self._transport.get_json(url, headers, query, self._timeout)
            except ProviderRequestError as error:
                if error.code != "PROVIDER_TIMEOUT" or attempt + 1 >= attempts:
                    raise ProviderRequestError(
                        error.code, f"配音任务{stage}失败：{error.message}"
                    ) from None
                time.sleep(0.25)
        raise AssertionError("unreachable")

    def _get_bytes_with_retry(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        options: dict[str, object],
        stage: str,
    ) -> bytes:
        attempts = _int_option(options, "network_retry_attempts", 2)
        for attempt in range(attempts):
            try:
                return self._transport.get_bytes(url, headers, query, self._timeout)
            except ProviderRequestError as error:
                if error.code != "PROVIDER_TIMEOUT" or attempt + 1 >= attempts:
                    raise ProviderRequestError(
                        error.code, f"配音任务{stage}失败：{error.message}"
                    ) from None
                time.sleep(0.25)
        raise AssertionError("unreachable")


class YoudaoSimultaneousRuntime(_BaseRuntime):
    _LOCALES: ClassVar[dict[str, str]] = {
        "en-US": "en",
        "ja-JP": "ja",
        "ko-KR": "ko",
        "vi-VN": "vi",
        "ms-MY": "ms",
        "th-TH": "th",
    }
    _ERROR_CODES: ClassVar[dict[str, tuple[str, str]]] = {
        "101": (
            "PROVIDER_JOB_FAILED",
            "智能翻译服务参数校验失败（101)，请联系管理员检查该应用的服务开通状态",
        ),
        "108": ("PROVIDER_AUTH_FAILED", "智能翻译服务鉴权失败，请检查密钥"),
        "110": ("PROVIDER_PERMISSION_DENIED", "智能翻译服务尚未开通或绑定"),
        "202": ("PROVIDER_AUTH_FAILED", "智能翻译服务鉴权失败，请检查密钥"),
        "206": ("PROVIDER_AUTH_FAILED", "智能翻译服务请求时间戳无效"),
        "207": ("PROVIDER_AUTH_FAILED", "智能翻译服务请求被判定为重放"),
        "901200": ("PROVIDER_NO_SPEECH", "测试音频没有可识别语音"),
        "901210": ("PROVIDER_TIMEOUT", "智能翻译服务连接空闲超时"),
    }

    def probe(self) -> None:
        output = io.BytesIO()
        with wave.open(output, "wb") as stream:
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(16000)
            stream.writeframes(b"\x00\x00" * 16000)
        self._exchange(
            output.getvalue(), "en-US", require_segments=False, with_tts=False
        )

    def interpret_text(
        self, audio_path: str, target_locale: str
    ) -> InterpretationResult:
        """Text-only interpretation: the service returns no TTS audio anymore."""
        try:
            audio = Path(audio_path).read_bytes()
        except OSError:
            raise ProviderRequestError(
                "MEDIA_INPUT_UNAVAILABLE", "智能翻译音频不可用"
            ) from None
        result = self._exchange(
            audio, target_locale, require_segments=False, with_tts=False
        )
        if not result.segments:
            raise ProviderRequestError("PROVIDER_NO_SPEECH", "智能翻译未返回有效结果")
        return result

    def _exchange(
        self,
        audio: bytes,
        target_locale: str,
        *,
        require_segments: bool,
        with_tts: bool = True,
    ) -> InterpretationResult:
        target = self._LOCALES.get(target_locale)
        if target is None:
            raise ProviderRequestError(
                "PROVIDER_LOCALE_UNSUPPORTED", "智能翻译暂不支持该目标语言"
            )
        options = self._version.config_json or {}
        app_key = _string_option(options, "app_key", "").strip()
        if not app_key:
            raise ProviderRequestError(
                "PROVIDER_CONFIG_INVALID", "智能翻译服务扩展配置不完整"
            )
        if with_tts:
            tts_sex = _string_option(options, "tts_sex", "female")
            if tts_sex not in {"female", "male"}:
                raise ProviderRequestError(
                    "PROVIDER_CONFIG_INVALID", "智能翻译服务扩展配置不完整"
                )
        else:
            tts_sex = ""
        if self._websocket is None:
            raise ProviderRequestError(
                "PROVIDER_CONFIG_INVALID", "智能翻译服务连接器不可用"
            )
        salt = str(uuid4())
        current_time = str(int(time.time()))
        sign = hashlib.sha256(
            f"{app_key}{salt}{current_time}{self._credential}".encode()
        ).hexdigest()
        query_params: dict[str, str] = {
            "appKey": app_key,
            "salt": salt,
            "curtime": current_time,
            "sign": sign,
            "signType": "v4",
            "from": "zh-CHS",
            "to": target,
            "speakerRequired": "false",
        }
        if with_tts:
            query_params["ttsRequired"] = "true"
            query_params["ttsSex"] = tts_sex
        else:
            query_params["ttsRequired"] = "false"
        query = urlencode(query_params)
        messages = self._websocket.exchange(
            f"{self._version.endpoint_url}?{query}",
            audio,
            6400,
            0.2,
            self._timeout,
        )
        segments: dict[int, InterpretationSegment] = {}
        saw_completed = False
        for message in messages:
            try:
                payload = json.loads(message)
            except (json.JSONDecodeError, TypeError):
                raise ProviderRequestError(
                    "PROVIDER_RESPONSE_INVALID", "智能翻译服务响应不是有效 JSON"
                ) from None
            if not isinstance(payload, dict):
                raise ProviderRequestError(
                    "PROVIDER_RESPONSE_INVALID", "智能翻译服务响应结构无效"
                )
            error_code = str(payload.get("errorCode", "0"))
            if error_code != "0":
                code, text = self._ERROR_CODES.get(
                    error_code,
                    ("PROVIDER_JOB_FAILED", f"智能翻译服务调用失败（{error_code}）"),
                )
                raise ProviderRequestError(code, text)
            raw_results = payload.get("result", [])
            if not isinstance(raw_results, list):
                raise ProviderRequestError(
                    "PROVIDER_RESPONSE_INVALID", "智能翻译服务结果结构无效"
                )
            for raw in raw_results:
                segment = self._parse_segment(raw, require_audio=with_tts)
                if segment is not None:
                    segments[segment.sequence_no] = segment
            saw_completed = saw_completed or payload.get("isEnd") is True
        if require_segments and (not saw_completed or not segments):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "智能翻译服务未返回完整翻译结果"
            )
        ordered = [
            InterpretationSegment(
                sequence_no=index,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                source_text=item.source_text,
                translated_text=item.translated_text,
                audio=item.audio,
                audio_format=item.audio_format,
            )
            for index, item in enumerate(
                (segments[key] for key in sorted(segments)), start=1
            )
        ]
        audio_seconds = max((item.end_ms for item in ordered), default=0) / 1000
        return InterpretationResult(ordered, ProviderUsage(audio_seconds=audio_seconds))

    @staticmethod
    def _parse_segment(
        value: object, *, require_audio: bool
    ) -> InterpretationSegment | None:
        if not isinstance(value, dict):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "智能翻译服务分段结构无效"
            )
        raw = value.get("st")
        if not isinstance(raw, dict):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "智能翻译服务分段内容缺失"
            )
        if raw.get("partial") is True or raw.get("type") == 1:
            return None
        sequence = value.get("segId")
        source = raw.get("sentence")
        translated = raw.get("translation")
        start = raw.get("bg")
        end = raw.get("ed")
        encoded_audio = raw.get("tts")
        if (
            not isinstance(sequence, int)
            or sequence < 0
            or not isinstance(source, str)
            or not source.strip()
            or not isinstance(translated, str)
            or not translated.strip()
            or not isinstance(start, int)
            or not isinstance(end, int)
            or start < 0
            or end <= start
        ):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "智能翻译服务分段字段无效"
            )
        audio = b""
        audio_format = ""
        if require_audio or (isinstance(encoded_audio, str) and encoded_audio):
            if not isinstance(encoded_audio, str) or not encoded_audio:
                raise ProviderRequestError(
                    "PROVIDER_RESPONSE_INVALID", "智能翻译服务分段字段无效"
                )
            try:
                audio = bytes.fromhex(encoded_audio)
            except ValueError:
                raise ProviderRequestError(
                    "PROVIDER_RESPONSE_INVALID", "智能翻译服务音频编码无效"
                ) from None
            if audio.startswith(b"RIFF"):
                audio_format = "wav"
            elif _is_mp3(audio):
                audio_format = "mp3"
            else:
                raise ProviderRequestError(
                    "PROVIDER_RESPONSE_INVALID", "智能翻译服务未返回有效音频"
                )
        return InterpretationSegment(
            sequence,
            start,
            end,
            source.strip(),
            translated.strip(),
            audio,
            audio_format,
        )


class SeedreamImageRuntime(_BaseRuntime):
    def probe(self) -> None:
        self.generate("一只可爱的猫", "2K", [])

    def generate(
        self, prompt: str, size: str, image_data_uris: list[str]
    ) -> ImageGenResult:
        options = self._version.config_json or {}
        payload: dict[str, object] = {
            "model": self._version.model_name,
            "prompt": prompt,
            "size": size,
            # Enterprise-verified accounts may disable the platform watermark.
            "watermark": _bool_option(options, "watermark", False),
        }
        if image_data_uris:
            payload["image"] = image_data_uris
        response = self._post(payload)
        data = response.get("data")
        if (
            not isinstance(data, list)
            or not data
            or not isinstance(data[0], dict)
        ):
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "图片生成响应无效"
            )
        url = data[0].get("url")
        if not isinstance(url, str) or not url:
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "图片生成响应缺少下载地址"
            )
        image = self._transport.get_bytes(url, {}, {}, self._timeout)
        if not image:
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "图片下载结果为空"
            )
        return ImageGenResult(
            image=image, content_type="image/png", usage=ProviderUsage(output_units=1)
        )


class SeedanceVideoRuntime(_BaseRuntime):
    """Async task-based image-to-video generation (create → poll → download)."""

    _TIER_OPTION_KEYS: ClassVar[dict[int, str]] = {
        1: "standard",
        2: "fast",
        3: "mini",
    }

    def probe(self) -> None:
        # Creates a minimal text-only task and immediately cancels/deletes it,
        # proving the key and model access without paying for a full render.
        task_id = self._create_task("一只可爱的猫", None, "480p", 5, 3)
        try:
            self._transport.delete_json(
                self._task_url(task_id),
                {"Authorization": f"Bearer {self._credential}"},
                self._timeout,
            )
        except ProviderRequestError:
            pass

    def generate_video(
        self,
        prompt: str,
        reference_image_data_uri: str,
        resolution: str,
        duration_seconds: int,
        tier: int,
    ) -> VideoGenResult:
        task_id = self._create_task(
            prompt, reference_image_data_uri, resolution, duration_seconds, tier
        )
        options = self._version.config_json or {}
        attempts = _int_option(options, "max_poll_attempts", 200)
        interval = _int_option(options, "poll_interval_ms", 3000) / 1000
        headers = {"Authorization": f"Bearer {self._credential}"}
        for attempt in range(attempts):
            status_payload = self._transport.get_json(
                self._task_url(task_id), headers, {}, self._timeout
            )
            state = status_payload.get("status")
            if state == "succeeded":
                content = status_payload.get("content")
                video_url = (
                    content.get("video_url") if isinstance(content, dict) else None
                )
                if not isinstance(video_url, str) or not video_url:
                    raise ProviderRequestError(
                        "PROVIDER_RESPONSE_INVALID", "视频生成响应缺少下载地址"
                    )
                video = self._transport.get_bytes(video_url, {}, {}, self._timeout)
                if not video:
                    raise ProviderRequestError(
                        "PROVIDER_RESPONSE_INVALID", "视频下载结果为空"
                    )
                return VideoGenResult(
                    video=video,
                    content_type="video/mp4",
                    usage=ProviderUsage(output_units=duration_seconds),
                )
            if state in {"failed", "cancelled", "expired"}:
                error = status_payload.get("error")
                detail = (
                    error.get("message")
                    if isinstance(error, dict) and isinstance(error.get("message"), str)
                    else None
                )
                raise ProviderRequestError(
                    "PROVIDER_JOB_FAILED",
                    f"视频生成任务失败{('：' + detail) if detail else ''}",
                )
            if attempt + 1 < attempts and interval:
                time.sleep(interval)
        raise ProviderRequestError("PROVIDER_TIMEOUT", "视频生成任务轮询超时")

    def _task_url(self, task_id: str) -> str:
        return f"{self._version.endpoint_url.rstrip('/')}/{task_id}"

    def _create_task(
        self,
        prompt: str,
        reference_image_data_uri: str | None,
        resolution: str,
        duration_seconds: int,
        tier: int,
    ) -> str:
        options = self._version.config_json or {}
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        if reference_image_data_uri:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": reference_image_data_uri},
                    "role": "first_frame",
                }
            )
        payload: dict[str, object] = {
            "model": self._tier_model(tier),
            "content": content,
            "resolution": resolution,
            # "adaptive" follows the first-frame image aspect ratio.
            "ratio": _string_option(options, "ratio", "adaptive"),
            "duration": duration_seconds,
            # Enterprise-verified accounts may disable the platform watermark.
            "watermark": _bool_option(options, "watermark", False),
            "generate_audio": _bool_option(options, "generate_audio", True),
        }
        response = self._post(payload)
        task_id = response.get("id")
        if not isinstance(task_id, str) or not task_id:
            raise ProviderRequestError(
                "PROVIDER_RESPONSE_INVALID", "视频生成任务响应缺少任务标识"
            )
        return task_id

    def _tier_model(self, tier: int) -> str:
        options = self._version.config_json or {}
        models = options.get("models")
        key = self._TIER_OPTION_KEYS.get(tier)
        model = (
            models.get(key) if isinstance(models, dict) and key is not None else None
        )
        if not isinstance(model, str) or not model.strip():
            raise ProviderRequestError(
                "PROVIDER_CONFIG_INVALID", "视频生成供应商缺少档位模型配置"
            )
        return model.strip()


class ArkVisionSubtitleRuntime(_BaseRuntime):
    """Reads burned-in subtitles from video frames via a vision chat model."""

    _PROBE_JPEG: ClassVar[str] = (
        "/9j/4AAQSkZJRgABAgAAAQABAAD//gAPTGF2YzYzLjEuMTAxAP/bAEMACAQEBAQEBQUFBQUFBgYGBgYG"
        "BgYGBgYGBgcHBwgICAcHBwYGBwcICAgICQkJCAgICAkJCgoKDAwLCw4ODhERFP/EAEsAAQEAAAAAAAAA"
        "AAAAAAAAAAAHAQEAAAAAAAAAAAAAAAAAAAAAEAEAAAAAAAAAAAAAAAAAAAAAEQEAAAAAAAAAAAAAAAAA"
        "AAAA/8AAEQgAQABAAwEiAAIRAAMRAP/aAAwDAQACEQMRAD8Av4AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
        "AP/Z"
    )

    def probe(self) -> None:
        try:
            frame = base64.b64decode(self._PROBE_JPEG)
        except ValueError:
            raise ProviderRequestError(
                "PROVIDER_CONFIG_INVALID", "字幕识别探测器无效"
            ) from None
        self.read_subtitle(frame)

    def read_subtitle(self, frame_jpg: bytes) -> str:
        if not frame_jpg:
            raise ProviderRequestError("MEDIA_INPUT_UNAVAILABLE", "字幕截图不可用")
        encoded = base64.b64encode(frame_jpg).decode("ascii")
        response = self._post(
            {
                "model": self._version.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": _SUBTITLE_READ_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
                            },
                        ],
                    }
                ],
            }
        )
        choices = response.get("choices")
        if (
            not isinstance(choices, list)
            or not choices
            or not isinstance(choices[0], dict)
        ):
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "字幕识别响应无效")
        message = choices[0].get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "字幕识别响应无效")
        text = content.strip()
        if not text or text == "NONE":
            return ""
        return text


_SUBTITLE_READ_PROMPT = (
    "这是一张视频截图。请只读出画面底部字幕的文字内容，原样输出文字本身，"
    "不要加任何解释、标点补充或引号；如果画面中没有字幕，只输出 NONE。"
)


class ProviderRuntimeFactory:
    def __init__(
        self,
        cipher: ProviderSecretCipher,
        transport: JsonTransport | None = None,
        websocket_transport: WebSocketTransport | None = None,
    ) -> None:
        self._cipher = cipher
        self._transport = transport or UrlLibJsonTransport()
        self._websocket_transport = websocket_transport or SyncWebSocketTransport()

    def build(
        self, config: ProviderConfig, version: ProviderVersion
    ) -> ProviderRuntime:
        runtime_type: type[_BaseRuntime] | None = {
            "doubao_asr": DoubaoAsrRuntime,
            "ark": ArkTranslationRuntime,
            "minimax": MiniMaxTtsRuntime,
            "youdao_si": YoudaoSimultaneousRuntime,
            "seedream": SeedreamImageRuntime,
            "ark_vision": ArkVisionSubtitleRuntime,
            "seedance_video": SeedanceVideoRuntime,
        }.get(config.provider_code.casefold())
        if runtime_type is None:
            raise ProviderRequestError("PROVIDER_UNSUPPORTED", "供应商类型不受支持")
        try:
            credential = self._cipher.decrypt(version.encrypted_secret)
        except (InvalidTag, UnicodeDecodeError, ValueError):
            raise ProviderRequestError(
                "PROVIDER_CREDENTIAL_INVALID", "供应商凭据无效"
            ) from None
        return runtime_type(
            version, credential, self._transport, self._websocket_transport
        )


def _segment(value: object) -> AsrSegment:
    if not isinstance(value, dict):
        raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "识别时间轴无效")
    text = value.get("text")
    start = value.get("start_ms", value.get("start_time", value.get("start")))
    end = value.get("end_ms", value.get("end_time", value.get("end")))
    if (
        not isinstance(text, str)
        or not isinstance(start, int)
        or not isinstance(end, int)
        or start < 0
        or end < start
    ):
        raise ProviderRequestError("PROVIDER_RESPONSE_INVALID", "识别时间轴无效")
    confidence = value.get("confidence")
    return AsrSegment(
        start,
        end,
        text,
        float(confidence) if isinstance(confidence, (int, float)) else None,
    )


def _usage(
    response: dict[str, object], *, input_units: int = 0, audio_seconds: float = 0.0
) -> ProviderUsage:
    raw = response.get("usage")
    usage = cast(dict[str, object], raw) if isinstance(raw, dict) else {}

    def number(*keys: str, default: float = 0) -> int | float:
        for key in keys:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                return value
        return default

    return ProviderUsage(
        int(number("prompt_tokens", "input_tokens", default=input_units)),
        int(number("completion_tokens", "output_tokens")),
        float(number("audio_seconds", "duration_seconds", default=audio_seconds)),
    )


def _extract_minimax_audio(payload: bytes) -> bytes:
    if _is_mp3(payload):
        return payload
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
            for member in archive.getmembers():
                if not member.isfile() or not member.name.casefold().endswith(".mp3"):
                    continue
                source = archive.extractfile(member)
                audio = source.read() if source is not None else b""
                if _is_mp3(audio):
                    return audio
    except (tarfile.TarError, OSError):
        pass
    raise ProviderRequestError(
        "PROVIDER_RESPONSE_INVALID", "配音任务下载结果缺少有效 MP3 音频"
    )


def _is_mp3(payload: bytes) -> bool:
    return payload.startswith(b"ID3") or (
        len(payload) >= 2 and payload[0] == 0xFF and payload[1] & 0xE0 == 0xE0
    )


def _string_option(options: dict[str, object], name: str, default: str) -> str:
    value = options.get(name, default)
    return value if isinstance(value, str) else default


def _bool_option(options: dict[str, object], name: str, default: bool) -> bool:
    value = options.get(name, default)
    return value if isinstance(value, bool) else default


def _int_option(options: dict[str, object], name: str, default: int) -> int:
    value = options.get(name, default)
    return value if isinstance(value, int) and value > 0 else default
