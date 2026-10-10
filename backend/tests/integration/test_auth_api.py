import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import hash_password
from app.main import create_app
from app.modules.account.model import AccountStatus, Role, UserAccount
from app.modules.account.repository import AccountRepository
from app.modules.account.schemas import AccountCreate, AccountRecord
from app.modules.audit.model import AuditLog
from app.modules.auth.dependencies import (
    AuthContext,
    get_account_repository,
    get_auth_service,
    get_session_store,
    require_account,
    require_admin,
    require_password_ready,
)
from app.modules.auth.schemas import LoginResult
from app.modules.auth.sessions import SessionData

_MIGRATION_DATABASE_URL_ENV = "AI_TRANSLATION_TEST_DATABASE_URL"
_RUNTIME_DATABASE_URL_ENV = "AI_TRANSLATION_RUNTIME_TEST_DATABASE_URL"


class LoginService:
    def __init__(self) -> None:
        self.logout_tokens: list[str] = []
        self.password_changes: list[tuple[str, str]] = []
        self.login_portals: list[str] = []

    async def login(
        self,
        login_name: str,
        password: str,
        ip_address: str | None,
        portal: str = "operator",
    ) -> LoginResult:
        assert login_name == "operator"
        assert password == "Correct-Horse-9!"
        assert ip_address == "127.0.0.1"
        self.login_portals.append(portal)
        now = datetime(2026, 9, 1, tzinfo=UTC)
        account = AccountRecord(
            id=7,
            public_id="01JTESTAUTHACCOUNT000000000",
            login_name="operator",
            display_name="Operator",
            role=Role.OPERATOR,
            status=AccountStatus.ACTIVE,
            password_hash="must-never-leak",
            must_change_password=True,
            videogen_enabled=False,
            password_changed_at=None,
            last_login_at=now,
            created_by=None,
            auth_version=3,
            version=4,
            created_at=now,
            updated_at=now,
        )
        session = SessionData(7, 3, "csrf-token", now, now)
        return LoginResult(account, "opaque-session-token", session)

    async def logout(
        self, session_token: str, *, account_id: int, ip_address: str | None
    ) -> None:
        assert account_id == 7
        assert ip_address == "127.0.0.1"
        self.logout_tokens.append(session_token)

    async def change_password(
        self,
        account: AccountRecord,
        *,
        current_password: str,
        new_password: str,
        ip_address: str | None,
    ) -> AccountRecord:
        assert account.id == 7
        assert ip_address == "127.0.0.1"
        self.password_changes.append((current_password, new_password))
        return account


def account(
    *,
    status: AccountStatus = AccountStatus.ACTIVE,
    role: Role = Role.OPERATOR,
    auth_version: int = 3,
    must_change_password: bool = True,
    videogen_enabled: bool = False,
) -> AccountRecord:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    return AccountRecord(
        id=7,
        public_id="01JTESTAUTHACCOUNT000000000",
        login_name="operator",
        display_name="Operator",
        role=role,
        status=status,
        password_hash="must-never-leak",
        must_change_password=must_change_password,
        videogen_enabled=videogen_enabled,
        password_changed_at=None,
        last_login_at=now,
        created_by=None,
        auth_version=auth_version,
        version=4,
        created_at=now,
        updated_at=now,
    )


def auth_context(**account_options: object) -> AuthContext:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    current = account(**account_options)
    return AuthContext(
        token="opaque-session-token",
        session=SessionData(7, 3, "csrf-token", now, now),
        account=current,
    )


class SessionLookup:
    def __init__(self, session: SessionData | None) -> None:
        self.session = session
        self.revoked: list[str] = []

    async def get_and_touch(self, token: str) -> SessionData | None:
        assert token == "browser-token"
        return self.session

    async def revoke(self, token: str) -> None:
        self.revoked.append(token)


