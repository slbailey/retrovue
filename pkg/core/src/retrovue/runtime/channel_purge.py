"""
Channel purge — INV-CHANNEL-PURGE-001, 002, 003

Removes all channel-scoped broadcast state from the database.
Preserves media catalog tables (assets, collections, sources, etc.).

Contract: docs/contracts/channel_purge.md
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def purge_all_channels(db: Session) -> None:
    """Delete all channels and their derived broadcast state.

    Non-FK tables (string-keyed, no CASCADE) are deleted explicitly first.
    Then deleting from ``channels`` cascades to all FK-linked tables.

    The caller owns the transaction — this function does not commit or
    roll back. It executes DELETE statements on the provided session.
    """
    # INV-CHANNEL-PURGE-003: Explicit cleanup of non-cascaded tables.
    # These use string channel identifiers without FK constraints.
    db.execute(text("DELETE FROM program_log_days"))
    db.execute(text("DELETE FROM traffic_play_log"))
    db.execute(text("DELETE FROM playlist_events"))

    # INV-CHANNEL-PURGE-001: Cascade handles programs, schedule_plans,
    # zones, schedule_plan_labels, schedule_revisions, schedule_items,
    # channel_active_revisions, serial_runs.
    db.execute(text("DELETE FROM channels"))
