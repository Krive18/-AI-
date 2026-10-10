from __future__ import annotations

import hashlib
import os
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from argon2 import Type, extract_parameters
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.errors import AppError
from app.core.security import hash_password
from app.modules.account.model import AccountStatus, Role
from app.modules.account.repository import AccountRepository
from app.modules.account.schemas import AccountCreate, AccountRecord
from app.modules.audit.model import AuditLog
from app.modules.auth.service import (
    _DUMMY_PASSWORD_HASH,
    AuthenticationInfrastructureError,
    AuthService,
    InvalidCredentials,
    LoginTemporarilyLocked,
)
from app.modules.auth.sessions import SessionData, SessionStore

_TEST_DATABASE_URL_ENV = "AI_TRANSLATION_TEST_DATABASE_URL"


@pytest.fixture
async def mysql_auth_session() -> AsyncIterator[AsyncSession]:
    database_url = os.getenv(_TEST_DATABASE_URL_ENV)
    assert database_url, (
        f"{_TEST_DATABASE_URL_ENV} must point to the dedicated test database"
    )
    engine = create_async_engine(database_url, pool_pre_ping=True)
    connection = await engine.connect()
    transaction = await connection.begin()
    session = AsyncSession(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()
        await engine.dispose()


class FakeRepository:
    def __init__(self, account: AccountRecord | None) -> None:
        self.account = account
        self.saved: list[AccountRecord] = []

    async def get_by_login_name(self, _: str) -> AccountRecord | None:
        return self.account

    async def save(
        self, account: AccountRecord, *, expected_version: int
    ) -> AccountRecord:
        assert self.account is not None
        assert expected_version == self.account.version
        saved = replace(account, version=account.version + 1)
        self.account = saved
        self.saved.append(saved)
        return saved


class FakeRateRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        value = self.values.get(key)
        return None if value is None else str(value)

    async def delete(self, key: str) -> int:
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return 1

    async def eval(self, _: str, numkeys: int, key: str, ttl: str) -> int:
        assert numkeys == 1
        value = self.values.get(key, 0) + 1
        self.values[key] = value
        if key not in self.ttls or value >= 5:
            self.ttls[key] = int(ttl)
        return value


class FakeSessionStore:
    def __init__(self) -> None:
        self.created: list[tuple[int, int]] = []
        self.revoked: list[str] = []
        self.revoked_accounts: list[int] = []

    async def create(
        self, *, account_id: int, auth_version: int
    ) -> tuple[str, SessionData]:
        self.created.append((account_id, auth_version))
        now = datetime(2026, 9, 1, tzinfo=UTC)
        return (
            "opaque-session-token",
            SessionData(account_id, auth_version, "csrf", now, now),
        )

    async def revoke(self, token: str) -> None:
        self.revoked.append(token)

    async def revoke_account(self, account_id: int) -> None:
        self.revoked_accounts.append(account_id)


class FailingRevokeSessionStore(FakeSessionStore):
    async def revoke_account(self, account_id: int) -> None:
        self.revoked_accounts.append(account_id)
        raise OSError("redis unavailable")


class FakeAuditWriter:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def append(self, **event: object) -> None:
        self.events.append(event)


class FailingAuditWriter(FakeAuditWriter):
    async def append(self, **event: object) -> None:
        raise OSError("audit database unavailable")


class FakeTransaction:
    def __init__(self, *, fail_commit: bool = False) -> None:
        self.fail_commit = fail_commit
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.fail_commit:
            raise OSError("commit failed")

    async def rollback(self) -> None:
        self.rollbacks += 1


class SqlAuditWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, **event: object) -> None:
        self._session.add(
            AuditLog(
                actor_id=event["actor_id"],
                action=event["action"],
                resource_type=event["resource_type"],
                resource_public_id=event["resource_public_id"],
                request_id="task5-test",
                ip_address=b"\x7f\x00\x00\x01",
                before_data=event["before_data"],
                after_data=event["after_data"],
                created_at=event["created_at"],
            )
        )
        await self._session.flush()


def active_account(
    *,
    status: AccountStatus = AccountStatus.ACTIVE,
    role: Role = Role.OPERATOR,
) -> AccountRecord:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return AccountRecord(
        id=41,
        public_id="01JTESTACCOUNT0000000000000",
        login_name="operator",
        display_name="Operator",
        role=role,
        status=status,
        password_hash=hash_password("correct-password"),
        must_change_password=True,
        videogen_enabled=False,
        password_changed_at=None,
        last_login_at=None,
        created_by=None,
        auth_version=2,
        version=7,
        created_at=now,
        updated_at=now,
    )