class AccountLookup:
    def __init__(self, current: AccountRecord | None) -> None:
        self.current = current

    async def get_by_id(self, account_id: int) -> AccountRecord | None:
        assert account_id == 7
        return self.current


async def test_login_endpoint_exists_and_auth_responses_are_not_cached(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    app.dependency_overrides[get_auth_service] = lambda: LoginService()
    response = await client.post(
        "/api/v1/auth/login",
        json={"loginName": "operator", "password": "Correct-Horse-9!"},
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json() == {
        "account": {
            "publicId": "01JTESTAUTHACCOUNT000000000",
            "loginName": "operator",
            "displayName": "Operator",
            "role": 1,
            "status": 1,
            "mustChangePassword": True,
            "videogenEnabled": False,
        },
        "csrfToken": "csrf-token",
    }
    cookie = response.headers["set-cookie"]
    assert "ai_translation_session=opaque-session-token" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/" in cookie
    assert "Domain=" not in cookie
    assert "opaque-session-token" not in str(response.json())
    assert "must-never-leak" not in str(response.json())


async def test_secure_cookie_setting_is_applied_without_a_domain(
    app: FastAPI, client: AsyncClient
) -> None:
    app.state.settings.session_cookie_secure = True
    app.dependency_overrides[get_auth_service] = LoginService

    response = await client.post(
        "/api/v1/auth/login",
        json={"loginName": "operator", "password": "Correct-Horse-9!"},
    )

    cookie = response.headers["set-cookie"]
    assert "Secure" in cookie
    assert "Domain=" not in cookie


async def test_admin_portal_login_sets_the_admin_session_cookie(
    app: FastAPI, client: AsyncClient
) -> None:
    service = LoginService()
    app.dependency_overrides[get_auth_service] = lambda: service

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "loginName": "operator",
            "password": "Correct-Horse-9!",
            "portal": "admin",
        },
    )

    assert response.status_code == 200
    assert service.login_portals == ["admin"]
    cookie = response.headers["set-cookie"]
    assert "ai_translation_admin_session=opaque-session-token" in cookie
    assert "ai_translation_session=" not in cookie.replace(
        "ai_translation_admin_session=", ""
    )


async def test_login_defaults_to_the_operator_portal(
    app: FastAPI, client: AsyncClient
) -> None:
    service = LoginService()
    app.dependency_overrides[get_auth_service] = lambda: service

    response = await client.post(
        "/api/v1/auth/login",
        json={"loginName": "operator", "password": "Correct-Horse-9!"},
    )

    assert response.status_code == 200
    assert service.login_portals == ["operator"]
    assert "ai_translation_session=opaque-session-token" in response.headers[
        "set-cookie"
    ]


async def test_login_rejects_an_unknown_portal_value(
    app: FastAPI, client: AsyncClient
) -> None:
    app.dependency_overrides[get_auth_service] = LoginService

    response = await client.post(
        "/api/v1/auth/login",
        json={
            "loginName": "operator",
            "password": "Correct-Horse-9!",
            "portal": "root",
        },
    )

    assert response.status_code == 422


async def test_require_account_reads_the_admin_cookie_for_admin_requests(
    app: FastAPI, client: AsyncClient
) -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    sessions = SessionLookup(SessionData(7, 3, "csrf-token", now, now))
    app.dependency_overrides[get_session_store] = lambda: sessions
    app.dependency_overrides[get_account_repository] = lambda: AccountLookup(
        account(role=Role.ADMIN, must_change_password=False)
    )
    client.cookies.set("ai_translation_admin_session", "browser-token")

    response = await client.get("/api/v1/auth/me", headers={"X-Portal": "admin"})

    assert response.status_code == 200
    assert response.json()["account"]["role"] == 9


