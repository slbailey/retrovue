"""merge tag migration with editorial indexed columns

Revision ID: 251e64733e7b
Revises: editorial_indexed_cols_001, h1i2j3k4l5m6
Create Date: 2026-04-09 19:58:32.870542

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '251e64733e7b'
down_revision: Union[str, Sequence[str], None] = ('editorial_indexed_cols_001', 'h1i2j3k4l5m6')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
