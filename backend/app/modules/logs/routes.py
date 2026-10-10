from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.model import AuditLog
from app.modules.auth.dependencies import (
    AuthContext,
    get_database_session,
    require_admin,
    require_password_ready,
)
from app.modules.cost.model import AiUsageRecord
from app.modules.media.model import TaskEvent

router = APIRouter(prefix="/admin/logs", tags=["admin-logs"])


async def _access(
    admin: Annotated[AuthContext, Depends(require_admin)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
) -> AuthContext:
    return admin


def _page(
    rows: list[Any], limit: int, mapper: Callable[[Any], dict[str, object]]
) -> dict[str, object]:
    mappings = rows[:limit]
    return {
        "items": [mapper(row) for row in mappings],
        "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }


@router.get("/audit")
async def audit_log(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    actor_id: int | None = Query(default=None, alias="actorId"),
    action: str | None = None,
) -> dict[str, object]:
    statement = (
        select(
            AuditLog.id,
            AuditLog.actor_id,
            AuditLog.action,
            AuditLog.resource_type,
            AuditLog.resource_public_id,
            AuditLog.request_id,
            AuditLog.before_data,
            AuditLog.after_data,
            AuditLog.created_at,
        )
        .order_by(AuditLog.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(AuditLog.id < cursor)
    if actor_id is not None:
        statement = statement.where(AuditLog.actor_id == actor_id)
    if action is not None:
        statement = statement.where(AuditLog.action == action)
    rows = list((await session.execute(statement)).mappings())
    return _page(
        rows,
        limit,
        lambda row: {
            "actorId": row["actor_id"],
            "action": row["action"],
            "resourceType": row["resource_type"],
            "resourceId": row["resource_public_id"],
            "requestId": row["request_id"],
            "before": row["before_data"],
            "after": row["after_data"],
            "createdAt": row["created_at"].isoformat(),
        },
    )


@router.get("/tasks")
async def task_log(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    project_id: int | None = Query(default=None, alias="projectId"),
    task_id: int | None = Query(default=None, alias="taskId"),
) -> dict[str, object]:
    statement = (
        select(
            TaskEvent.id,
            TaskEvent.project_id,
            TaskEvent.task_id,
            TaskEvent.event_type,
            TaskEvent.stage,
            TaskEvent.progress_percent,
            TaskEvent.error_code,
            TaskEvent.error_message,
            TaskEvent.created_at,
        )
        .order_by(TaskEvent.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(TaskEvent.id < cursor)
    if project_id is not None:
        statement = statement.where(TaskEvent.project_id == project_id)
    if task_id is not None:
        statement = statement.where(TaskEvent.task_id == task_id)
    rows = list((await session.execute(statement)).mappings())
    return _page(
        rows,
        limit,
        lambda row: {
            "projectId": row["project_id"],
            "taskId": row["task_id"],
            "type": row["event_type"],
            "stage": row["stage"],
            "progressPercent": row["progress_percent"],
            "errorCode": row["error_code"],
            "errorMessage": row["error_message"],
            "createdAt": row["created_at"].isoformat(),
        },
    )


@router.get("/provider-calls")
async def provider_calls(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    provider_id: int | None = Query(default=None, alias="providerId"),
    model: str | None = None,
) -> dict[str, object]:
    statement = (
        select(
            AiUsageRecord.id,
            AiUsageRecord.public_id,
            AiUsageRecord.project_id,
            AiUsageRecord.task_id,
            AiUsageRecord.provider_version_id,
            AiUsageRecord.capability,
            AiUsageRecord.model_name,
            AiUsageRecord.target_locale,
            AiUsageRecord.status,
            AiUsageRecord.duration_ms,
            AiUsageRecord.cost_microunit,
            AiUsageRecord.error_code,
            AiUsageRecord.created_at,
        )
        .order_by(AiUsageRecord.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(AiUsageRecord.id < cursor)
    if provider_id is not None:
        statement = statement.where(AiUsageRecord.provider_version_id == provider_id)
    if model is not None:
        statement = statement.where(AiUsageRecord.model_name == model)
    rows = list((await session.execute(statement)).mappings())
    return _page(
        rows,
        limit,
        lambda row: {
            "publicId": row["public_id"],
            "projectId": row["project_id"],
            "taskId": row["task_id"],
            "providerVersionId": row["provider_version_id"],
            "capability": row["capability"],
            "model": row["model_name"],
            "language": row["target_locale"],
            "status": row["status"],
            "durationMs": row["duration_ms"],
            "costMicrounit": row["cost_microunit"],
            "errorCode": row["error_code"],
            "createdAt": row["created_at"].isoformat(),
        },
    )
