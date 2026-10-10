from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import UTC, datetime
from typing import ClassVar
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.cli import main
from app.core.config import Settings
from app.modules.account.model import AccountStatus, Role, UserAccount
from app.modules.account.repository import AccountConflictError
from app.modules.account.schemas import AccountCreate, AccountRecord
from app.modules.audit.model import AuditLog

_MIGRATION_DATABASE_URL_ENV = "AI_TRANSLATION_TEST_DATABASE_URL"
_RUNTIME_DATABASE_URL_ENV = "AI_TRANSLATION_RUNTIME_TEST_DATABASE_URL"


class FakeSession:
    def __init__(self, *, fail_flush: bool = False) -> None:
        self.fail_flush = fail_flush
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        if self.fail_flush:
            raise OSError("sensitive database failure")

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class SessionContext(AbstractAsyncContextManager[FakeSession]):
    def __init__(self, session: FakeSession) -> None:
        self.session = session

    async def __aenter__(self) -> FakeSession:
        return self.session

    async def __aexit__(self, *_: object) -> None:
        return None


class FakeManager:
    def __init__(self, session: FakeSession) -> None:
        self.session = session
        self.closed = False

    def session_factory(self) -> SessionContext:
        return SessionContext(self.session)

    async def close(self) -> None:
        self.closed = True


class FakeRepository:
    created: ClassVar[list[AccountCreate]] = []
    conflict: ClassVar[bool] = False

    def __init__(self, _: object) -> None:
        pass

    async def create(self, data: AccountCreate) -> AccountRecord:
        if self.conflict:
            raise AccountConflictError("raw duplicate detail")
        self.created.append(data)
        now = datetime(2026, 9, 1, tzinfo=UTC)
        return AccountRecord(
            id=91,
            public_id="01JBOOTSTRAPADMIN0000000000",
            login_name=data.login_name,
            display_name=data.display_name,
            role=data.role,
            status=data.status,
            password_hash=data.password_hash,
            must_change_password=data.must_change_password,
            videogen_enabled=False,
            password_changed_at=None,
            last_login_at=None,
            created_by=None,
            auth_version=1,
            version=1,
            created_at=now,
            updated_at=now,
        )


@pytest.fixture
def settings() -> Settings:
    return Settings(
        app_env="test",
        database_url="mysql+asyncmy://127.0.0.1:3306/unused",
        redis_url="redis://127.0.0.1:6379/15",
        redis_protocol=2,
        session_hash_key="test-session-hash-key-that-is-at-least-32-bytes",
    )


def inputs(*values: str) -> Callable[[str], str]:
    remaining = iter(values)
    return lambda _prompt: next(remaining)


