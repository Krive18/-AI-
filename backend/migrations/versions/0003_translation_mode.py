"""Add the selected translation processing path.

Revision ID: 0003_translation_mode
Revises: 0002_translation_data
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0003_translation_mode"
down_revision: str | None = "0002_translation_data"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "translation_project",
        sa.Column(
            "translation_mode",
            mysql.VARCHAR(24),
            nullable=False,
            server_default=sa.text("'professional'"),
            comment="Selected processing path: professional or youdao",
        ),
    )
    op.create_check_constraint(
        "ck_translation_project_mode",
        "translation_project",
        "translation_mode IN ('professional','youdao')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_translation_project_mode", "translation_project", type_="check"
    )
    op.drop_column("translation_project", "translation_mode")
