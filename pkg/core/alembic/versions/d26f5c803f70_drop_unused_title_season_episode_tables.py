"""drop_unused_title_season_episode_tables

Revision ID: d26f5c803f70
Revises: 12a042220d1d
Create Date: 2025-11-04 16:06:48.742263

Drop unused title/season/episode tables that are not populated by current ingest.
Series/episode data is stored in asset_editorial.payload (JSONB) instead.

Tables dropped:
- episode_assets (junction table, depends on episodes and assets)
- episodes (depends on titles and seasons)
- seasons (depends on titles)
- titles (no dependencies from other domain tables)

Note: ProviderRef may reference these via foreign keys, but those are nullable.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd26f5c803f70'
down_revision: Union[str, Sequence[str], None] = '12a042220d1d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop unused title/season/episode tables."""
    # Drop in order respecting foreign key dependencies
    
    # First, drop columns from provider_refs (will cascade drop foreign key constraints)
    # These columns are nullable, so safe to drop
    try:
        op.drop_column('provider_refs', 'title_id')
    except Exception:
        pass  # Column may not exist or already dropped
    
    try:
        op.drop_column('provider_refs', 'episode_id')
    except Exception:
        pass  # Column may not exist or already dropped
    
    # Now drop the tables in dependency order
    # 1. Drop episode_assets junction table (depends on episodes and assets)
    op.drop_table('episode_assets')
    
    # 2. Drop episodes (depends on titles and seasons)
    op.drop_table('episodes')
    
    # 3. Drop seasons (depends on titles)
    op.drop_table('seasons')
    
    # 4. Drop titles (no dependencies from other domain tables)
    op.drop_table('titles')


def downgrade() -> None:
    """Recreate title/season/episode tables (for rollback purposes)."""
    # Note: This downgrade recreates the tables with minimal structure.
    # Full schema recreation should reference the original migration.
    
    # Recreate in reverse order
    
    # 1. Create titles
    op.create_table(
        'titles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('kind', sa.Enum('MOVIE', 'SHOW', name='titlekind'), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('year', sa.Integer(), nullable=True),
        sa.Column('external_ids', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_titles'))
    )
    
    # 2. Create seasons
    op.create_table(
        'seasons',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('title_id', sa.UUID(), nullable=False),
        sa.Column('number', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['title_id'], ['titles.id'], name=op.f('fk_seasons_title_id_titles'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_seasons'))
    )
    
    # 3. Create episodes
    op.create_table(
        'episodes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('title_id', sa.UUID(), nullable=False),
        sa.Column('season_id', sa.UUID(), nullable=True),
        sa.Column('number', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('external_ids', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['title_id'], ['titles.id'], name=op.f('fk_episodes_title_id_titles'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['season_id'], ['seasons.id'], name=op.f('fk_episodes_season_id_seasons'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_episodes'))
    )
    
    # 4. Create episode_assets junction table
    op.create_table(
        'episode_assets',
        sa.Column('episode_id', sa.UUID(), nullable=False),
        sa.Column('asset_uuid', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['asset_uuid'], ['assets.uuid'], name=op.f('fk_episode_assets_asset_uuid_assets'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['episode_id'], ['episodes.id'], name=op.f('fk_episode_assets_episode_id_episodes'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('episode_id', 'asset_uuid', name=op.f('pk_episode_assets'))
    )
    
    # 5. Re-add provider_refs columns
    op.add_column('provider_refs', sa.Column('title_id', sa.UUID(), nullable=True))
    op.add_column('provider_refs', sa.Column('episode_id', sa.UUID(), nullable=True))
    op.create_foreign_key('fk_provider_refs_title_id_titles', 'provider_refs', 'titles', ['title_id'], ['id'], ondelete='CASCADE')
    op.create_foreign_key('fk_provider_refs_episode_id_episodes', 'provider_refs', 'episodes', ['episode_id'], ['id'], ondelete='CASCADE')
