"""drop_unused_broadcast_tables

Revision ID: 12a042220d1d
Revises: 20251104_000400_drop_tz
Create Date: 2025-11-04 15:56:59.780201

Drop unused broadcast domain tables that are not currently modeled in SQLAlchemy.
These tables will be re-added when broadcast functionality is implemented.

Tables dropped:
- broadcast_playlog_event (depends on broadcast_channels)
- broadcast_schedule_day (depends on broadcast_channels and broadcast_template)
- broadcast_template_block (depends on broadcast_template)
- broadcast_template (no dependencies)
- broadcast_channels (no dependencies)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12a042220d1d'
down_revision: Union[str, Sequence[str], None] = '20251104_000400_drop_tz'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop unused broadcast domain tables."""
    # Drop in order respecting foreign key dependencies
    
    # 1. Drop broadcast_playlog_event (depends on broadcast_channels)
    op.drop_index('ix_broadcast_playlog_event_channel_start', table_name='broadcast_playlog_event', if_exists=True)
    op.drop_index('ix_broadcast_playlog_event_channel_id', table_name='broadcast_playlog_event', if_exists=True)
    op.drop_index('ix_broadcast_playlog_event_broadcast_day', table_name='broadcast_playlog_event', if_exists=True)
    op.drop_index('ix_broadcast_playlog_event_asset_uuid', table_name='broadcast_playlog_event', if_exists=True)
    op.drop_table('broadcast_playlog_event')
    
    # 2. Drop broadcast_schedule_day (depends on broadcast_channels and broadcast_template)
    op.drop_index('ix_broadcast_schedule_day_channel_id', table_name='broadcast_schedule_day', if_exists=True)
    op.drop_table('broadcast_schedule_day')
    
    # 3. Drop broadcast_template_block (depends on broadcast_template)
    op.drop_index('ix_broadcast_template_block_template_id', table_name='broadcast_template_block', if_exists=True)
    op.drop_table('broadcast_template_block')
    
    # 4. Drop broadcast_template (no dependencies from other broadcast tables)
    op.drop_table('broadcast_template')
    
    # 5. Drop broadcast_channels (no dependencies from other broadcast tables)
    op.drop_table('broadcast_channels')


def downgrade() -> None:
    """Recreate broadcast domain tables (for rollback purposes)."""
    # Note: This downgrade recreates the tables with minimal structure.
    # Full schema recreation should reference the original migration.
    
    # Recreate in reverse order
    
    # 1. Create broadcast_channels
    op.create_table(
        'broadcast_channels',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('timezone', sa.String(length=255), nullable=False),
        sa.Column('grid_size_minutes', sa.Integer(), nullable=False),
        sa.Column('grid_offset_minutes', sa.Integer(), nullable=False),
        sa.Column('rollover_minutes', sa.Integer(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_broadcast_channels')),
        sa.UniqueConstraint('name', name='uq_broadcast_channels_name')
    )
    
    # 2. Create broadcast_template
    op.create_table(
        'broadcast_template',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_broadcast_template')),
        sa.UniqueConstraint('name', name=op.f('uq_broadcast_template_name'))
    )
    
    # 3. Create broadcast_template_block
    op.create_table(
        'broadcast_template_block',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('start_time', sa.Text(), nullable=False),
        sa.Column('end_time', sa.Text(), nullable=False),
        sa.Column('rule_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['template_id'], ['broadcast_template.id'], name=op.f('fk_broadcast_template_block_template_id_broadcast_template'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_broadcast_template_block'))
    )
    op.create_index('ix_broadcast_template_block_template_id', 'broadcast_template_block', ['template_id'], unique=False)
    
    # 4. Create broadcast_schedule_day
    op.create_table(
        'broadcast_schedule_day',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('template_id', sa.Integer(), nullable=False),
        sa.Column('schedule_date', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['channel_id'], ['broadcast_channels.id'], name=op.f('fk_broadcast_schedule_day_channel_id_broadcast_channels'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['template_id'], ['broadcast_template.id'], name=op.f('fk_broadcast_schedule_day_template_id_broadcast_template'), ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_broadcast_schedule_day')),
        sa.UniqueConstraint('channel_id', 'schedule_date', name='uq_broadcast_schedule_day_channel_date')
    )
    op.create_index('ix_broadcast_schedule_day_channel_id', 'broadcast_schedule_day', ['channel_id'], unique=False)
    
    # 5. Create broadcast_playlog_event
    op.create_table(
        'broadcast_playlog_event',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('uuid', sa.UUID(), nullable=False),
        sa.Column('channel_id', sa.Integer(), nullable=False),
        sa.Column('asset_uuid', sa.UUID(), nullable=False),
        sa.Column('start_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_utc', sa.DateTime(timezone=True), nullable=False),
        sa.Column('broadcast_day', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),
        sa.ForeignKeyConstraint(['asset_uuid'], ['assets.uuid'], name=op.f('fk_broadcast_playlog_event_asset_uuid_assets'), ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['channel_id'], ['broadcast_channels.id'], name=op.f('fk_broadcast_playlog_event_channel_id_broadcast_channels'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_broadcast_playlog_event')),
        sa.UniqueConstraint('uuid', name=op.f('uq_broadcast_playlog_event_uuid'))
    )
    op.create_index('ix_broadcast_playlog_event_channel_start', 'broadcast_playlog_event', ['channel_id', 'start_utc'], unique=False)
    op.create_index('ix_broadcast_playlog_event_channel_id', 'broadcast_playlog_event', ['channel_id'], unique=False)
    op.create_index('ix_broadcast_playlog_event_broadcast_day', 'broadcast_playlog_event', ['broadcast_day'], unique=False)
    op.create_index('ix_broadcast_playlog_event_asset_uuid', 'broadcast_playlog_event', ['asset_uuid'], unique=False)
