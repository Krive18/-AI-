from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.modules.media.model import MediaAsset, TaskEvent
from app.modules.project.schemas import TranslationMode
from app.modules.translation.model import (
    ProjectStatus,
    TaskStatus,
    TranslationProject,
    TranslationTask,
)


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        account_id: int,
        name: str,
        filename: str,
        content_type: str,
        object_key: str,
        size: int,
        sha256: str,
        locales: list[str],
        translation_mode: TranslationMode,
        voice_id: str | None = None,
    ) -> TranslationProject:
        now = _now()
        project = TranslationProject(
            public_id=str(ULID()),
            created_by=account_id,
            name=name,
            source_filename=filename,
            source_content_type=content_type,
            source_object_key=object_key,
            source_sha256=sha256,
            source_size_bytes=size,
            source_duration_ms=None,
            source_container=None,
            source_video_codec=None,
            source_audio_codec=None,
            translation_mode=translation_mode.value,
            status=int(ProjectStatus.VALIDATING),
            progress_percent=0,
            estimated_cost_microunit=0,
            actual_cost_microunit=0,
            cancel_requested_at=None,
            completed_at=None,
            version=1,
            created_at=now,
            updated_at=now,
        )
        self.session.add(project)
        await self.session.flush()
        self.session.add(
            MediaAsset(
                public_id=str(ULID()),
                project_id=project.id,
                task_id=None,
                asset_type=1,
                object_key=object_key,
                content_type=content_type,
                sha256=sha256,
                size_bytes=size,
                duration_ms=None,
                container=None,
                video_codec=None,
                audio_codec=None,
                metadata_json=None,
                created_at=now,
            )
        )
        for locale in locales:
            self.session.add(
                TranslationTask(
                    public_id=str(ULID()),
                    project_id=project.id,
                    target_locale=locale,
                    voice_id=voice_id,
                    status=int(TaskStatus.QUEUED),
                    stage=1,
                    progress_percent=0,
                    retry_count=0,
                    max_retries=3,
                    error_code=None,
                    error_message=None,
                    estimated_cost_microunit=0,
                    actual_cost_microunit=0,
                    completed_at=None,
                    version=1,
                    created_at=now,
                    updated_at=now,
                )
            )
        self.session.add(
            TaskEvent(
                project_id=project.id,
                task_id=None,
                event_type="PROJECT_CREATED",
                stage=1,
                progress_percent=0,
                error_code=None,
                error_message=None,
                details_json={
                    "targetLocales": locales,
                    "translationMode": translation_mode.value,
                },
                created_at=now,
            )
        )
        await self.session.flush()
        return project

    async def list_page(
        self,
        account_id: int,
        admin: bool,
        cursor: int | None,
        limit: int,
        keyword: str | None = None,
        statuses: list[int] | None = None,
    ) -> list[TranslationProject]:
        statement = (
            select(TranslationProject)
            .order_by(TranslationProject.id.desc())
            .limit(limit + 1)
        )
        if not admin:
            statement = statement.where(TranslationProject.created_by == account_id)
        if cursor is not None:
            statement = statement.where(TranslationProject.id < cursor)
        if keyword:
            pattern = f"%{_escape_like(keyword)}%"
            statement = statement.where(
                or_(
                    TranslationProject.name.like(pattern, escape="\\"),
                    TranslationProject.source_filename.like(pattern, escape="\\"),
                )
            )
        if statuses:
            statement = statement.where(TranslationProject.status.in_(statuses))
        return list((await self.session.execute(statement)).scalars())

    async def get(
        self, public_id: str, account_id: int, admin: bool, lock: bool = False
    ) -> TranslationProject | None:
        statement = select(TranslationProject).where(
            TranslationProject.public_id == public_id
        )
        if not admin:
            statement = statement.where(TranslationProject.created_by == account_id)
        if lock:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalar_one_or_none()

    async def tasks(self, project_id: int) -> list[TranslationTask]:
        return [
            value
            for value in (
                await self.session.execute(
                    select(TranslationTask)
                    .where(TranslationTask.project_id == project_id)
                    .order_by(TranslationTask.id)
                )
            ).scalars()
        ]

    async def get_task(self, public_id: str, project_id: int) -> TranslationTask | None:
        return (
            await self.session.execute(
                select(TranslationTask)
                .where(
                    TranslationTask.public_id == public_id,
                    TranslationTask.project_id == project_id,
                )
                .with_for_update()
            )
        ).scalar_one_or_none()