def test_create_admin_uses_hidden_password_and_commits_account_with_audit(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeRepository.created = []
    FakeRepository.conflict = False
    session = FakeSession()
    manager = FakeManager(session)
    password_calls: list[str] = []

    exit_code = main(
        ["create-admin"],
        settings=settings,
        input_func=inputs(" Bootstrap.Admin ", "Operations Admin"),
        password_func=lambda prompt: (
            password_calls.append(prompt) or "Strong-Bootstrap-2026!"
        ),
        manager_factory=lambda _settings: manager,
        repository_factory=FakeRepository,
    )

    assert exit_code == 0
    assert len(password_calls) == 1
    created = FakeRepository.created[0]
    assert (created.role, created.status, created.must_change_password) == (
        Role.ADMIN,
        AccountStatus.ACTIVE,
        False,
    )
    assert created.login_name == "bootstrap.admin"
    assert created.password_hash != "Strong-Bootstrap-2026!"
    assert session.commits == 1
    assert session.rollbacks == 0
    audit = session.added[0]
    assert audit.action == "BOOTSTRAP_ADMIN_CREATED"
    assert audit.actor_id is None
    assert "Strong-Bootstrap-2026!" not in str(audit.after_data)
    assert "Strong-Bootstrap-2026!" not in capsys.readouterr().out
    assert manager.closed


def test_weak_password_is_rejected_before_database_manager_is_created(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    manager_created = False

    def manager_factory(_: Settings) -> FakeManager:
        nonlocal manager_created
        manager_created = True
        return FakeManager(FakeSession())

    exit_code = main(
        ["create-admin"],
        settings=settings,
        input_func=inputs("admin", "Admin"),
        password_func=lambda _prompt: "weak-password",
        manager_factory=manager_factory,
        repository_factory=FakeRepository,
    )

    assert exit_code == 1
    assert not manager_created
    output = capsys.readouterr().out
    assert "weak-password" not in output
    assert "密码" in output


def test_duplicate_login_has_safe_output_and_rolls_back(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeRepository.conflict = True
    session = FakeSession()
    manager = FakeManager(session)
    try:
        exit_code = main(
            ["create-admin"],
            settings=settings,
            input_func=inputs("admin", "Admin"),
            password_func=lambda _prompt: "Strong-Bootstrap-2026!",
            manager_factory=lambda _settings: manager,
            repository_factory=FakeRepository,
        )
    finally:
        FakeRepository.conflict = False

    assert exit_code == 1
    assert session.commits == 0
    assert session.rollbacks == 1
    output = capsys.readouterr().out
    assert "raw duplicate detail" not in output
    assert "Strong-Bootstrap-2026!" not in output


def test_audit_failure_rolls_back_and_has_safe_output(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    FakeRepository.created = []
    session = FakeSession(fail_flush=True)
    manager = FakeManager(session)

    exit_code = main(
        ["create-admin"],
        settings=settings,
        input_func=inputs("audit-failure-admin", "Admin"),
        password_func=lambda _prompt: "Strong-Bootstrap-2026!",
        manager_factory=lambda _settings: manager,
        repository_factory=FakeRepository,
    )

    assert exit_code == 1
    assert session.commits == 0
    assert session.rollbacks == 1
    output = capsys.readouterr().out
    assert "sensitive database failure" not in output
    assert "Strong-Bootstrap-2026!" not in output


def test_real_mysql_cli_creates_admin_and_audit_then_duplicate_is_safe(
    capsys: pytest.CaptureFixture[str],
) -> None:
    migration_url = os.getenv(_MIGRATION_DATABASE_URL_ENV)
    runtime_url = os.getenv(_RUNTIME_DATABASE_URL_ENV)
    assert migration_url, f"{_MIGRATION_DATABASE_URL_ENV} must be configured"
    assert runtime_url, f"{_RUNTIME_DATABASE_URL_ENV} must be configured"
    login_name = f"task6-cli-{uuid4().hex[:16]}"
    password = "Strong-Task6-Cli-2026!"
    settings = Settings(
        app_env="test",
        database_url=runtime_url,
        redis_url="redis://127.0.0.1:6379/15",
        redis_protocol=2,
        session_hash_key="task6-cli-session-key-that-is-at-least-32-bytes",
    )
    public_id: str | None = None

    async def load_created() -> tuple[UserAccount, AuditLog]:
        engine = create_async_engine(migration_url, pool_pre_ping=True)
        try:
            async with AsyncSession(engine) as session:
                account_row = (
                    await session.execute(
                        select(UserAccount).where(UserAccount.login_name == login_name)
                    )
                ).scalar_one()
                audit = (
                    await session.execute(
                        select(AuditLog).where(
                            AuditLog.action == "BOOTSTRAP_ADMIN_CREATED",
                            AuditLog.resource_public_id == account_row.public_id,
                        )
                    )
                ).scalar_one()
                return account_row, audit
        finally:
            await engine.dispose()

    async def cleanup_created(owned_public_id: str) -> None:
        engine = create_async_engine(migration_url, pool_pre_ping=True)
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    delete(AuditLog).where(
                        AuditLog.resource_public_id == owned_public_id
                    )
                )
                await connection.execute(
                    delete(UserAccount).where(UserAccount.login_name == login_name)
                )
        finally:
            await engine.dispose()

    try:
        first = main(
            ["create-admin"],
            settings=settings,
            input_func=inputs(login_name, "Task 6 CLI Admin"),
            password_func=lambda _prompt: password,
        )
        duplicate = main(
            ["create-admin"],
            settings=settings,
            input_func=inputs(login_name, "Task 6 Duplicate"),
            password_func=lambda _prompt: password,
        )

        account_row, audit = asyncio.run(load_created())
        public_id = account_row.public_id

        assert first == 0
        assert duplicate == 1
        assert account_row.role == int(Role.ADMIN)
        assert account_row.status == int(AccountStatus.ACTIVE)
        assert not account_row.must_change_password
        assert audit.actor_id is None
        assert audit.ip_address is None
        output = capsys.readouterr().out
        assert password not in output
        assert "duplicate" not in output.casefold()
    finally:
        if public_id is not None:
            asyncio.run(cleanup_created(public_id))
