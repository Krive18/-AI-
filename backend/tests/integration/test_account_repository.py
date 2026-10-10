import os
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.security import InvalidPasswordHashError, hash_password, verify_password
from app.modules.account.model import AccountStatus, Role
from app.modules.account.repository import (
    AccountConflictError,
    AccountRepository,
    AccountVersionConflictError,
)
from app.modules.account.schemas import AccountCreate

TEST_DATABASE_URL_ENV = "AI_TRANSLATION_TEST_DATABASE_URL"


@pytest.fixture
async def account_session() -> AsyncIterator[AsyncSession]:
    database_url = os.getenv(TEST_DATABASE_URL_ENV)
    assert database_url, (
        f"{TEST_DATABASE_URL_ENV} must point to the dedicated test database"
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


def _new_account(login_name: str, *, role: Role = Role.OPERATOR) -> AccountCreate:
    return AccountCreate(
        login_name=login_name,
        display_name=f"Display {login_name.strip()}",
        role=role,
        status=AccountStatus.ACTIVE,
        password_hash=hash_password("Correct-Horse-9!"),
        created_by=None,
    )


async def test_create_normalizes_login_and_maps_unique_conflict(
    account_session: AsyncSession,
) -> None:
    repository = AccountRepository(account_session)

    created = await repository.create(_new_account("  Alice.Repository  "))

    assert created.login_name == "alice.repository"
    assert created.password_hash != "Correct-Horse-9!"
    assert verify_password("Correct-Horse-9!", created.password_hash)
    assert await repository.get_by_login_name(" ALICE.REPOSITORY ") == created
    assert await repository.get_by_public_id(created.public_id) == created
    assert await repository.get_by_id(created.id) == created

    with pytest.raises(AccountConflictError) as conflict:
        await repository.create(_new_account("alice.repository"))

    assert "duplicate" not in str(conflict.value).casefold()
    assert "alice.repository" not in str(conflict.value).casefold()


async def test_create_rejects_unencoded_password_without_writing_account(
    account_session: AsyncSession,
) -> None:
    repository = AccountRepository(account_session)
    plaintext = "Plaintext-Must-Not-Persist-9!"
    invalid = replace(_new_account("invalid-create-hash"), password_hash=plaintext)

    with pytest.raises(InvalidPasswordHashError) as invalid_hash:
        await repository.create(invalid)

    assert plaintext not in str(invalid_hash.value)
    assert await repository.get_by_login_name(invalid.login_name) is None


async def test_list_page_uses_explicit_columns_and_descending_id_cursor(
    account_session: AsyncSession,
) -> None:
    repository = AccountRepository(account_session)
    created = [
        await repository.create(_new_account(f"page-{index}")) for index in range(3)
    ]
    statements: list[str] = []

    def capture_sql(
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        statements.append(statement)

    event.listen(
        account_session.bind.sync_engine,
        "before_cursor_execute",
        capture_sql,
    )
    try:
        first_page = await repository.list_page(limit=2)
        second_page = await repository.list_page(
            cursor=first_page.next_cursor,
            limit=2,
        )
    finally:
        event.remove(
            account_session.bind.sync_engine,
            "before_cursor_execute",
            capture_sql,
        )

    assert [account.id for account in first_page.items] == [
        created[2].id,
        created[1].id,
    ]
    assert first_page.next_cursor == created[1].id
    assert [account.id for account in second_page.items] == [created[0].id]
    assert second_page.next_cursor is None

    list_queries = [
        statement for statement in statements if "FROM user_account" in statement
    ]
    assert len(list_queries) == 2
    for statement in list_queries:
        normalized = " ".join(statement.casefold().split())
        assert "select *" not in normalized
        assert "user_account.id" in normalized
        assert "user_account.password_hash" in normalized
        assert "order by user_account.id desc" in normalized


async def test_save_uses_version_compare_and_swap(
    account_session: AsyncSession,
) -> None:
    repository = AccountRepository(account_session)
    original = await repository.create(_new_account("cas-account"))

    saved = await repository.save(
        replace(original, display_name="First writer"),
        expected_version=original.version,
    )

    assert saved.display_name == "First writer"
    assert saved.version == original.version + 1

    with pytest.raises(AccountVersionConflictError):
        await repository.save(
            replace(original, display_name="Stale writer"),
            expected_version=original.version,
        )

    persisted = await repository.get_by_public_id(original.public_id)
    assert persisted is not None
    assert persisted.display_name == "First writer"
    assert persisted.version == saved.version


async def test_save_rejects_unencoded_password_without_changing_account(
    account_session: AsyncSession,
) -> None:
    repository = AccountRepository(account_session)
    original = await repository.create(_new_account("invalid-save-hash"))
    plaintext = "Plaintext-Must-Not-Persist-10!"

    with pytest.raises(InvalidPasswordHashError) as invalid_hash:
        await repository.save(
            replace(
                original,
                display_name="Must not be saved",
                password_hash=plaintext,
            ),
            expected_version=original.version,
        )

    assert plaintext not in str(invalid_hash.value)
    persisted = await repository.get_by_public_id(original.public_id)
    assert persisted == original


async def test_save_rereads_by_stable_id_when_public_id_is_tampered(
    account_session: AsyncSession,
) -> None:
    repository = AccountRepository(account_session)
    original = await repository.create(_new_account("stable-id-original"))
    other = await repository.create(_new_account("stable-id-other"))

    saved = await repository.save(
        replace(
            original,
            public_id=other.public_id,
            display_name="Updated original",
        ),
        expected_version=original.version,
    )

    assert saved.id == original.id
    assert saved.public_id == original.public_id
    assert saved.display_name == "Updated original"
    persisted_other = await repository.get_by_public_id(other.public_id)
    assert persisted_other == other


async def test_count_active_admins_locks_only_matching_account_ids(
    account_session: AsyncSession,
) -> None:
    repository = AccountRepository(account_session)
    await repository.create(_new_account("active-admin", role=Role.ADMIN))
    disabled_admin = await repository.create(
        _new_account("disabled-admin", role=Role.ADMIN)
    )
    await repository.save(
        replace(disabled_admin, status=AccountStatus.DISABLED),
        expected_version=disabled_admin.version,
    )
    await repository.create(_new_account("active-operator"))
    statements: list[tuple[str, Any]] = []

    def capture_sql(
        _connection: Any,
        _cursor: Any,
        statement: str,
        parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        statements.append((statement, parameters))

    event.listen(
        account_session.bind.sync_engine,
        "before_cursor_execute",
        capture_sql,
    )
    try:
        count = await repository.count_active_admins_for_update()
    finally:
        event.remove(
            account_session.bind.sync_engine,
            "before_cursor_execute",
            capture_sql,
        )

    assert count == 1
    assert len(statements) == 1
    statement, parameters = statements[0]
    normalized = " ".join(statement.casefold().split())
    assert normalized.startswith("select user_account.id from user_account")
    assert "user_account.`role` = %s" in normalized
    assert "user_account.status = %s" in normalized
    assert normalized.endswith("for update")
    assert tuple(parameters) == (int(Role.ADMIN), int(AccountStatus.ACTIVE))