def auth_service(
    account: AccountRecord | None,
) -> tuple[AuthService, FakeRepository, FakeSessionStore, FakeAuditWriter]:
    repository = FakeRepository(account)
    sessions = FakeSessionStore()
    audit = FakeAuditWriter()
    return (
        AuthService(
            repository,
            sessions,
            FakeRateRedis(),
            audit,
            transaction=FakeTransaction(),
        ),
        repository,
        sessions,
        audit,
    )


async def test_fifth_failed_login_blocks_the_next_attempt() -> None:
    service, _, _, _ = auth_service(active_account())

    for _ in range(5):
        with pytest.raises(InvalidCredentials):
            await service.login("operator", "wrong", "127.0.0.1")

    with pytest.raises(LoginTemporarilyLocked):
        await service.login("operator", "correct-password", "127.0.0.1")


async def test_login_limit_key_is_digested_and_fifth_failure_refreshes_ttl() -> None:
    repository = FakeRepository(active_account())
    rate_redis = FakeRateRedis()
    service = AuthService(
        repository,
        FakeSessionStore(),
        rate_redis,
        FakeAuditWriter(),
        transaction=FakeTransaction(),
        key_prefix="task5-test:",
    )

    for _ in range(5):
        with pytest.raises(InvalidCredentials):
            await service.login(" Operator ", "wrong", "127.0.0.1")

    assert len(rate_redis.values) == 1
    key = next(iter(rate_redis.values))
    assert key.startswith("task5-test:login-limit:")
    assert "operator" not in key
    assert rate_redis.ttls[key] == 15 * 60


async def test_failed_login_repairs_a_preexisting_limit_key_without_ttl() -> None:
    repository = FakeRepository(active_account())
    rate_redis = FakeRateRedis()
    key = f"login-limit:{hashlib.sha256(b'operator').hexdigest()}"
    rate_redis.values[key] = 2
    service = AuthService(
        repository,
        FakeSessionStore(),
        rate_redis,
        FakeAuditWriter(),
        transaction=FakeTransaction(),
    )

    with pytest.raises(InvalidCredentials):
        await service.login("operator", "wrong", "127.0.0.1")

    assert rate_redis.ttls[key] == 15 * 60


async def test_missing_bad_and_disabled_accounts_share_the_same_credential_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    def record_verify(value: str, encoded: str) -> bool:
        calls.append((value, encoded))
        return False

    monkeypatch.setattr("app.modules.auth.service.verify_password", record_verify)
    errors: list[InvalidCredentials] = []
    for account in (
        None,
        active_account(),
        active_account(status=AccountStatus.DISABLED),
    ):
        service, _, _, _ = auth_service(account)
        with pytest.raises(InvalidCredentials) as error:
            await service.login("operator", "wrong", "127.0.0.1")
        errors.append(error.value)

    assert len(calls) == 3
    assert {(error.code, error.message) for error in errors} == {
        ("INVALID_CREDENTIALS", "用户名或密码错误")
    }


def test_fixed_dummy_hash_is_valid_required_argon2id() -> None:
    parameters = extract_parameters(_DUMMY_PASSWORD_HASH)

    assert parameters.type is Type.ID
    assert (parameters.memory_cost, parameters.time_cost, parameters.parallelism) == (
        65536,
        3,
        4,
    )


async def test_successful_login_creates_session_updates_account_and_audits() -> None:
    service, repository, sessions, audit = auth_service(active_account())

    result = await service.login(" OPERATOR ", "correct-password", "127.0.0.1")

    assert result.session_token == "opaque-session-token"
    assert sessions.created == [(41, 2)]
    assert repository.saved[0].last_login_at is not None
    assert audit.events[0]["action"] == "LOGIN_SUCCEEDED"
    assert "correct-password" not in str(audit.events)
    assert "opaque-session-token" not in str(audit.events)


async def test_admin_account_logging_in_via_operator_portal_is_rejected() -> None:
    service, repository, sessions, audit = auth_service(
        active_account(role=Role.ADMIN)
    )

    with pytest.raises(AppError) as error:
        await service.login("operator", "correct-password", "127.0.0.1")

    assert (error.value.code, error.value.status_code, error.value.message) == (
        "ROLE_PORTAL_MISMATCH",
        403,
        "该账号为管理员，请从管理后台入口登录",
    )
    assert sessions.created == []
    assert repository.saved == []
    assert [event["action"] for event in audit.events] == ["LOGIN_PORTAL_MISMATCH"]


