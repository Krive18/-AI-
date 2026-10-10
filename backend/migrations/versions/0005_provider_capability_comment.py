"""Update provider capability metadata for simultaneous interpretation.

Revision ID: 0005_provider_capability_comment
Revises: 0004_provider_simultaneous
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "0005_provider_capability_comment"
down_revision: str | None = "0004_provider_simultaneous"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS 4 simultaneous interpretation",
    )


def downgrade() -> None:
    op.alter_column(
        "provider_config",
        "capability",
        existing_type=mysql.TINYINT(unsigned=True),
        existing_nullable=False,
        comment="1 ASR 2 translation 3 TTS",
    )
