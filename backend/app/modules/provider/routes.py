from __future__ import annotations

from datetime import datetime
from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_context
from app.modules.auth.dependencies import (
    AuthContext,
    get_database_session,
    require_admin,
    require_csrf,
    require_password_ready,
)
from app.modules.provider.crypto import ProviderSecretCipher
from app.modules.provider.model import (
    ProviderCapability,
    ProviderConfig,
    ProviderStatus,
    ProviderVersion,
)
from app.modules.provider.repository import ProviderRepository
from app.modules.provider.service import ProviderService


class ProviderCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    provider_code: str = Field(alias="providerCode", min_length=1, max_length=64)
    display_name: str = Field(alias="displayName", min_length=1, max_length=128)
    capability: ProviderCapability
    priority: int = Field(default=100, ge=0, le=255)
    supported_locales: list[str] | None = Field(default=None, alias="supportedLocales")
    model_name: str = Field(alias="modelName", min_length=1, max_length=128)
    endpoint_url: str = Field(alias="endpointUrl", min_length=1, max_length=512)
    timeout_ms: int = Field(alias="timeoutMs", ge=1, le=600000)
    options: dict[str, object] | None = None
    api_key: str = Field(alias="apiKey", min_length=1, max_length=2048)


class ProviderUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    display_name: str | None = Field(
        default=None, alias="displayName", min_length=1, max_length=128
    )
    priority: int | None = Field(default=None, ge=0, le=255)
    status: ProviderStatus | None = None
    supported_locales: list[str] | None = Field(default=None, alias="supportedLocales")
    model_name: str | None = Field(
        default=None, alias="modelName", min_length=1, max_length=128
    )
    endpoint_url: str | None = Field(
        default=None, alias="endpointUrl", min_length=1, max_length=512
    )
    timeout_ms: int | None = Field(default=None, alias="timeoutMs", ge=1, le=600000)
    options: dict[str, object] | None = None
    api_key: str | None = Field(
        default=None, alias="apiKey", min_length=1, max_length=2048
    )
    expected_updated_at: datetime = Field(alias="expectedUpdatedAt")


class ActivateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    version_id: str = Field(alias="versionId", min_length=26, max_length=26)
    expected_updated_at: datetime = Field(alias="expectedUpdatedAt")


class PriceCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    version_id: str = Field(alias="versionId", min_length=26, max_length=26)
    capability: ProviderCapability
    locale: str | None = None
    billing_unit: str = Field(alias="billingUnit", min_length=1, max_length=32)
    unit_size: int = Field(alias="unitSize", gt=0)
    unit_price_microunit: int = Field(alias="unitPriceMicrounit", ge=0)
    currency: str = Field(min_length=3, max_length=3)
    effective_from: datetime = Field(alias="effectiveFrom")
    effective_to: datetime | None = Field(default=None, alias="effectiveTo")


async def _read_access(
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


def _service(
    request: Request, session: Annotated[AsyncSession, Depends(get_database_session)]
) -> ProviderService:
    settings = request.app.state.settings
    return ProviderService(
        ProviderRepository(session),
        session,
        ProviderSecretCipher(
            settings.provider_secret_encryption_key.get_secret_value()
        ),
        request_id_context.get() or cast(str, request.state.request_id),
    )


async def _active_version(
    session: AsyncSession, config: ProviderConfig
) -> ProviderVersion | None:
    return (
        await session.get(ProviderVersion, config.active_version_id)
        if config.active_version_id
        else None
    )


async def _public(config: ProviderConfig, session: AsyncSession) -> dict[str, object]:
    version = await _active_version(session, config)
    return {
        "publicId": config.public_id,
        "providerCode": config.provider_code,
        "displayName": config.display_name,
        "capability": config.capability,
        "status": config.status,
        "priority": config.priority,
        "supportedLocales": config.supported_locales_json,
        "activeVersionId": version.public_id if version else None,
        "modelName": version.model_name if version else None,
        "endpointUrl": version.endpoint_url if version else None,
        "hasKey": bool(version and version.encrypted_secret),
        "maskedKey": "****" if version else None,
        "createdAt": config.created_at.isoformat(),
        "updatedAt": config.updated_at.isoformat(),
    }


router = APIRouter(prefix="/admin/providers", tags=["admin-providers"])


@router.get("")
async def list_providers(
    response: Response,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_read_access)],
) -> dict[str, object]:
    configs = await ProviderRepository(session).list_configs()
    response.headers["Cache-Control"] = "no-store"
    return {"items": [await _public(config, session) for config in configs]}


