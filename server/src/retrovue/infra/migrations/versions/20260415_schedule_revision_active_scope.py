from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260415_schedrev_scope"
down_revision: str | None = "20251102_asset_meta"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Drop legacy channel-wide active uniqueness.
    op.execute(
        "DROP INDEX IF EXISTS uq_schedule_revisions_one_active_per_channel"
    )
    # Enforce one active revision per (channel, broadcast_day).
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_schedule_revisions_one_active_per_channel_day
        ON schedule_revisions (channel_id, broadcast_day)
        WHERE status = 'active'
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_schedule_revisions_one_active_per_channel_day"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_schedule_revisions_one_active_per_channel
        ON schedule_revisions (channel_id)
        WHERE status = 'active'
        """
    )

