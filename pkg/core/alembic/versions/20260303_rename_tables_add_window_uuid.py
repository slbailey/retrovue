"""Rename compiled_program_log -> program_log_days, transmission_log -> playlist_events, add window_uuid column

Revision ID: 20260303_rename
Revises: 90533b501986
Create Date: 2026-03-03 12:00:00.000000

Option B: full broadcast-correct rename.
  - Tier 1: compiled_program_log -> program_log_days (ProgramLogDay)
  - Tier 2: transmission_log -> playlist_events (PlaylistEvent)
  - playlist_events.window_uuid UUID nullable column + index
  - Compatibility views for old table names
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "20260303_rename"
down_revision: Union[str, Sequence[str], None] = "90533b501986"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Tier 1: compiled_program_log → program_log_days ──────────────
    op.rename_table("compiled_program_log", "program_log_days")

    op.execute("""
    DO $$
    BEGIN
      -- Unique constraint
      IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_compiled_program_log_channel_day'
      ) THEN
        ALTER TABLE public.program_log_days
          RENAME CONSTRAINT uq_compiled_program_log_channel_day
          TO uq_program_log_days_channel_day;
      END IF;

      -- Indexes
      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_compiled_program_log_channel_id'
      ) THEN
        ALTER INDEX ix_compiled_program_log_channel_id RENAME TO ix_program_log_days_channel_id;
      END IF;

      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_compiled_program_log_broadcast_day'
      ) THEN
        ALTER INDEX ix_compiled_program_log_broadcast_day RENAME TO ix_program_log_days_broadcast_day;
      END IF;

      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_compiled_program_log_range'
      ) THEN
        ALTER INDEX ix_compiled_program_log_range RENAME TO ix_program_log_days_range;
      END IF;

      -- Sequence (if exists from PK default)
      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'compiled_program_log_id_seq'
      ) THEN
        ALTER SEQUENCE compiled_program_log_id_seq RENAME TO program_log_days_id_seq;
      END IF;
    END $$;
    """)

    # ── Tier 2: transmission_log → playlist_events ───────────────────
    op.rename_table("transmission_log", "playlist_events")

    op.execute("""
    DO $$
    BEGIN
      -- Index
      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_transmission_log_channel_day'
      ) THEN
        ALTER INDEX ix_transmission_log_channel_day RENAME TO ix_playlist_events_channel_day;
      END IF;

      -- Sequence (if exists — unlikely since block_id is string PK)
      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'transmission_log_block_id_seq'
      ) THEN
        ALTER SEQUENCE transmission_log_block_id_seq RENAME TO playlist_events_block_id_seq;
      END IF;
    END $$;
    """)

    # ── New column: playlist_events.window_uuid ──────────────────────
    op.add_column(
        "playlist_events",
        sa.Column("window_uuid", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_playlist_events_window_uuid",
        "playlist_events",
        ["window_uuid"],
    )

    # ── Compatibility views ──────────────────────────────────────────
    op.execute(
        "CREATE OR REPLACE VIEW public.compiled_program_log AS SELECT * FROM public.program_log_days"
    )
    op.execute(
        "CREATE OR REPLACE VIEW public.transmission_log AS SELECT * FROM public.playlist_events"
    )


def downgrade() -> None:
    # Drop compatibility views first
    op.execute("DROP VIEW IF EXISTS public.transmission_log")
    op.execute("DROP VIEW IF EXISTS public.compiled_program_log")

    # Remove window_uuid column
    op.drop_index("ix_playlist_events_window_uuid", table_name="playlist_events")
    op.drop_column("playlist_events", "window_uuid")

    # ── Revert Tier 2 rename ─────────────────────────────────────────
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_playlist_events_channel_day'
      ) THEN
        ALTER INDEX ix_playlist_events_channel_day RENAME TO ix_transmission_log_channel_day;
      END IF;

      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'playlist_events_block_id_seq'
      ) THEN
        ALTER SEQUENCE playlist_events_block_id_seq RENAME TO transmission_log_block_id_seq;
      END IF;
    END $$;
    """)
    op.rename_table("playlist_events", "transmission_log")

    # ── Revert Tier 1 rename ─────────────────────────────────────────
    # Note: table is still program_log_days at this point; rename to compiled_program_log after
    op.execute("""
    DO $$
    BEGIN
      IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_program_log_days_channel_day'
      ) THEN
        ALTER TABLE public.program_log_days
          RENAME CONSTRAINT uq_program_log_days_channel_day
          TO uq_compiled_program_log_channel_day;
      END IF;

      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_program_log_days_channel_id'
      ) THEN
        ALTER INDEX ix_program_log_days_channel_id RENAME TO ix_compiled_program_log_channel_id;
      END IF;

      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_program_log_days_broadcast_day'
      ) THEN
        ALTER INDEX ix_program_log_days_broadcast_day RENAME TO ix_compiled_program_log_broadcast_day;
      END IF;

      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'i' AND relname = 'ix_program_log_days_range'
      ) THEN
        ALTER INDEX ix_program_log_days_range RENAME TO ix_compiled_program_log_range;
      END IF;

      IF EXISTS (
        SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = 'program_log_days_id_seq'
      ) THEN
        ALTER SEQUENCE program_log_days_id_seq RENAME TO compiled_program_log_id_seq;
      END IF;
    END $$;
    """)
    op.rename_table("program_log_days", "compiled_program_log")
