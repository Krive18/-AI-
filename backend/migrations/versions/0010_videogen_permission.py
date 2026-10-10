"""Grant video generation permission per account.

Revision ID: 0010_videogen_permission
Revises: 0009_video_generation
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_videogen_permission"
down_revision: str | None = "0009_video_generation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_account",
        sa.Column(
            "videogen_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
            comment="1 permits image-to-video generation",
        ),
    )


def downgrade() -> None:
    op.drop_column("user_account", "videogen_enabled")
