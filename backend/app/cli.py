from __future__ import annotations

import argparse
import asyncio
import getpass
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

from app.core.config import Settings
from app.core.database import DatabaseManager
from app.core.security import hash_password, is_strong_password, normalize_login_name
from app.modules.account.model import AccountStatus, Role
from app.modules.account.repository import AccountConflictError, AccountRepository
from app.modules.account.schemas import AccountCreate, AccountRecord
from app.modules.audit.model import AuditLog


class InvalidBootstrapInput(ValueError):
    """Bootstrap input is invalid without carrying the rejected secret."""


def _utc_now_milliseconds() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _validate_inputs(
    login_name: str, display_name: str, password: str
) -> tuple[str, str]:
    normalized_login = normalize_login_name(login_name)
    clean_display_name = display_name.strip()
    if not normalized_login or len(normalized_login) > 64:
        raise InvalidBootstrapInput("登录名必须为 1 至 64 个字符")
    if not clean_display_name or len(clean_display_name) > 64:
        raise InvalidBootstrapInput("显示名称必须为 1 至 64 个字符")
    if not is_strong_password(password):
        raise InvalidBootstrapInput("密码至少 12 位，且需包含大小写字母、数字和符号")
    return normalized_login, clean_display_name


async def _create_admin(
    *,
    settings: Settings,
    login_name: str,
    display_name: str,
    password: str,
    manager_factory: Callable[[Settings], Any],
    repository_factory: Callable[[Any], Any],
) -> AccountRecord:
    manager = manager_factory(settings)
    try:
        async with manager.session_factory() as session:
            repository = repository_factory(session)
            try:
                account = await repository.create(
                    AccountCreate(
                        login_name=login_name,
                        display_name=display_name,
                        password_hash=hash_password(password),
                        role=Role.ADMIN,
                        status=AccountStatus.ACTIVE,
                        must_change_password=False,
                        created_by=None,
                    )
                )
                session.add(
                    AuditLog(
                        actor_id=None,
                        action="BOOTSTRAP_ADMIN_CREATED",
                        resource_type="account",
                        resource_public_id=account.public_id,
                        request_id=f"cli-{uuid4().hex}",
                        ip_address=None,
                        before_data=None,
                        after_data={
                            "publicId": account.public_id,
                            "role": int(Role.ADMIN),
                            "status": int(AccountStatus.ACTIVE),
                        },
                        created_at=_utc_now_milliseconds(),
                    )
                )
                await session.flush()
                await session.commit()
                return cast(AccountRecord, account)
            except Exception:
                await session.rollback()
                raise
    finally:
        await manager.close()


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    input_func: Callable[[str], str] | None = None,
    password_func: Callable[[str], str] | None = None,
    manager_factory: Callable[[Settings], Any] = DatabaseManager,
    repository_factory: Callable[[Any], Any] = AccountRepository,
) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    parser.add_argument("command", choices=("create-admin",))
    arguments = parser.parse_args(argv)
    if arguments.command != "create-admin":
        return 1

    read_input = input_func or input
    read_password = password_func or getpass.getpass
    login_name = read_input("登录名: ")
    display_name = read_input("显示名称: ")
    password = read_password("密码: ")
    try:
        normalized_login, clean_display_name = _validate_inputs(
            login_name, display_name, password
        )
        app_settings = settings or Settings()  # type: ignore[call-arg]
        asyncio.run(
            _create_admin(
                settings=app_settings,
                login_name=normalized_login,
                display_name=clean_display_name,
                password=password,
                manager_factory=manager_factory,
                repository_factory=repository_factory,
            )
        )
    except InvalidBootstrapInput as error:
        print(str(error))
        return 1
    except AccountConflictError:
        print("管理员账号创建失败：登录名不可用")
        return 1
    except Exception:  # noqa: BLE001 - CLI boundary must never expose raw failures.
        print("管理员账号创建失败，请检查服务配置后重试")
        return 1
    print("管理员账号创建成功")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
