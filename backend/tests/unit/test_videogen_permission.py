from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.account import routes as account_routes
from app.modules.account.model import AccountStatus, Role
from app.modules.account.repository import AccountRepository
from app.modules.account.schemas import AccountRecord
from app.modules.account.service import AccountManagementService
from app.modules.audit.model import AuditLog
from app.modules.auth.dependencies import (
    AuthContext,
    require_account,
    require_admin,
    require_csrf,
    require_password_ready,
)
from app.modules.auth.sessions import SessionData, SessionStore
from app.modules.videogen import routes as videogen_routes


def _account(
    *,
    videogen_enabled: bool = False,
    role: Role = Role.OPERATOR,
) -> AccountRecord:
    now = datetime(2026, 11, 20, tzinfo=UTC)
    return AccountRecord(
        id=7,
        public_id="01JTESTVIDEOGENPERM00000000",
        login_name="operator",
        display_name="Operator",
        role=role,
        status=AccountStatus.ACTIVE,
        password_hash="must-never-leak",
        must_change_password=False,
        videogen_enabled=videogen_enabled,
        password_changed_at=None,
        last_login_at=None,
        created_by=None,
        auth_version=1,
        version=4,
        created_at=now,
        updated_at=now,
    )


def _context(account: AccountRecord) -> AuthContext:
    now = datetime(2026, 11, 20, tzinfo=UTC)
    return AuthContext(
        token="opaque-session-token",
        session=SessionData(account.id, account.auth_version, "csrf-token", now, now),
        account=account,
    )


def _override_identity(app: FastAPI, account: AccountRecord) -> None:
    context = _context(account)
    app.dependency_overrides[require_account] = lambda: context
    app.dependency_overrides[require_password_ready] = lambda: context
    app.dependency_overrides[require_csrf] = lambda: context


class _VideoGenServiceStub:
    async def create(
        self,
        account_id: int,
        prompt: str,
        tier: int,
        resolution: str,
        duration_seconds: int,
        reference: str,
    ) -> object:
        raise AppError("VIDEO_PROMPT_REQUIRED", "请填写视频描述", status_code=400)

    async def list_jobs(
        self, account_id: int, *, limit: int, offset: int
    ) -> list[object]:
        return []


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("POST", "/api/v1/videos"),
        ("GET", "/api/v1/videos"),
        ("GET", "/api/v1/videos/01M1GTESTVIDEOJOB0000000000"),
        ("GET", "/api/v1/videos/01M1GTESTVIDEOJOB0000000000/video"),
        ("GET", "/api/v1/videos/01M1GTESTVIDEOJOB0000000000/reference"),
    ],
)
async def test_videogen_routes_reject_accounts_without_permission(
    app: FastAPI, client: AsyncClient, method: str, url: str
) -> None:
    _override_identity(app, _account(videogen_enabled=False))
    app.dependency_overrides[videogen_routes._service] = _VideoGenServiceStub

    response = await client.request(method, url, json={})

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "VIDEOGEN_FORBIDDEN"


async def test_videogen_create_passes_permission_and_reaches_validation(
    app: FastAPI, client: AsyncClient
) -> None:
    _override_identity(app, _account(videogen_enabled=True))
    app.dependency_overrides[videogen_routes._service] = _VideoGenServiceStub

    response = await client.post("/api/v1/videos", json={"prompt": ""})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VIDEO_PROMPT_REQUIRED"


async def test_videogen_list_passes_for_permitted_account(
    app: FastAPI, client: AsyncClient
) -> None:
    _override_identity(app, _account(videogen_enabled=True))
    app.dependency_overrides[videogen_routes._service] = _VideoGenServiceStub

    response = await client.get("/api/v1/videos")

    assert response.status_code == 200
    assert response.json() == {"items": []}


