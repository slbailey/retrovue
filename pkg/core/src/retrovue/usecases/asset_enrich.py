"""
Use-case: single-asset enrichment lifecycle.

Implements the unified lifecycle contract for re-enriching an existing asset,
whether triggered by an explicit reprobe or by a stale enricher pipeline
checksum.  This is the canonical enforcement point for:

- INV-ASSET-REENRICH-RESETS-STALE-001
- INV-ASSET-DURATION-REQUIRED-FOR-READY-001
- INV-ASSET-APPROVAL-OPERATOR-ONLY-001
- INV-ASSET-REPROBE-RESETS-APPROVAL-001

This module MUST NOT commit; the caller owns the transaction boundary.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import (
    Asset,
    AssetProbed,
    Marker,
    validate_state_transition,
)
from ..shared.types import MarkerKind

logger = logging.getLogger(__name__)


@dataclass
class EnrichResult:
    """Result of a single-asset enrichment operation."""

    asset_uuid: str
    old_state: str
    new_state: str
    old_duration_ms: int | None
    new_duration_ms: int | None
    enricher_errors: list[str] = field(default_factory=list)
    checksum_applied: str | None = None


def enrich_asset(
    db: Session,
    asset: Asset,
    pipeline: list[tuple[int, str, Any]],
    *,
    pipeline_checksum: str | None = None,
) -> EnrichResult:
    """Prepare asset for re-enrichment and enqueue a processor job.

    Lifecycle steps:
      1. Snapshot old state
      2. Clear stale technical metadata
      3. Delete AssetProbed row
      4. Delete CHAPTER markers (preserve others)
      5. Reset approved_for_broadcast to False
      6. Reset state to 'new' (privileged lifecycle reset)
      7. Transition new → enriching; enqueue processor job (worker runs pipeline).

    Args:
        db: Active SQLAlchemy session (caller manages transaction).
        asset: The Asset row to re-enrich (must be attached to session).
        pipeline: Pre-built enricher (priority, enricher_id, instance) tuples; used for processor_ids.
        pipeline_checksum: Unused (retained for API compatibility).

    Returns:
        EnrichResult with new_state='enriching'; worker updates metadata and state on completion.
    """
    errors: list[str] = []

    # ── 1. Snapshot ───────────────────────────────────────────────────────
    old_state = asset.state
    old_duration_ms = asset.duration_ms

    # ── 2. Clear stale technical metadata ─────────────────────────────────
    asset.duration_ms = None
    asset.video_codec = None
    asset.audio_codec = None
    asset.container_format = None

    # ── 3. Delete AssetProbed row ─────────────────────────────────────────
    probed_row = db.get(AssetProbed, asset.uuid)
    if probed_row is not None:
        db.delete(probed_row)

    # ── 4. Delete CHAPTER markers, preserve others ────────────────────────
    chapter_markers = [
        m for m in (asset.markers or [])
        if m.kind == MarkerKind.CHAPTER
    ]
    for m in chapter_markers:
        db.delete(m)

    # ── 5. Reset approved_for_broadcast ───────────────────────────────────
    asset.approved_for_broadcast = False

    # ── 6. Reset state to 'new' ──────────────────────────────────────────
    #    This is a privileged lifecycle reset (same pattern as reprobe).
    #    The normal state machine does not allow ready→new, but re-enrichment
    #    is a full lifecycle restart.
    asset.state = "new"
    asset.updated_at = datetime.now(UTC)

    # ── 7. Transition new → enriching ─────────────────────────────────────
    validate_state_transition("new", "enriching")
    asset.state = "enriching"
    asset.updated_at = datetime.now(UTC)
    db.flush()

    # ── 8. Enqueue processor job; worker will run pipeline and update state ─
    from ..catalog.processor_jobs import enqueue_processor_jobs
    processor_ids = [eid for (_pr, eid, _) in pipeline]
    enqueue_processor_jobs([asset.uuid], processor_ids, db=db)

    return EnrichResult(
        asset_uuid=str(asset.uuid),
        old_state=old_state,
        new_state="enriching",
        old_duration_ms=old_duration_ms,
        new_duration_ms=None,
        enricher_errors=errors,
        checksum_applied=None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_label(labels: list[str], key: str) -> str | None:
    """Extract a value from a list of ``key:value`` labels."""
    prefix = f"{key}:"
    for label in labels:
        if isinstance(label, str) and label.startswith(prefix):
            return label[len(prefix):]
    return None
