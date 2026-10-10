from __future__ import annotations

import hashlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Protocol

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.core.errors import AppError
from app.core.security import hash_password, normalize_login_name, verify_password
from app.modules.account.model import AccountStatus, Role
from app.modules.account.schemas import AccountRecord
from app.modules.auth.schemas import LoginResult
from app.modules.auth.sessions import SessionData

_LOGIN_LIMIT_TTL_SECONDS = 15 * 60
_MAX_FAILED_ATTEMPTS = 5
_LOGIN_LIMIT_LUA = """
local value = redis.call('INCR', KEYS[1])
local ttl = redis.call('TTL', KEYS[1])
if ttl < 0 or value >= 5 then
    redis.call('EXPIRE', KEYS[1], ARGV[1])
end
return value
"""
_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$Hy9Xa6zkns8ZzCydqoUB1w$"
    "WFb/o9fuXd/Sh5XhpOtRKxjFmrjwCGTpI5qOKcsOQmg"
)
_LOGGER = logging.getLogger(__name__)


class InvalidCredentials(AppError):
    def __init__(self) -> None:
        super().__init__("INVALID_CREDENTIALS", "用户名或密码错误", status_code=401)


class LoginTemporarilyLocked(AppError):
    def __init__(self) -> None:
        super().__init__(
            "LOGIN_TEMPORARILY_LOCKED", "登录尝试过于频繁，请稍后再试", status_code=429
        )


class InvalidCurrentPassword(AppError):
    def __init__(self) -> None:
        super().__init__("INVALID_CURRENT_PASSWORD", "当前密码错误", status_code=400)


class RolePortalMismatch(AppError):
    def __init__(self, portal: str) -> None:
        message = (
            "该账号为运营成员，请从工作台入口登录"
            if portal == "admin"
            else "该账号为管理员，请从管理后台入口登录"
        )
        super().__init__("ROLE_PORTAL_MISMATCH", message, status_code=403)


class AuthenticationInfrastructureError(AppError):
    def __init__(self) -> None:
        super().__init__(
            "AUTHENTICATION_UNAVAILABLE", "认证服务暂时不可用", status_code=503
        )


class AccountRepository(Protocol):
    async def get_by_login_name(self, login_name: str) -> AccountRecord | None: ...

    async def save(
        self, account: AccountRecord, *, expected_version: int
    ) -> AccountRecord: ...


class RateLimitRedis(Protocol):
    async def get(self, key: str) -> str | None: ...

    async def delete(self, key: str) -> object: ...

    async def eval(self, script: str, numkeys: int, *args: str) -> object: ...


class SessionManager(Protocol):
    async def create(
        self, *, account_id: int, auth_version: int
    ) -> tuple[str, SessionData]: ...

    async def revoke(self, token: str) -> None: ...

    async def revoke_account(self, account_id: int) -> None: ...


class AuditWriter(Protocol):
    def append(self, **event: object) -> Awaitable[None]: ...


