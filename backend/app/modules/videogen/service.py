from __future__ import annotations

import asyncio
import base64
import logging
import math
import time
from collections.abc import Callable, Coroutine
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from app.core.errors import AppError
from app.modules.cost.model import AiUsageRecord, ProviderPrice, UsageStatus
from app.modules.media.storage import LocalObjectStorage
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider_runtime.contracts import (
    ProviderRequestError,
    VideoGenResult,
)
from app.modules.provider_runtime.runtime import (
    ProviderRuntimeFactory,
    ProviderSelector,
    SelectedProvider,
)
from app.modules.videogen.model import VideoGenerationJob, VideoJobStatus
from app.modules.videogen.repository import VideoGenRepository, _now

_LOGGER = logging.getLogger(__name__)

ALLOWED_SIZES = ("480p", "720p")
ALLOWED_DURATIONS = (5, 10, 15, 20, 25, 30)
ALLOWED_TIERS = (1, 2, 3)
MAX_REFERENCE_BYTES = 10 * 1024 * 1024


def _validate_request(
    prompt: str, tier: int, resolution: str, duration_seconds: int, reference: str
) -> None:
    if not prompt.strip():
        raise AppError("VIDEO_PROMPT_REQUIRED", "请填写视频描述", status_code=422)
    if tier not in ALLOWED_TIERS:
        raise AppError(
            "VIDEO_TIER_INVALID", "生成档位仅支持标准版、快速版或轻量版", status_code=422
        )
    if resolution not in ALLOWED_SIZES:
        raise AppError(
            "VIDEO_RESOLUTION_INVALID", "分辨率仅支持 480P 或 720P", status_code=422
        )
    if duration_seconds not in ALLOWED_DURATIONS:
        raise AppError(
            "VIDEO_DURATION_INVALID",
            "时长仅支持 5、10、15、20、25 或 30 秒",
            status_code=422,
        )
    if not reference.startswith("data:image/"):
        raise AppError(
            "VIDEO_REFERENCE_REQUIRED", "请上传一张参考图（图片 data URI）", status_code=422
        )


def _decode_reference(reference: str) -> tuple[bytes, str]:
    if not reference.startswith("data:image/") or ";base64," not in reference:
        raise AppError(
            "VIDEO_REFERENCE_INVALID", "参考图必须是图片 data URI", status_code=422
        )
    encoded = reference.split(";base64,", 1)[1]
    try:
        payload = base64.b64decode(encoded, validate=True)
    except ValueError:
        raise AppError(
            "VIDEO_REFERENCE_INVALID", "参考图编码无效", status_code=422
        ) from None
    if not payload or len(payload) > MAX_REFERENCE_BYTES:
        raise AppError(
            "VIDEO_REFERENCE_INVALID", "参考图大小必须在 10MB 以内", status_code=422
        )
    if payload[:8] == b"\x89PNG\r\n\x1a\n":
        return payload, "png"
    if payload[:3] == b"\xff\xd8\xff":
        return payload, "jpg"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return payload, "webp"
    raise AppError(
        "VIDEO_REFERENCE_INVALID", "参考图仅支持 PNG、JPG 或 WEBP 格式", status_code=422
    )


