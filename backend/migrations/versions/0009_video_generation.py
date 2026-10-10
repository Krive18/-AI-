"""Add video generation capability and job table.

Revision ID: 0009_video_generation
Revises: 0008_subtitle_ocr
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0009_video_generation"
down_revision: str | None = "0008_subtitle_ocr"
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
    _replace_capability_constraints("1,2,3,4,5,6,7")
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation 5 image generation 6 subtitle OCR 7 video generation",
    )
    op.create_table(
        "video_generation",
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
            "prompt", mysql.VARCHAR(2000), nullable=False, comment="Video prompt"
        ),
        sa.Column(
            "size",
            mysql.VARCHAR(8),
            nullable=False,
            comment="Requested video resolution 480p or 720p",
        ),
        sa.Column(
            "duration_seconds",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            comment="Requested video duration in seconds",
        ),
        sa.Column(
            "tier",
            mysql.TINYINT(unsigned=True),
            nullable=False,
            comment="Quality tier 1 standard 2 fast 3 mini",
        ),
        sa.Column(
            "reference_object_key",
            mysql.VARCHAR(512),
            nullable=True,
            comment="Private storage object key of the first-frame reference image",
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
        sa.CheckConstraint("size IN ('480p','720p')", name="ck_video_generation_size"),
        sa.CheckConstraint(
            "duration_seconds IN (5,10,15,20,25,30)",
            name="ck_video_generation_duration",
        ),
        sa.CheckConstraint("tier IN (1,2,3)", name="ck_video_generation_tier"),
        sa.CheckConstraint(
            "status IN (1,2,3,4)", name="ck_video_generation_status"
        ),
        comment="AI video generation jobs and their prompt settings",
        **TABLE_OPTIONS,
    )
    op.create_index(
        "uk_video_generation_public_id", "video_generation", ["public_id"], unique=True
    )
    op.create_index(
        "idx_video_generation_account_created",
        "video_generation",
        ["account_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("video_generation")
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation 5 image generation 6 subtitle OCR",
    )
    _replace_capability_constraints("1,2,3,4,5,6")
