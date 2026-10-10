import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

TEST_DATABASE_URL_ENV = "AI_TRANSLATION_TEST_DATABASE_URL"
RUNTIME_TEST_DATABASE_URL_ENV = "AI_TRANSLATION_RUNTIME_TEST_DATABASE_URL"
GRANT_TEST_DATABASE_URL_ENV = "AI_TRANSLATION_GRANT_TEST_DATABASE_URL"
RUNTIME_ROLE_NAME = "ai_translation_audit_rt_test"


def _test_database_url() -> str:
    database_url = os.getenv(TEST_DATABASE_URL_ENV)
    assert database_url, (
        f"{TEST_DATABASE_URL_ENV} must point to an empty dedicated MySQL test database"
    )
    return database_url


def _runtime_test_database_url() -> str:
    database_url = os.getenv(RUNTIME_TEST_DATABASE_URL_ENV)
    assert database_url, (
        f"{RUNTIME_TEST_DATABASE_URL_ENV} must point to the restricted runtime principal"
    )
    return database_url


def _grant_test_database_url() -> str:
    database_url = os.getenv(GRANT_TEST_DATABASE_URL_ENV)
    assert database_url, (
        f"{GRANT_TEST_DATABASE_URL_ENV} must point to the grant-test principal"
    )
    return database_url


@pytest.fixture
async def db_connection() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