class VideoGenService:
    def __init__(
        self,
        session: AsyncSession,
        storage: LocalObjectStorage,
        cipher: ProviderSecretCipher,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        task_spawner: Callable[[Coroutine[object, object, None]], object] = asyncio.create_task,
        runtime_factory: ProviderRuntimeFactory | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._cipher = cipher
        self._session_factory = session_factory
        self._repo = VideoGenRepository(session)
        self._task_spawner = task_spawner
        self._factory = runtime_factory or ProviderRuntimeFactory(cipher)
        self._background_tasks: set[asyncio.Task[None]] = set()

    def _spawn(self, coroutine: Coroutine[object, object, None]) -> None:
        # Keep a strong reference so the event loop cannot garbage-collect
        # a running generation before it finishes.
        task = self._task_spawner(coroutine)
        if isinstance(task, asyncio.Task):
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

    async def create(
        self,
        account_id: int,
        prompt: str,
        tier: int,
        resolution: str,
        duration_seconds: int,
        reference: str,
    ) -> VideoGenerationJob:
        _validate_request(prompt, tier, resolution, duration_seconds, reference)
        reference_bytes, extension = _decode_reference(reference)
        try:
            await self._select_provider()
        except ProviderRequestError as error:
            raise AppError(
                "PROVIDER_NOT_CONFIGURED",
                "尚未配置视频生成供应商，请联系管理员",
                status_code=409,
            ) from error
        job = await self._repo.create(
            account_id=account_id,
            prompt=prompt.strip(),
            size=resolution,
            duration_seconds=duration_seconds,
            tier=tier,
        )
        reference_key = f"videogen/{job.public_id}/reference.{extension}"
        await asyncio.to_thread(
            self._storage.put_bytes, reference_key, reference_bytes
        )
        job.reference_object_key = reference_key
        await self._session.flush()
        await self._session.commit()
        self._spawn(
            self._run_job(
                job.public_id, prompt.strip(), resolution, duration_seconds, tier
            )
        )
        return job

    async def list_jobs(
        self, account_id: int, *, limit: int, offset: int
    ) -> list[VideoGenerationJob]:
        return await self._repo.list_page(account_id, limit=limit, offset=offset)

    async def list_all_jobs(
        self, *, limit: int, offset: int
    ) -> list[VideoGenerationJob]:
        return await self._repo.list_all(limit=limit, offset=offset)

    async def require(self, account_id: int, public_id: str) -> VideoGenerationJob:
        job = await self._repo.get(public_id)
        if job is None or job.account_id != account_id:
            raise AppError("VIDEO_JOB_NOT_FOUND", "生成任务不存在", status_code=404)
        return job

    async def require_any(self, public_id: str) -> VideoGenerationJob:
        job = await self._repo.get(public_id)
        if job is None:
            raise AppError("VIDEO_JOB_NOT_FOUND", "生成任务不存在", status_code=404)
        return job

    def video_path(self, job: VideoGenerationJob) -> Path:
        if job.status != int(VideoJobStatus.SUCCEEDED):
            raise AppError("VIDEO_NOT_READY", "视频尚未生成完成", status_code=404)
        try:
            return self._storage.download_path(f"videogen/{job.public_id}/video.mp4")
        except FileNotFoundError:
            raise AppError("VIDEO_NOT_FOUND", "视频不存在", status_code=404) from None

    def reference_path(self, job: VideoGenerationJob) -> Path:
        if not job.reference_object_key:
            raise AppError("VIDEO_REFERENCE_NOT_FOUND", "参考图不存在", status_code=404)
        try:
            return self._storage.download_path(job.reference_object_key)
        except FileNotFoundError:
            raise AppError(
                "VIDEO_REFERENCE_NOT_FOUND", "参考图不存在", status_code=404
            ) from None

    async def _select_provider(self) -> SelectedProvider:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ProviderConfig, ProviderVersion)
                .join(
                    ProviderVersion,
                    ProviderVersion.id == ProviderConfig.active_version_id,
                )
                .where(
                    ProviderConfig.status == int(ProviderStatus.ENABLED),
                    ProviderConfig.capability
                    == int(ProviderCapability.VIDEO_GENERATION),
                )
            )
            rows = [(row[0], row[1]) for row in result]
        return ProviderSelector().select(
            ProviderCapability.VIDEO_GENERATION, None, rows
        )

    async def _run_job(
        self,
        public_id: str,
        prompt: str,
        size: str,
        duration_seconds: int,
        tier: int,
    ) -> None:
        try:
            await self._generate(public_id, prompt, size, duration_seconds, tier)
        except ProviderRequestError as error:
            await self._finish_failed(public_id, error.code, error.message)
        except Exception:
            _LOGGER.exception("videogen job crashed %s", public_id)
            await self._finish_failed(
                public_id, "PROVIDER_INTERNAL", "生成任务内部错误，请重试"
            )

    async def _load_reference_data_uri(self, public_id: str) -> str:
        async with self._session_factory() as session:
            job = await VideoGenRepository(session).get(public_id)
            key = job.reference_object_key if job is not None else None
        if not key:
            raise ProviderRequestError(
                "MEDIA_INPUT_UNAVAILABLE", "视频参考图不可用"
            )
        try:
            payload = await asyncio.to_thread(
                Path(self._storage.download_path(key)).read_bytes
            )
        except (FileNotFoundError, OSError):
            raise ProviderRequestError(
                "MEDIA_INPUT_UNAVAILABLE", "视频参考图不可用"
            ) from None
        mime = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "webp": "image/webp",
        }.get(key.rsplit(".", 1)[-1], "image/png")
        return f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"

    async def _generate(
        self,
        public_id: str,
        prompt: str,
        size: str,
        duration_seconds: int,
        tier: int,
    ) -> None:
        try:
            selected = await self._select_provider()
            runtime = self._factory.build(selected.config, selected.version)
        except ProviderRequestError as error:
            await self._finish_failed(public_id, error.code, error.message)
            return
        request_id = f"videogen:{public_id}"
        started = time.monotonic()
        try:
            reference = await self._load_reference_data_uri(public_id)
            result = await asyncio.to_thread(
                runtime.generate_video,
                prompt,
                reference,
                size,
                duration_seconds,
                tier,
            )
            await asyncio.to_thread(
                self._storage.put_bytes,
                f"videogen/{public_id}/video.mp4",
                result.video,
            )
        except ProviderRequestError as error:
            await self._record_attempt(
                selected,
                request_id,
                round((time.monotonic() - started) * 1000),
                error=error,
            )
            await self._finish_failed(public_id, error.code, error.message)
            return
        await self._record_attempt(
            selected,
            request_id,
            round((time.monotonic() - started) * 1000),
            result=result,
        )
        await self._finish_succeeded(public_id)

    async def _finish_succeeded(self, public_id: str) -> None:
        async with self._session_factory() as session:
            job = await VideoGenRepository(session).get(public_id)
            if job is None:
                _LOGGER.warning("videogen job disappeared %s", public_id)
                return
            await VideoGenRepository(session).mark_succeeded(job)
            await session.commit()

    async def _finish_failed(
        self, public_id: str, error_code: str, error_message: str
    ) -> None:
        async with self._session_factory() as session:
            job = await VideoGenRepository(session).get(public_id)
            if job is None:
                _LOGGER.warning("videogen job disappeared %s", public_id)
                return
            await VideoGenRepository(session).mark_failed(
                job, error_code=error_code, error_message=error_message
            )
            await session.commit()

    async def _record_attempt(
        self,
        selected: SelectedProvider,
        request_id: str,
        duration_ms: int,
        *,
        result: VideoGenResult | None = None,
        error: ProviderRequestError | None = None,
    ) -> None:
        async with self._session_factory() as session:
            existing = await session.scalar(
                select(AiUsageRecord.id).where(AiUsageRecord.request_id == request_id)
            )
            if existing is not None:
                return
            now = _now()
            input_units = result.usage.input_units if result else 0
            output_units = result.usage.output_units if result else 0
            cost = 0
            unit_price = 0
            snapshot: dict[str, object] = {"source": "unconfigured", "currency": "CNY"}
            price = await session.scalar(
                select(ProviderPrice)
                .where(
                    ProviderPrice.provider_version_id == selected.version.id,
                    ProviderPrice.capability
                    == int(ProviderCapability.VIDEO_GENERATION),
                    ProviderPrice.model_name == selected.version.model_name,
                    ProviderPrice.effective_from <= now,
                    or_(
                        ProviderPrice.effective_to.is_(None),
                        ProviderPrice.effective_to > now,
                    ),
                )
                .order_by(ProviderPrice.effective_from.desc())
                .limit(1)
            )
            if price is not None:
                billable = input_units + output_units
                cost = math.ceil(billable / price.unit_size) * price.unit_price_microunit
                unit_price = price.unit_price_microunit
                snapshot = {
                    "priceId": price.public_id,
                    "billingUnit": price.billing_unit,
                    "unitSize": price.unit_size,
                    "unitPriceMicrounit": price.unit_price_microunit,
                    "currency": price.currency,
                }
            session.add(
                AiUsageRecord(
                    public_id=str(ULID()),
                    project_id=0,
                    task_id=None,
                    provider_version_id=selected.version.id,
                    request_id=request_id,
                    capability=int(ProviderCapability.VIDEO_GENERATION),
                    model_name=selected.version.model_name,
                    target_locale=None,
                    input_units=input_units,
                    output_units=output_units,
                    duration_ms=duration_ms,
                    status=int(UsageStatus.SUCCEEDED if result else UsageStatus.FAILED),
                    unit_price_microunit=unit_price,
                    cost_microunit=cost,
                    price_snapshot_json=snapshot,
                    error_code=error.code if error else None,
                    created_at=now,
                )
            )
            await session.commit()
