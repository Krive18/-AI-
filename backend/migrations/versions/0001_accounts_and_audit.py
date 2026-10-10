"""Create account and audit tables.

Revision ID: 0001_accounts_and_audit
Revises:
Create Date: 2026-09-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0001_accounts_and_audit"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


MYSQL_TABLE_OPTIONS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def upgrade() -> None:
    op.create_table(
        "user_account",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            primary_key=True,
            autoincrement=True,
            comment="Primary key",
        ),
        sa.Column(
            "public_id",
            mysql.CHAR(26),
            nullable=False,
            comment="Public ULID identifier",
        ),
        sa.Column(
            "login_name",
            mysql.VARCHAR(64),
            nullable=False,
            comment="Normalized casefolded login name",
        ),
        sa.Column(
            "display_name",
            mysql.VARCHAR(64),
            nullable=False,
            comment="Internal display name",
        ),
        sa.Column(
            "role",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            comment="1 operator, 9 administrator",
        ),
        sa.Column(
            "status",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            comment="1 active, 2 disabled",
        ),
        sa.Column(
            "password_hash",
            mysql.VARCHAR(255),
            nullable=False,
            comment="Argon2id password hash",
        ),
        sa.Column(
            "must_change_password",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
            comment="1 requires password change",
        ),
        sa.Column(
            "password_changed_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
            comment="UTC password change timestamp",
        ),
        sa.Column(
            "last_login_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
            comment="UTC successful login timestamp",
        ),
        sa.Column(
            "created_by",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="Logical creator account id",
        ),
        sa.Column(
            "auth_version",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("1"),
            comment="Session invalidation version",
        ),
        sa.Column(
            "version",
            mysql.INTEGER(unsigned=True),
            nullable=False,
            server_default=sa.text("1"),
            comment="Optimistic lock version",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            comment="UTC creation timestamp",
        ),
        sa.Column(
            "updated_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            comment="UTC last update timestamp",
        ),
        sa.CheckConstraint("role IN (1, 9)", name="ck_user_account_role"),
        sa.CheckConstraint("status IN (1, 2)", name="ck_user_account_status"),
        sa.PrimaryKeyConstraint("id"),
        comment="Internal operator and administrator accounts",
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "uk_user_account_login_name", "user_account", ["login_name"], unique=True
    )
    op.create_index(
        "uk_user_account_public_id", "user_account", ["public_id"], unique=True
    )
    op.create_index(
        "idx_user_account_status_created_at", "user_account", ["status", "created_at"]
    )

    op.create_table(
        "audit_log",
        sa.Column(
            "id",
            mysql.BIGINT(unsigned=True),
            primary_key=True,
            autoincrement=True,
            comment="Primary key",
        ),
        sa.Column(
            "actor_id",
            mysql.BIGINT(unsigned=True),
            nullable=True,
            comment="Logical actor account id",
        ),
        sa.Column(
            "action",
            mysql.VARCHAR(64),
            nullable=False,
            comment="Stable audit action code",
        ),
        sa.Column(
            "resource_type",
            mysql.VARCHAR(64),
            nullable=False,
            comment="Audited resource type",
        ),
        sa.Column(
            "resource_public_id",
            mysql.CHAR(26),
            nullable=True,
            comment="Audited resource public identifier",
        ),
        sa.Column(
            "request_id",
            mysql.VARCHAR(64),
            nullable=False,
            comment="Correlated API request identifier",
        ),
        sa.Column(
            "ip_address",
            mysql.VARBINARY(16),
            nullable=True,
            comment="Packed IPv4 or IPv6 address",
        ),
        sa.Column(
            "before_data",
            mysql.JSON(),
            nullable=True,
            comment="Redacted state before the action",
        ),
        sa.Column(
            "after_data",
            mysql.JSON(),
            nullable=True,
            comment="Redacted state after the action",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            comment="UTC event timestamp",
        ),
        sa.PrimaryKeyConstraint("id"),
        comment="Append-only security and operation audit events",
        **MYSQL_TABLE_OPTIONS,
    )
    op.create_index(
        "idx_audit_log_actor_id_created_at", "audit_log", ["actor_id", "created_at"]
    )
    op.create_index(
        "idx_audit_log_resource_created_at",
        "audit_log",
        ["resource_type", "resource_public_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("user_account")
