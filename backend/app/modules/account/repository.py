from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import Select, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.core.security import normalize_login_name, validate_password_hash
from app.modules.account.model import AccountStatus, Role, UserAccount
from app.modules.account.schemas import AccountCreate, AccountPage, AccountRecord


class AccountConflictError(Exception):
    """A create or update conflicts with existing account data."""


class AccountVersionConflictError(AccountConflictError):
    """An account changed after the caller loaded it."""


_ACCOUNT_COLUMNS = (
    UserAccount.id,
    UserAccount.public_id,
    UserAccount.login_name,
    UserAccount.display_name,
    UserAccount.role,
    UserAccount.status,
    UserAccount.password_hash,
    UserAccount.must_change_password,
    UserAccount.videogen_enabled,
    UserAccount.password_changed_at,
    UserAccount.last_login_at,
    UserAccount.created_by,
    UserAccount.auth_version,
    UserAccount.version,
    UserAccount.created_at,
    UserAccount.updated_at,
)


def _utc_now_milliseconds() -> datetime:
    value = datetime.now(UTC).replace(tzinfo=None)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _to_record(row: dict[str, Any]) -> AccountRecord:
    return AccountRecord(
        id=int(row["id"]),
        public_id=str(row["public_id"]),
        login_name=str(row["login_name"]),
        display_name=str(row["display_name"]),
        role=Role(int(row["role"])),
        status=AccountStatus(int(row["status"])),
        password_hash=str(row["password_hash"]),
        must_change_password=bool(row["must_change_password"]),
        videogen_enabled=bool(row["videogen_enabled"]),
        password_changed_at=row["password_changed_at"],
        last_login_at=row["last_login_at"],
        created_by=row["created_by"],
        auth_version=int(row["auth_version"]),
        version=int(row["version"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_login_name(self, login_name: str) -> AccountRecord | None:
        statement = select(*_ACCOUNT_COLUMNS).where(
            UserAccount.login_name == normalize_login_name(login_name)
        )
        return await self._one_or_none(statement)

    async def get_by_public_id(self, public_id: str) -> AccountRecord | None:
        statement = select(*_ACCOUNT_COLUMNS).where(UserAccount.public_id == public_id)
        return await self._one_or_none(statement)

    async def get_by_public_id_for_update(self, public_id: str) -> AccountRecord | None:
        """Load one account under the caller's short mutation transaction."""
        statement = (
            select(*_ACCOUNT_COLUMNS)
            .where(UserAccount.public_id == public_id)
            .with_for_update()
        )
        return await self._one_or_none(statement)

    async def get_by_id(self, account_id: int) -> AccountRecord | None:
        statement = select(*_ACCOUNT_COLUMNS).where(UserAccount.id == account_id)
        return await self._one_or_none(statement)

    async def create(self, data: AccountCreate) -> AccountRecord:
        validate_password_hash(data.password_hash)
        now = _utc_now_milliseconds()
        account = UserAccount(
            public_id=str(ULID()),
            login_name=normalize_login_name(data.login_name),
            display_name=data.display_name,
            role=int(data.role),
            status=int(data.status),
            password_hash=data.password_hash,
            must_change_password=data.must_change_password,
            videogen_enabled=False,
            password_changed_at=None,
            last_login_at=None,
            created_by=data.created_by,
            auth_version=1,
            version=1,
            created_at=now,
            updated_at=now,
        )
        try:
            async with self._session.begin_nested():
                self._session.add(account)
                await self._session.flush()
        except IntegrityError:
            raise AccountConflictError("account data conflict") from None

        return AccountRecord(
            id=account.id,
            public_id=account.public_id,
            login_name=account.login_name,
            display_name=account.display_name,
            role=Role(account.role),
            status=AccountStatus(account.status),
            password_hash=account.password_hash,
            must_change_password=account.must_change_password,
            videogen_enabled=bool(account.videogen_enabled),
            password_changed_at=account.password_changed_at,
            last_login_at=account.last_login_at,
            created_by=account.created_by,
            auth_version=account.auth_version,
            version=account.version,
            created_at=account.created_at,
            updated_at=account.updated_at,
        )

    async def list_page(
        self,
        *,
        cursor: int | None = None,
        limit: int = 20,
    ) -> AccountPage:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")

        statement = select(*_ACCOUNT_COLUMNS)
        if cursor is not None:
            statement = statement.where(UserAccount.id < cursor)
        statement = statement.order_by(UserAccount.id.desc()).limit(limit + 1)
        result = await self._session.execute(statement)
        records = tuple(_to_record(dict(row)) for row in result.mappings())
        items = records[:limit]
        next_cursor = items[-1].id if len(records) > limit else None
        return AccountPage(items=items, next_cursor=next_cursor)

    async def save(
        self,
        account: AccountRecord,
        *,
        expected_version: int,
    ) -> AccountRecord:
        validate_password_hash(account.password_hash)
        statement = (
            update(UserAccount)
            .where(
                UserAccount.id == account.id,
                UserAccount.version == expected_version,
            )
            .values(
                login_name=normalize_login_name(account.login_name),
                display_name=account.display_name,
                role=int(account.role),
                status=int(account.status),
                password_hash=account.password_hash,
                must_change_password=account.must_change_password,
                videogen_enabled=account.videogen_enabled,
                password_changed_at=account.password_changed_at,
                last_login_at=account.last_login_at,
                auth_version=account.auth_version,
                version=expected_version + 1,
                updated_at=_utc_now_milliseconds(),
            )
        )
        try:
            result = cast(
                CursorResult[Any],
                await self._session.execute(statement),
            )
        except IntegrityError:
            raise AccountConflictError("account data conflict") from None
        if result.rowcount != 1:
            raise AccountVersionConflictError("account version conflict")

        saved = await self.get_by_id(account.id)
        if saved is None:
            raise AccountVersionConflictError("account version conflict")
        return saved

    async def count_active_admins_for_update(self) -> int:
        statement = (
            select(UserAccount.id)
            .where(
                UserAccount.role == int(Role.ADMIN),
                UserAccount.status == int(AccountStatus.ACTIVE),
            )
            .with_for_update()
        )
        result = await self._session.execute(statement)
        return len(result.scalars().all())

    async def _one_or_none(self, statement: Select[Any]) -> AccountRecord | None:
        result = await self._session.execute(statement)
        row = result.mappings().one_or_none()
        return None if row is None else _to_record(dict(row))
