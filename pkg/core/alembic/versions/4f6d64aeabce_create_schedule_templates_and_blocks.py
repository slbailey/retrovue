"""create_schedule_templates_and_blocks

Revision ID: 4f6d64aeabce
Revises: d26f5c803f70
Create Date: 2025-11-05 14:21:42.321404

Create schedule_templates and schedule_template_blocks tables for template-based scheduling.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "4f6d64aeabce"
down_revision: Union[str, Sequence[str], None] = "d26f5c803f70"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create schedule_templates and schedule_template_blocks tables."""
    # Create schedule_templates table
    op.create_table(
        "schedule_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("name", name="uq_schedule_templates_name"),
    )

    # Create indexes for schedule_templates
    op.create_index("ix_schedule_templates_name", "schedule_templates", ["name"])
    op.create_index("ix_schedule_templates_is_active", "schedule_templates", ["is_active"])

    # Create schedule_template_blocks table
    op.create_table(
        "schedule_template_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "template_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("start_time", sa.Text(), nullable=False),  # HH:MM format
        sa.Column("end_time", sa.Text(), nullable=False),  # HH:MM format
        sa.Column("rule_json", sa.Text(), nullable=False),  # JSON string
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["schedule_templates.id"],
            ondelete="CASCADE",
            name="fk_schedule_template_blocks_template_id",
        ),
    )

    # Create indexes for schedule_template_blocks
    op.create_index(
        "ix_schedule_template_blocks_template_id",
        "schedule_template_blocks",
        ["template_id"],
    )
    op.create_index(
        "ix_schedule_template_blocks_start_time",
        "schedule_template_blocks",
        ["start_time"],
    )


def downgrade() -> None:
    """Drop schedule_template_blocks and schedule_templates tables."""
    op.drop_index("ix_schedule_template_blocks_start_time", table_name="schedule_template_blocks")
    op.drop_index(
        "ix_schedule_template_blocks_template_id", table_name="schedule_template_blocks"
    )
    op.drop_table("schedule_template_blocks")

    op.drop_index("ix_schedule_templates_is_active", table_name="schedule_templates")
    op.drop_index("ix_schedule_templates_name", table_name="schedule_templates")
    op.drop_table("schedule_templates")