async def test_require_account_does_not_fall_back_to_the_other_portal_cookie(
    app: FastAPI, client: AsyncClient
) -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    sessions = SessionLookup(SessionData(7, 3, "csrf-token", now, now))
    app.dependency_overrides[get_session_store] = lambda: sessions
    app.dependency_overrides[get_account_repository] = lambda: AccountLookup(
        account()
    )
    client.cookies.set("ai_translation_session", "browser-token")

    response = await client.get("/api/v1/auth/me", headers={"X-Portal": "admin"})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert sessions.revoked == []


async def test_logout_expires_the_admin_cookie_for_admin_portal_requests(
    app: FastAPI, client: AsyncClient
) -> None:
    service = LoginService()
    app.dependency_overrides[require_account] = lambda: auth_context()
    app.dependency_overrides[get_auth_service] = lambda: service

    response = await client.post(
        "/api/v1/auth/logout",
        headers={"X-CSRF-Token": "csrf-token", "X-Portal": "admin"},
    )

    assert response.status_code == 204
    cookie = response.headers["set-cookie"]
    assert "ai_translation_admin_session=" in cookie
    assert "Max-Age=0" in cookie


async def test_unknown_auth_route_is_not_cached(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/not-a-route")

    assert response.status_code == 404
    assert response.headers["Cache-Control"] == "no-store"


async def test_me_returns_public_account_and_current_csrf(
    app: FastAPI, client: AsyncClient
) -> None:
    app.dependency_overrides[require_account] = lambda: auth_context()

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["csrfToken"] == "csrf-token"
    assert response.json()["account"]["publicId"] == "01JTESTAUTHACCOUNT000000000"
    assert "id" not in response.json()["account"]
    assert "passwordHash" not in response.json()["account"]


@pytest.mark.parametrize("csrf_header", [None, "wrong-token"])
async def test_logout_rejects_missing_or_wrong_csrf(
    app: FastAPI, client: AsyncClient, csrf_header: str | None
) -> None:
    app.dependency_overrides[require_account] = lambda: auth_context()
    app.dependency_overrides[get_auth_service] = LoginService
    headers = {} if csrf_header is None else {"X-CSRF-Token": csrf_header}

    response = await client.post("/api/v1/auth/logout", headers=headers)

    assert response.status_code == 403
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["error"]["code"] == "CSRF_INVALID"


async def test_logout_revokes_only_current_session_and_expires_cookie(
    app: FastAPI, client: AsyncClient
) -> None:
    service = LoginService()
    app.dependency_overrides[require_account] = lambda: auth_context()
    app.dependency_overrides[get_auth_service] = lambda: service

    response = await client.post(
        "/api/v1/auth/logout", headers={"X-CSRF-Token": "csrf-token"}
    )

    assert response.status_code == 204
    assert service.logout_tokens == ["opaque-session-token"]
    cookie = response.headers["set-cookie"]
    assert "ai_translation_session=" in cookie
    assert "Max-Age=0" in cookie
    assert "Path=/" in cookie


async def test_password_change_requires_csrf_then_expires_session_cookie(
    app: FastAPI, client: AsyncClient
) -> None:
    service = LoginService()
    app.dependency_overrides[require_account] = lambda: auth_context()
    app.dependency_overrides[get_auth_service] = lambda: service
    payload = {
        "currentPassword": "Correct-Horse-9!",
        "newPassword": "New-Correct-Horse-10!",
    }

    missing = await client.post("/api/v1/auth/password", json=payload)
    changed = await client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": "csrf-token"},
        json=payload,
    )

    assert missing.status_code == 403
    assert changed.status_code == 204
    assert service.password_changes == [("Correct-Horse-9!", "New-Correct-Horse-10!")]
    assert "Max-Age=0" in changed.headers["set-cookie"]


async def test_password_change_accepts_any_six_character_new_password(
    app: FastAPI, client: AsyncClient
) -> None:
    service = LoginService()
    app.dependency_overrides[require_account] = lambda: auth_context()
    app.dependency_overrides[get_auth_service] = lambda: service

    response = await client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": "csrf-token"},
        json={
            "currentPassword": "Correct-Horse-9!",
            "newPassword": "123456",
        },
    )

    assert response.status_code == 204
    assert service.password_changes == [("Correct-Horse-9!", "123456")]


