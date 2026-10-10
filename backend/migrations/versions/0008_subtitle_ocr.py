"""Add subtitle OCR translation mode and provider capability.

Revision ID: 0008_subtitle_ocr
Revises: 0007_image_generation
Create Date: 2026-10-08
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0008_subtitle_ocr"
down_revision: str | None = "0007_image_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


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


def _replace_mode_constraint(values: str) -> None:
    op.drop_constraint(
        "ck_translation_project_mode", "translation_project", type_="check"
    )
    op.create_check_constraint(
        "ck_translation_project_mode",
        "translation_project",
        f"translation_mode IN ({values})",
    )


def upgrade() -> None:
    _replace_capability_constraints("1,2,3,4,5,6")
    _replace_mode_constraint("'professional','youdao','subtitle'")
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation 5 image generation 6 subtitle OCR",
    )
    op.alter_column(
        "translation_project",
        "translation_mode",
        existing_type=mysql.VARCHAR(24),
        existing_nullable=False,
        comment="Selected processing path: professional, youdao, or subtitle",
    )


def downgrade() -> None:
    op.alter_column(
        "translation_project",
        "translation_mode",
        existing_type=mysql.VARCHAR(24),
        existing_nullable=False,
        comment="Selected processing path: professional or youdao",
    )
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation 5 image generation",
    )
    _replace_mode_constraint("'professional','youdao'")
    _replace_capability_constraints("1,2,3,4,5")
