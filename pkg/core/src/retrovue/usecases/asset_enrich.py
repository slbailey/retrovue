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
from uuid import uuid4

from sqlalchemy.orm import Session

from ..adapters.importers.base import DiscoveredItem
from ..domain.entities import (
    Asset,
    AssetProbed,
    Marker,
    validate_marker_bounds,
    validate_state_transition,
)
from ..infra.metadata.persistence import persist_asset_metadata
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
    """Re-enrich a single asset through the canonical lifecycle.

    Lifecycle steps:
      1. Snapshot old state
      2. Clear stale technical metadata
      3. Delete AssetProbed row
      4. Delete CHAPTER markers (preserve others)
      5. Reset approved_for_broadcast to False
      6. Reset state to 'new' (privileged lifecycle reset)
      7. Transition new → enriching via validate_state_transition()
      8. Build DiscoveredItem wrapper and run enricher pipeline
      9. Map enricher labels back to asset fields
     10. Persist refreshed probed/editorial metadata
     11. Recreate chapter markers from probed data when valid
     12. Promotion gate: duration_ms > 0 → ready; else → new
     13. Update last_enricher_checksum
     14. Flush (do NOT commit)

    Args:
        db: Active SQLAlchemy session (caller manages transaction).
        asset: The Asset row to re-enrich (must be attached to session).
        pipeline: Pre-built enricher instances as (priority, enricher_id, instance)
                  tuples, already sorted by priority.
        pipeline_checksum: Pre-computed SHA256 of pipeline signature.  Stored on
                          the asset if provided.

    Returns:
        EnrichResult with old/new state, old/new duration, errors, and checksum.
    """
    errors: list[str] = []

    # ── 1. Snapshot ───────────────────────────────────────────────────────
    old_state = asset.state
    old_duration_ms = asset.duration_ms

    # ── 2. Clear stale technical metadata ─────────────────────────────────
    asset.duration_ms = None
    asset.video_codec = None
    asset.audio_codec = None
    asset.container = None

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
    db.flush()

    # ── 8. Build DiscoveredItem and run pipeline ──────────────────────────
    path_uri = asset.canonical_uri or asset.uri or ""
    item = DiscoveredItem(
        path_uri=path_uri,
        raw_labels=[],
        size=asset.size,
    )

    for _priority, _eid, enricher in pipeline:
        try:
            item = enricher.enrich(item)
        except Exception as exc:
            errors.append(f"{_eid}: {exc}")
            logger.warning(
                "enricher %s failed for asset %s: %s",
                _eid, asset.uuid, exc,
            )

    # ── 9. Map labels back to asset fields ────────────────────────────────
    labels = item.raw_labels or []

    dur_val = _extract_label(labels, "duration_ms")
    if dur_val is not None:
        try:
            asset.duration_ms = int(dur_val)
        except (ValueError, TypeError):
            pass

    vid_val = _extract_label(labels, "video_codec")
    if vid_val is not None:
        asset.video_codec = vid_val

    aud_val = _extract_label(labels, "audio_codec")
    if aud_val is not None:
        asset.audio_codec = aud_val

    cont_val = _extract_label(labels, "container")
    if cont_val is not None:
        asset.container = cont_val

    # ── 10. Persist refreshed metadata ────────────────────────────────────
    probed_data = item.probed or {}
    editorial_data = item.editorial or {}

    # If duration came from probed dict rather than labels, capture it
    if asset.duration_ms is None and probed_data.get("duration_ms"):
        try:
            asset.duration_ms = int(probed_data["duration_ms"])
        except (ValueError, TypeError):
            pass

    if probed_data:
        persist_asset_metadata(db, asset, probed=probed_data)

    # Editorial: merge enricher output into existing payload to avoid
    # destroying operator-provided or importer-provided fields.
    if editorial_data:
        from ..domain.entities import AssetEditorial

        existing_ed = db.get(AssetEditorial, asset.uuid)
        if existing_ed:
            merged = dict(existing_ed.payload or {})
            merged.update(editorial_data)
            existing_ed.payload = merged
            db.add(existing_ed)
        else:
            db.add(AssetEditorial(
                asset_uuid=asset.uuid,
                payload=dict(editorial_data),
            ))

    # ── 11. Recreate chapter markers from probed chapters ─────────────────
    chapters = probed_data.get("chapters", [])
    if chapters and asset.duration_ms and asset.duration_ms > 0:
        for ch in chapters:
            ch_start = ch.get("start_ms", 0)
            ch_end = ch.get("end_ms", 0)
            try:
                validate_marker_bounds(ch_start, ch_end, asset.duration_ms)
            except ValueError:
                logger.warning(
                    "skipping invalid chapter for asset %s: start=%d end=%d duration=%d",
                    asset.uuid, ch_start, ch_end, asset.duration_ms,
                )
                continue
            marker = Marker(
                id=uuid4(),
                asset_uuid=asset.uuid,
                kind=MarkerKind.CHAPTER,
                start_ms=ch_start,
                end_ms=ch_end,
                payload={"title": ch.get("title", "")},
            )
            db.add(marker)

    # ── 12. Promotion gate ────────────────────────────────────────────────
    if asset.duration_ms and asset.duration_ms > 0:
        validate_state_transition("enriching", "ready")
        asset.state = "ready"
    else:
        validate_state_transition("enriching", "new")
        asset.state = "new"
        logger.warning(
            "asset %s enriched but missing valid duration (duration_ms=%s), keeping in new state",
            asset.uuid, asset.duration_ms,
        )

    # ── 13. Update checksum ───────────────────────────────────────────────
    if pipeline_checksum is not None:
        asset.last_enricher_checksum = pipeline_checksum

    # ── 14. Flush ─────────────────────────────────────────────────────────
    asset.updated_at = datetime.now(UTC)
    db.flush()

    return EnrichResult(
        asset_uuid=str(asset.uuid),
        old_state=old_state,
        new_state=asset.state,
        old_duration_ms=old_duration_ms,
        new_duration_ms=asset.duration_ms,
        enricher_errors=errors,
        checksum_applied=pipeline_checksum,
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
