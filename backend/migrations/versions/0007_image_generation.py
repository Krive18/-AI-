"""Add image generation capability and job table.

Revision ID: 0007_image_generation
Revises: 0006_expand_target_locales
Create Date: 2026-09-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0007_image_generation"
down_revision: str | None = "0006_expand_target_locales"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE_OPTIONS = {
    "mysql_charset": "utf8mb4",
    "mysql_collate": "utf8mb4_0900_ai_ci",
    "mysql_engine": "InnoDB",
}


def _replace_capability_constraints(values: str) -> None:
    for table_name, constraint_name in (
        ("provider_config", "ck_provider_config_capability"),
        ("provider_price", "ck_provider_price_capability"),
        ("ai_usage_record", "ck_ai_usage_record_capability"),
    ):
        op.drop_constraint(constraint_name, table_name, type_="check")
        op.create_check_constraint(
            constraint_name, table_name, f"capability IN ({values})"
        )


def upgrade() -> None:
    _replace_capability_constraints("1,2,3,4,5")
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation 5 image generation",
    )
    op.create_table(
        "image_generation",
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
            "account_id",
            mysql.BIGINT(unsigned=True),
            nullable=False,
            comment="Logical creator account id",
        ),
        sa.Column(
            "prompt", mysql.VARCHAR(2000), nullable=False, comment="Image prompt"
        ),
        sa.Column(
            "size", mysql.VARCHAR(8), nullable=False, comment="Requested image size"
        ),
        sa.Column(
            "count",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            comment="Requested image count from 1 to 3",
        ),
        sa.Column(
            "reference_count",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            comment="Reference image count from 0 to 3",
        ),
        sa.Column(
            "status",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            server_default=sa.text("1"),
            comment="1 pending 2 running 3 succeeded 4 failed",
        ),
        sa.Column(
            "error_code",
            mysql.VARCHAR(64),
            nullable=True,
            comment="Stable failure code",
        ),
        sa.Column(
            "error_message",
            mysql.VARCHAR(512),
            nullable=True,
            comment="Safe displayable failure message",
        ),
        sa.Column(
            "created_at",
            mysql.DATETIME(fsp=3),
            nullable=False,
            comment="UTC creation time",
        ),
        sa.Column(
            "finished_at",
            mysql.DATETIME(fsp=3),
            nullable=True,
            comment="UTC terminal completion time",
        ),
        sa.CheckConstraint("count BETWEEN 1 AND 3", name="ck_image_generation_count"),
        sa.CheckConstraint(
            "reference_count BETWEEN 0 AND 3",
            name="ck_image_generation_reference_count",
        ),
        sa.CheckConstraint(
            "status IN (1,2,3,4)", name="ck_image_generation_status"
        ),
        comment="AI image generation jobs and their prompt settings",
        **TABLE_OPTIONS,
    )
    op.create_index(
        "uk_image_generation_public_id", "image_generation", ["public_id"], unique=True
    )
    op.create_index(
        "idx_image_generation_account_created",
        "image_generation",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("image_generation")
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation",
    )
    _replace_capability_constraints("1,2,3,4")