class TransactionController(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


def _utc_now_milliseconds() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class AuthService:
    """Authentication use cases with an explicit database transaction controller."""

    def __init__(
        self,
        accounts: AccountRepository,
        sessions: SessionManager,
        rate_limits: RateLimitRedis,
        audit: AuditWriter,
        *,
        transaction: TransactionController,
        now: Callable[[], datetime] = _utc_now_milliseconds,
        key_prefix: str = "",
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._rate_limits = rate_limits
        self._audit = audit
        self._transaction = transaction
        self._now = now
        self._key_prefix = key_prefix

    async def login(
        self,
        login_name: str,
        password: str,
        ip_address: str | None,
        portal: str = "operator",
    ) -> LoginResult:
        normalized_login = normalize_login_name(login_name)
        key = self._rate_limit_key(normalized_login)
        failures = await self._rate_limits.get(key)
        if failures is not None and int(failures) >= _MAX_FAILED_ATTEMPTS:
            await self._audit_and_commit_failure(
                action="LOGIN_LOCKED",
                account=None,
                ip_address=ip_address,
            )
            raise LoginTemporarilyLocked()

        account = await self._accounts.get_by_login_name(normalized_login)
        encoded_hash = (
            account.password_hash if account is not None else _DUMMY_PASSWORD_HASH
        )
        password_matches = verify_password(password, encoded_hash)
        if (
            account is None
            or not password_matches
            or account.status is not AccountStatus.ACTIVE
        ):
            await self._record_failed_attempt(key)
            await self._audit_and_commit_failure(
                action="LOGIN_FAILED",
                account=account,
                ip_address=ip_address,
            )
            raise InvalidCredentials()

        if (portal == "admin") != (account.role is Role.ADMIN):
            await self._audit_and_commit_failure(
                action="LOGIN_PORTAL_MISMATCH",
                account=account,
                ip_address=ip_address,
            )
            raise RolePortalMismatch(portal)

        token: str | None = None
        try:
            updated = await self._accounts.save(
                replace(account, last_login_at=self._now()),
                expected_version=account.version,
            )
            token, session = await self._sessions.create(
                account_id=updated.id,
                auth_version=updated.auth_version,
            )
            await self._append_audit(
                action="LOGIN_SUCCEEDED",
                actor_id=updated.id,
                resource_public_id=updated.public_id,
                ip_address=ip_address,
                after_data={"authVersion": updated.auth_version},
            )
            await self._transaction.commit()
        except (OSError, RedisError, SQLAlchemyError) as error:
            await self._rollback_and_revoke(token)
            if isinstance(error, AppError):
                raise
            raise AuthenticationInfrastructureError() from None
        assert token is not None
        try:
            await self._rate_limits.delete(key)
        except (OSError, RedisError):
            _LOGGER.warning("auth_rate_limit_clear_failed")
        return LoginResult(account=updated, session_token=token, session=session)

    async def change_password(
        self,
        account: AccountRecord,
        *,
        current_password: str,
        new_password: str,
        ip_address: str | None,
    ) -> AccountRecord:
        if not verify_password(current_password, account.password_hash):
            raise InvalidCurrentPassword()
        try:
            changed = await self._accounts.save(
                replace(
                    account,
                    password_hash=hash_password(new_password),
                    must_change_password=False,
                    password_changed_at=self._now(),
                    auth_version=account.auth_version + 1,
                ),
                expected_version=account.version,
            )
            await self._append_audit(
                action="PASSWORD_CHANGED",
                actor_id=changed.id,
                resource_public_id=changed.public_id,
                ip_address=ip_address,
                before_data={"authVersion": account.auth_version},
                after_data={"authVersion": changed.auth_version},
            )
            await self._transaction.commit()
        except (OSError, RedisError, SQLAlchemyError) as error:
            await self._rollback()
            if isinstance(error, AppError):
                raise
            raise AuthenticationInfrastructureError() from None
        try:
            await self._sessions.revoke_account(changed.id)
        except (OSError, RedisError):
            _LOGGER.warning("auth_session_revoke_failed")
        return changed

    async def logout(
        self,
        session_token: str,
        *,
        account_id: int,
        ip_address: str | None,
    ) -> None:
        try:
            await self._sessions.revoke(session_token)
            await self._append_audit(
                action="LOGOUT",
                actor_id=account_id,
                resource_public_id=None,
                ip_address=ip_address,
            )
            await self._transaction.commit()
        except (OSError, RedisError, SQLAlchemyError) as error:
            await self._rollback()
            if isinstance(error, AppError):
                raise
            raise AuthenticationInfrastructureError() from None

    async def _record_failed_attempt(self, key: str) -> None:
        await self._rate_limits.eval(
            _LOGIN_LIMIT_LUA,
            1,
            key,
            str(_LOGIN_LIMIT_TTL_SECONDS),
        )

    def _rate_limit_key(self, normalized_login: str) -> str:
        digest = hashlib.sha256(normalized_login.encode()).hexdigest()
        return f"{self._key_prefix}login-limit:{digest}"

    async def _append_audit(
        self,
        *,
        action: str,
        actor_id: int | None,
        resource_public_id: str | None,
        ip_address: str | None,
        before_data: dict[str, object] | None = None,
        after_data: dict[str, object] | None = None,
    ) -> None:
        await self._audit.append(
            action=action,
            actor_id=actor_id,
            resource_type="account",
            resource_public_id=resource_public_id,
            ip_address=ip_address,
            before_data=before_data,
            after_data=after_data,
            created_at=self._now(),
        )

    async def _audit_and_commit_failure(
        self,
        *,
        action: str,
        account: AccountRecord | None,
        ip_address: str | None,
    ) -> None:
        try:
            await self._append_audit(
                action=action,
                actor_id=account.id if account is not None else None,
                resource_public_id=account.public_id if account is not None else None,
                ip_address=ip_address,
            )
            await self._transaction.commit()
        except (OSError, SQLAlchemyError):
            await self._rollback()
            raise AuthenticationInfrastructureError() from None

    async def _rollback_and_revoke(self, token: str | None) -> None:
        await self._rollback()
        if token is not None:
            try:
                await self._sessions.revoke(token)
            except (OSError, RedisError):
                _LOGGER.warning("auth_session_compensation_failed")

    async def _rollback(self) -> None:
        try:
            await self._transaction.rollback()
        except (OSError, SQLAlchemyError):
            _LOGGER.warning("auth_transaction_rollback_failed")
