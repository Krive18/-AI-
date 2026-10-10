from __future__ import annotations

import ipaddress
import logging
import secrets
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Annotated, Any, cast

from fastapi import Depends, Header, Request
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.logging import request_id_context
from app.modules.account.model import AccountStatus, Role
from app.modules.account.repository import AccountRepository
from app.modules.account.schemas import AccountRecord
from app.modules.audit.model import AuditLog
from app.modules.auth.service import AuthService, RateLimitRedis
from app.modules.auth.sessions import SessionData, SessionRedis, SessionStore

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AuthContext:
    token: str
    session: SessionData
    account: AccountRecord


def _unauthorized() -> AppError:
    return AppError("UNAUTHORIZED", "请先登录", status_code=401)


def resolve_portal(request: Request) -> str:
    settings = request.app.state.settings
    if request.url.path.startswith(f"{settings.api_prefix}/admin"):
        return "admin"
    header = request.headers.get("X-Portal", "")
    if header in ("admin", "operator"):
        return header
    return "operator"


def session_cookie_name_for(settings: Any, portal: str) -> str:
    if portal == "admin":
        return cast(str, settings.admin_session_cookie_name)
    return cast(str, settings.session_cookie_name)


class SqlAuditWriter:
    def __init__(self, session: AsyncSession, request_id: str) -> None:
        self._session = session
        self._request_id = request_id

    async def append(self, **event: object) -> None:
        raw_ip = event.get("ip_address")
        packed_ip: bytes | None = None
        if isinstance(raw_ip, str):
            try:
                packed_ip = ipaddress.ip_address(raw_ip).packed
            except ValueError:
                packed_ip = None
        self._session.add(
            AuditLog(
                actor_id=cast(int | None, event.get("actor_id")),
                action=cast(str, event["action"]),
                resource_type=cast(str, event["resource_type"]),
                resource_public_id=cast(str | None, event.get("resource_public_id")),
                request_id=self._request_id,
                ip_address=packed_ip,
                before_data=cast(dict[str, object] | None, event.get("before_data")),
                after_data=cast(dict[str, object] | None, event.get("after_data")),
                created_at=event["created_at"],
            )
        )
        await self._session.flush()


async def get_database_session(request: Request) -> AsyncIterator[AsyncSession]:
    manager = cast(Any, request.app.state.database_manager)
    async with manager.session_factory() as session:
        yield cast(AsyncSession, session)


def get_redis_client(request: Request) -> Redis:
    manager = cast(Any, request.app.state.redis_manager)
    return cast(Redis, manager.client)


def get_account_repository(
    session: Annotated[AsyncSession, Depends(get_database_session)],
) -> AccountRepository:
    return AccountRepository(session)


def get_session_store(
    request: Request,
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> SessionStore:
    settings = request.app.state.settings
    key_prefix = cast(str, getattr(request.app.state, "auth_key_prefix", ""))
    return SessionStore(
        cast(SessionRedis, redis),
        settings.session_hash_key.get_secret_value(),
        key_prefix=key_prefix,
    )


def get_auth_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_database_session)],
    accounts: Annotated[AccountRepository, Depends(get_account_repository)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> AuthService:
    request_id = request_id_context.get() or request.state.request_id
    key_prefix = cast(str, getattr(request.app.state, "auth_key_prefix", ""))
    return AuthService(
        accounts,
        sessions,
        cast(RateLimitRedis, redis),
        SqlAuditWriter(session, request_id),
        transaction=session,
        key_prefix=key_prefix,
    )


async def require_account(
    request: Request,
    accounts: Annotated[AccountRepository, Depends(get_account_repository)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> AuthContext:
    settings = request.app.state.settings
    portal = resolve_portal(request)
    token = request.cookies.get(session_cookie_name_for(settings, portal))
    if not token:
        raise _unauthorized()
    try:
        session = await sessions.get_and_touch(token)
    except (OSError, RedisError):
        raise AppError(
            "AUTHENTICATION_UNAVAILABLE",
            "认证服务暂时不可用",
            status_code=503,
        ) from None
    if session is None:
        raise _unauthorized()
    account = await accounts.get_by_id(session.account_id)
    if (
        account is None
        or account.status is not AccountStatus.ACTIVE
        or account.auth_version != session.auth_version
    ):
        try:
            await sessions.revoke(token)
        except (OSError, RedisError):
            _LOGGER.warning("invalid_auth_session_revoke_failed")
        raise _unauthorized()
    return AuthContext(token=token, session=session, account=account)


async def require_csrf(
    context: Annotated[AuthContext, Depends(require_account)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    if csrf_token is None or not secrets.compare_digest(
        csrf_token, context.session.csrf_token
    ):
        raise AppError("CSRF_INVALID", "CSRF 校验失败", status_code=403)
    return context


async def require_admin(
    context: Annotated[AuthContext, Depends(require_account)],
) -> AuthContext:
    if context.account.role is not Role.ADMIN:
        raise AppError("FORBIDDEN", "无权访问该资源", status_code=403)
    return context


async def require_password_ready(
    context: Annotated[AuthContext, Depends(require_account)],
) -> AuthContext:
    if context.account.must_change_password:
        raise AppError(
            "PASSWORD_CHANGE_REQUIRED",
            "请先修改临时密码",
            status_code=403,
        )
    return context
