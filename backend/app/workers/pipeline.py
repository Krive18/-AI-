from __future__ import annotations

import asyncio
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar

from redis.asyncio import Redis
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from ulid import ULID

from app.modules.cost.model import AiUsageRecord, ProviderPrice, UsageStatus
from app.modules.media.model import (
    AssetType,
    MediaAsset,
    SourceSegment,
    SubtitleSegment,
    TaskEvent,
)
from app.modules.media.storage import LocalObjectStorage
from app.modules.media_runtime.ffmpeg import FFmpeg, MediaCommandError
from app.modules.media_runtime.subtitle_mask import detect_subtitle_band
from app.modules.media_runtime.subtitle_ocr import (
    FRAME_BYTES,
    OcrSegmentBuilder,
    plan_ocr_indices,
)
from app.modules.project.schemas import TranslationMode
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider_runtime.contracts import (
    InterpretationSegment,
    ProviderRequestError,
    ProviderUsage,
)
from app.modules.provider_runtime.runtime import (
    ProviderRuntimeFactory,
    ProviderSelector,
    SelectedProvider,
)
from app.modules.translation.model import (
    ProjectStatus,
    TaskStage,
    TaskStatus,
    TranslationProject,
    TranslationTask,
)
from app.modules.translation.subtitle_text import clean_subtitle_text
from app.workers.lease import WorkLease
from app.workers.subtitles import SubtitleCue, render_srt

logger = logging.getLogger(__name__)
_ResultT = TypeVar("_ResultT")

_PROJECT_ACTIVE = (
    int(ProjectStatus.VALIDATING),
    int(ProjectStatus.EXTRACTING_AUDIO),
    int(ProjectStatus.RECOGNIZING),
    int(ProjectStatus.CANCEL_REQUESTED),
)
_TASK_ACTIVE = (
    int(TaskStatus.QUEUED),
    int(TaskStatus.TRANSLATING),
    int(TaskStatus.SYNTHESIZING),
    int(TaskStatus.RENDERING),
    int(TaskStatus.CANCEL_REQUESTED),
)
_TASK_TERMINAL = (
    int(TaskStatus.SUCCEEDED),
    int(TaskStatus.FAILED),
    int(TaskStatus.CANCELLED),
)


def _validate_youdao_delivery(
    segments: list[InterpretationSegment], source_duration_ms: int
) -> list[InterpretationSegment]:
    if source_duration_ms <= 0 or not segments:
        raise ValueError("youdao delivery timeline is empty")
    ordered = sorted(segments, key=lambda item: item.sequence_no)
    if len({item.sequence_no for item in ordered}) != len(ordered):
        raise ValueError("youdao delivery timeline contains duplicate segments")
    validated: list[InterpretationSegment] = []
    for item in ordered:
        end_ms = min(item.end_ms, source_duration_ms)
        if item.start_ms >= source_duration_ms or end_ms <= item.start_ms:
            raise ValueError("youdao delivery timeline is outside the video")
        validated.append(
            InterpretationSegment(
                sequence_no=item.sequence_no,
                start_ms=item.start_ms,
                end_ms=end_ms,
                source_text=item.source_text,
                translated_text=item.translated_text,
                audio=item.audio,
                audio_format=item.audio_format,
            )
        )
    return validated


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _subtitle_mask_rect(
    source: Path, duration_ms: int, width: int, height: int
) -> tuple[int, int, int, int] | None:
    """Full-width rectangle covering the detected source-subtitle band."""
    band = detect_subtitle_band(source, duration_ms, height)
    if band is None:
        return None
    mask_x = max(1, round(width * 0.06))
    mask_width = min(width - mask_x - 1, round(width * 0.88))
    return (mask_x, band[0], mask_width, band[1] - band[0])


@dataclass(frozen=True, slots=True)
class WorkerRun:
    projects: int = 0
    tasks: int = 0


class TranslationWorker:
    """Resumable MySQL-backed pipeline with Redis leases for horizontal workers."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        storage: LocalObjectStorage,
        ffmpeg: FFmpeg,
        runtime_factory: ProviderRuntimeFactory,
        *,
        lease_seconds: int = 1800,
        max_concurrency: int = 2,
    ) -> None:
        self._sessions = session_factory
        self._redis = redis
        self._storage = storage
        self._ffmpeg = ffmpeg
        self._runtime_factory = runtime_factory
        self._selector = ProviderSelector()
        self._lease_seconds = lease_seconds
        self._max_concurrency = max_concurrency

    async def run_once(self) -> WorkerRun:
        semaphore = asyncio.Semaphore(self._max_concurrency)
        project_ids = await self._pending_projects()
        task_ids = await self._pending_tasks()
        results = await asyncio.gather(
            *(
                self._run_with_lease(
                    semaphore,
                    f"ai-translation:worker:project:{project_id}",
                    partial(self._run_project, project_id),
                )
                for project_id in project_ids
            ),
            *(
                self._run_with_lease(
                    semaphore,
                    f"ai-translation:worker:task:{task_id}",
                    partial(self._run_task, task_id),
                )
                for task_id in task_ids
            ),
        )
        projects = sum(results[: len(project_ids)])
        tasks = sum(results[len(project_ids) :])
        return WorkerRun(projects, tasks)

    async def _run_with_lease(
        self,
        semaphore: asyncio.Semaphore,
        lease_key: str,
        run: Callable[[], Awaitable[None]],
    ) -> int:
        async with semaphore:
            try:
                async with WorkLease(
                    self._redis, lease_key, self._lease_seconds
                ) as lease:
                    if lease is None:
                        return 0
                    await run()
            except Exception:
                logger.exception(
                    "worker item failed", extra={"lease_key": lease_key}
                )
                return 0
            return 1

    async def _pending_projects(self) -> list[int]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(TranslationProject.id)
                .where(TranslationProject.status.in_(_PROJECT_ACTIVE))
                .order_by(TranslationProject.id)
                .limit(10)
            )
            return list(result)

    async def _pending_tasks(self) -> list[int]:
        async with self._sessions() as session:
            result = await session.scalars(
                select(TranslationTask.id)
                .join(
                    TranslationProject,
                    TranslationProject.id == TranslationTask.project_id,
                )
                .where(
                    TranslationProject.status.in_(
                        (
                            int(ProjectStatus.PROCESSING),
                            int(ProjectStatus.CANCEL_REQUESTED),
                        )
                    ),
                    TranslationTask.status.in_(_TASK_ACTIVE),
                )
                .order_by(TranslationTask.id)
                .limit(20)
            )
            return list(result)

    async def _run_project(self, project_id: int) -> None:
        try:
            if await self._cancel_project_if_requested(project_id):
                return
            status = await self._project_status(project_id)
            if status == int(ProjectStatus.VALIDATING):
                await self._validate_source(project_id)
                status = int(ProjectStatus.EXTRACTING_AUDIO)
            if status == int(ProjectStatus.EXTRACTING_AUDIO):
                await self._extract_audio(project_id)
                status = int(ProjectStatus.RECOGNIZING)
            if status == int(ProjectStatus.RECOGNIZING):
                await self._recognize(project_id)
        except (MediaCommandError, ProviderRequestError, OSError, ValueError) as error:
            code = getattr(error, "code", "SOURCE_PROCESSING_FAILED")
            await self._fail_project(project_id, str(code))
        except Exception:
            logger.exception(
                "unexpected shared pipeline failure", extra={"project_id": project_id}
            )
            await self._fail_project(project_id, "WORKER_UNEXPECTED")

    async def _run_task(self, task_id: int) -> None:
        try:
            if await self._cancel_task_if_requested(task_id):
                return
            context = await self._task_project_context(task_id)
            if context is None:
                return
            project_id, translation_mode = context
            if translation_mode == TranslationMode.YOUDAO.value:
                async with WorkLease(
                    self._redis,
                    f"ai-translation:worker:youdao-project:{project_id}",
                    self._lease_seconds,
                ) as lease:
                    if lease is None:
                        return
                    status = await self._task_status(task_id)
                    if status in (
                        int(TaskStatus.QUEUED),
                        int(TaskStatus.TRANSLATING),
                    ):
                        await self._translate_with_youdao(task_id)
                        status = int(TaskStatus.SYNTHESIZING)
                    if status == int(TaskStatus.SYNTHESIZING):
                        await self._synthesize(task_id)
                        status = int(TaskStatus.RENDERING)
                    if status == int(TaskStatus.RENDERING):
                        await self._render(task_id)
                return
            status = await self._task_status(task_id)
            if status in (int(TaskStatus.QUEUED), int(TaskStatus.TRANSLATING)):
                await self._translate(task_id)
                status = int(TaskStatus.SYNTHESIZING)
            if status == int(TaskStatus.SYNTHESIZING):
                await self._synthesize(task_id)
                status = int(TaskStatus.RENDERING)
            if status == int(TaskStatus.RENDERING):
                await self._render(task_id)
        except (MediaCommandError, ProviderRequestError, OSError, ValueError) as error:
            code = getattr(error, "code", "TASK_PROCESSING_FAILED")
            message = getattr(error, "message", None)
            await self._fail_task(task_id, str(code), str(message) if message else None)
        except Exception:
            logger.exception(
                "unexpected task pipeline failure", extra={"task_id": task_id}
            )
            await self._fail_task(task_id, "WORKER_UNEXPECTED")

    async def _task_project_context(self, task_id: int) -> tuple[int, str] | None:
        async with self._sessions() as session:
            row = (
                await session.execute(
                    select(
                        TranslationTask.project_id, TranslationProject.translation_mode
                    )
                    .join(
                        TranslationProject,
                        TranslationProject.id == TranslationTask.project_id,
                    )
                    .where(TranslationTask.id == task_id)
                )
            ).one_or_none()
            return (int(row[0]), str(row[1])) if row is not None else None

    async def _project_status(self, project_id: int) -> int:
        async with self._sessions() as session:
            return int(
                await session.scalar(
                    select(TranslationProject.status).where(
                        TranslationProject.id == project_id
                    )
                )
                or 0
            )

    async def _task_status(self, task_id: int) -> int:
        async with self._sessions() as session:
            return int(
                await session.scalar(
                    select(TranslationTask.status).where(TranslationTask.id == task_id)
                )
                or 0
            )

    async def _validate_source(self, project_id: int) -> None:
        async with self._sessions() as session:
            project = await session.get(TranslationProject, project_id)
            if project is None:
                return
            translation_mode = project.translation_mode
            source = self._storage.resolve_private_path(project.source_object_key)
        probe = await asyncio.to_thread(self._ffmpeg.probe, source)
        requires_audio = translation_mode != TranslationMode.SUBTITLE_OCR.value
        if (
            probe.video_codec is None
            or probe.duration_ms <= 0
            or (requires_audio and probe.audio_codec is None)
        ):
            raise MediaCommandError("MEDIA_STREAMS_REQUIRED", "视频必须包含音视频流")
        async with self._sessions() as session:
            project = await session.get(
                TranslationProject, project_id, with_for_update=True
            )
            if project is None or project.status != int(ProjectStatus.VALIDATING):
                return
            project.source_duration_ms = probe.duration_ms
            project.source_container = probe.container
            project.source_video_codec = probe.video_codec
            project.source_audio_codec = probe.audio_codec
            await self._advance_project(
                session, project, ProjectStatus.EXTRACTING_AUDIO, 15, "SOURCE_VALIDATED"
            )

    async def _extract_audio(self, project_id: int) -> None:
        async with self._sessions() as session:
            project = await session.get(TranslationProject, project_id)
            if project is None:
                return
            if project.translation_mode == TranslationMode.SUBTITLE_OCR.value:
                project = await session.get(
                    TranslationProject, project_id, with_for_update=True
                )
                if project is not None and project.status == int(
                    ProjectStatus.EXTRACTING_AUDIO
                ):
                    # Subtitle OCR reads frames instead of audio; skip extraction.
                    await self._advance_project(
                        session, project, ProjectStatus.RECOGNIZING, 30, "AUDIO_SKIPPED"
                    )
                return
        existing = await self._asset(project_id, None, AssetType.EXTRACTED_AUDIO)
        if existing is None:
            async with self._sessions() as session:
                project = await session.get(TranslationProject, project_id)
                if project is None:
                    return
                public_id = project.public_id
                source = self._storage.resolve_private_path(project.source_object_key)
            with TemporaryDirectory(prefix="ai-translation-") as directory:
                audio = Path(directory) / "source.wav"
                await asyncio.to_thread(self._ffmpeg.extract_audio, source, audio)
                object_key = f"projects/{public_id}/shared/source.wav"
                stored = self._storage.put_file(object_key, audio)
                size = stored.stat().st_size
            async with self._sessions() as session:
                session.add(
                    MediaAsset(
                        public_id=str(ULID()),
                        project_id=project_id,
                        task_id=None,
                        asset_type=int(AssetType.EXTRACTED_AUDIO),
                        object_key=object_key,
                        content_type="audio/wav",
                        sha256=None,
                        size_bytes=size,
                        duration_ms=None,
                        container="wav",
                        video_codec=None,
                        audio_codec="pcm_s16le",
                        metadata_json=None,
                        created_at=_now(),
                    )
                )
                await session.commit()
        async with self._sessions() as session:
            project = await session.get(
                TranslationProject, project_id, with_for_update=True
            )
            if project is not None and project.status == int(
                ProjectStatus.EXTRACTING_AUDIO
            ):
                await self._advance_project(
                    session, project, ProjectStatus.RECOGNIZING, 30, "AUDIO_EXTRACTED"
                )

    async def _recognize(self, project_id: int) -> None:
        async with self._sessions() as session:
            count = int(
                await session.scalar(
                    select(func.count(SourceSegment.id)).where(
                        SourceSegment.project_id == project_id
                    )
                )
                or 0
            )
            project = await session.get(TranslationProject, project_id)
            if project is None:
                return
            public_id = project.public_id
            translation_mode = project.translation_mode
        if translation_mode == TranslationMode.YOUDAO.value:
            async with self._sessions() as session:
                project = await session.get(
                    TranslationProject, project_id, with_for_update=True
                )
                if project is not None and project.status == int(
                    ProjectStatus.RECOGNIZING
                ):
                    await self._advance_project(
                        session,
                        project,
                        ProjectStatus.PROCESSING,
                        45,
                        "YOUDAO_STREAM_READY",
                    )
            return
        if translation_mode == TranslationMode.SUBTITLE_OCR.value:
            if count == 0:
                await self._extract_subtitles_via_ocr(project_id, public_id)
            else:
                async with self._sessions() as session:
                    project = await session.get(
                        TranslationProject, project_id, with_for_update=True
                    )
                    if project is not None:
                        await self._advance_project(
                            session,
                            project,
                            ProjectStatus.PROCESSING,
                            45,
                            "SUBTITLE_REUSED",
                        )
            return
        if count == 0:
            audio_asset = await self._require_asset(
                project_id, None, AssetType.EXTRACTED_AUDIO
            )
            selected = await self._select_provider(ProviderCapability.ASR, None)
            runtime = self._runtime_factory.build(selected.config, selected.version)
            result, duration_ms, request_id = await self._invoke_provider(
                lambda: runtime.transcribe(
                    str(self._storage.resolve_private_path(audio_asset.object_key))
                ),
                base_request_id=f"project:{public_id}:asr",
                project_id=project_id,
                task_id=None,
                capability=ProviderCapability.ASR,
                selected=selected,
                locale=None,
                failure_usage=ProviderUsage(),
            )
            if not result.segments:
                raise ProviderRequestError("ASR_EMPTY", "未识别到可翻译语音")
            async with self._sessions() as session:
                now = _now()
                for index, segment in enumerate(result.segments, 1):
                    if segment.end_ms <= segment.start_ms or not segment.text.strip():
                        raise ProviderRequestError(
                            "ASR_TIMELINE_INVALID", "识别时间轴无效"
                        )
                    session.add(
                        SourceSegment(
                            project_id=project_id,
                            sequence_no=index,
                            start_ms=segment.start_ms,
                            end_ms=segment.end_ms,
                            speaker_label=None,
                            source_text=segment.text.strip(),
                            confidence=segment.confidence,
                            created_at=now,
                        )
                    )
                await self._record_usage(
                    session,
                    project_id=project_id,
                    task_id=None,
                    request_id=request_id,
                    capability=ProviderCapability.ASR,
                    selected=selected,
                    locale=None,
                    usage=result.usage,
                    duration_ms=duration_ms,
                )
                project = await session.get(
                    TranslationProject, project_id, with_for_update=True
                )
                if project is not None:
                    await self._advance_project(
                        session, project, ProjectStatus.PROCESSING, 45, "ASR_COMPLETED"
                    )
                else:
                    await session.commit()
        else:
            async with self._sessions() as session:
                project = await session.get(
                    TranslationProject, project_id, with_for_update=True
                )
                if project is not None:
                    await self._advance_project(
                        session, project, ProjectStatus.PROCESSING, 45, "ASR_REUSED"
                    )

    async def _extract_subtitles_via_ocr(
        self, project_id: int, public_id: str
    ) -> None:
        async with self._sessions() as session:
            project = await session.get(TranslationProject, project_id)
            if project is None or project.source_duration_ms is None:
                raise ValueError("source duration is unavailable")
            source = self._storage.resolve_private_path(project.source_object_key)
            source_duration_ms = project.source_duration_ms
        selected = await self._select_provider(ProviderCapability.SUBTITLE_OCR, None)
        runtime = self._runtime_factory.build(selected.config, selected.version)
        with TemporaryDirectory(prefix="ai-translation-subtitle-") as directory:
            frames_dir = Path(directory) / "frames"
            gray_path = Path(directory) / "gray.raw"
            frame_count = await asyncio.to_thread(
                self._ffmpeg.extract_subtitle_frames, source, frames_dir, gray_path
            )
            gray = gray_path.read_bytes()
            gray_frames = [
                gray[offset : offset + FRAME_BYTES]
                for offset in range(0, frame_count * FRAME_BYTES, FRAME_BYTES)
            ]
            async with self._sessions() as session:
                await self._event(
                    session,
                    project_id,
                    None,
                    "SUBTITLE_FRAMES_EXTRACTED",
                    int(ProjectStatus.RECOGNIZING),
                    35,
                )
                await session.commit()
            builder = OcrSegmentBuilder(source_duration_ms)
            planned = set(plan_ocr_indices(gray_frames))
            for index in range(frame_count):
                if index not in planned:
                    # Pixel-identical to the previous frame: an open segment
                    # persists without another OCR call.
                    builder.note_unchanged(index)
                    continue
                frame_path = frames_dir / f"frame-{index + 1:06d}.jpg"
                try:
                    frame_jpg = frame_path.read_bytes()
                except OSError:
                    raise MediaCommandError(
                        "MEDIA_COMMAND_FAILED", "字幕帧读取失败"
                    ) from None
                text, duration_ms, request_id = await self._invoke_provider(
                    partial(runtime.read_subtitle, frame_jpg),
                    base_request_id=f"project:{public_id}:ocr:{index + 1}",
                    project_id=project_id,
                    task_id=None,
                    capability=ProviderCapability.SUBTITLE_OCR,
                    selected=selected,
                    locale=None,
                    failure_usage=ProviderUsage(input_units=1),
                )
                builder.add(index, text)
                async with self._sessions() as session:
                    await self._record_usage(
                        session,
                        project_id=project_id,
                        task_id=None,
                        request_id=request_id,
                        capability=ProviderCapability.SUBTITLE_OCR,
                        selected=selected,
                        locale=None,
                        usage=ProviderUsage(input_units=1),
                        duration_ms=duration_ms,
                    )
                    await session.commit()
            segments = builder.finish()
        if not segments:
            raise ProviderRequestError("PROVIDER_NO_SPEECH", "未在画面中识别到字幕")
        async with self._sessions() as session:
            now = _now()
            for index, segment in enumerate(segments, 1):
                session.add(
                    SourceSegment(
                        project_id=project_id,
                        sequence_no=index,
                        start_ms=segment.start_ms,
                        end_ms=segment.end_ms,
                        speaker_label=None,
                        source_text=segment.text,
                        confidence=None,
                        created_at=now,
                    )
                )
            await session.commit()
        async with self._sessions() as session:
            project = await session.get(
                TranslationProject, project_id, with_for_update=True
            )
            if project is not None:
                await self._advance_project(
                    session,
                    project,
                    ProjectStatus.PROCESSING,
                    45,
                    "SUBTITLE_OCR_COMPLETED",
                )

    async def _translate(self, task_id: int) -> None:
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id)
            if task is None:
                return
            project = await session.get(TranslationProject, task.project_id)
            if project is None:
                return
            source_rows = list(
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.project_id == task.project_id)
                    .order_by(SourceSegment.sequence_no)
                )
            )
            existing = set(
                await session.scalars(
                    select(SubtitleSegment.source_segment_id).where(
                        SubtitleSegment.task_id == task_id
                    )
                )
            )
            task_public_id = task.public_id
            locale = task.target_locale
            project_id = task.project_id
        if not source_rows:
            raise ValueError("source transcript is unavailable")
        selected = await self._select_provider(ProviderCapability.TRANSLATION, locale)
        runtime = self._runtime_factory.build(selected.config, selected.version)
        for index, source in enumerate(source_rows, 1):
            if source.id in existing:
                continue
            result, duration_ms, request_id = await self._invoke_provider(
                partial(
                    runtime.translate,
                    source.source_text,
                    locale,
                    source.end_ms - source.start_ms,
                ),
                base_request_id=(
                    f"task:{task_public_id}:translate:{source.sequence_no}"
                ),
                project_id=project_id,
                task_id=task_id,
                capability=ProviderCapability.TRANSLATION,
                selected=selected,
                locale=locale,
                failure_usage=ProviderUsage(input_units=len(source.source_text)),
            )
            async with self._sessions() as session:
                session.add(
                    SubtitleSegment(
                        task_id=task_id,
                        source_segment_id=source.id,
                        sequence_no=source.sequence_no,
                        translated_text=result.text.strip(),
                        tts_text=result.text.strip(),
                        created_at=_now(),
                    )
                )
                await self._record_usage(
                    session,
                    project_id=project_id,
                    task_id=task_id,
                    request_id=request_id,
                    capability=ProviderCapability.TRANSLATION,
                    selected=selected,
                    locale=locale,
                    usage=result.usage,
                    duration_ms=duration_ms,
                )
                task = await session.get(TranslationTask, task_id, with_for_update=True)
                if task is not None:
                    task.status = int(TaskStatus.TRANSLATING)
                    task.stage = int(TaskStage.TRANSLATING)
                    task.progress_percent = 10 + round(index / len(source_rows) * 35)
                    task.updated_at = _now()
                    await self._event(
                        session,
                        task.project_id,
                        task.id,
                        "SEGMENT_TRANSLATED",
                        task.stage,
                        task.progress_percent,
                    )
                await session.commit()
        await self._create_srt(task_id)
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id, with_for_update=True)
            if task is not None:
                task.status = int(TaskStatus.SYNTHESIZING)
                task.stage = int(TaskStage.SYNTHESIZING)
                task.progress_percent = 50
                task.updated_at = _now()
                await self._event(
                    session,
                    task.project_id,
                    task.id,
                    "TRANSLATION_COMPLETED",
                    task.stage,
                    50,
                )
                await session.commit()

    async def _create_srt(self, task_id: int) -> None:
        if await self._asset_for_task(task_id, AssetType.SUBTITLE_SRT) is not None:
            return
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id)
            if task is None:
                return
            project = await session.get(TranslationProject, task.project_id)
            rows = list(
                (
                    await session.execute(
                        select(SourceSegment, SubtitleSegment)
                        .join(
                            SubtitleSegment,
                            and_(
                                SubtitleSegment.source_segment_id == SourceSegment.id,
                                SubtitleSegment.task_id == task_id,
                            ),
                        )
                        .where(SourceSegment.project_id == task.project_id)
                        .order_by(SourceSegment.sequence_no)
                    )
                ).all()
            )
            if project is None:
                return
            object_key = (
                f"projects/{project.public_id}/{task.target_locale}/subtitles.srt"
            )
        payload = render_srt(
            SubtitleCue(
                source.sequence_no,
                source.start_ms,
                source.end_ms,
                clean_subtitle_text(target.translated_text),
            )
            for source, target in rows
        )
        path = self._storage.put_bytes(object_key, payload)
        await self._add_asset(
            project.id,
            task_id,
            AssetType.SUBTITLE_SRT,
            object_key,
            "application/x-subrip",
            path.stat().st_size,
        )

    async def _translate_with_youdao(self, task_id: int) -> None:
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id)
            if task is None:
                return
            project = await session.get(TranslationProject, task.project_id)
            if project is None or project.source_duration_ms is None:
                raise ValueError("source duration is unavailable")
            already_translated = int(
                await session.scalar(
                    select(func.count(SubtitleSegment.id)).where(
                        SubtitleSegment.task_id == task_id
                    )
                )
                or 0
            )
            task.status = int(TaskStatus.TRANSLATING)
            task.stage = int(TaskStage.TRANSLATING)
            task.progress_percent = max(task.progress_percent, 10)
            task.updated_at = _now()
            await self._event(
                session,
                task.project_id,
                task.id,
                "YOUDAO_STREAM_STARTED",
                task.stage,
                task.progress_percent,
            )
            await session.commit()
            project_id = project.id
            task_public_id = task.public_id
            locale = task.target_locale
            source_duration_ms = project.source_duration_ms
        if already_translated:
            async with self._sessions() as session:
                task = await session.get(TranslationTask, task_id, with_for_update=True)
                if task is not None:
                    task.status = int(TaskStatus.SYNTHESIZING)
                    task.stage = int(TaskStage.SYNTHESIZING)
                    task.progress_percent = max(task.progress_percent, 50)
                    task.updated_at = _now()
                    await session.commit()
            return

        audio_asset = await self._require_asset(
            project_id, None, AssetType.EXTRACTED_AUDIO
        )
        selected = await self._select_provider(
            ProviderCapability.SIMULTANEOUS_INTERPRETATION, locale
        )
        runtime = self._runtime_factory.build(selected.config, selected.version)
        result, duration_ms, request_id = await self._invoke_provider(
            partial(
                runtime.interpret_text,
                str(self._storage.resolve_private_path(audio_asset.object_key)),
                locale,
            ),
            base_request_id=f"task:{task_public_id}:youdao",
            project_id=project_id,
            task_id=task_id,
            capability=ProviderCapability.SIMULTANEOUS_INTERPRETATION,
            selected=selected,
            locale=locale,
            failure_usage=ProviderUsage(audio_seconds=source_duration_ms / 1000),
        )
        segments = _validate_youdao_delivery(result.segments, source_duration_ms)

        async with self._sessions() as session:
            source_rows = list(
                await session.scalars(
                    select(SourceSegment)
                    .where(SourceSegment.project_id == project_id)
                    .order_by(SourceSegment.sequence_no)
                    .with_for_update()
                )
            )
            now = _now()
            if not source_rows:
                source_rows = [
                    SourceSegment(
                        project_id=project_id,
                        sequence_no=item.sequence_no,
                        start_ms=item.start_ms,
                        end_ms=item.end_ms,
                        speaker_label=None,
                        source_text=item.source_text,
                        confidence=None,
                        created_at=now,
                    )
                    for item in segments
                ]
                session.add_all(source_rows)
                await session.flush()
            if [row.sequence_no for row in source_rows] != [
                item.sequence_no for item in segments
            ]:
                raise ProviderRequestError(
                    "PROVIDER_RESPONSE_INVALID", "智能翻译服务分段与已有项目不一致"
                )
            for source, item in zip(source_rows, segments, strict=True):
                session.add(
                    SubtitleSegment(
                        task_id=task_id,
                        source_segment_id=source.id,
                        sequence_no=item.sequence_no,
                        translated_text=item.translated_text,
                        tts_text=item.translated_text,
                        created_at=now,
                    )
                )
            await self._record_usage(
                session,
                project_id=project_id,
                task_id=task_id,
                request_id=request_id,
                capability=ProviderCapability.SIMULTANEOUS_INTERPRETATION,
                selected=selected,
                locale=locale,
                usage=result.usage,
                duration_ms=duration_ms,
            )
            await session.commit()
        await self._create_srt(task_id)
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id, with_for_update=True)
            if task is None:
                return
            task.status = int(TaskStatus.SYNTHESIZING)
            task.stage = int(TaskStage.SYNTHESIZING)
            task.progress_percent = 50
            task.updated_at = _now()
            await self._event(
                session,
                project_id,
                task_id,
                "YOUDAO_STREAM_COMPLETED",
                task.stage,
                50,
            )
            await session.commit()

    async def _synthesize(self, task_id: int) -> None:
        if await self._asset_for_task(task_id, AssetType.DUBBED_AUDIO) is None:
            async with self._sessions() as session:
                task = await session.get(TranslationTask, task_id)
                if task is None:
                    return
                project = await session.get(TranslationProject, task.project_id)
                rows = list(
                    (
                        await session.execute(
                            select(SourceSegment, SubtitleSegment)
                            .join(
                                SubtitleSegment,
                                and_(
                                    SubtitleSegment.source_segment_id
                                    == SourceSegment.id,
                                    SubtitleSegment.task_id == task_id,
                                ),
                            )
                            .order_by(SourceSegment.sequence_no)
                        )
                    ).all()
                )
                if project is None or project.source_duration_ms is None:
                    return
                project_id = task.project_id
                project_public_id = project.public_id
                task_public_id = task.public_id
                locale = task.target_locale
                requested_voice = task.voice_id
                source_duration_ms = project.source_duration_ms
            if not rows:
                raise ValueError("translated subtitles are unavailable")
            selected = await self._select_provider(ProviderCapability.TTS, locale)
            options = selected.version.config_json or {}
            default_voice = options.get("default_voice_id")
            voice_id = requested_voice or (
                default_voice if isinstance(default_voice, str) else "male-qn-qingse"
            )
            runtime = self._runtime_factory.build(selected.config, selected.version)
            timeline: list[tuple[Path, int, int, int]] = []
            for index, (source, subtitle) in enumerate(rows, 1):
                request_base = f"task:{task_public_id}:tts:{source.sequence_no}"
                segment_path: Path | None = None
                if await self._successful_usage_exists(request_base):
                    for extension in (".wav", ".mp3"):
                        key = (
                            f"projects/{project_public_id}/{locale}/tts/"
                            f"segment-{source.sequence_no:06d}{extension}"
                        )
                        try:
                            segment_path = self._storage.resolve_private_path(key)
                            break
                        except FileNotFoundError:
                            continue
                if segment_path is None:
                    text = (subtitle.tts_text or subtitle.translated_text).strip()
                    result, duration_ms, request_id = await self._invoke_provider(
                        partial(runtime.synthesize, text, locale, voice_id),
                        base_request_id=request_base,
                        project_id=project_id,
                        task_id=task_id,
                        capability=ProviderCapability.TTS,
                        selected=selected,
                        locale=locale,
                        failure_usage=ProviderUsage(input_units=len(text)),
                    )
                    extension = ".wav" if result.content_type == "audio/wav" else ".mp3"
                    key = (
                        f"projects/{project_public_id}/{locale}/tts/"
                        f"segment-{source.sequence_no:06d}{extension}"
                    )
                    segment_path = self._storage.put_bytes(key, result.audio)
                    async with self._sessions() as session:
                        await self._record_usage(
                            session,
                            project_id=project_id,
                            task_id=task_id,
                            request_id=request_id,
                            capability=ProviderCapability.TTS,
                            selected=selected,
                            locale=locale,
                            usage=result.usage,
                            duration_ms=duration_ms,
                        )
                        current = await session.get(
                            TranslationTask, task_id, with_for_update=True
                        )
                        if current is not None:
                            current.progress_percent = 50 + round(
                                index / len(rows) * 20
                            )
                            current.updated_at = _now()
                        await session.commit()
                audio_probe = await asyncio.to_thread(self._ffmpeg.probe, segment_path)
                timeline.append(
                    (
                        segment_path,
                        source.start_ms,
                        min(source.end_ms, source_duration_ms),
                        audio_probe.duration_ms,
                    )
                )
            with TemporaryDirectory(prefix="ai-translation-voice-") as directory:
                combined = Path(directory) / "dubbed.wav"
                await asyncio.to_thread(
                    self._ffmpeg.compose_timeline,
                    timeline,
                    source_duration_ms,
                    combined,
                )
                object_key = f"projects/{project_public_id}/{locale}/dubbed.wav"
                path = self._storage.put_file(object_key, combined)
            async with self._sessions() as session:
                session.add(
                    self._new_asset(
                        project_id,
                        task_id,
                        AssetType.DUBBED_AUDIO,
                        object_key,
                        "audio/wav",
                        path.stat().st_size,
                    )
                )
                task = await session.get(TranslationTask, task_id, with_for_update=True)
                if task is not None:
                    task.status = int(TaskStatus.RENDERING)
                    task.stage = int(TaskStage.RENDERING)
                    task.progress_percent = 75
                    task.updated_at = _now()
                    await self._event(
                        session,
                        task.project_id,
                        task.id,
                        "TTS_COMPLETED",
                        task.stage,
                        75,
                    )
                await session.commit()
        else:
            async with self._sessions() as session:
                task = await session.get(TranslationTask, task_id, with_for_update=True)
                if task is not None:
                    task.status = int(TaskStatus.RENDERING)
                    task.stage = int(TaskStage.RENDERING)
                    task.progress_percent = max(task.progress_percent, 75)
                    task.updated_at = _now()
                    await session.commit()

    async def _render(self, task_id: int) -> None:
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id)
            if task is None:
                return
            project = await session.get(TranslationProject, task.project_id)
            if project is None:
                return
            project_id = project.id
            public_id = project.public_id
            locale = task.target_locale
            source = self._storage.resolve_private_path(project.source_object_key)
            stale_outputs = await session.scalars(
                select(MediaAsset).where(
                    MediaAsset.task_id == task_id,
                    MediaAsset.asset_type == int(AssetType.OUTPUT_VIDEO),
                )
            )
            stale_rows = list(stale_outputs.all())
            stale_keys = [stale.object_key for stale in stale_rows]
            for stale in stale_rows:
                await session.delete(stale)
            await session.commit()
        for stale_key in stale_keys:
            try:
                self._storage.delete(stale_key)
            except OSError:
                logger.warning("failed to remove stale output %s", stale_key)
        audio_asset = await self._require_asset(
            project_id, task_id, AssetType.DUBBED_AUDIO
        )
        audio = self._storage.resolve_private_path(audio_asset.object_key)
        probe = await asyncio.to_thread(self._ffmpeg.probe, source)
        if probe.width is None or probe.height is None:
            raise MediaCommandError("MEDIA_PROBE_INVALID", "无法读取视频尺寸")
        mask_rect = await asyncio.to_thread(
            _subtitle_mask_rect, source, probe.duration_ms, probe.width, probe.height
        )
        with TemporaryDirectory(prefix="ai-translation-render-") as directory:
            output = Path(directory) / "translated.mp4"
            await asyncio.to_thread(
                self._ffmpeg.mux,
                source,
                audio,
                output,
                video_width=probe.width,
                video_height=probe.height,
                mask_rect=mask_rect,
                original_volume=0.0,
            )
            object_key = f"projects/{public_id}/{locale}/translated.mp4"
            stored = self._storage.put_file(object_key, output)
            size = stored.stat().st_size
        await self._add_asset(
            project_id,
            task_id,
            AssetType.OUTPUT_VIDEO,
            object_key,
            "video/mp4",
            size,
        )
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id, with_for_update=True)
            if task is None:
                return
            task.status = int(TaskStatus.SUCCEEDED)
            task.stage = int(TaskStage.COMPLETED)
            task.progress_percent = 100
            task.completed_at = _now()
            task.updated_at = _now()
            await self._event(
                session, task.project_id, task.id, "TASK_COMPLETED", task.stage, 100
            )
            await session.commit()
            project_id = task.project_id
        await self._aggregate_project(project_id)

    async def _select_provider(
        self, capability: ProviderCapability, locale: str | None
    ) -> SelectedProvider:
        async with self._sessions() as session:
            result = await session.execute(
                select(ProviderConfig, ProviderVersion)
                .join(
                    ProviderVersion,
                    ProviderVersion.id == ProviderConfig.active_version_id,
                )
                .where(
                    ProviderConfig.status == int(ProviderStatus.ENABLED),
                    ProviderConfig.capability == int(capability),
                )
            )
            rows = [(row[0], row[1]) for row in result]
        return self._selector.select(capability, locale, rows)

    async def _invoke_provider(
        self,
        operation: Callable[[], _ResultT],
        *,
        base_request_id: str,
        project_id: int,
        task_id: int | None,
        capability: ProviderCapability,
        selected: SelectedProvider,
        locale: str | None,
        failure_usage: ProviderUsage,
    ) -> tuple[_ResultT, int, str]:
        retryable = {
            "PROVIDER_TIMEOUT",
            "PROVIDER_RATE_LIMITED",
            "PROVIDER_HTTP_ERROR",
        }
        for retry_index in range(3):
            attempt = await self._next_provider_attempt(base_request_id)
            request_id = f"{base_request_id}:attempt:{attempt}"
            started = time.monotonic()
            try:
                result = await asyncio.to_thread(operation)
            except ProviderRequestError as error:
                duration_ms = round((time.monotonic() - started) * 1000)
                await self._record_failed_usage(
                    project_id=project_id,
                    task_id=task_id,
                    request_id=request_id,
                    capability=capability,
                    selected=selected,
                    locale=locale,
                    usage=failure_usage,
                    duration_ms=duration_ms,
                    error_code=error.code,
                )
                if error.code not in retryable or retry_index == 2:
                    raise
                await asyncio.sleep(2**retry_index)
            else:
                return (
                    result,
                    round((time.monotonic() - started) * 1000),
                    request_id,
                )
        raise ProviderRequestError("PROVIDER_RETRY_EXHAUSTED")

    async def _record_usage(
        self,
        session: AsyncSession,
        *,
        project_id: int,
        task_id: int | None,
        request_id: str,
        capability: ProviderCapability,
        selected: SelectedProvider,
        locale: str | None,
        usage: ProviderUsage,
        duration_ms: int,
    ) -> int:
        existing = await session.scalar(
            select(AiUsageRecord).where(AiUsageRecord.request_id == request_id)
        )
        if existing is not None:
            return existing.cost_microunit
        now = _now()
        price = await session.scalar(
            select(ProviderPrice)
            .where(
                ProviderPrice.provider_version_id == selected.version.id,
                ProviderPrice.capability == int(capability),
                ProviderPrice.model_name == selected.version.model_name,
                ProviderPrice.effective_from <= now,
                or_(
                    ProviderPrice.effective_to.is_(None),
                    ProviderPrice.effective_to > now,
                ),
                or_(
                    ProviderPrice.target_locale == locale,
                    ProviderPrice.target_locale.is_(None),
                ),
            )
            .order_by(
                ProviderPrice.target_locale.is_not(None).desc(),
                ProviderPrice.effective_from.desc(),
            )
            .limit(1)
        )
        input_units = usage.input_units
        if (
            capability
            in {
                ProviderCapability.ASR,
                ProviderCapability.SIMULTANEOUS_INTERPRETATION,
            }
            and input_units == 0
        ):
            input_units = round(usage.audio_seconds * 1000)
        output_units = usage.output_units
        cost = 0
        snapshot: dict[str, object] = {"source": "unconfigured", "currency": "CNY"}
        unit_price = 0
        if price is not None:
            billable = input_units + output_units
            if price.billing_unit in {"milliseconds", "audio_ms"}:
                billable = round(usage.audio_seconds * 1000)
            elif price.billing_unit in {"seconds", "audio_seconds"}:
                billable = math.ceil(usage.audio_seconds)
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
                project_id=project_id,
                task_id=task_id,
                provider_version_id=selected.version.id,
                request_id=request_id,
                capability=int(capability),
                model_name=selected.version.model_name,
                target_locale=locale,
                input_units=input_units,
                output_units=output_units,
                duration_ms=duration_ms,
                status=int(UsageStatus.SUCCEEDED),
                unit_price_microunit=unit_price,
                cost_microunit=cost,
                price_snapshot_json=snapshot,
                error_code=None,
                created_at=now,
            )
        )
        project = await session.get(
            TranslationProject, project_id, with_for_update=True
        )
        if project is not None:
            project.actual_cost_microunit += cost
            project.updated_at = now
        if task_id is not None:
            task = await session.get(TranslationTask, task_id, with_for_update=True)
            if task is not None:
                task.actual_cost_microunit += cost
                task.updated_at = now
        return cost

    async def _successful_usage_exists(self, base_request_id: str) -> bool:
        async with self._sessions() as session:
            return bool(
                await session.scalar(
                    select(AiUsageRecord.id).where(
                        AiUsageRecord.request_id.like(f"{base_request_id}:attempt:%"),
                        AiUsageRecord.status == int(UsageStatus.SUCCEEDED),
                    )
                )
            )

    async def _next_provider_attempt(self, base_request_id: str) -> int:
        async with self._sessions() as session:
            count = await session.scalar(
                select(func.count(AiUsageRecord.id)).where(
                    AiUsageRecord.request_id.like(f"{base_request_id}:attempt:%")
                )
            )
            return int(count or 0) + 1

    async def _record_failed_usage(
        self,
        *,
        project_id: int,
        task_id: int | None,
        request_id: str,
        capability: ProviderCapability,
        selected: SelectedProvider,
        locale: str | None,
        usage: ProviderUsage,
        duration_ms: int,
        error_code: str,
    ) -> None:
        async with self._sessions() as session:
            if await session.scalar(
                select(AiUsageRecord.id).where(AiUsageRecord.request_id == request_id)
            ):
                return
            input_units = usage.input_units
            if (
                capability
                in {
                    ProviderCapability.ASR,
                    ProviderCapability.SIMULTANEOUS_INTERPRETATION,
                }
                and input_units == 0
            ):
                input_units = round(usage.audio_seconds * 1000)
            session.add(
                AiUsageRecord(
                    public_id=str(ULID()),
                    project_id=project_id,
                    task_id=task_id,
                    provider_version_id=selected.version.id,
                    request_id=request_id,
                    capability=int(capability),
                    model_name=selected.version.model_name,
                    target_locale=locale,
                    input_units=input_units,
                    output_units=usage.output_units,
                    duration_ms=duration_ms,
                    status=int(UsageStatus.FAILED),
                    unit_price_microunit=0,
                    cost_microunit=0,
                    price_snapshot_json={
                        "source": "provider-failure",
                        "currency": "CNY",
                    },
                    error_code=error_code,
                    created_at=_now(),
                )
            )
            await session.commit()

    async def _asset(
        self, project_id: int, task_id: int | None, asset_type: AssetType
    ) -> MediaAsset | None:
        async with self._sessions() as session:
            statement = select(MediaAsset).where(
                MediaAsset.project_id == project_id,
                MediaAsset.asset_type == int(asset_type),
            )
            statement = (
                statement.where(MediaAsset.task_id.is_(None))
                if task_id is None
                else statement.where(MediaAsset.task_id == task_id)
            )
            value = await session.scalar(
                statement.order_by(MediaAsset.id.desc()).limit(1)
            )
            return value

    async def _asset_for_task(
        self, task_id: int, asset_type: AssetType
    ) -> MediaAsset | None:
        async with self._sessions() as session:
            value = await session.scalar(
                select(MediaAsset)
                .where(
                    MediaAsset.task_id == task_id,
                    MediaAsset.asset_type == int(asset_type),
                )
                .order_by(MediaAsset.id.desc())
                .limit(1)
            )
            return value

    async def _require_asset(
        self, project_id: int, task_id: int | None, asset_type: AssetType
    ) -> MediaAsset:
        asset = await self._asset(project_id, task_id, asset_type)
        if asset is None:
            raise FileNotFoundError(asset_type.name)
        return asset

    def _new_asset(
        self,
        project_id: int,
        task_id: int | None,
        asset_type: AssetType,
        object_key: str,
        content_type: str,
        size: int,
    ) -> MediaAsset:
        return MediaAsset(
            public_id=str(ULID()),
            project_id=project_id,
            task_id=task_id,
            asset_type=int(asset_type),
            object_key=object_key,
            content_type=content_type,
            sha256=None,
            size_bytes=size,
            duration_ms=None,
            container=Path(object_key).suffix.removeprefix(".") or None,
            video_codec=None,
            audio_codec=None,
            metadata_json=None,
            created_at=_now(),
        )

    async def _add_asset(
        self,
        project_id: int,
        task_id: int | None,
        asset_type: AssetType,
        object_key: str,
        content_type: str,
        size: int,
    ) -> None:
        async with self._sessions() as session:
            session.add(
                self._new_asset(
                    project_id, task_id, asset_type, object_key, content_type, size
                )
            )
            await session.commit()

    async def _advance_project(
        self,
        session: AsyncSession,
        project: TranslationProject,
        status: ProjectStatus,
        progress: int,
        event_type: str,
    ) -> None:
        project.status = int(status)
        project.progress_percent = progress
        project.updated_at = _now()
        project.version += 1
        await self._event(session, project.id, None, event_type, int(status), progress)
        await session.commit()
        await self._cache_progress("project", project.public_id, status.name, progress)

    async def _event(
        self,
        session: AsyncSession,
        project_id: int,
        task_id: int | None,
        event_type: str,
        stage: int | None,
        progress: int | None,
        *,
        error_code: str | None = None,
    ) -> None:
        session.add(
            TaskEvent(
                project_id=project_id,
                task_id=task_id,
                event_type=event_type,
                stage=stage,
                progress_percent=progress,
                error_code=error_code,
                error_message=None,
                details_json=None,
                created_at=_now(),
            )
        )

    async def _cache_progress(
        self, kind: str, public_id: str, status: str, progress: int
    ) -> None:
        key = f"ai-translation:progress:{kind}:{public_id}"
        async with self._redis.pipeline(transaction=True) as pipeline:
            pipeline.hset(key, "status", status)
            pipeline.hset(key, "progress", str(progress))
            pipeline.expire(key, 604800)
            await pipeline.execute()

    async def _cancel_project_if_requested(self, project_id: int) -> bool:
        async with self._sessions() as session:
            project = await session.get(
                TranslationProject, project_id, with_for_update=True
            )
            if project is None or project.status != int(ProjectStatus.CANCEL_REQUESTED):
                return False
            now = _now()
            tasks = list(
                await session.scalars(
                    select(TranslationTask)
                    .where(TranslationTask.project_id == project_id)
                    .with_for_update()
                )
            )
            for task in tasks:
                if task.status not in _TASK_TERMINAL:
                    task.status = int(TaskStatus.CANCELLED)
                    task.completed_at = now
                    task.updated_at = now
            project.status = int(ProjectStatus.CANCELLED)
            project.progress_percent = 100
            project.completed_at = now
            project.updated_at = now
            await self._event(
                session,
                project_id,
                None,
                "PROJECT_CANCELLED",
                int(ProjectStatus.CANCELLED),
                100,
            )
            await session.commit()
            return True

    async def _cancel_task_if_requested(self, task_id: int) -> bool:
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id, with_for_update=True)
            if task is None:
                return True
            project = await session.get(TranslationProject, task.project_id)
            if task.status != int(TaskStatus.CANCEL_REQUESTED) and (
                project is None or project.status != int(ProjectStatus.CANCEL_REQUESTED)
            ):
                return False
            task.status = int(TaskStatus.CANCELLED)
            task.completed_at = _now()
            task.updated_at = _now()
            await self._event(
                session,
                task.project_id,
                task.id,
                "TASK_CANCELLED",
                task.stage,
                task.progress_percent,
            )
            await session.commit()
            project_id = task.project_id
        await self._aggregate_project(project_id)
        return True

    async def _fail_project(self, project_id: int, code: str) -> None:
        async with self._sessions() as session:
            project = await session.get(
                TranslationProject, project_id, with_for_update=True
            )
            if project is None:
                return
            now = _now()
            project.status = int(ProjectStatus.FAILED)
            project.completed_at = now
            project.updated_at = now
            tasks = list(
                await session.scalars(
                    select(TranslationTask)
                    .where(TranslationTask.project_id == project_id)
                    .with_for_update()
                )
            )
            for task in tasks:
                if task.status not in _TASK_TERMINAL:
                    task.status = int(TaskStatus.FAILED)
                    task.error_code = code
                    task.error_message = "源视频处理失败，请联系管理员查看任务日志"
                    task.completed_at = now
                    task.updated_at = now
            await self._event(
                session,
                project_id,
                None,
                "PROJECT_FAILED",
                project.status,
                project.progress_percent,
                error_code=code,
            )
            await session.commit()

    async def _fail_task(
        self, task_id: int, code: str, message: str | None = None
    ) -> None:
        async with self._sessions() as session:
            task = await session.get(TranslationTask, task_id, with_for_update=True)
            if task is None:
                return
            task.status = int(TaskStatus.FAILED)
            task.error_code = code
            task.error_message = (
                message[:500]
                if message
                else "翻译处理失败，可重试或联系管理员查看日志"
            )
            task.completed_at = _now()
            task.updated_at = _now()
            await self._event(
                session,
                task.project_id,
                task.id,
                "TASK_FAILED",
                task.stage,
                task.progress_percent,
                error_code=code,
            )
            await session.commit()
            project_id = task.project_id
        await self._aggregate_project(project_id)

    async def _aggregate_project(self, project_id: int) -> None:
        async with self._sessions() as session:
            project = await session.get(
                TranslationProject, project_id, with_for_update=True
            )
            if project is None:
                return
            tasks = list(
                await session.scalars(
                    select(TranslationTask).where(
                        TranslationTask.project_id == project_id
                    )
                )
            )
            if not tasks:
                return
            terminal = all(task.status in _TASK_TERMINAL for task in tasks)
            project.progress_percent = min(
                100,
                45
                + round(
                    sum(task.progress_percent for task in tasks) / len(tasks) * 0.55
                ),
            )
            if terminal:
                succeeded = sum(
                    task.status == int(TaskStatus.SUCCEEDED) for task in tasks
                )
                if succeeded == len(tasks):
                    project.status = int(ProjectStatus.SUCCEEDED)
                elif succeeded:
                    project.status = int(ProjectStatus.PARTIALLY_SUCCEEDED)
                elif all(task.status == int(TaskStatus.CANCELLED) for task in tasks):
                    project.status = int(ProjectStatus.CANCELLED)
                else:
                    project.status = int(ProjectStatus.FAILED)
                project.progress_percent = 100
                project.completed_at = _now()
            project.updated_at = _now()
            project.version += 1
            await session.commit()
