from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.account.model import Role
from app.modules.account.schemas import AccountRecord
from app.modules.media.model import SourceSegment, SubtitleSegment, TaskEvent
from app.modules.project.repository import ProjectRepository, _now
from app.modules.project.schemas import (
    ALLOWED_SUFFIXES,
    MAX_CHUNK_BYTES,
    MAX_UPLOAD_BYTES,
    SUPPORTED_LOCALES,
    YOUDAO_SUPPORTED_LOCALES,
    TaskSubtitles,
    TranslationMode,
    UploadSession,
)
from app.modules.project.storage import LocalPrivateStorage
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.translation.model import (
    ProjectStatus,
    TaskStatus,
    TranslationProject,
    TranslationTask,
)
from app.modules.translation.subtitle_text import clean_subtitle_text


def _format_subtitle_timestamp(milliseconds: int) -> str:
    total_seconds, remainder_ms = divmod(milliseconds, 1000)
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{remainder_ms:03d}"


# UI-facing state buckets for the project list filter, keyed by the `state`
# query value accepted by GET /projects. Terminal outcomes live under
# "succeeded" (7, 8) and "failed" (9, 11); every other ProjectStatus is still
# in flight and therefore belongs to "processing".
PROJECT_STATE_STATUSES: dict[str, tuple[ProjectStatus, ...]] = {
    "processing": (
        ProjectStatus.DRAFT,
        ProjectStatus.UPLOADING,
        ProjectStatus.VALIDATING,
        ProjectStatus.EXTRACTING_AUDIO,
        ProjectStatus.RECOGNIZING,
        ProjectStatus.PROCESSING,
        ProjectStatus.CANCEL_REQUESTED,
    ),
    "succeeded": (ProjectStatus.SUCCEEDED, ProjectStatus.PARTIALLY_SUCCEEDED),
    "failed": (ProjectStatus.FAILED, ProjectStatus.CANCELLED),
}


