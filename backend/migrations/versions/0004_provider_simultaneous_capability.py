"""Add simultaneous interpretation provider capability.

Revision ID: 0004_provider_simultaneous
Revises: 0003_translation_mode
Create Date: 2026-09-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004_provider_simultaneous"
down_revision: str | None = "0003_translation_mode"
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


def upgrade() -> None:
    _replace_capability_constraints("1,2,3,4")


def downgrade() -> None:
    _replace_capability_constraints("1,2,3")
