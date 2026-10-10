from __future__ import annotations

import asyncio
import base64
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import pytest

from app.core.errors import AppError
from app.modules.cost.model import AiUsageRecord, UsageStatus
from app.modules.media.storage import LocalObjectStorage
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider.service import _validate_runtime_config
from app.modules.provider_runtime.contracts import ProviderRequestError
from app.modules.provider_runtime.runtime import ProviderRuntimeFactory
from app.modules.videogen.model import VideoGenerationJob, VideoJobStatus
from app.modules.videogen.service import VideoGenService

_MP4_BYTES = b"\x00\x00\x00\x18ftypmp42video-bytes"
_PNG_BYTES = b"\x89PNG\r\n\x1a\nreference-bytes"
_REFERENCE_DATA_URI = (
    "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode("ascii")
)
_MODELS = {
    "standard": "doubao-seedance-2-0-260128",
    "fast": "doubao-seedance-2-0-fast-260128",
    "mini": "doubao-seedance-2-0-mini-260615",
}
_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"


def _cipher() -> ProviderSecretCipher:
    return ProviderSecretCipher(urlsafe_b64encode(b"a" * 32).decode())


def _seedance_provider(
    models: dict[str, str] | None = None,
) -> tuple[ProviderConfig, ProviderVersion]:
    cipher = _cipher()
    config = ProviderConfig(
        provider_code="seedance_video",
        capability=int(ProviderCapability.VIDEO_GENERATION),
        status=int(ProviderStatus.ENABLED),
        priority=10,
        supported_locales_json=None,
    )
    version = ProviderVersion(
        model_name="video-generation",
        endpoint_url=_ENDPOINT,
        timeout_ms=750,
        config_json={"models": dict(_MODELS if models is None else models)},
        encrypted_secret=cipher.encrypt("secret-value"),
        status=int(ProviderStatus.ENABLED),
    )
    return config, version