async def test_password_change_rejects_new_password_shorter_than_six_characters(
    app: FastAPI, client: AsyncClient
) -> None:
    service = LoginService()
    app.dependency_overrides[require_account] = lambda: auth_context()
    app.dependency_overrides[get_auth_service] = lambda: service

    response = await client.post(
        "/api/v1/auth/password",
        headers={"X-CSRF-Token": "csrf-token"},
        json={
            "currentPassword": "Correct-Horse-9!",
            "newPassword": "12345",
        },
    )

    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    assert service.password_changes == []


@pytest.mark.parametrize(
    ("status", "auth_version"),
    [
        (AccountStatus.DISABLED, 3),
        (AccountStatus.ACTIVE, 4),
    ],
)
async def test_disabled_or_auth_version_changed_account_revokes_session(
    app: FastAPI,
    client: AsyncClient,
    status: AccountStatus,
    auth_version: int,
) -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    sessions = SessionLookup(SessionData(7, 3, "csrf-token", now, now))
    invalid_account = account(status=status, auth_version=auth_version)
    app.dependency_overrides[get_session_store] = lambda: sessions
    app.dependency_overrides[get_account_repository] = lambda: AccountLookup(
        invalid_account
    )

    client.cookies.set("ai_translation_session", "browser-token")
    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert sessions.revoked == ["browser-token"]


async def test_missing_account_uses_generic_unauthorized_error_and_revokes_session(
    app: FastAPI, client: AsyncClient
) -> None:
    now = datetime(2026, 9, 1, tzinfo=UTC)
    sessions = SessionLookup(SessionData(7, 3, "csrf-token", now, now))
    app.dependency_overrides[get_session_store] = lambda: sessions
    app.dependency_overrides[get_account_repository] = lambda: AccountLookup(None)
    client.cookies.set("ai_translation_session", "browser-token")

    response = await client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    assert response.json()["error"]["message"] == "请先登录"
    assert sessions.revoked == ["browser-token"]


async def test_admin_and_password_ready_dependencies_enforce_policies() -> None:
    with pytest.raises(AppError) as operator_error:
        await require_admin(auth_context())
    assert (operator_error.value.status_code, operator_error.value.code) == (
        403,
        "FORBIDDEN",
    )

    with pytest.raises(AppError) as password_error:
        await require_password_ready(auth_context())
    assert password_error.value.code == "PASSWORD_CHANGE_REQUIRED"

    admin = auth_context(role=Role.ADMIN, must_change_password=False)
    assert await require_admin(admin) is admin
    assert await require_password_ready(admin) is admin


