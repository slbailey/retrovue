"""add_priority_non_negative_constraint

Revision ID: c4c7476b4dbe
Revises: a66ac92bfe74
Create Date: 2025-11-07 05:24:52.908497

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4c7476b4dbe'
down_revision: str | Sequence[str] | None = 'a66ac92bfe74'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add check constraint to ensure priority is non-negative
    op.create_check_constraint(
        'chk_schedule_plans_priority_non_negative',
        'schedule_plans',
        'priority >= 0'
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Remove check constraint
    op.drop_constraint(
        'chk_schedule_plans_priority_non_negative',
        'schedule_plans',
        type_='check'
    )
