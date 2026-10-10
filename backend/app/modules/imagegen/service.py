from __future__ import annotations

import asyncio
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
from app.modules.imagegen.model import ImageGenerationJob, ImageJobStatus
from app.modules.imagegen.repository import ImageGenRepository, _now
from app.modules.media.storage import LocalObjectStorage
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider_runtime.contracts import (
    ImageGenResult,
    ProviderRequestError,
)
from app.modules.provider_runtime.runtime import (
    ProviderRuntimeFactory,
    ProviderSelector,
    SelectedProvider,
)

_LOGGER = logging.getLogger(__name__)

ALLOWED_SIZES = ("2K", "3K", "4K")
MAX_IMAGES_PER_JOB = 3
MAX_REFERENCE_IMAGES = 3


def _validate_request(
    prompt: str, size: str, count: int, references: list[str]
) -> None:
    if not prompt.strip():
        raise AppError(
            "IMAGE_PROMPT_REQUIRED", "请填写图片描述", status_code=422
        )
    if size not in ALLOWED_SIZES:
        raise AppError(
            "IMAGE_SIZE_INVALID", "分辨率仅支持 2K、3K 或 4K", status_code=422
        )
    if not 1 <= count <= MAX_IMAGES_PER_JOB:
        raise AppError(
            "IMAGE_COUNT_INVALID", "一次最多生成 3 张图片", status_code=422
        )
    if len(references) > MAX_REFERENCE_IMAGES:
        raise AppError(
            "IMAGE_REFERENCES_LIMIT", "参考图最多上传 3 张", status_code=422
        )
    for reference in references:
        if not reference.startswith("data:image/"):
            raise AppError(
                "IMAGE_REFERENCE_INVALID",
                "参考图必须是图片 data URI",
                status_code=422,
            )


class ImageGenService:
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
        self._repo = ImageGenRepository(session)
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
        size: str,
        count: int,
        references: list[str],
    ) -> ImageGenerationJob:
        _validate_request(prompt, size, count, references)
        try:
            await self._select_provider()
        except ProviderRequestError as error:
            raise AppError(
                "PROVIDER_NOT_CONFIGURED",
                "尚未配置图片生成供应商，请联系管理员",
                status_code=409,
            ) from error
        job = await self._repo.create(
            account_id=account_id,
            prompt=prompt.strip(),
            size=size,
            count=count,
            reference_count=len(references),
        )
        await self._session.commit()
        self._spawn(
            self._run_job(job.public_id, prompt.strip(), size, count, list(references))
        )
        return job

    async def list_jobs(
        self, account_id: int, *, limit: int, offset: int
    ) -> list[ImageGenerationJob]:
        return await self._repo.list_page(account_id, limit=limit, offset=offset)

    async def list_all_jobs(
        self, *, limit: int, offset: int
    ) -> list[ImageGenerationJob]:
        return await self._repo.list_all(limit=limit, offset=offset)

    async def require(self, account_id: int, public_id: str) -> ImageGenerationJob:
        job = await self._repo.get(public_id)
        if job is None or job.account_id != account_id:
            raise AppError(
                "IMAGE_JOB_NOT_FOUND", "生成任务不存在", status_code=404
            )
        return job

    async def require_any(self, public_id: str) -> ImageGenerationJob:
        job = await self._repo.get(public_id)
        if job is None:
            raise AppError(
                "IMAGE_JOB_NOT_FOUND", "生成任务不存在", status_code=404
            )
        return job

    def image_path(self, job: ImageGenerationJob, index: int) -> Path:
        if job.status != int(ImageJobStatus.SUCCEEDED):
            raise AppError(
                "IMAGE_NOT_READY", "图片尚未生成完成", status_code=404
            )
        if not 0 <= index < job.count:
            raise AppError("IMAGE_NOT_FOUND", "图片不存在", status_code=404)
        try:
            return self._storage.download_path(
                f"imagegen/{job.public_id}/{index}.png"
            )
        except FileNotFoundError:
            raise AppError("IMAGE_NOT_FOUND", "图片不存在", status_code=404) from None

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
                    == int(ProviderCapability.IMAGE_GENERATION),
                )
            )
            rows = [(row[0], row[1]) for row in result]
        return ProviderSelector().select(
            ProviderCapability.IMAGE_GENERATION, None, rows
        )

    async def _run_job(
        self,
        public_id: str,
        prompt: str,
        size: str,
        count: int,
        references: list[str],
    ) -> None:
        try:
            await self._generate(public_id, prompt, size, count, references)
        except ProviderRequestError as error:
            await self._finish_failed(public_id, error.code, error.message)
        except Exception:
            _LOGGER.exception("imagegen job crashed %s", public_id)
            await self._finish_failed(
                public_id, "PROVIDER_INTERNAL", "生成任务内部错误，请重试"
            )

    async def _generate(
        self,
        public_id: str,
        prompt: str,
        size: str,
        count: int,
        references: list[str],
    ) -> None:
        try:
            selected = await self._select_provider()
            runtime = self._factory.build(selected.config, selected.version)
        except ProviderRequestError as error:
            await self._finish_failed(public_id, error.code, error.message)
            return
        for index in range(count):
            request_id = f"imagegen:{public_id}:{index}"
            started = time.monotonic()
            try:
                result = await asyncio.to_thread(
                    runtime.generate, prompt, size, references
                )
                await asyncio.to_thread(
                    self._storage.put_bytes,
                    f"imagegen/{public_id}/{index}.png",
                    result.image,
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
            job = await ImageGenRepository(session).get(public_id)
            if job is None:
                _LOGGER.warning("imagegen job disappeared %s", public_id)
                return
            await ImageGenRepository(session).mark_succeeded(job)
            await session.commit()

    async def _finish_failed(
        self, public_id: str, error_code: str, error_message: str
    ) -> None:
        async with self._session_factory() as session:
            job = await ImageGenRepository(session).get(public_id)
            if job is None:
                _LOGGER.warning("imagegen job disappeared %s", public_id)
                return
            await ImageGenRepository(session).mark_failed(
                job, error_code=error_code, error_message=error_message
            )
            await session.commit()

    async def _record_attempt(
        self,
        selected: SelectedProvider,
        request_id: str,
        duration_ms: int,
        *,
        result: ImageGenResult | None = None,
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
                    == int(ProviderCapability.IMAGE_GENERATION),
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
                    capability=int(ProviderCapability.IMAGE_GENERATION),
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