async def test_real_http_login_me_and_password_change_use_mysql_and_owned_redis_keys() -> (
    None
):
    migration_url = os.getenv(_MIGRATION_DATABASE_URL_ENV)
    runtime_url = os.getenv(_RUNTIME_DATABASE_URL_ENV)
    assert migration_url, f"{_MIGRATION_DATABASE_URL_ENV} must be configured"
    assert runtime_url, f"{_RUNTIME_DATABASE_URL_ENV} must be configured"
    login_name = f"task6-http-{uuid4().hex[:16]}"
    current_password = "Strong-Task6-Http-2026!"
    new_password = "New-Strong-Task6-Http-2026!"
    prefix = f"task6-http:{uuid4().hex}:"
    migration_engine = create_async_engine(migration_url, pool_pre_ping=True)
    public_id: str | None = None
    real_app = create_app(
        Settings(
            app_env="test",
            database_url=runtime_url,
            redis_url="redis://127.0.0.1:6379/15",
            redis_protocol=2,
            session_hash_key="task6-http-session-key-that-is-at-least-32-bytes",
        )
    )
    real_app.state.auth_key_prefix = prefix
    try:
        async with AsyncSession(migration_engine, expire_on_commit=False) as session:
            created = await AccountRepository(session).create(
                AccountCreate(
                    login_name=login_name,
                    display_name="Task 6 HTTP Operator",
                    password_hash=hash_password(current_password),
                )
            )
            await session.commit()
            public_id = created.public_id

        async with AsyncClient(
            transport=ASGITransport(app=real_app), base_url="http://127.0.0.1"
        ) as real_client:
            logged_in = await real_client.post(
                "/api/v1/auth/login",
                json={"loginName": login_name, "password": current_password},
            )
            token = real_client.cookies.get("ai_translation_session")
            assert logged_in.status_code == 200
            assert token is not None
            assert token not in str(logged_in.json())
            csrf_token = logged_in.json()["csrfToken"]

            current = await real_client.get("/api/v1/auth/me")
            changed = await real_client.post(
                "/api/v1/auth/password",
                headers={"X-CSRF-Token": csrf_token},
                json={
                    "currentPassword": current_password,
                    "newPassword": new_password,
                },
            )
            real_client.cookies.set("ai_translation_session", token)
            old_session = await real_client.get("/api/v1/auth/me")

        assert current.status_code == 200
        assert changed.status_code == 204
        assert "Max-Age=0" in changed.headers["set-cookie"]
        assert old_session.status_code == 401
        assert old_session.json()["error"]["code"] == "UNAUTHORIZED"
        async with AsyncSession(migration_engine) as session:
            audits = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(AuditLog.resource_public_id == public_id)
                        .order_by(AuditLog.id)
                    )
                )
                .scalars()
                .all()
            )
        assert [audit.action for audit in audits] == [
            "LOGIN_SUCCEEDED",
            "PASSWORD_CHANGED",
        ]
        assert all(audit.request_id for audit in audits)
        assert all(audit.ip_address == b"\x7f\x00\x00\x01" for audit in audits)
        assert current_password not in str([audit.after_data for audit in audits])
        assert new_password not in str([audit.after_data for audit in audits])
    finally:
        redis = real_app.state.redis_manager.client
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await redis.delete(*keys)
        await real_app.state.database_manager.close()
        await real_app.state.redis_manager.close()
        if public_id is not None:
            async with migration_engine.begin() as connection:
                await connection.execute(
                    delete(AuditLog).where(AuditLog.resource_public_id == public_id)
                )
                await connection.execute(
                    delete(UserAccount).where(UserAccount.login_name == login_name)
                )
        await migration_engine.dispose()


