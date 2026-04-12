"""update_schedule_plans_add_name_description_cron_is_active

Revision ID: a66ac92bfe74
Revises: d0c624e253c0
Create Date: 2025-11-06 21:26:14.923242

"""
from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'a66ac92bfe74'
down_revision: str | Sequence[str] | None = 'd0c624e253c0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # Make start_date and end_date nullable
    op.alter_column('schedule_plans', 'start_date', nullable=True, existing_type=sa.Date())
    op.alter_column('schedule_plans', 'end_date', nullable=True, existing_type=sa.Date())
    
    # Add new required fields
    op.add_column('schedule_plans', sa.Column('name', sa.String(length=255), nullable=False, server_default='Unnamed Plan'))
    op.add_column('schedule_plans', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('schedule_plans', sa.Column('cron_expression', sa.Text(), nullable=True))
    op.add_column('schedule_plans', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')))
    
    # Fix priority comment
    op.alter_column('schedule_plans', 'priority', 
                     nullable=False, 
                     server_default='0',
                     comment='Higher number = higher priority',
                     existing_type=sa.Integer())
    
    # Drop old unique constraint on channel_id, start_date, end_date
    op.drop_constraint('uq_schedule_plans_channel_dates', 'schedule_plans', type_='unique')
    
    # Add new unique constraint on channel_id, name
    op.create_unique_constraint('uq_schedule_plans_channel_name', 'schedule_plans', ['channel_id', 'name'])
    
    # Add indexes
    op.create_index('ix_schedule_plans_name', 'schedule_plans', ['name'], unique=False)
    op.create_index('ix_schedule_plans_is_active', 'schedule_plans', ['is_active'], unique=False)
    
    # Remove server_default from name after constraint is created
    op.alter_column('schedule_plans', 'name', server_default=None, existing_type=sa.String(length=255))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove indexes
    op.drop_index('ix_schedule_plans_is_active', table_name='schedule_plans')
    op.drop_index('ix_schedule_plans_name', table_name='schedule_plans')
    
    # Drop new unique constraint
    op.drop_constraint('uq_schedule_plans_channel_name', 'schedule_plans', type_='unique')
    
    # Restore old unique constraint
    op.create_unique_constraint('uq_schedule_plans_channel_dates', 'schedule_plans', ['channel_id', 'start_date', 'end_date'])
    
    # Remove new columns
    op.drop_column('schedule_plans', 'is_active')
    op.drop_column('schedule_plans', 'cron_expression')
    op.drop_column('schedule_plans', 'description')
    op.drop_column('schedule_plans', 'name')
    
    # Make start_date and end_date NOT NULL again
    op.alter_column('schedule_plans', 'start_date', nullable=False, existing_type=sa.Date())
    op.alter_column('schedule_plans', 'end_date', nullable=False, existing_type=sa.Date())
    
    # Restore priority to nullable
    op.alter_column('schedule_plans', 'priority', nullable=True, server_default=None, existing_type=sa.Integer())