async def test_operator_account_logging_in_via_admin_portal_is_rejected() -> None:
    service, repository, sessions, audit = auth_service(active_account())

    with pytest.raises(AppError) as error:
        await service.login(
            "operator", "correct-password", "127.0.0.1", portal="admin"
        )

    assert (error.value.code, error.value.status_code, error.value.message) == (
        "ROLE_PORTAL_MISMATCH",
        403,
        "该账号为运营成员，请从工作台入口登录",
    )
    assert sessions.created == []
    assert repository.saved == []
    assert [event["action"] for event in audit.events] == ["LOGIN_PORTAL_MISMATCH"]


async def test_admin_account_logging_in_via_admin_portal_succeeds() -> None:
    service, _, sessions, audit = auth_service(active_account(role=Role.ADMIN))

    result = await service.login(
        "operator", "correct-password", "127.0.0.1", portal="admin"
    )

    assert result.session_token == "opaque-session-token"
    assert sessions.created == [(41, 2)]
    assert audit.events[0]["action"] == "LOGIN_SUCCEEDED"


async def test_change_password_increments_auth_version_and_revokes_sessions() -> None:
    service, repository, sessions, audit = auth_service(active_account())

    changed = await service.change_password(
        repository.account,
        current_password="correct-password",
        new_password="New-Correct-Password-2026!",
        ip_address="127.0.0.1",
    )

    assert changed.auth_version == 3
    assert not changed.must_change_password
    assert sessions.revoked_accounts == [41]
    assert audit.events[0]["action"] == "PASSWORD_CHANGED"
    assert "New-Correct-Password-2026!" not in str(audit.events)


async def test_logout_revokes_current_session_and_audits() -> None:
    service, _, sessions, audit = auth_service(active_account())

    await service.logout("opaque-session-token", account_id=41, ip_address="127.0.0.1")

    assert sessions.revoked == ["opaque-session-token"]
    assert audit.events[0]["action"] == "LOGOUT"
    assert "opaque-session-token" not in str(audit.events)


async def test_login_commits_account_update_and_audit_before_returning_token() -> None:
    repository = FakeRepository(active_account())
    sessions = FakeSessionStore()
    audit = FakeAuditWriter()
    transaction = FakeTransaction()
    service = AuthService(
        repository,
        sessions,
        FakeRateRedis(),
        audit,
        transaction=transaction,
    )

    await service.login("operator", "correct-password", "127.0.0.1")

    assert transaction.commits == 1
    assert audit.events[0]["action"] == "LOGIN_SUCCEEDED"


async def test_login_audit_or_commit_failure_revokes_created_session() -> None:
    repository = FakeRepository(active_account())
    sessions = FakeSessionStore()
    transaction = FakeTransaction()
    service = AuthService(
        repository,
        sessions,
        FakeRateRedis(),
        FailingAuditWriter(),
        transaction=transaction,
    )

    with pytest.raises(AuthenticationInfrastructureError):
        await service.login("operator", "correct-password", "127.0.0.1")

    assert sessions.created == [(41, 2)]
    assert sessions.revoked == ["opaque-session-token"]
    assert transaction.rollbacks == 1


async def test_failed_login_and_lock_are_audited_before_their_public_errors() -> None:
    repository = FakeRepository(active_account())
    audit = FakeAuditWriter()
    transaction = FakeTransaction()
    service = AuthService(
        repository,
        FakeSessionStore(),
        FakeRateRedis(),
        audit,
        transaction=transaction,
    )

    with pytest.raises(InvalidCredentials):
        await service.login("operator", "wrong", "127.0.0.1")
    for _ in range(4):
        with pytest.raises(InvalidCredentials):
            await service.login("operator", "wrong", "127.0.0.1")
    with pytest.raises(LoginTemporarilyLocked):
        await service.login("operator", "correct-password", "127.0.0.1")

    assert [event["action"] for event in audit.events] == [
        "LOGIN_FAILED",
        "LOGIN_FAILED",
        "LOGIN_FAILED",
        "LOGIN_FAILED",
        "LOGIN_FAILED",
        "LOGIN_LOCKED",
    ]
    assert transaction.commits == 6
    assert "operator" not in str(audit.events)


async def test_failed_login_audit_failure_is_an_infrastructure_error() -> None:
    service = AuthService(
        FakeRepository(active_account()),
        FakeSessionStore(),
        FakeRateRedis(),
        FailingAuditWriter(),
        transaction=FakeTransaction(),
    )

    with pytest.raises(AuthenticationInfrastructureError):
        await service.login("operator", "wrong", "127.0.0.1")


async def test_password_change_remains_committed_when_redis_revoke_fails() -> None:
    repository = FakeRepository(active_account())
    sessions = FailingRevokeSessionStore()
    transaction = FakeTransaction()
    service = AuthService(
        repository,
        sessions,
        FakeRateRedis(),
        FakeAuditWriter(),
        transaction=transaction,
    )

    changed = await service.change_password(
        repository.account,
        current_password="correct-password",
        new_password="New-Correct-Password-2026!",
        ip_address="127.0.0.1",
    )

    assert changed.auth_version == 3
    assert transaction.commits == 1
    assert sessions.revoked_accounts == [41]


async def test_real_redis_resp2_session_store_uses_an_owned_db15_namespace() -> None:
    redis: Redis = Redis.from_url(
        "redis://127.0.0.1:6379/15", decode_responses=True, protocol=2
    )
    prefix = f"task5-test:{uuid4().hex}:"
    store = SessionStore(
        redis,
        "real-redis-session-hash-key-that-is-at-least-32-bytes",
        key_prefix=prefix,
    )
    try:
        assert await redis.ping()
        token, _ = await store.create(account_id=53, auth_version=4)
        assert 8 * 60 * 60 - 5 <= await store.ttl(token) <= 8 * 60 * 60
        loaded = await store.get_and_touch(token)
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]

        assert loaded is not None
        assert loaded.account_id == 53
        assert all(token not in key for key in keys)

        await store.revoke_account(53)
        assert await store.get_and_touch(token) is None
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


async def test_real_mysql_and_redis_auth_side_effects(
    mysql_auth_session: AsyncSession,
) -> None:
    redis: Redis = Redis.from_url(
        "redis://127.0.0.1:6379/15", decode_responses=True, protocol=2
    )
    prefix = f"task5-auth:{uuid4().hex}:"
    store = SessionStore(
        redis,
        "real-redis-auth-hash-key-that-is-at-least-32-bytes",
        key_prefix=prefix,
    )
    repository = AccountRepository(mysql_auth_session)
    account = await repository.create(
        AccountCreate(
            login_name=f"auth-{uuid4().hex[:12]}",
            display_name="Auth integration",
            password_hash=hash_password("correct-password"),
        )
    )
    service = AuthService(
        repository,
        store,
        redis,
        SqlAuditWriter(mysql_auth_session),
        transaction=mysql_auth_session,
    )
    try:
        result = await service.login(
            account.login_name, "correct-password", "127.0.0.1"
        )
        persisted = await repository.get_by_public_id(account.public_id)

        assert persisted is not None
        assert persisted.last_login_at is not None
        assert await store.get_and_touch(result.session_token) is not None
        audit_rows = (
            await mysql_auth_session.execute(
                select(AuditLog)
                .where(AuditLog.actor_id == account.id)
                .order_by(AuditLog.id)
            )
        ).scalars()
        assert [row.action for row in audit_rows] == ["LOGIN_SUCCEEDED"]

        changed = await service.change_password(
            result.account,
            current_password="correct-password",
            new_password="New-Correct-Password-2026!",
            ip_address="127.0.0.1",
        )

        assert changed.auth_version == account.auth_version + 1
        persisted_after_change = await repository.get_by_public_id(account.public_id)
        assert persisted_after_change is not None
        assert persisted_after_change.auth_version == changed.auth_version
        assert await store.get_and_touch(result.session_token) is None
        audit_rows = (
            await mysql_auth_session.execute(
                select(AuditLog)
                .where(AuditLog.actor_id == account.id)
                .order_by(AuditLog.id)
            )
        ).scalars()
        assert [row.action for row in audit_rows] == [
            "LOGIN_SUCCEEDED",
            "PASSWORD_CHANGED",
        ]
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()


async def test_real_redis_session_is_compensated_when_audit_write_fails(
    mysql_auth_session: AsyncSession,
) -> None:
    redis: Redis = Redis.from_url(
        "redis://127.0.0.1:6379/15", decode_responses=True, protocol=2
    )
    prefix = f"task5-audit-failure:{uuid4().hex}:"
    repository = AccountRepository(mysql_auth_session)
    account = await repository.create(
        AccountCreate(
            login_name=f"audit-failure-{uuid4().hex[:10]}",
            display_name="Audit failure integration",
            password_hash=hash_password("correct-password"),
        )
    )
    service = AuthService(
        repository,
        SessionStore(
            redis,
            "real-redis-audit-failure-hash-key-that-is-at-least-32-bytes",
            key_prefix=prefix,
        ),
        redis,
        FailingAuditWriter(),
        transaction=mysql_auth_session,
    )
    try:
        with pytest.raises(AuthenticationInfrastructureError):
            await service.login(account.login_name, "correct-password", "127.0.0.1")

        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        assert keys == []
    finally:
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await redis.delete(*keys)
        await redis.aclose()
