from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.dependencies import (
    AuthContext,
    get_database_session,
    require_admin,
    require_password_ready,
)
from app.modules.cost.model import AiUsageRecord
from app.modules.translation.model import TranslationProject

router = APIRouter(prefix="/admin/costs", tags=["admin-costs"])


async def _access(
    admin: Annotated[AuthContext, Depends(require_admin)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
) -> AuthContext:
    return admin


def _filtered(
    statement: Any,
    start: datetime | None,
    end: datetime | None,
    account_id: int | None,
    project_id: int | None,
    language: str | None,
    capability: int | None,
    provider_id: int | None,
    model: str | None,
) -> Any:
    query = statement
    if start is not None:
        query = query.where(AiUsageRecord.created_at >= start)
    if end is not None:
        query = query.where(AiUsageRecord.created_at < end)
    if account_id is not None:
        query = query.join(
            TranslationProject, TranslationProject.id == AiUsageRecord.project_id
        ).where(TranslationProject.created_by == account_id)
    if project_id is not None:
        query = query.where(AiUsageRecord.project_id == project_id)
    if language is not None:
        query = query.where(AiUsageRecord.target_locale == language)
    if capability is not None:
        query = query.where(AiUsageRecord.capability == capability)
    if provider_id is not None:
        query = query.where(AiUsageRecord.provider_version_id == provider_id)
    if model is not None:
        query = query.where(AiUsageRecord.model_name == model)
    return query


@router.get("/summary")
async def summary(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    group_by: str = Query(default="capability", alias="groupBy"),
    start: datetime | None = None,
    end: datetime | None = None,
    account_id: int | None = Query(default=None, alias="accountId"),
    project_id: int | None = Query(default=None, alias="projectId"),
    language: str | None = None,
    capability: int | None = None,
    provider_id: int | None = Query(default=None, alias="providerId"),
    model: str | None = None,
) -> dict[str, object]:
    dimensions = {
        "capability": AiUsageRecord.capability,
        "provider": AiUsageRecord.provider_version_id,
        "model": AiUsageRecord.model_name,
        "language": AiUsageRecord.target_locale,
        "project": AiUsageRecord.project_id,
    }
    dimension = dimensions.get(group_by)
    if dimension is None:
        group_by, dimension = "capability", AiUsageRecord.capability
    statement = (
        select(
            dimension.label("group_value"),
            func.count(AiUsageRecord.id).label("request_count"),
            func.coalesce(func.sum(AiUsageRecord.cost_microunit), 0).label(
                "cost_microunit"
            ),
            func.coalesce(func.sum(AiUsageRecord.input_units), 0).label("input_units"),
            func.coalesce(func.sum(AiUsageRecord.output_units), 0).label(
                "output_units"
            ),
        )
        .group_by(dimension)
        .order_by(func.sum(AiUsageRecord.cost_microunit).desc())
    )
    result = await session.execute(
        _filtered(
            statement,
            start,
            end,
            account_id,
            project_id,
            language,
            capability,
            provider_id,
            model,
        )
    )
    return {
        "groupBy": group_by,
        "items": [
            {
                "group": row.group_value,
                "requestCount": row.request_count,
                "costMicrounit": int(row.cost_microunit),
                "inputUnits": int(row.input_units),
                "outputUnits": int(row.output_units),
            }
            for row in result
        ],
    }


@router.get("/records")
async def records(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_access)],
    response: Response,
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    format: str = "json",
    start: datetime | None = None,
    end: datetime | None = None,
    account_id: int | None = Query(default=None, alias="accountId"),
    project_id: int | None = Query(default=None, alias="projectId"),
    language: str | None = None,
    capability: int | None = None,
    provider_id: int | None = Query(default=None, alias="providerId"),
    model: str | None = None,
) -> object:
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
            AiUsageRecord.input_units,
            AiUsageRecord.output_units,
            AiUsageRecord.duration_ms,
            AiUsageRecord.status,
            AiUsageRecord.unit_price_microunit,
            AiUsageRecord.cost_microunit,
            AiUsageRecord.error_code,
            AiUsageRecord.created_at,
        )
        .order_by(AiUsageRecord.id.desc())
        .limit(limit + 1)
    )
    if cursor is not None:
        statement = statement.where(AiUsageRecord.id < cursor)
    rows = list(
        (
            await session.execute(
                _filtered(
                    statement,
                    start,
                    end,
                    account_id,
                    project_id,
                    language,
                    capability,
                    provider_id,
                    model,
                )
            )
        ).mappings()
    )
    items = [
        {
            "publicId": row["public_id"],
            "projectId": row["project_id"],
            "taskId": row["task_id"],
            "providerVersionId": row["provider_version_id"],
            "capability": row["capability"],
            "model": row["model_name"],
            "language": row["target_locale"],
            "inputUnits": row["input_units"],
            "outputUnits": row["output_units"],
            "durationMs": row["duration_ms"],
            "status": row["status"],
            "unitPriceMicrounit": row["unit_price_microunit"],
            "costMicrounit": row["cost_microunit"],
            "errorCode": row["error_code"],
            "createdAt": row["created_at"].isoformat(),
        }
        for row in rows[:limit]
    ]
    if format.lower() == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=list(items[0]) if items else ["publicId", "costMicrounit"],
        )
        writer.writeheader()
        writer.writerows(items)
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=ai-usage-records.csv"
            },
        )
    response.headers["Cache-Control"] = "no-store"
    return {
        "items": items,
        "nextCursor": rows[limit - 1]["id"] if len(rows) > limit else None,
    }
