"""create_zones_table

Revision ID: 20260126_zones
Revises: c4c7476b4dbe
Create Date: 2026-01-26 14:00:00.000000

Create zones table for daypart scheduling. Zones are named time windows
within the programming day that organize content into logical areas
(e.g., "Morning Cartoons", "Prime Time", "Late Night Horror").
"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '20260126_zones'
down_revision: str | Sequence[str] | None = 'c4c7476b4dbe'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create zones table."""
    op.create_table(
        'zones',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('plan_id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False,
                  comment="Human-readable zone name (e.g., 'Morning Cartoons')"),
        sa.Column('start_time', sa.Time(), nullable=False,
                  comment='Zone start in broadcast day time (00:00-24:00)'),
        sa.Column('end_time', sa.Time(), nullable=False,
                  comment='Zone end in broadcast day time. 24:00 stored as 23:59:59.999999'),
        sa.Column('schedulable_assets', postgresql.JSONB(astext_type=sa.Text()),
                  nullable=False, server_default=sa.text("'[]'::jsonb"),
                  comment='Array of SchedulableAsset UUIDs (Programs, Assets, VirtualAssets)'),
        sa.Column('day_filters', postgresql.JSONB(astext_type=sa.Text()), nullable=True,
                  comment="Day-of-week constraints: ['MON','TUE',...]. Null = all days."),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.text('true'),
                  comment='Active flag. Disabled zones are ignored during resolution.'),
        sa.Column('effective_start', sa.Date(), nullable=True,
                  comment='Start date for zone validity (inclusive)'),
        sa.Column('effective_end', sa.Date(), nullable=True,
                  comment='End date for zone validity (inclusive)'),
        sa.Column('dst_policy', sa.String(length=50), nullable=True,
                  comment="DST policy: 'reject', 'shrink_one_block', 'expand_one_block'"),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['schedule_plans.id'],
                                name=op.f('fk_zones_plan_id_schedule_plans'),
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_zones')),
        sa.UniqueConstraint('plan_id', 'name', name='uq_zones_plan_name'),
        sa.CheckConstraint(
            "dst_policy IS NULL OR dst_policy IN ('reject', 'shrink_one_block', 'expand_one_block')",
            name='chk_zones_dst_policy_valid'
        ),
        sa.CheckConstraint(
            "(effective_start IS NULL AND effective_end IS NULL) OR "
            "(effective_start IS NULL) OR (effective_end IS NULL) OR "
            "(effective_start <= effective_end)",
            name='chk_zones_effective_range'
        ),
    )
    op.create_index('ix_zones_plan_id', 'zones', ['plan_id'], unique=False)
    op.create_index('ix_zones_enabled', 'zones', ['enabled'], unique=False)
    op.create_index('ix_zones_start_time', 'zones', ['start_time'], unique=False)


def downgrade() -> None:
    """Drop zones table."""
    op.drop_index('ix_zones_start_time', table_name='zones')
    op.drop_index('ix_zones_enabled', table_name='zones')
    op.drop_index('ix_zones_plan_id', table_name='zones')
    op.drop_table('zones')
