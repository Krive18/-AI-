from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.errors import AppError
from app.modules.auth.dependencies import (
    AuthContext,
    get_database_session,
    require_account,
    require_csrf,
    require_password_ready,
)
from app.modules.media.storage import LocalObjectStorage
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.videogen.model import VideoGenerationJob, VideoJobStatus
from app.modules.videogen.service import VideoGenService

router = APIRouter(prefix="/videos", tags=["videos"])

_STATUS_LABELS = {
    int(VideoJobStatus.PENDING): "pending",
    int(VideoJobStatus.RUNNING): "running",
    int(VideoJobStatus.SUCCEEDED): "succeeded",
    int(VideoJobStatus.FAILED): "failed",
}

_TIER_LABELS = {1: "standard", 2: "fast", 3: "mini"}


class VideoGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    prompt: str = Field(default="", max_length=2000)
    tier: int = Field(default=2)
    resolution: str = Field(default="720p", max_length=8)
    duration_seconds: int = Field(default=5, alias="durationSeconds")
    reference: str = Field(default="")


def _require_videogen_enabled(context: AuthContext) -> AuthContext:
    if not context.account.videogen_enabled:
        raise AppError(
            "VIDEOGEN_FORBIDDEN",
            "当前账号未开通图生视频权限，请联系管理员开通",
            status_code=403,
        )
    return context


async def _read_access(
    account: Annotated[AuthContext, Depends(require_account)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
) -> AuthContext:
    return _require_videogen_enabled(account)


async def _write_access(
    account: Annotated[AuthContext, Depends(require_account)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
    __: Annotated[AuthContext, Depends(require_csrf)],
) -> AuthContext:
    return _require_videogen_enabled(account)


def _service(
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


def _job(value: VideoGenerationJob, *, with_outputs: bool = True) -> dict[str, object]:
    outputs = (
        [f"/api/v1/videos/{value.public_id}/video"]
        if with_outputs and value.status == int(VideoJobStatus.SUCCEEDED)
        else []
    )
    return {
        "publicId": value.public_id,
        "prompt": value.prompt,
        "size": value.size,
        "durationSeconds": value.duration_seconds,
        "tier": value.tier,
        "tierLabel": _TIER_LABELS.get(value.tier, "unknown"),
        "hasReference": bool(value.reference_object_key),
        "status": value.status,
        "statusLabel": _STATUS_LABELS.get(value.status, "unknown"),
        "outputs": outputs,
        "errorCode": value.error_code,
        "errorMessage": value.error_message,
        "createdAt": value.created_at.isoformat(),
        "finishedAt": value.finished_at.isoformat() if value.finished_at else None,
    }


@router.post("")
async def create_job(
    payload: VideoGenerateRequest,
    service: Annotated[VideoGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    job = await service.create(
        context.account.id,
        payload.prompt,
        payload.tier,
        payload.resolution,
        payload.duration_seconds,
        payload.reference,
    )
    return {"job": _job(job, with_outputs=False)}


@router.get("")
async def list_jobs(
    service: Annotated[VideoGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    jobs = await service.list_jobs(context.account.id, limit=limit, offset=offset)
    return {"items": [_job(job) for job in jobs]}


@router.get("/{public_id}")
async def job_detail(
    public_id: str,
    service: Annotated[VideoGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> dict[str, object]:
    job = await service.require(context.account.id, public_id)
    return {"job": _job(job)}


def _sniff_image_type(path: Path) -> tuple[str, str]:
    head = path.open("rb").read(16)
    if head[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "application/octet-stream", "bin"


@router.get("/{public_id}/video")
async def download_video(
    public_id: str,
    service: Annotated[VideoGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> FileResponse:
    job = await service.require(context.account.id, public_id)
    path = service.video_path(job)
    return FileResponse(
        path,
        filename=f"{public_id}.mp4",
        media_type="video/mp4",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{public_id}/reference")
async def download_reference(
    public_id: str,
    service: Annotated[VideoGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> FileResponse:
    job = await service.require(context.account.id, public_id)
    path = service.reference_path(job)
    media_type, extension = _sniff_image_type(path)
    return FileResponse(
        path,
        filename=f"{public_id}-reference.{extension}",
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )
