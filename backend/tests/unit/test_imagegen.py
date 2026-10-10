from __future__ import annotations

import asyncio
from base64 import urlsafe_b64encode
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import pytest

from app.core.errors import AppError
from app.modules.cost.model import AiUsageRecord, UsageStatus
from app.modules.imagegen.model import ImageGenerationJob, ImageJobStatus
from app.modules.imagegen.service import ImageGenService
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

_PNG_BYTES = b"\x89PNG\r\n\x1a\nimage-bytes"


def _cipher() -> ProviderSecretCipher:
    return ProviderSecretCipher(urlsafe_b64encode(b"a" * 32).decode())


def _seedream_provider() -> tuple[ProviderConfig, ProviderVersion]:
    cipher = _cipher()
    config = ProviderConfig(
        provider_code="seedream",
        capability=int(ProviderCapability.IMAGE_GENERATION),
        status=int(ProviderStatus.ENABLED),
        priority=10,
        supported_locales_json=None,
    )
    version = ProviderVersion(
        model_name="doubao-seedream-5-0-260128",
        endpoint_url="https://ark.cn-beijing.volces.com/api/v3/images/generations",
        timeout_ms=750,
        config_json=None,
        encrypted_secret=cipher.encrypt("secret-value"),
        status=int(ProviderStatus.ENABLED),
    )
    return config, version


class _ImageTransport:
    def __init__(
        self,
        response: dict[str, object] | None = None,
        error: ProviderRequestError | None = None,
    ) -> None:
        self.response = (
            response
            if response is not None
            else {"data": [{"url": "https://cdn.example/out.png"}]}
        )
        self.error = error
        self.posts: list[tuple[str, dict[str, str], dict[str, object], float]] = []
        self.downloads: list[tuple[str, dict[str, str], dict[str, str], float]] = []

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
        return self.response

    def get_json(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> dict[str, object]:
        raise AssertionError("seedream runtime must not request JSON")

    def get_bytes(
        self,
        url: str,
        headers: dict[str, str],
        query: dict[str, str],
        timeout_seconds: float,
    ) -> bytes:
        self.downloads.append((url, headers, query, timeout_seconds))
        return _PNG_BYTES


class _RowsResult:
    def __init__(self, rows: list[tuple[ProviderConfig, ProviderVersion]]) -> None:
        self._rows = rows

    def __iter__(self) -> object:
        return iter(self._rows)


class _ListResult:
    def __init__(self, jobs: list[ImageGenerationJob]) -> None:
        self._jobs = jobs

    def scalars(self) -> object:
        return iter(self._jobs)


class _JobResult:
    def __init__(self, job: ImageGenerationJob | None) -> None:
        self._job = job

    def scalar_one_or_none(self) -> ImageGenerationJob | None:
        return self._job


class _SessionStub:
    def __init__(
        self,
        provider_rows: list[tuple[ProviderConfig, ProviderVersion]] | None = None,
        job: ImageGenerationJob | None = None,
        jobs: list[ImageGenerationJob] | None = None,
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
        if entity is ImageGenerationJob and self.jobs is not None:
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


def _job() -> ImageGenerationJob:
    return ImageGenerationJob(
        public_id="01M1GTESTIMAGEJOB0000000000",
        account_id=7,
        prompt="一只可爱的猫",
        size="2K",
        count=2,
        reference_count=0,
        status=int(ImageJobStatus.RUNNING),
        error_code=None,
        error_message=None,
        created_at=datetime(2026, 9, 16, tzinfo=UTC).replace(tzinfo=None),
        finished_at=None,
    )


def _service(
    background: _SessionStub,
    *,
    request_session: _SessionStub | None = None,
    storage: LocalObjectStorage | None = None,
    task_spawner: object = None,
    runtime_factory: ProviderRuntimeFactory | None = None,
) -> ImageGenService:
    service = ImageGenService(
        request_session or _SessionStub(),
        storage or _StorageStub(),
        _cipher(),
        _SessionFactoryStub(background),
        task_spawner=task_spawner,
        runtime_factory=runtime_factory,
    )
    return service


def test_seedream_generate_posts_prompt_size_and_downloads_image() -> None:
    config, version = _seedream_provider()
    transport = _ImageTransport()

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    result = runtime.generate("星空下的古城", "4K", ["data:image/png;base64,abc"])

    url, headers, payload, _ = transport.posts[0]
    assert url == "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    assert headers["Authorization"] == "Bearer secret-value"
    assert payload["model"] == "doubao-seedream-5-0-260128"
    assert payload["prompt"] == "星空下的古城"
    assert payload["size"] == "4K"
    assert payload["image"] == ["data:image/png;base64,abc"]
    assert transport.downloads[0][0] == "https://cdn.example/out.png"
    assert result.image == _PNG_BYTES
    assert result.content_type == "image/png"
    assert result.usage.output_units == 1


def test_seedream_generate_omits_image_param_without_references() -> None:
    config, version = _seedream_provider()
    transport = _ImageTransport()

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    runtime.generate("一只可爱的猫", "2K", [])

    _url, _headers, payload, _ = transport.posts[0]
    assert "image" not in payload


def test_seedream_probe_generates_a_single_real_image() -> None:
    config, version = _seedream_provider()
    transport = _ImageTransport()

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    runtime.probe()

    _url, _headers, payload, _ = transport.posts[0]
    assert payload["prompt"] == "一只可爱的猫"
    assert payload["size"] == "2K"
    assert len(transport.downloads) == 1


def test_seedream_generate_rejects_invalid_response() -> None:
    config, version = _seedream_provider()
    transport = _ImageTransport(response={})

    runtime = ProviderRuntimeFactory(_cipher(), transport).build(config, version)
    with pytest.raises(ProviderRequestError, match="PROVIDER_RESPONSE_INVALID"):
        runtime.generate("星空", "2K", [])


def test_seedream_runtime_config_accepts_official_endpoint() -> None:
    _validate_runtime_config(
        "seedream",
        5,
        "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        None,
    )

    with pytest.raises(AppError) as caught:
        _validate_runtime_config(
            "seedream",
            2,
            "https://ark.cn-beijing.volces.com/api/v3/images/generations",
            None,
        )
    assert caught.value.code == "PROVIDER_TYPE_INVALID"


@pytest.mark.parametrize(
    ("prompt", "size", "count", "references", "code"),
    [
        ("", "2K", 1, [], "IMAGE_PROMPT_REQUIRED"),
        ("星空", "8K", 1, [], "IMAGE_SIZE_INVALID"),
        ("星空", "2K", 4, [], "IMAGE_COUNT_INVALID"),
        ("星空", "2K", 0, [], "IMAGE_COUNT_INVALID"),
        ("星空", "2K", 1, ["a", "b", "c", "d"], "IMAGE_REFERENCES_LIMIT"),
        ("星空", "2K", 1, ["not-a-data-uri"], "IMAGE_REFERENCE_INVALID"),
    ],
)
def test_imagegen_service_validates_request_parameters(
    prompt: str, size: str, count: int, references: list[str], code: str
) -> None:
    service = _service(_SessionStub(provider_rows=[_seedream_provider()]))

    with pytest.raises(AppError) as caught:
        asyncio.run(service.create(7, prompt, size, count, references))

    assert caught.value.code == code


def test_imagegen_create_fails_without_provider() -> None:
    service = _service(_SessionStub(provider_rows=[]))

    with pytest.raises(AppError) as caught:
        asyncio.run(service.create(7, "星空", "2K", 1, []))

    assert caught.value.code == "PROVIDER_NOT_CONFIGURED"


def test_imagegen_create_commits_and_schedules_background_task(
    tmp_path: Path,
) -> None:
    spawned: list[object] = []
    request_session = _SessionStub(provider_rows=[_seedream_provider()])
    service = _service(
        _SessionStub(provider_rows=[_seedream_provider()]),
        request_session=request_session,
        storage=LocalObjectStorage(tmp_path),
        task_spawner=lambda coro: spawned.append(coro),
    )

    job = asyncio.run(service.create(7, "星空", "2K", 2, []))

    assert job.status == int(ImageJobStatus.RUNNING)
    assert job.count == 2
    assert request_session.commit_count == 1
    assert len(spawned) == 1
    assert hasattr(spawned[0], "close")
    for coro in spawned:
        coro.close()


def test_run_job_success_stores_images_and_records_usage(tmp_path: Path) -> None:
    job = _job()
    background = _SessionStub(provider_rows=[_seedream_provider()], job=job)
    storage = LocalObjectStorage(tmp_path)
    service = _service(
        background,
        storage=storage,
        runtime_factory=ProviderRuntimeFactory(_cipher(), _ImageTransport()),
    )

    asyncio.run(service._run_job(job.public_id, "星空", "2K", 2, []))

    assert job.status == int(ImageJobStatus.SUCCEEDED)
    assert job.finished_at is not None
    assert (tmp_path / "imagegen" / job.public_id / "0.png").is_file()
    assert (tmp_path / "imagegen" / job.public_id / "1.png").is_file()
    usage = [row for row in background.added if isinstance(row, AiUsageRecord)]
    assert len(usage) == 2
    assert all(row.status == int(UsageStatus.SUCCEEDED) for row in usage)
    assert all(row.capability == 5 for row in usage)
    assert all(row.output_units == 1 for row in usage)
    assert all(row.project_id == 0 for row in usage)
    assert all(
        row.request_id.startswith(f"imagegen:{job.public_id}:") for row in usage
    )
    assert background.commit_count >= 3


def test_run_job_failure_marks_failed_and_records_failed_usage(
    tmp_path: Path,
) -> None:
    job = _job()
    background = _SessionStub(provider_rows=[_seedream_provider()], job=job)
    service = _service(
        background,
        storage=LocalObjectStorage(tmp_path),
        runtime_factory=ProviderRuntimeFactory(
            _cipher(), _ImageTransport(error=ProviderRequestError("PROVIDER_RATE_LIMITED"))
        ),
    )

    asyncio.run(service._run_job(job.public_id, "星空", "2K", 2, []))

    assert job.status == int(ImageJobStatus.FAILED)
    assert job.error_code == "PROVIDER_RATE_LIMITED"
    usage = [row for row in background.added if isinstance(row, AiUsageRecord)]
    assert len(usage) == 1
    assert usage[0].status == int(UsageStatus.FAILED)
    assert usage[0].error_code == "PROVIDER_RATE_LIMITED"


def test_run_job_unexpected_error_is_marked_failed(tmp_path: Path) -> None:
    job = _job()
    background = _SessionStub(provider_rows=[_seedream_provider()], job=job)
    service = _service(
        background,
        storage=LocalObjectStorage(tmp_path),
        runtime_factory=ProviderRuntimeFactory(
            _cipher(), _ImageTransport(error=RuntimeError("boom"))
        ),
    )

    asyncio.run(service._run_job(job.public_id, "星空", "2K", 1, []))

    assert job.status == int(ImageJobStatus.FAILED)
    assert job.error_code == "PROVIDER_INTERNAL"


def test_download_sniffs_real_image_type(tmp_path: Path) -> None:
    from app.modules.imagegen.routes import _sniff_image_type

    jpeg = tmp_path / "a.png"
    jpeg.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
    assert _sniff_image_type(jpeg) == ("image/jpeg", "jpg")
    png = tmp_path / "b.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    assert _sniff_image_type(png) == ("image/png", "png")
    webp = tmp_path / "c.png"
    webp.write_bytes(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * 20)
    assert _sniff_image_type(webp) == ("image/webp", "webp")


def test_list_all_jobs_returns_every_account_newest_first() -> None:
    older = _job()
    newer = _job()
    newer.public_id = "01M1GTESTIMAGEJOB0000000001"
    service = _service(
        _SessionStub(), request_session=_SessionStub(jobs=[newer, older])
    )

    result = asyncio.run(service.list_all_jobs(limit=20, offset=0))

    assert result == [newer, older]


def test_require_any_skips_ownership_check() -> None:
    job = _job()
    service = _service(_SessionStub(), request_session=_SessionStub(job=job))

    found = asyncio.run(service.require_any(job.public_id))

    assert found is job


def test_require_any_missing_job_raises_not_found() -> None:
    service = _service(_SessionStub(), request_session=_SessionStub(job=None))

    with pytest.raises(AppError) as caught:
        asyncio.run(service.require_any("01M1GMISSINGIMAGE00000000000"))

    assert caught.value.code == "IMAGE_JOB_NOT_FOUND"
    assert caught.value.status_code == 404


def test_seedream_requests_no_watermark_by_default() -> None:
    from app.modules.provider_runtime.runtime import SeedreamImageRuntime

    _config, version = _seedream_provider()
    transport = _ImageTransport()

    SeedreamImageRuntime(version, _cipher(), transport).generate(
        "星空", "2K", []
    )

    _url, _headers, payload, _timeout = transport.posts[0]
    assert payload["watermark"] is False


def test_seedream_watermark_can_be_enabled_via_options() -> None:
    from app.modules.provider_runtime.runtime import SeedreamImageRuntime

    _config, version = _seedream_provider()
    version.config_json = {"watermark": True}
    transport = _ImageTransport()

    SeedreamImageRuntime(version, _cipher(), transport).generate(
        "星空", "2K", []
    )

    _url, _headers, payload, _timeout = transport.posts[0]
    assert payload["watermark"] is True
