from datetime import datetime
from enum import IntEnum

from sqlalchemy import Boolean, CheckConstraint, Index, text
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DATETIME, INTEGER, TINYINT, VARCHAR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Role(IntEnum):
    OPERATOR = 1
    ADMIN = 9


class AccountStatus(IntEnum):
    ACTIVE = 1
    DISABLED = 2


class UserAccount(Base):
    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint("role IN (1, 9)", name="ck_user_account_role"),
        CheckConstraint("status IN (1, 2)", name="ck_user_account_status"),
        Index("uk_user_account_login_name", "login_name", unique=True),
        Index("uk_user_account_public_id", "public_id", unique=True),
        Index("idx_user_account_status_created_at", "status", "created_at"),
        {
            "comment": "Internal operator and administrator accounts",
            "mysql_charset": "utf8mb4",
            "mysql_collate": "utf8mb4_0900_ai_ci",
            "mysql_engine": "InnoDB",
        },
    )

    id: Mapped[int] = mapped_column(
        BIGINT(unsigned=True),
        primary_key=True,
        autoincrement=True,
        comment="Primary key",
    )
    public_id: Mapped[str] = mapped_column(
        CHAR(26), nullable=False, comment="Public ULID identifier"
    )
    login_name: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment="Normalized casefolded login name"
    )
    display_name: Mapped[str] = mapped_column(
        VARCHAR(64), nullable=False, comment="Internal display name"
    )
    role: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, comment="1 operator, 9 administrator"
    )
    status: Mapped[int] = mapped_column(
        TINYINT(unsigned=True), nullable=False, comment="1 active, 2 disabled"
    )
    password_hash: Mapped[str] = mapped_column(
        VARCHAR(255), nullable=False, comment="Argon2id password hash"
    )
    must_change_password: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("1"),
        comment="1 requires password change",
    )
    videogen_enabled: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("0"),
        comment="1 permits image-to-video generation",
    )
    password_changed_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="UTC password change timestamp"
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DATETIME(fsp=3), nullable=True, comment="UTC successful login timestamp"
    )
    created_by: Mapped[int | None] = mapped_column(
        BIGINT(unsigned=True), nullable=True, comment="Logical creator account id"
    )
    auth_version: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Session invalidation version",
    )
    version: Mapped[int] = mapped_column(
        INTEGER(unsigned=True),
        nullable=False,
        server_default=text("1"),
        comment="Optimistic lock version",
    )
    created_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC creation timestamp"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DATETIME(fsp=3), nullable=False, comment="UTC last update timestamp"
    )