@pytest.fixture
async def runtime_connection() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(_runtime_test_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


@pytest.fixture
async def grant_connection() -> AsyncIterator[AsyncConnection]:
    engine = create_async_engine(_grant_test_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            yield connection
    finally:
        await engine.dispose()


def _render_runtime_grant_template(runtime_principal: str) -> list[str]:
    template_path = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "sql"
        / "runtime_audit_privileges.sql.template"
    )
    rendered = (
        template_path.read_text(encoding="utf-8")
        .replace("__DATABASE_NAME__", "ai_translation_test")
        .replace("__RUNTIME_ROLE__", RUNTIME_ROLE_NAME)
        .replace("__RUNTIME_PRINCIPAL__", runtime_principal)
    )
    executable_sql = "\n".join(
        line for line in rendered.splitlines() if not line.lstrip().startswith("--")
    )
    return [
        statement.strip()
        for statement in executable_sql.split(";")
        if statement.strip()
    ]


async def _runtime_principal_expression() -> str:
    engine = create_async_engine(_runtime_test_database_url(), pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            current_user = str(await connection.scalar(text("SELECT CURRENT_USER()")))
    finally:
        await engine.dispose()

    username, host = current_user.rsplit("@", maxsplit=1)
    quoted_username = username.replace("'", "''")
    quoted_host = host.replace("'", "''")
    return f"'{quoted_username}'@'{quoted_host}'"


async def _table_metadata(
    connection: AsyncConnection, table_name: str
) -> dict[str, object] | None:
    result = await connection.execute(
        text(
            """
            SELECT engine, table_collation, table_comment
            FROM information_schema.tables
            WHERE table_schema = DATABASE() AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    row = result.mappings().one_or_none()
    return None if row is None else {key.lower(): value for key, value in row.items()}


async def _columns(
    connection: AsyncConnection, table_name: str
) -> dict[str, dict[str, object]]:
    result = await connection.execute(
        text(
            """
            SELECT column_name, data_type, column_type, datetime_precision, column_comment
            FROM information_schema.columns
            WHERE table_schema = DATABASE() AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    )
    rows = (
        {key.lower(): value for key, value in row.items()} for row in result.mappings()
    )
    return {row["column_name"]: row for row in rows}


async def _indexes(
    connection: AsyncConnection, table_name: str
) -> dict[str, tuple[bool, tuple[str, ...]]]:
    result = await connection.execute(
        text(
            """
            SELECT index_name, non_unique, seq_in_index, column_name
            FROM information_schema.statistics
            WHERE table_schema = DATABASE() AND table_name = :table_name
            ORDER BY index_name, seq_in_index
            """
        ),
        {"table_name": table_name},
    )
    indexes: dict[str, list[tuple[int, str]]] = {}
    uniqueness: dict[str, bool] = {}
    for index_name, non_unique, sequence, column_name in result:
        name = str(index_name)
        indexes.setdefault(name, []).append((int(sequence), str(column_name)))
        uniqueness[name] = not bool(non_unique)

    return {
        name: (
            uniqueness[name],
            tuple(column for _, column in sorted(columns)),
        )
        for name, columns in indexes.items()
    }


async def _foreign_key_names(connection: AsyncConnection, table_name: str) -> set[str]:
    result = await connection.execute(
        text(
            """
            SELECT constraint_name
            FROM information_schema.table_constraints
            WHERE table_schema = DATABASE()
              AND table_name = :table_name
              AND constraint_type = 'FOREIGN KEY'
            """
        ),
        {"table_name": table_name},
    )
    return {str(row[0]) for row in result}


async def _check_constraints(
    connection: AsyncConnection, table_name: str
) -> dict[str, str]:
    result = await connection.execute(
        text(
            """
            SELECT constraints.constraint_name, checks.check_clause
            FROM information_schema.table_constraints AS constraints
            INNER JOIN information_schema.check_constraints AS checks
              ON constraints.constraint_schema = checks.constraint_schema
             AND constraints.constraint_name = checks.constraint_name
            WHERE constraints.table_schema = DATABASE()
              AND constraints.table_name = :table_name
              AND constraints.constraint_type = 'CHECK'
            """
        ),
        {"table_name": table_name},
    )
    return {str(name): str(clause) for name, clause in result}


async def _insert_invalid_account(
    connection: AsyncConnection, *, role: int, status: int
) -> None:
    identifier = uuid4().hex
    with pytest.raises(OperationalError, match="(?i)check constraint"):
        await connection.execute(
            text(
                """
                INSERT INTO user_account (
                    public_id, login_name, display_name, role, status, password_hash,
                    created_at, updated_at
                ) VALUES (
                    :public_id, :login_name, :display_name, :role, :status, :password_hash,
                    UTC_TIMESTAMP(3), UTC_TIMESTAMP(3)
                )
                """
            ),
            {
                "public_id": identifier[:26],
                "login_name": f"invalid-{identifier[:48]}",
                "display_name": "Invalid account",
                "role": role,
                "status": status,
                "password_hash": "not-a-real-password-hash",
            },
        )


@pytest.mark.parametrize("table_name", ["user_account", "audit_log"])
async def test_account_schema_uses_required_mysql_table_options(
    db_connection: AsyncConnection, table_name: str
) -> None:
    table = await _table_metadata(db_connection, table_name)

    assert table is not None
    assert table["engine"] == "InnoDB"
    assert table["table_collation"] == "utf8mb4_0900_ai_ci"
    assert table["table_comment"]


async def test_user_account_schema_has_required_constraints(
    db_connection: AsyncConnection,
) -> None:
    indexes = await _indexes(db_connection, "user_account")
    columns = await _columns(db_connection, "user_account")
    check_constraints = await _check_constraints(db_connection, "user_account")

    assert indexes["uk_user_account_login_name"] == (True, ("login_name",))
    assert indexes["uk_user_account_public_id"] == (True, ("public_id",))
    assert indexes["idx_user_account_status_created_at"] == (
        False,
        ("status", "created_at"),
    )
    assert "role" in check_constraints["ck_user_account_role"].lower()
    assert "status" in check_constraints["ck_user_account_status"].lower()
    assert await _foreign_key_names(db_connection, "user_account") == set()
    assert columns["id"]["column_type"] == "bigint unsigned"
    assert columns["videogen_enabled"]["column_type"] == "tinyint(1)"
    assert columns["created_at"]["data_type"] == "datetime"
    assert columns["created_at"]["datetime_precision"] == 3
    assert columns["updated_at"]["data_type"] == "datetime"
    assert columns["updated_at"]["datetime_precision"] == 3
    assert all(columns[name]["column_comment"] for name in columns)


async def test_user_account_rejects_invalid_role_and_status(
    db_connection: AsyncConnection,
) -> None:
    await _insert_invalid_account(db_connection, role=2, status=1)
    await _insert_invalid_account(db_connection, role=1, status=3)


async def test_audit_log_schema_is_append_only_and_keeps_required_data(
    db_connection: AsyncConnection,
) -> None:
    indexes = await _indexes(db_connection, "audit_log")
    columns = await _columns(db_connection, "audit_log")

    assert indexes["idx_audit_log_actor_id_created_at"] == (
        False,
        ("actor_id", "created_at"),
    )
    assert indexes["idx_audit_log_resource_created_at"] == (
        False,
        ("resource_type", "resource_public_id", "created_at"),
    )
    assert await _foreign_key_names(db_connection, "audit_log") == set()
    assert columns["actor_id"]["column_type"] == "bigint unsigned"
    assert columns["ip_address"]["column_type"] == "varbinary(16)"
    assert columns["before_data"]["data_type"] == "json"
    assert columns["after_data"]["data_type"] == "json"
    assert columns["created_at"]["data_type"] == "datetime"
    assert columns["created_at"]["datetime_precision"] == 3
    assert all(columns[name]["column_comment"] for name in columns)


async def test_runtime_grant_template_is_repeatable_and_enforces_append_only(
    grant_connection: AsyncConnection,
) -> None:
    runtime_principal = await _runtime_principal_expression()
    statements = _render_runtime_grant_template(runtime_principal)

    for _ in range(2):
        for statement in statements:
            await grant_connection.execute(text(statement))

    runtime_engine = create_async_engine(
        _runtime_test_database_url(), pool_pre_ping=True
    )
    cleanup_engine = create_async_engine(_test_database_url(), pool_pre_ping=True)
    account_login = f"runtime-grant-{uuid4().hex[:16]}"
    account_public_id = f"01{uuid4().hex[:24]}"
    forbidden_table = f"runtime_forbidden_{uuid4().hex[:16]}"
    request_id = uuid4().hex
    try:
        async with runtime_engine.connect() as connection:
            insert_account = await connection.execute(
                text(
                    """
                    INSERT INTO user_account (
                        public_id, login_name, display_name, role, status,
                        password_hash, must_change_password, auth_version,
                        version, created_at, updated_at
                    ) VALUES (
                        :public_id, :login_name, :display_name, 1, 1,
                        :password_hash, 1, 1, 1, UTC_TIMESTAMP(3), UTC_TIMESTAMP(3)
                    )
                    """
                ),
                {
                    "public_id": account_public_id,
                    "login_name": account_login,
                    "display_name": "Runtime Grant Contract",
                    "password_hash": "$argon2id$test-contract-only",
                },
            )
            assert insert_account.rowcount == 1
            assert (
                await connection.scalar(
                    text(
                        "SELECT display_name FROM user_account "
                        "WHERE login_name = :login_name"
                    ),
                    {"login_name": account_login},
                )
                == "Runtime Grant Contract"
            )
            update_account = await connection.execute(
                text(
                    "UPDATE user_account SET display_name = :display_name "
                    "WHERE login_name = :login_name"
                ),
                {
                    "display_name": "Runtime Grant Updated",
                    "login_name": account_login,
                },
            )
            assert update_account.rowcount == 1
            with pytest.raises(DBAPIError, match="command denied"):
                await connection.execute(
                    text("DELETE FROM user_account WHERE login_name = :login_name"),
                    {"login_name": account_login},
                )
            with pytest.raises(DBAPIError, match="denied"):
                await connection.execute(
                    text(f"CREATE TABLE `{forbidden_table}` (id BIGINT PRIMARY KEY)")
                )
            with pytest.raises(DBAPIError, match="denied"):
                await connection.execute(
                    text(
                        "GRANT SELECT ON `ai_translation_test`.`user_account` "
                        f"TO {runtime_principal}"
                    )
                )

            result = await connection.execute(
                text(
                    """
                    INSERT INTO audit_log (action, resource_type, request_id, created_at)
                    VALUES (:action, :resource_type, :request_id, UTC_TIMESTAMP(3))
                    """
                ),
                {
                    "action": "runtime_grant_template_contract",
                    "resource_type": "audit_log",
                    "request_id": request_id,
                },
            )
            await connection.commit()
            assert result.rowcount == 1

            with pytest.raises(DBAPIError, match="command denied"):
                await connection.execute(
                    text(
                        "UPDATE audit_log SET action = :action "
                        "WHERE request_id = :request_id"
                    ),
                    {"action": "should_not_be_allowed", "request_id": request_id},
                )

            with pytest.raises(DBAPIError, match="command denied"):
                await connection.execute(
                    text("DELETE FROM audit_log WHERE request_id = :request_id"),
                    {"request_id": request_id},
                )
    finally:
        await runtime_engine.dispose()
        async with cleanup_engine.begin() as connection:
            await connection.execute(text(f"DROP TABLE IF EXISTS `{forbidden_table}`"))
            await connection.execute(
                text("DELETE FROM audit_log WHERE request_id = :request_id"),
                {"request_id": request_id},
            )
            await connection.execute(
                text("DELETE FROM user_account WHERE login_name = :login_name"),
                {"login_name": account_login},
            )
        await cleanup_engine.dispose()


async def test_restricted_runtime_principal_can_only_append_audit_rows(
    runtime_connection: AsyncConnection,
) -> None:
    request_id = uuid4().hex
    insert_result = await runtime_connection.execute(
        text(
            """
            INSERT INTO audit_log (action, resource_type, request_id, created_at)
            VALUES (:action, :resource_type, :request_id, UTC_TIMESTAMP(3))
            """
        ),
        {
            "action": "runtime_permission_contract",
            "resource_type": "audit_log",
            "request_id": request_id,
        },
    )
    await runtime_connection.commit()
    assert insert_result.rowcount == 1

    with pytest.raises(DBAPIError, match="command denied"):
        await runtime_connection.execute(
            text(
                "UPDATE audit_log SET action = :action WHERE request_id = :request_id"
            ),
            {"action": "should_not_be_allowed", "request_id": request_id},
        )

    with pytest.raises(DBAPIError, match="command denied"):
        await runtime_connection.execute(
            text("DELETE FROM audit_log WHERE request_id = :request_id"),
            {"request_id": request_id},
        )
