"""
Channel reconciliation — INV-CHANNEL-CONFIG-SOURCE-OF-TRUTH,
INV-CHANNEL-RECONCILE-DELETE, INV-CHANNEL-RECONCILE-IDEMPOTENT

Reconciles the database channel set against the operator-provided YAML
slug set. Creates missing channels, deletes removed channels with all
derived broadcast state.

Contract: docs/contracts/channel_reconciliation.md
"""

from __future__ import annotations

import logging
from datetime import time

from sqlalchemy import text
from sqlalchemy.orm import Session

from retrovue.domain.entities import Channel

logger = logging.getLogger(__name__)


def reconcile_channels(db: Session, yaml_channel_slugs: set[str]) -> None:
    """Reconcile database channels against the YAML-declared slug set.

    Channels in the database but absent from ``yaml_channel_slugs`` are
    deleted along with all derived broadcast state. Channels in
    ``yaml_channel_slugs`` but absent from the database are created with
    minimal defaults.

    The caller owns the transaction — this function does not commit or
    roll back.
    """
    # Current DB state
    db_channels = db.query(Channel).all()
    db_slug_map = {ch.slug: ch for ch in db_channels}
    db_slugs = set(db_slug_map.keys())
    db_before = len(db_slugs)

    # --- Delete channels not in YAML ---
    slugs_to_remove = db_slugs - yaml_channel_slugs
    if slugs_to_remove:
        slug_list = list(slugs_to_remove)

        # INV-CHANNEL-RECONCILE-DELETE: Explicit cleanup of non-FK tables.
        # These use string channel identifiers without FK constraints.
        db.execute(
            text("DELETE FROM program_log_days WHERE channel_id = ANY(:slugs)"),
            {"slugs": slug_list},
        )
        db.execute(
            text("DELETE FROM traffic_play_log WHERE channel_slug = ANY(:slugs)"),
            {"slugs": slug_list},
        )
        db.execute(
            text("DELETE FROM playlist_events WHERE channel_slug = ANY(:slugs)"),
            {"slugs": slug_list},
        )

        # FK CASCADE handles programs, schedule_plans, zones,
        # schedule_plan_labels, schedule_revisions, schedule_items,
        # channel_active_revisions, serial_runs.
        db.execute(
            text("DELETE FROM channels WHERE slug = ANY(:slugs)"),
            {"slugs": slug_list},
        )

    # --- Create channels in YAML but not in DB ---
    slugs_to_add = yaml_channel_slugs - db_slugs
    for slug in sorted(slugs_to_add):
        db.add(Channel(
            slug=slug,
            title=slug,
            grid_block_minutes=30,
            kind="network",
            programming_day_start=time(6, 0),
            block_start_offsets_minutes=[0],
        ))

    if slugs_to_add:
        db.flush()

    db_after = db_before - len(slugs_to_remove) + len(slugs_to_add)
    logger.info(
        "[channels] config=%d db_before=%d added=%d removed=%d db_after=%d",
        len(yaml_channel_slugs), db_before,
        len(slugs_to_add), len(slugs_to_remove), db_after,
    )
    if slugs_to_remove:
        logger.info("[channels] removed: %s", ", ".join(sorted(slugs_to_remove)))
    if slugs_to_add:
        logger.info("[channels] added: %s", ", ".join(sorted(slugs_to_add)))