class _AccountManagementStub:
    def __init__(self, target: AccountRecord) -> None:
        self._target = target
        self.calls: list[dict[str, object]] = []

    async def set_videogen_permission(
        self,
        *,
        actor: AccountRecord,
        public_id: str,
        expected_version: int,
        enabled: bool,
        ip_address: str | None,
    ) -> AccountRecord:
        self.calls.append(
            {
                "actor": actor,
                "public_id": public_id,
                "expected_version": expected_version,
                "enabled": enabled,
                "ip_address": ip_address,
            }
        )
        assert public_id == self._target.public_id
        return replace(self._target, videogen_enabled=enabled)


async def test_admin_can_toggle_videogen_permission(
    app: FastAPI, client: AsyncClient
) -> None:
    admin = _account(role=Role.ADMIN)
    _override_identity(app, admin)
    app.dependency_overrides[require_admin] = lambda: _context(admin)
    stub = _AccountManagementStub(_account())
    app.dependency_overrides[account_routes.get_account_management_service] = lambda: (
        stub
    )

    response = await client.post(
        "/api/v1/admin/accounts/01JTESTVIDEOGENPERM00000000/videogen-permission",
        json={"version": 4, "enabled": True},
    )

    assert response.status_code == 200
    assert response.json()["account"]["videogenEnabled"] is True
    assert stub.calls == [
        {
            "actor": admin,
            "public_id": "01JTESTVIDEOGENPERM00000000",
            "expected_version": 4,
            "enabled": True,
            "ip_address": "127.0.0.1",
        }
    ]


async def test_videogen_permission_route_requires_admin(
    app: FastAPI, client: AsyncClient
) -> None:
    _override_identity(app, _account())
    app.dependency_overrides[account_routes.get_account_management_service] = lambda: (
        _AccountManagementStub(_account())
    )

    response = await client.post(
        "/api/v1/admin/accounts/01JTESTVIDEOGENPERM00000000/videogen-permission",
        json={"version": 4, "enabled": True},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


class _AccountsStub:
    def __init__(self, target: AccountRecord | None) -> None:
        self._target = target

    async def get_by_public_id_for_update(self, public_id: str) -> AccountRecord | None:
        if self._target is not None:
            assert public_id == self._target.public_id
        return self._target

    async def save(
        self, account: AccountRecord, *, expected_version: int
    ) -> AccountRecord:
        assert self._target is not None
        assert expected_version == self._target.version
        return replace(account, version=account.version + 1)


class _TransactionStub:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    def add(self, value: object) -> None:
        self.added.append(value)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _management_service(
    accounts: _AccountsStub, transaction: _TransactionStub
) -> AccountManagementService:
    return AccountManagementService(
        cast(AccountRepository, accounts),
        cast(SessionStore, object()),
        cast(AsyncSession, transaction),
        request_id="req-videogen-permission",
    )


async def test_set_videogen_permission_updates_flag_and_writes_audit() -> None:
    target = _account(videogen_enabled=False)
    accounts = _AccountsStub(target)
    transaction = _TransactionStub()
    service = _management_service(accounts, transaction)

    saved = await service.set_videogen_permission(
        actor=_account(role=Role.ADMIN),
        public_id=target.public_id,
        expected_version=target.version,
        enabled=True,
        ip_address="127.0.0.1",
    )

    assert saved.videogen_enabled is True
    assert transaction.commits == 1
    audits = [row for row in transaction.added if isinstance(row, AuditLog)]
    assert len(audits) == 1
    audit = audits[0]
    assert audit.action == "ACCOUNT_VIDEOGEN_PERMISSION_UPDATED"
    assert audit.resource_type == "account"
    assert audit.resource_public_id == target.public_id
    assert audit.before_data == {"videogenEnabled": False}
    assert audit.after_data == {"videogenEnabled": True}


async def test_set_videogen_permission_rejects_unknown_account() -> None:
    accounts = _AccountsStub(None)
    transaction = _TransactionStub()
    service = _management_service(accounts, transaction)

    with pytest.raises(AppError) as caught:
        await service.set_videogen_permission(
            actor=_account(role=Role.ADMIN),
            public_id="01JTESTMISSING000000000000",
            expected_version=1,
            enabled=True,
            ip_address=None,
        )

    assert caught.value.code == "ACCOUNT_NOT_FOUND"
    assert transaction.commits == 0
    assert transaction.rollbacks == 1
