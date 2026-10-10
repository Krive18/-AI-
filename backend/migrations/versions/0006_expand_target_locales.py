"""Expand translation task target locales with German and French.

Revision ID: 0006_expand_target_locales
Revises: 0005_provider_capability_comment
Create Date: 2026-09-05
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006_expand_target_locales"
down_revision: str | None = "0005_provider_capability_comment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LOCALES_BEFORE = "'en-US','ja-JP','ko-KR','vi-VN','ms-MY','th-TH','en-SG','fil-PH'"
_LOCALES_AFTER = _LOCALES_BEFORE + ",'de-DE','fr-FR'"


def upgrade() -> None:
    op.drop_constraint(
        "ck_translation_task_target_locale", "translation_task", type_="check"
    )
    op.create_check_constraint(
        "ck_translation_task_target_locale",
        "translation_task",
        f"target_locale IN ({_LOCALES_AFTER})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_translation_task_target_locale", "translation_task", type_="check"
    )
    op.create_check_constraint(
        "ck_translation_task_target_locale",
        "translation_task",
        f"target_locale IN ({_LOCALES_BEFORE})",
    )
