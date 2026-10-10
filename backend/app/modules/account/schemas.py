from dataclasses import dataclass
from datetime import datetime

from app.modules.account.model import AccountStatus, Role


@dataclass(frozen=True, slots=True)
class AccountCreate:
    login_name: str
    display_name: str
    password_hash: str
    role: Role = Role.OPERATOR
    status: AccountStatus = AccountStatus.ACTIVE
    must_change_password: bool = True
    created_by: int | None = None


@dataclass(frozen=True, slots=True)
class AccountRecord:
    id: int
    public_id: str
    login_name: str
    display_name: str
    role: Role
    status: AccountStatus
    password_hash: str
    must_change_password: bool
    videogen_enabled: bool
    password_changed_at: datetime | None
    last_login_at: datetime | None
    created_by: int | None
    auth_version: int
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class AccountPage:
    items: tuple[AccountRecord, ...]
    next_cursor: int | None
