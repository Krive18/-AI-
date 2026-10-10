from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import (
    AuthContext,
    get_database_session,
    require_account,
    require_csrf,
    require_password_ready,
)
from app.modules.project.schemas import (
    MAX_CHUNK_BYTES,
    YOUDAO_SUPPORTED_LOCALES,
    TaskSubtitles,
    TranslationMode,
)
from app.modules.project.service import ProjectService
from app.modules.project.storage import LocalPrivateStorage
from app.modules.translation.model import TranslationProject, TranslationTask

router = APIRouter(prefix="/projects", tags=["projects"])


class UploadStartRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(alias="contentType", min_length=1, max_length=128)
    total_bytes: int = Field(alias="totalBytes", gt=0)


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = Field(min_length=1, max_length=128)
    upload_token: str = Field(alias="uploadToken", min_length=16, max_length=256)
    target_locales: list[str] = Field(alias="targetLocales", min_length=1, max_length=8)
    translation_mode: TranslationMode = Field(
        default=TranslationMode.PROFESSIONAL, alias="translationMode"
    )
    voice_id: str | None = Field(default=None, alias="voiceId", max_length=64)

    @model_validator(mode="after")
    def validate_mode_locales(self) -> ProjectCreateRequest:
        if self.translation_mode is TranslationMode.YOUDAO and not set(
            self.target_locales
        ).issubset(YOUDAO_SUPPORTED_LOCALES):
            raise ValueError("智能翻译暂不支持所选目标语言")
        return self


def _service(
    request: Request, session: Annotated[AsyncSession, Depends(get_database_session)]
) -> ProjectService:
    root = Path(
        cast(
            str,
            getattr(request.app.state, "local_storage_root", ".ai_translation_private"),
        )
    )
    return ProjectService(session, LocalPrivateStorage(root))


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


@router.post("/uploads")
async def start_upload(
    payload: UploadStartRequest,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    upload = service.start_upload(
        context.account, payload.filename, payload.content_type, payload.total_bytes
    )
    return {
        "uploadToken": upload.token,
        "objectKey": upload.object_key,
        "totalBytes": upload.total_bytes,
    }


@router.put("/uploads/{upload_token}/chunks")
async def upload_chunk(
    upload_token: str,
    file: Annotated[UploadFile, File()],
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
    offset: int = Query(ge=0),
) -> dict[str, int]:
    content = await file.read(MAX_CHUNK_BYTES + 1)
    # appending chunks is blocking disk IO, so keep it off the event loop.
    received = await asyncio.to_thread(
        service.upload_chunk, context.account, upload_token, offset, content
    )
    return {"receivedBytes": received}


@router.post("/uploads/{upload_token}/complete")
async def complete_upload(
    upload_token: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    upload = service.complete_upload(context.account, upload_token)
    return {"objectKey": upload.object_key, "totalBytes": upload.total_bytes}


@router.post("")
async def create_project(
    payload: ProjectCreateRequest,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key")],
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    project = await service.create_project(
        context.account,
        idempotency_key,
        payload.upload_token,
        payload.name,
        payload.target_locales,
        payload.translation_mode,
        payload.voice_id,
    )
    return {"project": _project(project)}


@router.get("/translation-options")
async def translation_options(
    service: Annotated[ProjectService, Depends(_service)],
    _: Annotated[AuthContext, Depends(_read_access)],
) -> dict[str, object]:
    return await service.translation_options()


@router.get("")
async def list_projects(
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    keyword: str | None = Query(default=None, max_length=100),
    state: str | None = Query(default=None, pattern="^(processing|succeeded|failed)$"),
) -> dict[str, object]:
    rows = await service.list_page(
        context.account.id,
        context.account.role == 9,
        cursor,
        limit,
        keyword=keyword or None,
        state=state,
    )
    return {
        "items": [_project(row) for row in rows[:limit]],
        "nextCursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.get("/{project_id}")
async def project_detail(
    project_id: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> dict[str, object]:
    project = await service._require(context.account, project_id)
    tasks = await service._repo.tasks(project.id)
    return {"project": _project(project), "tasks": [_task(task) for task in tasks]}


@router.post("/{project_id}/cancel")
async def cancel_project(
    project_id: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    return {"project": _project(await service.cancel(context.account, project_id))}


@router.post("/{project_id}/retry")
async def retry_project(
    project_id: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    return {
        "project": _project(await service.retry_project(context.account, project_id))
    }


@router.post("/{project_id}/tasks/{task_id}/retry")
async def retry_task(
    project_id: str,
    task_id: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    return {"task": _task(await service.retry(context.account, project_id, task_id))}


@router.get("/{project_id}/tasks/{task_id}/download/{asset_kind}")
async def download_output(
    project_id: str,
    task_id: str,
    asset_kind: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> FileResponse:
    path = await service.download(context.account, project_id, task_id, asset_kind)
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.get("/{project_id}/tasks/{task_id}/preview")
async def preview_output(
    project_id: str,
    task_id: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> FileResponse:
    path = await service.download(context.account, project_id, task_id, "video")
    return FileResponse(
        path,
        media_type="video/mp4",
        content_disposition_type="inline",
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{project_id}/tasks/{task_id}/subtitles")
async def task_subtitles(
    project_id: str,
    task_id: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> TaskSubtitles:
    return await service.get_task_subtitles(context.account, project_id, task_id)


@router.get("/{project_id}/tasks/{task_id}/preview-subtitles")
async def preview_subtitles(
    project_id: str,
    task_id: str,
    service: Annotated[ProjectService, Depends(_service)],
    context: Annotated[AuthContext, Depends(_read_access)],
) -> PlainTextResponse:
    path = await service.download(context.account, project_id, task_id, "subtitle")
    return PlainTextResponse(
        _srt_to_vtt(path.read_bytes()),
        media_type="text/vtt; charset=utf-8",
        headers={"Cache-Control": "private, no-store"},
    )


def _srt_to_vtt(payload: bytes) -> str:
    text = payload.decode("utf-8-sig")
    lines: list[str] = ["WEBVTT", ""]
    for line in text.splitlines():
        if line.strip().isdigit():
            continue
        if "-->" in line:
            line = line.replace(",", ".")
        lines.append(line)
    return "\n".join(lines)


def _project(value: TranslationProject) -> dict[str, object]:
    return {
        "publicId": value.public_id,
        "name": value.name,
        "translationMode": value.translation_mode,
        "status": value.status,
        "progressPercent": value.progress_percent,
        "sourceFilename": value.source_filename,
        "sourceSizeBytes": value.source_size_bytes,
        "estimatedCostMicrounit": value.estimated_cost_microunit,
        "actualCostMicrounit": value.actual_cost_microunit,
        "createdAt": value.created_at.isoformat(),
    }


def _task(value: TranslationTask) -> dict[str, object]:
    return {
        "publicId": value.public_id,
        "language": value.target_locale,
        "status": value.status,
        "stage": value.stage,
        "progressPercent": value.progress_percent,
        "retryCount": value.retry_count,
        "errorCode": value.error_code,
        "errorMessage": value.error_message,
        "voiceId": value.voice_id,
    }