class ProjectService:
    def __init__(self, session: AsyncSession, storage: LocalPrivateStorage) -> None:
        self._session, self._storage, self._repo = (
            session,
            storage,
            ProjectRepository(session),
        )

    async def list_page(
        self,
        account_id: int,
        admin: bool,
        cursor: int | None,
        limit: int,
        keyword: str | None = None,
        state: str | None = None,
    ) -> list[TranslationProject]:
        statuses = PROJECT_STATE_STATUSES.get(state) if state else None
        cleaned = keyword.strip() if keyword else None
        return await self._repo.list_page(
            account_id,
            admin,
            cursor,
            limit,
            keyword=cleaned or None,
            statuses=[int(status) for status in statuses] if statuses else None,
        )

    async def translation_options(self) -> dict[str, object]:
        asr_locales = await self._available_locales(ProviderCapability.ASR)
        translation_locales = await self._available_locales(
            ProviderCapability.TRANSLATION
        )
        tts_locales = await self._available_locales(ProviderCapability.TTS)
        professional_locales = asr_locales & translation_locales & tts_locales
        youdao_locales = await self._available_locales(
            ProviderCapability.SIMULTANEOUS_INTERPRETATION,
            scope=YOUDAO_SUPPORTED_LOCALES,
        )
        subtitle_ocr_locales = await self._available_locales(
            ProviderCapability.SUBTITLE_OCR
        )
        subtitle_locales = translation_locales & tts_locales
        return {
            "modes": {
                "professional": {
                    "available": bool(professional_locales),
                    "supportedLocales": sorted(professional_locales),
                },
                "youdao": {
                    "available": bool(youdao_locales),
                    "supportedLocales": sorted(youdao_locales),
                },
                "subtitle": {
                    "available": bool(subtitle_ocr_locales & subtitle_locales),
                    "supportedLocales": sorted(subtitle_locales),
                },
            }
        }

    async def _available_locales(
        self,
        capability: ProviderCapability,
        *,
        scope: frozenset[str] = SUPPORTED_LOCALES,
    ) -> set[str]:
        statement = (
            select(ProviderConfig)
            .join(
                ProviderVersion,
                ProviderVersion.id == ProviderConfig.active_version_id,
            )
            .where(
                ProviderConfig.capability == int(capability),
                ProviderConfig.status == int(ProviderStatus.ENABLED),
                ProviderVersion.status == int(ProviderStatus.ENABLED),
            )
        )
        configs = list((await self._session.execute(statement)).scalars())
        available: set[str] = set()
        for config in configs:
            locales = config.supported_locales_json
            available.update(scope if not locales else scope.intersection(locales))
        return available

    def start_upload(
        self, account: AccountRecord, filename: str, content_type: str, total_bytes: int
    ) -> UploadSession:
        suffix = Path(filename).suffix.lower()
        if (
            suffix not in ALLOWED_SUFFIXES
            or total_bytes <= 0
            or total_bytes > MAX_UPLOAD_BYTES
        ):
            raise AppError(
                "UPLOAD_INVALID", "文件类型或大小不符合要求", status_code=422
            )
        return self._storage.create_upload(
            account.id, filename, content_type, total_bytes
        )

    def upload_chunk(
        self, account: AccountRecord, token: str, offset: int, content: bytes
    ) -> int:
        if not content or len(content) > MAX_CHUNK_BYTES:
            raise AppError("UPLOAD_CHUNK_INVALID", "上传分片大小无效", status_code=422)
        try:
            return self._storage.append_chunk(token, account.id, offset, content)
        except ValueError:
            raise AppError("UPLOAD_INVALID", "上传分片无效", status_code=422) from None

    def complete_upload(self, account: AccountRecord, token: str) -> UploadSession:
        try:
            return self._storage.complete_upload(token, account.id)
        except ValueError:
            raise AppError(
                "UPLOAD_INCOMPLETE", "上传尚未完成", status_code=409
            ) from None

    async def create_project(
        self,
        account: AccountRecord,
        idempotency_key: str,
        upload_token: str,
        name: str,
        locales: list[str],
        translation_mode: TranslationMode = TranslationMode.PROFESSIONAL,
        voice_id: str | None = None,
    ) -> TranslationProject:
        if (
            not idempotency_key
            or len(idempotency_key) > 128
            or not locales
            or len(set(locales)) != len(locales)
            or not set(locales).issubset(SUPPORTED_LOCALES)
        ):
            raise AppError("PROJECT_INVALID", "项目参数无效", status_code=422)
        if voice_id is not None and (
            not voice_id.strip() or len(voice_id) > 64
        ):
            raise AppError("VOICE_INVALID", "音色参数无效", status_code=422)
        existing = self._storage.idempotency_get(account.id, idempotency_key)
        if existing:
            project = await self._repo.get(existing, account.id, False)
            if project is not None:
                return project
        if translation_mode is TranslationMode.YOUDAO:
            available_locales = await self._available_locales(
                ProviderCapability.SIMULTANEOUS_INTERPRETATION,
                scope=YOUDAO_SUPPORTED_LOCALES,
            )
            unavailable_message = "智能翻译服务尚未配置或不支持所选语言"
        elif translation_mode is TranslationMode.SUBTITLE_OCR:
            subtitle_ocr_locales = await self._available_locales(
                ProviderCapability.SUBTITLE_OCR
            )
            translation_locales = await self._available_locales(
                ProviderCapability.TRANSLATION
            )
            tts_locales = await self._available_locales(ProviderCapability.TTS)
            available_locales = subtitle_ocr_locales & translation_locales & tts_locales
            unavailable_message = "字幕翻译供应商尚未配置或不支持所选语言"
        else:
            asr_locales = await self._available_locales(ProviderCapability.ASR)
            translation_locales = await self._available_locales(
                ProviderCapability.TRANSLATION
            )
            tts_locales = await self._available_locales(ProviderCapability.TTS)
            available_locales = asr_locales & translation_locales & tts_locales
            unavailable_message = "专业精译供应商尚未配置或不支持所选语言"
        if not set(locales).issubset(available_locales):
            raise AppError(
                "TRANSLATION_MODE_UNAVAILABLE",
                unavailable_message,
                status_code=409,
            )
        try:
            upload = self._storage.get_upload(upload_token, account.id)
            # completed uploads remove the token; creating a project requires a final object.
            # hashing multi-GB sources is blocking IO, so keep it off the event loop.
            size, digest = await asyncio.to_thread(
                self._storage.object_size_and_hash, upload.object_key
            )
        except (ValueError, FileNotFoundError):
            raise AppError(
                "UPLOAD_NOT_READY", "请先完成上传", status_code=409
            ) from None
        try:
            project = await self._repo.create(
                account.id,
                name,
                upload.filename,
                upload.content_type,
                upload.object_key,
                size,
                digest,
                locales,
                translation_mode,
                voice_id.strip() if voice_id else None,
            )
            await self._session.commit()
            self._storage.idempotency_put(
                account.id, idempotency_key, project.public_id
            )
            return project
        except SQLAlchemyError:
            await self._session.rollback()
            raise AppError(
                "PROJECT_UNAVAILABLE", "项目服务暂时不可用", status_code=503
            ) from None

    async def cancel(
        self, account: AccountRecord, project_id: str
    ) -> TranslationProject:
        project = await self._require(account, project_id, lock=True)
        if project.status not in (
            int(ProjectStatus.SUCCEEDED),
            int(ProjectStatus.PARTIALLY_SUCCEEDED),
            int(ProjectStatus.FAILED),
            int(ProjectStatus.CANCELLED),
        ):
            project.status = int(ProjectStatus.CANCEL_REQUESTED)
            project.cancel_requested_at = _now()
            project.updated_at = _now()
            await self._session.commit()
        return project

    async def retry(
        self, account: AccountRecord, project_id: str, task_id: str
    ) -> TranslationTask:
        project = await self._require(account, project_id, lock=True)
        if (
            project.status == int(ProjectStatus.FAILED)
            and project.progress_percent < 45
        ):
            raise AppError(
                "PROJECT_RETRY_REQUIRED",
                "源视频阶段失败，请重试整个项目",
                status_code=409,
            )
        task = await self._repo.get_task(task_id, project.id)
        if task is None:
            raise AppError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        if task.status != int(TaskStatus.FAILED):
            raise AppError("TASK_NOT_RETRYABLE", "仅失败任务可以重试", status_code=409)
        if task.retry_count >= task.max_retries:
            raise AppError(
                "TASK_RETRY_LIMIT", "该任务已达到最大重试次数", status_code=409
            )
        now = _now()
        task.status = int(TaskStatus.QUEUED)
        task.stage = 1
        task.progress_percent = 0
        task.error_code = None
        task.error_message = None
        task.completed_at = None
        task.retry_count += 1
        task.updated_at = now
        project.status = int(ProjectStatus.PROCESSING)
        project.progress_percent = min(project.progress_percent, 99)
        project.completed_at = None
        project.updated_at = now
        project.version += 1
        self._session.add(
            TaskEvent(
                project_id=project.id,
                task_id=task.id,
                event_type="TASK_MANUAL_RETRY",
                stage=task.stage,
                progress_percent=task.progress_percent,
                error_code=None,
                error_message=None,
                details_json={"retryCount": task.retry_count},
                created_at=now,
            )
        )
        await self._session.commit()
        return task

    async def retry_project(
        self, account: AccountRecord, project_id: str
    ) -> TranslationProject:
        project = await self._require(account, project_id, lock=True)
        if project.status not in (
            int(ProjectStatus.FAILED),
            int(ProjectStatus.PARTIALLY_SUCCEEDED),
        ):
            raise AppError(
                "PROJECT_NOT_RETRYABLE",
                "仅失败或部分成功项目可以重试",
                status_code=409,
            )
        now = _now()
        tasks = await self._repo.tasks(project.id)
        retried = 0
        limited = 0
        for task in tasks:
            if task.status != int(TaskStatus.FAILED):
                continue
            if task.retry_count >= task.max_retries:
                limited += 1
                continue
            task.status = int(TaskStatus.QUEUED)
            task.stage = 1
            task.progress_percent = 0
            task.error_code = None
            task.error_message = None
            task.completed_at = None
            task.retry_count += 1
            task.updated_at = now
            retried += 1
        if retried == 0:
            if limited > 0:
                raise AppError(
                    "PROJECT_RETRY_LIMIT",
                    "所有失败任务均已达到最大重试次数",
                    status_code=400,
                )
            raise AppError(
                "PROJECT_NOT_RETRYABLE",
                "项目没有可重试的失败任务",
                status_code=409,
            )
        project.status = int(ProjectStatus.VALIDATING)
        project.progress_percent = 0
        project.cancel_requested_at = None
        project.completed_at = None
        project.updated_at = now
        project.version += 1
        self._session.add(
            TaskEvent(
                project_id=project.id,
                task_id=None,
                event_type="PROJECT_MANUAL_RETRY",
                stage=int(ProjectStatus.VALIDATING),
                progress_percent=0,
                error_code=None,
                error_message=None,
                details_json={"retriedTasks": retried},
                created_at=now,
            )
        )
        await self._session.commit()
        return project

    async def get_task_subtitles(
        self, account: AccountRecord, project_id: str, task_id: str
    ) -> TaskSubtitles:
        project = await self._require(account, project_id)
        task = await self._repo.get_task(task_id, project.id)
        if task is None:
            raise AppError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        rows = list(
            (
                await self._session.execute(
                    select(SourceSegment, SubtitleSegment)
                    .join(
                        SubtitleSegment,
                        SubtitleSegment.source_segment_id == SourceSegment.id,
                    )
                    .where(SubtitleSegment.task_id == task.id)
                    .order_by(SubtitleSegment.sequence_no)
                )
            ).all()
        )
        # Both sides are cleaned for consistent display: ASR source text can
        # carry the same stray whitespace as LLM-translated target text, while
        # stored DB values stay untouched. Each line carries its segment
        # timestamp so the boxes stay aligned with the video timeline.
        timestamps = [
            f"[{_format_subtitle_timestamp(source.start_ms)} --> {_format_subtitle_timestamp(source.end_ms)}]"
            for source, _ in rows
        ]
        return TaskSubtitles(
            source_text="\n".join(
                f"{timestamp} {clean_subtitle_text(source.source_text)}"
                for timestamp, (source, _) in zip(timestamps, rows, strict=True)
            ),
            target_text="\n".join(
                f"{timestamp} {clean_subtitle_text(target.translated_text)}"
                for timestamp, (_, target) in zip(timestamps, rows, strict=True)
            ),
            segment_count=len(rows),
        )

    async def download(
        self, account: AccountRecord, project_id: str, task_id: str, asset_kind: str
    ) -> Path:
        project = await self._require(account, project_id)
        task = await self._repo.get_task(task_id, project.id)
        if task is None or task.status != int(TaskStatus.SUCCEEDED):
            raise AppError("OUTPUT_NOT_READY", "输出文件尚未生成", status_code=409)
        from app.modules.media.model import MediaAsset

        asset_type = (
            4 if asset_kind == "video" else 5 if asset_kind == "subtitle" else 0
        )
        asset = (
            await self._session.execute(
                __import__("sqlalchemy")
                .select(MediaAsset)
                .where(
                    MediaAsset.task_id == task.id, MediaAsset.asset_type == asset_type
                )
                .order_by(MediaAsset.id.desc())
            )
        ).scalar_one_or_none()
        if asset is None:
            raise AppError("OUTPUT_NOT_FOUND", "输出文件不存在", status_code=404)
        try:
            return self._storage.download_path(asset.object_key)
        except FileNotFoundError:
            raise AppError(
                "OUTPUT_EXPIRED", "输出文件不可用", status_code=410
            ) from None

    async def _require(
        self, account: AccountRecord, public_id: str, lock: bool = False
    ) -> TranslationProject:
        project = await self._repo.get(
            public_id, account.id, account.role is Role.ADMIN, lock
        )
        if project is None:
            raise AppError("PROJECT_NOT_FOUND", "项目不存在", status_code=404)
        return project