async def test_portal_role_mismatch_and_dual_session_coexistence() -> None:
    migration_url = os.getenv(_MIGRATION_DATABASE_URL_ENV)
    runtime_url = os.getenv(_RUNTIME_DATABASE_URL_ENV)
    assert migration_url, f"{_MIGRATION_DATABASE_URL_ENV} must be configured"
    assert runtime_url, f"{_RUNTIME_DATABASE_URL_ENV} must be configured"
    suffix = uuid4().hex[:12]
    operator_login = f"portal-op-{suffix}"
    admin_login = f"portal-admin-{suffix}"
    password = "Strong-Portal-2026!"
    prefix = f"portal-test:{uuid4().hex}:"
    migration_engine = create_async_engine(migration_url, pool_pre_ping=True)
    real_app = create_app(
        Settings(
            app_env="test",
            database_url=runtime_url,
            redis_url="redis://127.0.0.1:6379/15",
            redis_protocol=2,
            session_hash_key="portal-test-session-key-that-is-at-least-32-bytes",
        )
    )
    real_app.state.auth_key_prefix = prefix
    try:
        async with AsyncSession(migration_engine, expire_on_commit=False) as session:
            repository = AccountRepository(session)
            operator_account = await repository.create(
                AccountCreate(
                    login_name=operator_login,
                    display_name="Portal Operator",
                    password_hash=hash_password(password),
                    must_change_password=False,
                )
            )
            admin_account = await repository.create(
                AccountCreate(
                    login_name=admin_login,
                    display_name="Portal Admin",
                    password_hash=hash_password(password),
                    role=Role.ADMIN,
                    must_change_password=False,
                )
            )
            await session.commit()

        async with AsyncClient(
            transport=ASGITransport(app=real_app), base_url="http://127.0.0.1"
        ) as real_client:
            admin_via_operator = await real_client.post(
                "/api/v1/auth/login",
                json={"loginName": admin_login, "password": password},
            )
            assert admin_via_operator.status_code == 403
            assert admin_via_operator.json()["error"]["code"] == "ROLE_PORTAL_MISMATCH"
            assert (
                admin_via_operator.json()["error"]["message"]
                == "该账号为管理员，请从管理后台入口登录"
            )
            assert real_client.cookies.get("ai_translation_session") is None
            assert real_client.cookies.get("ai_translation_admin_session") is None

            operator_via_admin = await real_client.post(
                "/api/v1/auth/login",
                json={
                    "loginName": operator_login,
                    "password": password,
                    "portal": "admin",
                },
            )
            assert operator_via_admin.status_code == 403
            assert operator_via_admin.json()["error"]["code"] == "ROLE_PORTAL_MISMATCH"
            assert (
                operator_via_admin.json()["error"]["message"]
                == "该账号为运营成员，请从工作台入口登录"
            )

            operator_logged_in = await real_client.post(
                "/api/v1/auth/login",
                json={"loginName": operator_login, "password": password},
            )
            assert operator_logged_in.status_code == 200
            assert real_client.cookies.get("ai_translation_session") is not None

            admin_logged_in = await real_client.post(
                "/api/v1/auth/login",
                json={
                    "loginName": admin_login,
                    "password": password,
                    "portal": "admin",
                },
            )
            assert admin_logged_in.status_code == 200
            assert real_client.cookies.get("ai_translation_admin_session") is not None

            operator_me = await real_client.get(
                "/api/v1/auth/me", headers={"X-Portal": "operator"}
            )
            assert operator_me.status_code == 200
            assert (
                operator_me.json()["account"]["publicId"]
                == operator_account.public_id
            )

            admin_dashboard = await real_client.get("/api/v1/admin/dashboard")
            assert admin_dashboard.status_code == 200

            admin_me = await real_client.get(
                "/api/v1/auth/me", headers={"X-Portal": "admin"}
            )
            assert admin_me.status_code == 200
            assert admin_me.json()["account"]["publicId"] == admin_account.public_id

        async with AsyncSession(migration_engine) as session:
            audits = (
                (
                    await session.execute(
                        select(AuditLog)
                        .where(
                            AuditLog.resource_public_id.in_(
                                [
                                    operator_account.public_id,
                                    admin_account.public_id,
                                ]
                            )
                        )
                        .order_by(AuditLog.id)
                    )
                )
                .scalars()
                .all()
            )
        mismatch_audits = [
            audit for audit in audits if audit.action == "LOGIN_PORTAL_MISMATCH"
        ]
        assert len(mismatch_audits) == 2
    finally:
        redis = real_app.state.redis_manager.client
        keys = [key async for key in redis.scan_iter(match=f"{prefix}*")]
        if keys:
            await redis.delete(*keys)
        await real_app.state.database_manager.close()
        await real_app.state.redis_manager.close()
        async with migration_engine.begin() as connection:
            await connection.execute(
                delete(AuditLog).where(
                    AuditLog.resource_public_id.in_(
                        [operator_account.public_id, admin_account.public_id]
                    )
                )
            )
            await connection.execute(
                delete(UserAccount).where(
                    UserAccount.login_name.in_([operator_login, admin_login])
                )
            )
        await migration_engine.dispose()
