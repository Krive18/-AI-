from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.auth.dependencies import (
    AuthContext,
    get_database_session,
    require_account,
    require_csrf,
    require_password_ready,
)
from app.modules.imagegen.model import ImageGenerationJob, ImageJobStatus
from app.modules.imagegen.service import ImageGenService
from app.modules.media.storage import LocalObjectStorage
from app.modules.provider.crypto import ProviderSecretCipher

router = APIRouter(prefix="/image-generations", tags=["image-generations"])

_STATUS_LABELS = {
    int(ImageJobStatus.PENDING): "pending",
    int(ImageJobStatus.RUNNING): "running",
    int(ImageJobStatus.SUCCEEDED): "succeeded",
    int(ImageJobStatus.FAILED): "failed",
}


class ImageGenerateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    prompt: str = Field(default="", max_length=2000)
    size: str = Field(default="2K", max_length=8)
    count: int = Field(default=1)
    references: list[str] = Field(default_factory=list)


async def _read_access(
    account: Annotated[AuthContext, Depends(require_account)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
) -> AuthContext:
    return account


async def _write_access(
    account: Annotated[AuthContext, Depends(require_account)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
    __: Annotated[AuthContext, Depends(require_csrf)],
) -> AuthContext:
    return account


def _service(
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


def _job(value: ImageGenerationJob, *, with_outputs: bool = True) -> dict[str, object]:
    outputs = (
        [
            f"/api/v1/image-generations/{value.public_id}/images/{index}"
            for index in range(value.count)
        ]
        if with_outputs and value.status == int(ImageJobStatus.SUCCEEDED)
        else []
    )
    return {
        "publicId": value.public_id,
        "prompt": value.prompt,
        "size": value.size,
        "count": value.count,
        "referenceCount": value.reference_count,
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
    payload: ImageGenerateRequest,
    service: Annotated[ImageGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    job = await service.create(
        context.account.id,
        payload.prompt,
        payload.size,
        payload.count,
        payload.references,
    )
    return {"job": _job(job, with_outputs=False)}


@router.get("")
async def list_jobs(
    service: Annotated[ImageGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    jobs = await service.list_jobs(context.account.id, limit=limit, offset=offset)
    return {"items": [_job(job) for job in jobs]}


@router.get("/{public_id}")
async def job_detail(
    public_id: str,
    service: Annotated[ImageGenService, Depends(_service)],
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


@router.get("/{public_id}/images/{index}")
async def download_image(
    public_id: str,
    index: int,
    service: Annotated[ImageGenService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> FileResponse:
    job = await service.require(context.account.id, public_id)
    path = service.image_path(job, index)
    media_type, extension = _sniff_image_type(path)
    return FileResponse(
        path,
        filename=f"{public_id}-{index + 1}.{extension}",
        media_type=media_type,
        headers={"Cache-Control": "private, no-store"},
    )