@router.post("")
async def create_provider(
    payload: ProviderCreateRequest,
    response: Response,
    service: Annotated[ProviderService, Depends(_service)],
    actor: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    config = await service.create(
        actor_id=actor.account.id,
        provider_code=payload.provider_code,
        display_name=payload.display_name,
        capability=int(payload.capability),
        priority=payload.priority,
        locales=payload.supported_locales,
        model_name=payload.model_name,
        endpoint_url=payload.endpoint_url,
        timeout_ms=payload.timeout_ms,
        options=payload.options,
        api_key=payload.api_key,
    )
    response.headers["Cache-Control"] = "no-store"
    return {"provider": await _public(config, service._session)}


@router.get("/prices")
async def list_prices(
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_read_access)],
    provider_id: str | None = None,
    version_id: str | None = Query(default=None, alias="versionId"),
    capability: ProviderCapability | None = None,
    locale: str | None = None,
) -> dict[str, object]:
    repo = ProviderRepository(session)
    version = await repo.get_version(version_id) if version_id else None
    if version_id and version is None:
        return {"items": []}
    prices = await repo.list_prices(
        version.id if version else None, int(capability) if capability else None, locale
    )
    return {
        "items": [
            {
                "publicId": price.public_id,
                "versionId": version_id if version else None,
                "capability": price.capability,
                "modelName": price.model_name,
                "locale": price.target_locale,
                "billingUnit": price.billing_unit,
                "unitSize": price.unit_size,
                "unitPriceMicrounit": price.unit_price_microunit,
                "currency": price.currency,
                "effectiveFrom": price.effective_from.isoformat(),
                "effectiveTo": price.effective_to.isoformat()
                if price.effective_to
                else None,
            }
            for price in prices
        ]
    }


@router.post("/prices")
async def create_price(
    payload: PriceCreateRequest,
    service: Annotated[ProviderService, Depends(_service)],
    actor: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    price = await service.create_price(
        actor_id=actor.account.id,
        version_public_id=payload.version_id,
        capability=int(payload.capability),
        locale=payload.locale,
        billing_unit=payload.billing_unit,
        unit_size=payload.unit_size,
        unit_price=payload.unit_price_microunit,
        currency=payload.currency,
        effective_from=payload.effective_from.replace(tzinfo=None),
        effective_to=payload.effective_to.replace(tzinfo=None)
        if payload.effective_to
        else None,
    )
    return {
        "price": {
            "publicId": price.public_id,
            "unitPriceMicrounit": price.unit_price_microunit,
        }
    }


@router.get("/{provider_id}")
async def provider_detail(
    provider_id: str,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_read_access)],
) -> dict[str, object]:
    config = await ProviderRepository(session).get_config(provider_id)
    if config is None:
        from app.core.errors import AppError

        raise AppError("PROVIDER_NOT_FOUND", "供应商不存在", status_code=404)
    return {"provider": await _public(config, session)}


@router.get("/{provider_id}/versions")
async def provider_versions(
    provider_id: str,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    _: Annotated[AuthContext, Depends(_read_access)],
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    repo = ProviderRepository(session)
    config = await repo.get_config(provider_id)
    if config is None:
        from app.core.errors import AppError

        raise AppError("PROVIDER_NOT_FOUND", "供应商不存在", status_code=404)
    rows = await repo.list_versions(config.id, cursor, limit)
    return {
        "items": [
            {
                "publicId": row.public_id,
                "versionNo": row.version_no,
                "modelName": row.model_name,
                "endpointUrl": row.endpoint_url,
                "timeoutMs": row.timeout_ms,
                "hasKey": bool(row.encrypted_secret),
                "maskedKey": "****",
                "createdAt": row.created_at.isoformat(),
            }
            for row in rows[:limit]
        ],
        "nextCursor": rows[limit - 1].id if len(rows) > limit else None,
    }


@router.patch("/{provider_id}")
async def update_provider(
    provider_id: str,
    payload: ProviderUpdateRequest,
    service: Annotated[ProviderService, Depends(_service)],
    actor: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    result = await service.update(
        actor_id=actor.account.id,
        public_id=provider_id,
        expected_updated_at=payload.expected_updated_at,
        display_name=payload.display_name,
        priority=payload.priority,
        status=payload.status,
        locales=payload.supported_locales,
        model_name=payload.model_name,
        endpoint_url=payload.endpoint_url,
        timeout_ms=payload.timeout_ms,
        options=payload.options,
        api_key=payload.api_key,
    )
    return {
        "provider": await _public(result.config, service._session),
        "newVersionId": result.version.public_id if result.version else None,
    }


@router.post("/{provider_id}/test")
async def test_provider(
    provider_id: str,
    service: Annotated[ProviderService, Depends(_service)],
    actor: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, str]:
    return {
        "result": await service.test(actor_id=actor.account.id, public_id=provider_id)
    }


@router.post("/{provider_id}/activate")
async def activate_provider(
    provider_id: str,
    payload: ActivateRequest,
    service: Annotated[ProviderService, Depends(_service)],
    actor: Annotated[AuthContext, Depends(_write_access)],
) -> dict[str, object]:
    config = await service.activate(
        actor_id=actor.account.id,
        public_id=provider_id,
        version_public_id=payload.version_id,
        expected_updated_at=payload.expected_updated_at,
    )
    return {"provider": await _public(config, service._session)}