class _VideoTransport:
    def __init__(
        self,
        statuses: list[dict[str, object]] | None = None,
        create_response: dict[str, object] | None = None,
        error: ProviderRequestError | None = None,
    ) -> None:
        self.create_response = (
            create_response if create_response is not None else {"id": "cgt-test-1"}
        )
        self.statuses = list(
            statuses
            if statuses is not None
            else [
                {"status": "queued"},
                {
                    "status": "succeeded",
                    "content": {"video_url": "https://cdn.example/out.mp4"},
                },
            ]
        )
        self.error = error
        self.posts: list[tuple[str, dict[str, str], dict[str, object], float]] = []
        self.polls: list[tuple[str, dict[str, str], dict[str, str], float]] = []
        self.downloads: list[tuple[str, dict[str, str], dict[str, str], float]] = []
        self.deletes: list[str] = []

    def post_json(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, object],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.posts.append((url, headers, payload, timeout_seconds))
        if self.error is not None:
            raise self.error
        return self.create_response

    def get_json(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]:
        self.polls.append((url, headers, query, timeout_seconds))
        if self.statuses:
            return self.statuses.pop(0)
        return {"status": "queued"}

    def get_bytes(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> bytes:
        self.downloads.append((url, headers, query, timeout_seconds))
        return _MP4_BYTES

    def delete_json(
        self, url: str, headers: dict[str, str], timeout_seconds: float
    ) -> dict[str, object]:
        self.deletes.append(url)
        return {}


class _RowsResult:
    def __init__(self, rows: list[tuple[ProviderConfig, ProviderVersion]]) -> None:
        self._rows = rows

    def __iter__(self) -> object:
        return iter(self._rows)


class _ListResult:
    def __init__(self, jobs: list[VideoGenerationJob]) -> None:
        self._jobs = jobs

    def scalars(self) -> object:
        return iter(self._jobs)


class _JobResult:
    def __init__(self, job: VideoGenerationJob | None) -> None:
        self._job = job

    def scalar_one_or_none(self) -> VideoGenerationJob | None:
        return self._job


class _SessionStub:
    def __init__(
        self,
        provider_rows: list[tuple[ProviderConfig, ProviderVersion]] | None = None,
        job: VideoGenerationJob | None = None,
        jobs: list[VideoGenerationJob] | None = None,
    ) -> None:
        self.provider_rows = provider_rows or []
        self.job = job
        self.jobs = jobs
        self.added: list[object] = []
        self.flush_count = 0
        self.commit_count = 0

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def execute(self, statement: object) -> object:
        entity = statement.column_descriptions[0].get("entity")
        if entity is ProviderConfig:
            return _RowsResult(self.provider_rows)
        if entity is VideoGenerationJob and self.jobs is not None:
            return _ListResult(self.jobs)
        return _JobResult(self.job)

    async def scalar(self, _statement: object) -> None:
        return None

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        self.flush_count += 1

    async def commit(self) -> None:
        self.commit_count += 1


class _SessionFactoryStub:
    def __init__(self, session: _SessionStub) -> None:
        self._session = session

    def __call__(self) -> _SessionStub:
        return self._session


class _StorageStub:
    def put_bytes(self, _key: str, _value: bytes) -> Path:
        raise AssertionError("storage must not be used")

    def download_path(self, _key: str) -> Path:
        raise AssertionError("storage must not be used")


def _job() -> VideoGenerationJob:
    return VideoGenerationJob(
        public_id="01M1GTESTVIDEOJOB0000000000",
        account_id=7,
        prompt="镜头缓慢推进",
        size="720p",
        duration_seconds=5,
        tier=2,
        reference_object_key=None,
        status=int(VideoJobStatus.RUNNING),
        error_code=None,
        error_message=None,
        created_at=datetime(2026, 10, 15, tzinfo=UTC).replace(tzinfo=None),
        finished_at=None,
    )


def _service(
    background: _SessionStub,
    *,
    request_session: _SessionStub | None = None,
    storage: LocalObjectStorage | None = None,
    task_spawner: object = None,
    runtime_factory: ProviderRuntimeFactory | None = None,
) -> VideoGenService:
    return VideoGenService(
        request_session or _SessionStub(),
        storage or _StorageStub(),
        _cipher(),
        _SessionFactoryStub(background),
        task_spawner=task_spawner,
        runtime_factory=runtime_factory,
    )


def test_seedance_create_task_posts_prompt_reference_and_options() -> None:
    config, version = _seedance_provider()
    transport = _VideoTransport()

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    result = runtime.generate_video("镜头缓慢推进", _REFERENCE_DATA_URI, "720p", 10, 2)

    url, headers, payload, _ = transport.posts[0]
    assert url == _ENDPOINT
    assert headers["Authorization"] == "Bearer secret-value"
    assert payload["model"] == "doubao-seedance-2-0-fast-260128"
    assert payload["resolution"] == "720p"
    assert payload["ratio"] == "adaptive"
    assert payload["duration"] == 10
    assert payload["watermark"] is False
    content = payload["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "镜头缓慢推进"}
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": _REFERENCE_DATA_URI},
        "role": "first_frame",
    }
    assert transport.polls[0][0] == f"{_ENDPOINT}/cgt-test-1"
    assert transport.downloads[0][0] == "https://cdn.example/out.mp4"
    assert result.video == _MP4_BYTES
    assert result.content_type == "video/mp4"
    assert result.usage.output_units == 10


@pytest.mark.parametrize(
    ("tier", "model"),
    [(1, "doubao-seedance-2-0-260128"), (2, "doubao-seedance-2-0-fast-260128"), (3, "doubao-seedance-2-0-mini-260615")],
)
def test_seedance_tier_maps_to_model_id(tier: int, model: str) -> None:
    config, version = _seedance_provider()
    transport = _VideoTransport()

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    runtime.generate_video("星空", _REFERENCE_DATA_URI, "480p", 5, tier)

    assert transport.posts[0][2]["model"] == model


def test_seedance_missing_tier_model_rejected() -> None:
    config, version = _seedance_provider(
        models={"standard": "doubao-seedance-2-0-260128", "fast": "", "mini": "x"}
    )
    transport = _VideoTransport()

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    with pytest.raises(ProviderRequestError, match="PROVIDER_CONFIG_INVALID"):
        runtime.generate_video("星空", _REFERENCE_DATA_URI, "480p", 5, 2)


def test_seedance_polls_until_succeeded() -> None:
    config, version = _seedance_provider()
    transport = _VideoTransport(
        statuses=[
            {"status": "queued"},
            {"status": "running"},
            {
                "status": "succeeded",
                "content": {"video_url": "https://cdn.example/out.mp4"},
            },
        ]
    )

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    result = runtime.generate_video("星空", _REFERENCE_DATA_URI, "480p", 5, 3)

    assert len(transport.polls) == 3
    assert result.video == _MP4_BYTES


def test_seedance_failed_task_raises_with_provider_message() -> None:
    config, version = _seedance_provider()
    transport = _VideoTransport(
        statuses=[{"status": "failed", "error": {"message": "content rejected"}}]
    )

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    with pytest.raises(ProviderRequestError, match="PROVIDER_JOB_FAILED"):
        runtime.generate_video("星空", _REFERENCE_DATA_URI, "480p", 5, 1)


def test_seedance_succeeded_without_video_url_is_invalid() -> None:
    config, version = _seedance_provider()
    transport = _VideoTransport(statuses=[{"status": "succeeded", "content": {}}])

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    with pytest.raises(ProviderRequestError, match="PROVIDER_RESPONSE_INVALID"):
        runtime.generate_video("星空", _REFERENCE_DATA_URI, "480p", 5, 1)


def test_seedance_poll_timeout() -> None:
    config, version = _seedance_provider()
    version.config_json = {
        "models": dict(_MODELS),
        "max_poll_attempts": 2,
        "poll_interval_ms": 1,
    }
    transport = _VideoTransport(statuses=[])

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    with pytest.raises(ProviderRequestError, match="PROVIDER_TIMEOUT"):
        runtime.generate_video("星空", _REFERENCE_DATA_URI, "480p", 5, 1)
    assert len(transport.polls) == 2


def test_seedance_create_response_without_id_is_invalid() -> None:
    config, version = _seedance_provider()
    transport = _VideoTransport(create_response={})

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    with pytest.raises(ProviderRequestError, match="PROVIDER_RESPONSE_INVALID"):
        runtime.generate_video("星空", _REFERENCE_DATA_URI, "480p", 5, 1)


def test_seedance_probe_creates_then_deletes_a_task() -> None:
    config, version = _seedance_provider()
    transport = _VideoTransport()

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    runtime.probe()

    _url, _headers, payload, _ = transport.posts[0]
    assert payload["model"] == "doubao-seedance-2-0-mini-260615"
    assert payload["resolution"] == "480p"
    assert payload["duration"] == 5
    content = payload["content"]
    assert isinstance(content, list) and len(content) == 1
    assert transport.deletes == [f"{_ENDPOINT}/cgt-test-1"]


def test_seedance_runtime_config_requires_three_tier_models() -> None:
    _validate_runtime_config(
        "seedance_video",
        7,
        _ENDPOINT,
        {"models": dict(_MODELS)},
    )

    with pytest.raises(AppError) as caught:
        _validate_runtime_config("seedance_video", 7, _ENDPOINT, None)
    assert caught.value.code == "PROVIDER_CONFIG_INVALID"

    with pytest.raises(AppError) as caught:
        _validate_runtime_config(
            "seedance_video",
            7,
            _ENDPOINT,
            {"models": {"standard": "a", "fast": "b"}},
        )
    assert caught.value.code == "PROVIDER_CONFIG_INVALID"

    with pytest.raises(AppError) as caught:
        _validate_runtime_config(
            "seedance_video", 5, _ENDPOINT, {"models": dict(_MODELS)}
        )
    assert caught.value.code == "PROVIDER_TYPE_INVALID"


@pytest.mark.parametrize(
    ("prompt", "tier", "resolution", "duration", "reference", "code"),
    [
        ("", 2, "720p", 5, _REFERENCE_DATA_URI, "VIDEO_PROMPT_REQUIRED"),
        ("星空", 4, "720p", 5, _REFERENCE_DATA_URI, "VIDEO_TIER_INVALID"),
        ("星空", 0, "720p", 5, _REFERENCE_DATA_URI, "VIDEO_TIER_INVALID"),
        ("星空", 2, "1080p", 5, _REFERENCE_DATA_URI, "VIDEO_RESOLUTION_INVALID"),
        ("星空", 2, "720p", 7, _REFERENCE_DATA_URI, "VIDEO_DURATION_INVALID"),
        ("星空", 2, "720p", 5, "", "VIDEO_REFERENCE_REQUIRED"),
    ],
)
def test_videogen_service_validates_request_parameters(
    prompt: str, tier: int, resolution: str, duration: int, reference: str, code: str
) -> None:
    service = _service(_SessionStub(provider_rows=[_seedance_provider()]))

    with pytest.raises(AppError) as caught:
        asyncio.run(
            service.create(7, prompt, tier, resolution, duration, reference)
        )

    assert caught.value.code == code


def test_videogen_create_fails_without_provider() -> None:
    service = _service(_SessionStub(provider_rows=[]))

    with pytest.raises(AppError) as caught:
        asyncio.run(
            service.create(7, "星空", 2, "720p", 5, _REFERENCE_DATA_URI)
        )

    assert caught.value.code == "PROVIDER_NOT_CONFIGURED"


def test_videogen_create_rejects_invalid_reference_bytes() -> None:
    service = _service(_SessionStub(provider_rows=[_seedance_provider()]))
    bad = "data:image/png;base64," + base64.b64encode(b"not-an-image").decode()

    with pytest.raises(AppError) as caught:
        asyncio.run(service.create(7, "星空", 2, "720p", 5, bad))

    assert caught.value.code == "VIDEO_REFERENCE_INVALID"


def test_videogen_create_persists_reference_and_schedules_task(
    tmp_path: Path,
) -> None:
    spawned: list[object] = []
    request_session = _SessionStub(provider_rows=[_seedance_provider()])
    service = _service(
        _SessionStub(provider_rows=[_seedance_provider()]),
        request_session=request_session,
        storage=LocalObjectStorage(tmp_path),
        task_spawner=lambda coro: spawned.append(coro),
    )

    job = asyncio.run(
        service.create(7, "星空", 2, "720p", 5, _REFERENCE_DATA_URI)
    )

    assert job.status == int(VideoJobStatus.RUNNING)
    assert job.reference_object_key == f"videogen/{job.public_id}/reference.png"
    assert (tmp_path / "videogen" / job.public_id / "reference.png").read_bytes() == (
        _PNG_BYTES
    )
    assert request_session.commit_count == 1
    assert len(spawned) == 1
    for coro in spawned:
        coro.close()


def _serving_service(
    tmp_path: Path, job: VideoGenerationJob, transport: _VideoTransport
) -> tuple[VideoGenService, _SessionStub]:
    job.reference_object_key = f"videogen/{job.public_id}/reference.png"
    storage = LocalObjectStorage(tmp_path)
    storage.put_bytes(job.reference_object_key, _PNG_BYTES)
    background = _SessionStub(provider_rows=[_seedance_provider()], job=job)
    service = _service(
        background,
        storage=storage,
        runtime_factory=ProviderRuntimeFactory(_cipher(), transport),
    )
    return service, background


def test_run_job_success_stores_video_and_records_usage(tmp_path: Path) -> None:
    job = _job()
    service, background = _serving_service(tmp_path, job, _VideoTransport())

    asyncio.run(service._run_job(job.public_id, "星空", "720p", 5, 2))

    assert job.status == int(VideoJobStatus.SUCCEEDED)
    assert job.finished_at is not None
    assert (
        tmp_path / "videogen" / job.public_id / "video.mp4"
    ).read_bytes() == _MP4_BYTES
    usage = [row for row in background.added if isinstance(row, AiUsageRecord)]
    assert len(usage) == 1
    assert usage[0].status == int(UsageStatus.SUCCEEDED)
    assert usage[0].capability == 7
    assert usage[0].output_units == 5
    assert usage[0].input_units == 0
    assert usage[0].request_id == f"videogen:{job.public_id}"


def test_run_job_failure_marks_failed_and_records_failed_usage(
    tmp_path: Path,
) -> None:
    job = _job()
    service, background = _serving_service(
        tmp_path,
        job,
        _VideoTransport(error=ProviderRequestError("PROVIDER_RATE_LIMITED")),
    )

    asyncio.run(service._run_job(job.public_id, "星空", "720p", 5, 2))

    assert job.status == int(VideoJobStatus.FAILED)
    assert job.error_code == "PROVIDER_RATE_LIMITED"
    usage = [row for row in background.added if isinstance(row, AiUsageRecord)]
    assert len(usage) == 1
    assert usage[0].status == int(UsageStatus.FAILED)
    assert usage[0].error_code == "PROVIDER_RATE_LIMITED"


class _BrokenFactory:
    def build(self, config: object, version: object) -> object:
        raise RuntimeError("boom")


def test_run_job_unexpected_error_is_marked_failed(tmp_path: Path) -> None:
    job = _job()
    job.reference_object_key = f"videogen/{job.public_id}/reference.png"
    storage = LocalObjectStorage(tmp_path)
    storage.put_bytes(job.reference_object_key, _PNG_BYTES)
    background = _SessionStub(provider_rows=[_seedance_provider()], job=job)
    service = VideoGenService(
        background,
        storage,
        _cipher(),
        _SessionFactoryStub(background),
        runtime_factory=_BrokenFactory(),
    )

    asyncio.run(service._run_job(job.public_id, "星空", "720p", 5, 2))

    assert job.status == int(VideoJobStatus.FAILED)
    assert job.error_code == "PROVIDER_INTERNAL"


def test_require_any_missing_job_raises_not_found() -> None:
    service = _service(_SessionStub(), request_session=_SessionStub(job=None))

    with pytest.raises(AppError) as caught:
        asyncio.run(service.require_any("01M1GMISSINGVIDEO00000000000"))

    assert caught.value.code == "VIDEO_JOB_NOT_FOUND"
    assert caught.value.status_code == 404
