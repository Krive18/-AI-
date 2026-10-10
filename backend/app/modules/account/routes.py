from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import request_id_context
from app.modules.account.model import AccountStatus, Role
from app.modules.account.repository import AccountRepository
from app.modules.account.schemas import AccountRecord
from app.modules.account.service import AccountManagementService
from app.modules.auth.dependencies import (
    AuthContext,
    get_account_repository,
    get_database_session,
    get_session_store,
    require_admin,
    require_csrf,
    require_password_ready,
)
from app.modules.auth.sessions import SessionStore


class AccountCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    login_name: str = Field(alias="loginName", min_length=1, max_length=64)
    display_name: str = Field(alias="displayName", min_length=1, max_length=64)
    role: Role = Role.OPERATOR
    status: AccountStatus = AccountStatus.ACTIVE


class AccountUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int = Field(ge=1)
    display_name: str | None = Field(
        default=None, alias="displayName", min_length=1, max_length=64
    )
    role: Role | None = None
    status: AccountStatus | None = None


class AccountVersionRequest(BaseModel):
    version: int = Field(ge=1)


class VideogenPermissionRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    version: int = Field(ge=1)
    enabled: bool


def _public_account(account: AccountRecord) -> dict[str, object]:
    return {
        "publicId": account.public_id,
        "loginName": account.login_name,
        "displayName": account.display_name,
        "role": int(account.role),
        "status": int(account.status),
        "mustChangePassword": account.must_change_password,
        "videogenEnabled": account.videogen_enabled,
        "authVersion": account.auth_version,
        "version": account.version,
        "createdAt": account.created_at.isoformat(),
        "updatedAt": account.updated_at.isoformat(),
    }


def get_account_management_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    accounts: Annotated[AccountRepository, Depends(get_account_repository)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> AccountManagementService:
    request_id = request_id_context.get() or cast(str, request.state.request_id)
    return AccountManagementService(
        accounts,
        sessions,
        session,
        request_id=request_id,
    )


router = APIRouter(prefix="/admin/accounts", tags=["admin-accounts"])


async def _require_mutation_access(
    admin: Annotated[AuthContext, Depends(require_admin)],
    _: Annotated[AuthContext, Depends(require_csrf)],
    __: Annotated[AuthContext, Depends(require_password_ready)],
) -> AuthContext:
    return admin


async def _require_read_access(
    admin: Annotated[AuthContext, Depends(require_admin)],
    _: Annotated[AuthContext, Depends(require_password_ready)],
) -> AuthContext:
    return admin


@router.get("")
async def list_accounts(
    response: Response,
    service: Annotated[
        AccountManagementService, Depends(get_account_management_service)
    ],
    _: Annotated[AuthContext, Depends(_require_read_access)],
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, object]:
    page = await service.list_accounts(cursor=cursor, limit=limit)
    response.headers["Cache-Control"] = "no-store"
    return {
        "items": [_public_account(account) for account in page.items],
        "nextCursor": page.next_cursor,
    }


@router.post("")
async def create_account(
    payload: AccountCreateRequest,
    request: Request,
    response: Response,
    service: Annotated[
        AccountManagementService, Depends(get_account_management_service)
    ],
    actor: Annotated[AuthContext, Depends(_require_mutation_access)],
) -> dict[str, object]:
    ip_address = request.client.host if request.client is not None else None
    account, temporary_password = await service.create_account(
        actor=actor.account,
        login_name=payload.login_name,
        display_name=payload.display_name,
        role=payload.role,
        status=payload.status,
        ip_address=ip_address,
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "account": _public_account(account),
        "temporaryPassword": temporary_password,
    }


@router.patch("/{account_id}")
async def update_account(
    account_id: str,
    payload: AccountUpdateRequest,
    request: Request,
    service: Annotated[
        AccountManagementService, Depends(get_account_management_service)
    ],
    actor: Annotated[AuthContext, Depends(_require_mutation_access)],
) -> dict[str, object]:
    ip_address = request.client.host if request.client is not None else None
    account = await service.update_account(
        actor=actor.account,
        public_id=account_id,
        expected_version=payload.version,
        display_name=payload.display_name,
        role=payload.role,
        status=payload.status,
        ip_address=ip_address,
    )
    return {"account": _public_account(account)}


@router.post("/{account_id}/videogen-permission")
async def set_videogen_permission(
    account_id: str,
    payload: VideogenPermissionRequest,
    request: Request,
    service: Annotated[
        AccountManagementService, Depends(get_account_management_service)
    ],
    actor: Annotated[AuthContext, Depends(_require_mutation_access)],
) -> dict[str, object]:
    ip_address = request.client.host if request.client is not None else None
    account = await service.set_videogen_permission(
        actor=actor.account,
        public_id=account_id,
        expected_version=payload.version,
        enabled=payload.enabled,
        ip_address=ip_address,
    )
    return {"account": _public_account(account)}


@router.post("/{account_id}/reset-password")
async def reset_password(
    account_id: str,
    payload: AccountVersionRequest,
    request: Request,
    response: Response,
    service: Annotated[
        AccountManagementService, Depends(get_account_management_service)
    ],
    actor: Annotated[AuthContext, Depends(_require_mutation_access)],
) -> dict[str, object]:
    ip_address = request.client.host if request.client is not None else None
    account, temporary_password = await service.reset_password(
        actor=actor.account,
        public_id=account_id,
        expected_version=payload.version,
        ip_address=ip_address,
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "account": _public_account(account),
        "temporaryPassword": temporary_password,
    }


@router.post("/{account_id}/sessions/revoke")
async def revoke_account_sessions(
    account_id: str,
    payload: AccountVersionRequest,
    request: Request,
    service: Annotated[
        AccountManagementService, Depends(get_account_management_service)
    ],
    actor: Annotated[AuthContext, Depends(_require_mutation_access)],
) -> dict[str, object]:
    ip_address = request.client.host if request.client is not None else None
    account = await service.revoke_account_sessions(
        actor=actor.account,
        public_id=account_id,
        expected_version=payload.version,
        ip_address=ip_address,
    )
    return {"account": _public_account(account)}
