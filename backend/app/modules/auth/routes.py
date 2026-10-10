from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.modules.account.schemas import AccountRecord
from app.modules.auth.dependencies import (
    AuthContext,
    get_auth_service,
    require_account,
    require_csrf,
    resolve_portal,
    session_cookie_name_for,
)
from app.modules.auth.service import AuthService


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    login_name: str = Field(alias="loginName", min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)
    portal: Literal["operator", "admin"] = "operator"


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_password: str = Field(
        alias="currentPassword", min_length=1, max_length=1024
    )
    new_password: str = Field(alias="newPassword", min_length=6, max_length=1024)


def _public_account(account: AccountRecord) -> dict[str, object]:
    return {
        "publicId": account.public_id,
        "loginName": account.login_name,
        "displayName": account.display_name,
        "role": int(account.role),
        "status": int(account.status),
        "mustChangePassword": account.must_change_password,
        "videogenEnabled": account.videogen_enabled,
    }


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, object]:
    client_ip = request.client.host if request.client is not None else None
    result = await service.login(
        payload.login_name, payload.password, client_ip, payload.portal
    )
    settings = request.app.state.settings
    response.set_cookie(
        key=session_cookie_name_for(settings, payload.portal),
        value=result.session_token,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {
        "account": _public_account(result.account),
        "csrfToken": result.session.csrf_token,
    }


@router.get("/me")
async def me(
    context: Annotated[AuthContext, Depends(require_account)],
    response: Response,
) -> dict[str, object]:
    response.headers["Cache-Control"] = "no-store"
    return {
        "account": _public_account(context.account),
        "csrfToken": context.session.csrf_token,
    }


def _expire_session_cookie(response: Response, request: Request) -> None:
    settings = request.app.state.settings
    response.delete_cookie(
        key=session_cookie_name_for(settings, resolve_portal(request)),
        path="/",
        secure=settings.session_cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    client_ip = request.client.host if request.client is not None else None
    await service.logout(
        context.token,
        account_id=context.account.id,
        ip_address=client_ip,
    )
    _expire_session_cookie(response, request)
    response.headers["Cache-Control"] = "no-store"


@router.post("/password", status_code=204)
async def change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    context: Annotated[AuthContext, Depends(require_csrf)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> None:
    client_ip = request.client.host if request.client is not None else None
    await service.change_password(
        context.account,
        current_password=payload.current_password,
        new_password=payload.new_password,
        ip_address=client_ip,
    )
    _expire_session_cookie(response, request)
    response.headers["Cache-Control"] = "no-store"
