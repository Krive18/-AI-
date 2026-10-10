from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import RowMapping, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.core.logging import request_id_context
from app.modules.account.model import UserAccount
from app.modules.audit.model import AuditLog
from app.modules.auth.dependencies import (
    AuthContext,
    get_database_session,
    require_admin,
    require_csrf,
    require_password_ready,
)
from app.modules.cost.model import AiUsageRecord
from app.modules.imagegen.model import ImageGenerationJob, ImageJobStatus
from app.modules.imagegen.service import ImageGenService
from app.modules.media.model import TaskEvent
from app.modules.media.storage import LocalObjectStorage
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import ProviderConfig, ProviderStatus
from app.modules.translation.model import (
    ProjectStatus,
    TaskStage,
    TaskStatus,
    TranslationProject,
    TranslationTask,
)
from app.modules.videogen.model import VideoGenerationJob, VideoJobStatus
from app.modules.videogen.service import VideoGenService

router = APIRouter(prefix="/admin", tags=["admin"])


async def _access(
    admin: Annotated[AuthContext, Depends(require_admin)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
) -> AuthContext:
    return admin


async def _write_access(
    admin: Annotated[AuthContext, Depends(require_admin)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
    __: Annotated[AuthContext, Depends(require_csrf)],
) -> AuthContext:
    return admin


def _now() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _task_payload(task: TranslationTask) -> dict[str, object]:
    return {
        "publicId": task.public_id,
        "projectId": task.project_id,
        "language": task.target_locale,
        "status": task.status,
        "stage": task.stage,
        "progressPercent": task.progress_percent,
        "retryCount": task.retry_count,
        "errorCode": task.error_code,
        "errorMessage": task.error_message,
        "createdAt": task.created_at.isoformat(),
        "updatedAt": task.updated_at.isoformat(),
    }


def _audit_task(
    request: Request,
    actor: AuthContext,
    task: TranslationTask,
    action: str,
    before: Mapping[str, object],
    after: Mapping[str, object],
    now: datetime,
) -> AuditLog:
    return AuditLog(
        actor_id=actor.account.id,
        action=action,
        resource_type="translation_task",
        resource_public_id=task.public_id,
        request_id=request_id_context.get() or str(request.state.request_id),
        ip_address=None,
        before_data=dict(before),
        after_data=dict(after),
        created_at=now,
    )


@router.get("/dashboard")
async def dashboard(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
) -> dict[str, object]:
    now = datetime.now(UTC).replace(tzinfo=None)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    projects = int(
        (await session.scalar(select(func.count(TranslationProject.id)))) or 0
    )
    succeeded = int(
        (
            await session.scalar(
                select(func.count(TranslationProject.id)).where(
                    TranslationProject.status.in_(
                        [
                            int(ProjectStatus.SUCCEEDED),
                            int(ProjectStatus.PARTIALLY_SUCCEEDED),
                        ]
                    )
                )
            )
        )
        or 0
    )
    backlog = int(
        (
            await session.scalar(
                select(func.count(TranslationTask.id)).where(
                    TranslationTask.status.in_([1, 2, 3, 4, 7])
                )
            )
        )
        or 0
    )
    minutes = (
        int(
            (
                await session.scalar(
                    select(
                        func.coalesce(
                            func.sum(TranslationProject.source_duration_ms), 0
                        )
                    )
                )
            )
            or 0
        )
        // 60000
    )
    today_cost = int(
        (
            await session.scalar(
                select(func.coalesce(func.sum(AiUsageRecord.cost_microunit), 0)).where(
                    AiUsageRecord.created_at >= day
                )
            )
        )
        or 0
    )
    month_cost = int(
        (
            await session.scalar(
                select(func.coalesce(func.sum(AiUsageRecord.cost_microunit), 0)).where(
                    AiUsageRecord.created_at >= month
                )
            )
        )
        or 0
    )
    enabled = int(
        (
            await session.scalar(
                select(func.count(ProviderConfig.id)).where(
                    ProviderConfig.status == int(ProviderStatus.ENABLED)
                )
            )
        )
        or 0
    )
    return {
        "projectCount": projects,
        "successRate": succeeded / projects if projects else 0,
        "queueBacklog": backlog,
        "videoMinutes": minutes,
        "todayCostMicrounit": today_cost,
        "monthCostMicrounit": month_cost,
        "providerStatus": {"enabled": enabled},
    }


@router.get("/tasks")
async def tasks(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    status: int | None = None,
    language: str | None = None,
) -> dict[str, object]:
    statement = (
        select(
            TranslationTask.id,
            TranslationTask.public_id,
            TranslationTask.project_id,
            TranslationProject.public_id.label("project_public_id"),
            TranslationProject.name.label("project_name"),
            TranslationProject.created_by,
            TranslationProject.translation_mode,
            TranslationTask.target_locale,
            TranslationTask.status,
            TranslationTask.stage,
            TranslationTask.progress_percent,
            TranslationTask.retry_count,
            TranslationTask.error_code,
            TranslationTask.error_message,
            TranslationTask.created_at,
            TranslationTask.updated_at,
        )
        .join(TranslationProject, TranslationProject.id == TranslationTask.project_id)
        .order_by(TranslationTask.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(TranslationTask.id < cursor)
    if status is not None:
        statement = statement.where(TranslationTask.status == status)
    if language is not None:
        statement = statement.where(TranslationTask.target_locale == language)
    rows = list((await session.execute(statement)).mappings())
    items = [
        {
            "publicId": row["public_id"],
            "projectId": row["project_id"],
            "projectPublicId": row["project_public_id"],
            "projectName": row["project_name"],
            "createdBy": row["created_by"],
            "translationMode": row["translation_mode"],
            "language": row["target_locale"],
            "status": row["status"],
            "stage": row["stage"],
            "progressPercent": row["progress_percent"],
            "retryCount": row["retry_count"],
            "errorCode": row["error_code"],
            "errorMessage": row["error_message"],
            "createdAt": row["created_at"].isoformat(),
            "updatedAt": row["updated_at"].isoformat(),
        }
        for row in rows[:limit]
    ]
    return {
        "items": items,
        "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


@router.get("/tasks/{task_id}")
async def task_detail(
    task_id: str,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
) -> dict[str, object]:
    task = (
        await session.execute(
            select(TranslationTask).where(TranslationTask.public_id == task_id)
        )
    ).scalar_one_or_none()
    if task is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在", status_code=404)
    events = (
        await session.execute(
            select(
                TaskEvent.event_type,
                TaskEvent.stage,
                TaskEvent.progress_percent,
                TaskEvent.error_code,
                TaskEvent.error_message,
                TaskEvent.created_at,
            )
            .where(TaskEvent.task_id == task.id)
            .order_by(TaskEvent.id.desc())
        )
    ).mappings()
    return {
        "task": {
            "publicId": task.public_id,
            "projectId": task.project_id,
            "language": task.target_locale,
            "status": task.status,
            "stage": task.stage,
            "progressPercent": task.progress_percent,
            "errorCode": task.error_code,
            "errorMessage": task.error_message,
        },
        "events": [
            {
                "type": event["event_type"],
                "stage": event["stage"],
                "progressPercent": event["progress_percent"],
                "errorCode": event["error_code"],
                "errorMessage": event["error_message"],
                "createdAt": event["created_at"].isoformat(),
            }
            for event in events
        ],
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    actor: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    task = (
        await session.execute(
            select(TranslationTask)
            .where(TranslationTask.public_id == task_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if task is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在", status_code=404)
    if task.status not in (
        int(TaskStatus.QUEUED),
        int(TaskStatus.TRANSLATING),
        int(TaskStatus.SYNTHESIZING),
        int(TaskStatus.RENDERING),
        int(TaskStatus.CANCEL_REQUESTED),
    ):
        raise AppError("TASK_NOT_CANCELLABLE", "当前任务不能取消", status_code=409)
    if task.status != int(TaskStatus.CANCEL_REQUESTED):
        now = _now()
        before = {"status": task.status, "stage": task.stage}
        task.status = int(TaskStatus.CANCEL_REQUESTED)
        task.updated_at = now
        session.add(
            TaskEvent(
                project_id=task.project_id,
                task_id=task.id,
                event_type="TASK_CANCEL_REQUESTED_BY_ADMIN",
                stage=task.stage,
                progress_percent=task.progress_percent,
                error_code=None,
                error_message=None,
                details_json={"actorId": actor.account.id},
                created_at=now,
            )
        )
        session.add(
            _audit_task(
                request,
                actor,
                task,
                "TASK_CANCEL_REQUESTED",
                before,
                {"status": task.status, "stage": task.stage},
                now,
            )
        )
        await session.commit()
    return {"task": _task_payload(task)}


@router.post("/tasks/{task_id}/retry")
async def retry_task(
    task_id: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    actor: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    task = (
        await session.execute(
            select(TranslationTask)
            .where(TranslationTask.public_id == task_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if task is None:
        raise AppError("TASK_NOT_FOUND", "任务不存在", status_code=404)
    if task.status != int(TaskStatus.FAILED):
        raise AppError("TASK_NOT_RETRYABLE", "仅失败任务可以重试", status_code=409)
    project = await session.get(
        TranslationProject, task.project_id, with_for_update=True
    )
    if project is None:
        raise AppError("PROJECT_NOT_FOUND", "项目不存在", status_code=404)
    if project.status == int(ProjectStatus.FAILED) and project.progress_percent < 45:
        raise AppError(
            "PROJECT_RETRY_REQUIRED",
            "源视频阶段失败，请进入项目详情重试整个项目",
            status_code=409,
        )
    now = _now()
    before = {
        "status": task.status,
        "stage": task.stage,
        "retryCount": task.retry_count,
    }
    task.status = int(TaskStatus.QUEUED)
    task.stage = int(TaskStage.QUEUED)
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
    after = {"status": task.status, "stage": task.stage, "retryCount": task.retry_count}
    session.add(
        TaskEvent(
            project_id=project.id,
            task_id=task.id,
            event_type="TASK_MANUAL_RETRY_BY_ADMIN",
            stage=task.stage,
            progress_percent=task.progress_percent,
            error_code=None,
            error_message=None,
            details_json={"actorId": actor.account.id, "retryCount": task.retry_count},
            created_at=now,
        )
    )
    session.add(
        _audit_task(request, actor, task, "TASK_MANUAL_RETRY", before, after, now)
    )
    await session.commit()
    return {"task": _task_payload(task)}


_IMAGE_STATUS_LABELS = {
    int(ImageJobStatus.PENDING): "pending",
    int(ImageJobStatus.RUNNING): "running",
    int(ImageJobStatus.SUCCEEDED): "succeeded",
    int(ImageJobStatus.FAILED): "failed",
}


def _imagegen_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_database_session)]
) -> ImageGenService:
    settings = request.app.state.settings
    root = Path(
        cast(
            str,
            getattr(request.app.state, "local_storage_root", ".ai_translation_private"),
        )
    )
    factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.database_manager.session_factory,
    )
    return ImageGenService(
        session,
        LocalObjectStorage(root),
        ProviderSecretCipher(
            settings.provider_secret_encryption_key.get_secret_value()
        ),
        factory,
    )


def _imagegen_job_payload(row: RowMapping) -> dict[str, object]:
    public_id = cast(str, row["public_id"])
    status = cast(int, row["status"])
    outputs = (
        [
            f"/api/v1/admin/image-generations/{public_id}/images/{index}"
            for index in range(cast(int, row["count"]))
        ]
        if status == int(ImageJobStatus.SUCCEEDED)
        else []
    )
    created_at = cast(datetime, row["created_at"])
    finished_at = cast(datetime | None, row["finished_at"])
    return {
        "publicId": public_id,
        "prompt": row["prompt"],
        "size": row["size"],
        "count": row["count"],
        "referenceCount": row["reference_count"],
        "status": status,
        "statusLabel": _IMAGE_STATUS_LABELS.get(status, "unknown"),
        "outputs": outputs,
        "errorCode": row["error_code"],
        "errorMessage": row["error_message"],
        "createdAt": created_at.isoformat(),
        "finishedAt": finished_at.isoformat() if finished_at else None,
        "accountLoginName": row["login_name"],
        "accountDisplayName": row["display_name"],
    }


@router.get("/image-generations")
async def image_generations(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    rows = list(
        (
            await session.execute(
                select(
                    ImageGenerationJob.public_id,
                    ImageGenerationJob.prompt,
                    ImageGenerationJob.size,
                    ImageGenerationJob.count,
                    ImageGenerationJob.reference_count,
                    ImageGenerationJob.status,
                    ImageGenerationJob.error_code,
                    ImageGenerationJob.error_message,
                    ImageGenerationJob.created_at,
                    ImageGenerationJob.finished_at,
                    UserAccount.login_name,
                    UserAccount.display_name,
                )
                .join(UserAccount, UserAccount.id == ImageGenerationJob.account_id)
                .order_by(ImageGenerationJob.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).mappings()
    )
    return {"items": [_imagegen_job_payload(row) for row in rows]}


def _sniff_image_type(path: Path) -> tuple[str, str]:
    head = path.open("rb").read(16)
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "application/octet-stream", "bin"


@router.get("/image-generations/{public_id}/images/{index}")
async def download_image_generation(
    public_id: str,
    index: int,
    service: Annotated[ImageGenService, Depends(_imagegen_service)],
    _: Annotated[AuthContext, Depends(_access)],
) -> FileResponse:
    job = await service.require_any(public_id)
    path = service.image_path(job, index)
    media_type, extension = _sniff_image_type(path)
    return FileResponse(
        path,
        filename=f"{public_id}-{index + 1}.{extension}",
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )


_VIDEO_STATUS_LABELS = {
    int(VideoJobStatus.PENDING): "pending",
    int(VideoJobStatus.RUNNING): "running",
    int(VideoJobStatus.SUCCEEDED): "succeeded",
    int(VideoJobStatus.FAILED): "failed",
}


def _videogen_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_database_session)]
) -> VideoGenService:
    settings = request.app.state.settings
    root = Path(
        cast(
            str,
            getattr(request.app.state, "local_storage_root", ".ai_translation_private"),
        )
    )
    factory = cast(
        async_sessionmaker[AsyncSession],
        request.app.state.database_manager.session_factory,
    )
    return VideoGenService(
        session,
        LocalObjectStorage(root),
        ProviderSecretCipher(
            settings.provider_secret_encryption_key.get_secret_value()
        ),
        factory,
    )


def _videogen_job_payload(row: RowMapping) -> dict[str, object]:
    public_id = cast(str, row["public_id"])
    status = cast(int, row["status"])
    outputs = (
        [f"/api/v1/admin/video-generations/{public_id}/video"]
        if status == int(VideoJobStatus.SUCCEEDED)
        else []
    )
    created_at = cast(datetime, row["created_at"])
    finished_at = cast(datetime | None, row["finished_at"])
    return {
        "publicId": public_id,
        "prompt": row["prompt"],
        "size": row["size"],
        "durationSeconds": row["duration_seconds"],
        "tier": row["tier"],
        "status": status,
        "statusLabel": _VIDEO_STATUS_LABELS.get(status, "unknown"),
        "outputs": outputs,
        "errorCode": row["error_code"],
        "errorMessage": row["error_message"],
        "createdAt": created_at.isoformat(),
        "finishedAt": finished_at.isoformat() if finished_at else None,
        "accountLoginName": row["login_name"],
        "accountDisplayName": row["display_name"],
    }


@router.get("/video-generations")
async def video_generations(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    rows = list(
        (
            await session.execute(
                select(
                    VideoGenerationJob.public_id,
                    VideoGenerationJob.prompt,
                    VideoGenerationJob.size,
                    VideoGenerationJob.duration_seconds,
                    VideoGenerationJob.tier,
                    VideoGenerationJob.status,
                    VideoGenerationJob.error_code,
                    VideoGenerationJob.error_message,
                    VideoGenerationJob.created_at,
                    VideoGenerationJob.finished_at,
                    UserAccount.login_name,
                    UserAccount.display_name,
                )
                .join(UserAccount, UserAccount.id == VideoGenerationJob.account_id)
                .order_by(VideoGenerationJob.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).mappings()
    )
    return {"items": [_videogen_job_payload(row) for row in rows]}


@router.get("/video-generations/{public_id}/video")
async def download_video_generation(
    public_id: str,
    service: Annotated[VideoGenService, Depends(_videogen_service)],
    _: Annotated[AuthContext, Depends(_access)],
) -> FileResponse:
    job = await service.require_any(public_id)
    path = service.video_path(job)
    return FileResponse(
        path,
        filename=f"{public_id}.mp4",
        media_type="video/mp4",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/video-generations/{public_id}/reference")
async def download_video_generation_reference(
    public_id: str,
    service: Annotated[VideoGenService, Depends(_videogen_service)],
    _: Annotated[AuthContext, Depends(_access)],
) -> FileResponse:
    job = await service.require_any(public_id)
    path = service.reference_path(job)
    media_type, extension = _sniff_image_type(path)
    return FileResponse(
        path,
        filename=f"{public_id}-reference.{extension}",
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )
