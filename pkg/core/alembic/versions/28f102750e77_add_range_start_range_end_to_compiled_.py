"""Add range_start, range_end to compiled_program_log

Revision ID: 28f102750e77
Revises: a1b2c3d4e5f6
Create Date: 2026-03-01 11:19:34.542628

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28f102750e77'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('compiled_program_log', sa.Column('range_start', sa.DateTime(timezone=True), nullable=True))
    op.add_column('compiled_program_log', sa.Column('range_end', sa.DateTime(timezone=True), nullable=True))
    op.create_index('ix_compiled_program_log_range', 'compiled_program_log', ['channel_id', 'range_start', 'range_end'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_compiled_program_log_range', table_name='compiled_program_log')
    op.drop_column('compiled_program_log', 'range_end')
    op.drop_column('compiled_program_log', 'range_start')
