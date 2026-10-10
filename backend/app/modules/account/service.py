from __future__ import annotations

import ipaddress
import logging
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.security import generate_temporary_password, hash_password
from app.modules.account.model import AccountStatus, Role
from app.modules.account.repository import (
    AccountConflictError,
    AccountRepository,
    AccountVersionConflictError,
)
from app.modules.account.schemas import AccountCreate, AccountPage, AccountRecord
from app.modules.audit.model import AuditLog
from app.modules.auth.sessions import SessionStore

_LOGGER = logging.getLogger(__name__)


def _utc_now_milliseconds() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


class AccountManagementService:
    """Administrator-only account lifecycle operations."""

    def __init__(
        self,
        accounts: AccountRepository,
        sessions: SessionStore,
        transaction: AsyncSession,
        *,
        request_id: str,
        now: Callable[[], datetime] = _utc_now_milliseconds,
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._transaction = transaction
        self._request_id = request_id
        self._now = now

    async def list_accounts(self, *, cursor: int | None, limit: int) -> AccountPage:
        return await self._accounts.list_page(cursor=cursor, limit=limit)

    async def create_account(
        self,
        *,
        actor: AccountRecord,
        login_name: str,
        display_name: str,
        role: Role,
        status: AccountStatus,
        ip_address: str | None,
    ) -> tuple[AccountRecord, str]:
        temporary_password = generate_temporary_password()
        try:
            account = await self._accounts.create(
                AccountCreate(
                    login_name=login_name,
                    display_name=display_name,
                    password_hash=hash_password(temporary_password),
                    role=role,
                    status=status,
                    must_change_password=True,
                    created_by=actor.id,
                )
            )
            await self._append_audit(
                action="ACCOUNT_CREATED",
                actor_id=actor.id,
                account=account,
                ip_address=ip_address,
                after_data=self._audit_state(account),
            )
            await self._transaction.commit()
        except AccountConflictError:
            await self._rollback()
            raise AppError(
                "LOGIN_NAME_CONFLICT", "登录名已存在", status_code=409
            ) from None
        except SQLAlchemyError:
            await self._rollback()
            raise AppError(
                "ACCOUNT_MANAGEMENT_UNAVAILABLE",
                "账号服务暂时不可用",
                status_code=503,
            ) from None
        return account, temporary_password

    async def update_account(
        self,
        *,
        actor: AccountRecord,
        public_id: str,
        expected_version: int,
        display_name: str | None,
        role: Role | None,
        status: AccountStatus | None,
        ip_address: str | None,
    ) -> AccountRecord:
        try:
            target = await self._load_for_mutation(public_id, expected_version)
            next_role = target.role if role is None else role
            next_status = target.status if status is None else status
            if actor.id == target.id and next_status is AccountStatus.DISABLED:
                raise AppError(
                    "SELF_DISABLE_FORBIDDEN", "不能停用当前账号", status_code=409
                )
            await self._assert_active_admin_can_change(target, next_role, next_status)
            security_changed = (
                next_role is not target.role or next_status is not target.status
            )
            changed = replace(
                target,
                display_name=target.display_name
                if display_name is None
                else display_name,
                role=next_role,
                status=next_status,
                auth_version=target.auth_version + (1 if security_changed else 0),
            )
            saved = await self._accounts.save(
                changed, expected_version=expected_version
            )
            await self._append_audit(
                action="ACCOUNT_UPDATED",
                actor_id=actor.id,
                account=saved,
                ip_address=ip_address,
                before_data=self._audit_state(target),
                after_data=self._audit_state(saved),
            )
            await self._transaction.commit()
        except AppError:
            await self._rollback()
            raise
        except AccountVersionConflictError:
            await self._rollback()
            raise AppError(
                "ACCOUNT_VERSION_CONFLICT",
                "账号数据已更新，请刷新后重试",
                status_code=409,
            ) from None
        except AccountConflictError:
            await self._rollback()
            raise AppError(
                "LOGIN_NAME_CONFLICT", "登录名已存在", status_code=409
            ) from None
        except SQLAlchemyError:
            await self._rollback()
            raise AppError(
                "ACCOUNT_MANAGEMENT_UNAVAILABLE",
                "账号服务暂时不可用",
                status_code=503,
            ) from None
        if security_changed:
            await self._revoke_sessions_after_commit(saved.id)
        return saved

    async def reset_password(
        self,
        *,
        actor: AccountRecord,
        public_id: str,
        expected_version: int,
        ip_address: str | None,
    ) -> tuple[AccountRecord, str]:
        temporary_password = generate_temporary_password()
        try:
            target = await self._load_for_mutation(public_id, expected_version)
            saved = await self._accounts.save(
                replace(
                    target,
                    password_hash=hash_password(temporary_password),
                    must_change_password=True,
                    password_changed_at=self._now(),
                    auth_version=target.auth_version + 1,
                ),
                expected_version=expected_version,
            )
            await self._append_audit(
                action="ACCOUNT_PASSWORD_RESET",
                actor_id=actor.id,
                account=saved,
                ip_address=ip_address,
                before_data={"authVersion": target.auth_version},
                after_data={
                    "authVersion": saved.auth_version,
                    "mustChangePassword": True,
                },
            )
            await self._transaction.commit()
        except AppError:
            await self._rollback()
            raise
        except AccountVersionConflictError:
            await self._rollback()
            raise AppError(
                "ACCOUNT_VERSION_CONFLICT",
                "账号数据已更新，请刷新后重试",
                status_code=409,
            ) from None
        except (AccountConflictError, SQLAlchemyError):
            await self._rollback()
            raise AppError(
                "ACCOUNT_MANAGEMENT_UNAVAILABLE",
                "账号服务暂时不可用",
                status_code=503,
            ) from None
        await self._revoke_sessions_after_commit(saved.id)
        return saved, temporary_password

    async def set_videogen_permission(
        self,
        *,
        actor: AccountRecord,
        public_id: str,
        expected_version: int,
        enabled: bool,
        ip_address: str | None,
    ) -> AccountRecord:
        try:
            target = await self._load_for_mutation(public_id, expected_version)
            saved = await self._accounts.save(
                replace(target, videogen_enabled=enabled),
                expected_version=expected_version,
            )
            await self._append_audit(
                action="ACCOUNT_VIDEOGEN_PERMISSION_UPDATED",
                actor_id=actor.id,
                account=saved,
                ip_address=ip_address,
                before_data={"videogenEnabled": target.videogen_enabled},
                after_data={"videogenEnabled": saved.videogen_enabled},
            )
            await self._transaction.commit()
        except AppError:
            await self._rollback()
            raise
        except AccountVersionConflictError:
            await self._rollback()
            raise AppError(
                "ACCOUNT_VERSION_CONFLICT",
                "账号数据已更新，请刷新后重试",
                status_code=409,
            ) from None
        except (AccountConflictError, SQLAlchemyError):
            await self._rollback()
            raise AppError(
                "ACCOUNT_MANAGEMENT_UNAVAILABLE",
                "账号服务暂时不可用",
                status_code=503,
            ) from None
        return saved

    async def revoke_account_sessions(
        self,
        *,
        actor: AccountRecord,
        public_id: str,
        expected_version: int,
        ip_address: str | None,
    ) -> AccountRecord:
        try:
            target = await self._load_for_mutation(public_id, expected_version)
            saved = await self._accounts.save(
                replace(target, auth_version=target.auth_version + 1),
                expected_version=expected_version,
            )
            await self._append_audit(
                action="ACCOUNT_SESSIONS_REVOKED",
                actor_id=actor.id,
                account=saved,
                ip_address=ip_address,
                before_data={"authVersion": target.auth_version},
                after_data={"authVersion": saved.auth_version},
            )
            await self._transaction.commit()
        except AppError:
            await self._rollback()
            raise
        except AccountVersionConflictError:
            await self._rollback()
            raise AppError(
                "ACCOUNT_VERSION_CONFLICT",
                "账号数据已更新，请刷新后重试",
                status_code=409,
            ) from None
        except (AccountConflictError, SQLAlchemyError):
            await self._rollback()
            raise AppError(
                "ACCOUNT_MANAGEMENT_UNAVAILABLE",
                "账号服务暂时不可用",
                status_code=503,
            ) from None
        await self._revoke_sessions_after_commit(saved.id)
        return saved

    async def _load_for_mutation(
        self, public_id: str, expected_version: int
    ) -> AccountRecord:
        target = await self._accounts.get_by_public_id_for_update(public_id)
        if target is None:
            raise AppError("ACCOUNT_NOT_FOUND", "账号不存在", status_code=404)
        if target.version != expected_version:
            raise AppError(
                "ACCOUNT_VERSION_CONFLICT",
                "账号数据已更新，请刷新后重试",
                status_code=409,
            )
        return target

    async def _assert_active_admin_can_change(
        self,
        target: AccountRecord,
        next_role: Role,
        next_status: AccountStatus,
    ) -> None:
        removing_active_admin = (
            target.role is Role.ADMIN
            and target.status is AccountStatus.ACTIVE
            and (next_role is not Role.ADMIN or next_status is not AccountStatus.ACTIVE)
        )
        if (
            removing_active_admin
            and await self._accounts.count_active_admins_for_update() <= 1
        ):
            raise AppError(
                "LAST_ADMIN_REQUIRED",
                "至少保留一个启用的管理员账号",
                status_code=409,
            )

    async def _append_audit(
        self,
        *,
        action: str,
        actor_id: int,
        account: AccountRecord,
        ip_address: str | None,
        before_data: dict[str, object] | None = None,
        after_data: dict[str, object] | None = None,
    ) -> None:
        packed_ip: bytes | None = None
        if ip_address is not None:
            try:
                packed_ip = ipaddress.ip_address(ip_address).packed
            except ValueError:
                packed_ip = None
        self._transaction.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                resource_type="account",
                resource_public_id=account.public_id,
                request_id=self._request_id,
                ip_address=packed_ip,
                before_data=before_data,
                after_data=after_data,
                created_at=self._now(),
            )
        )
        await self._transaction.flush()

    @staticmethod
    def _audit_state(account: AccountRecord) -> dict[str, object]:
        return {
            "loginName": account.login_name,
            "displayName": account.display_name,
            "role": int(account.role),
            "status": int(account.status),
            "mustChangePassword": account.must_change_password,
            "videogenEnabled": account.videogen_enabled,
            "authVersion": account.auth_version,
        }

    async def _revoke_sessions_after_commit(self, account_id: int) -> None:
        try:
            await self._sessions.revoke_account(account_id)
        except (OSError, RedisError):
            _LOGGER.warning(
                "account_session_revoke_failed", extra={"account_id": account_id}
            )

    async def _rollback(self) -> None:
        try:
            await self._transaction.rollback()
        except SQLAlchemyError:
            _LOGGER.warning("account_transaction_rollback_failed")
