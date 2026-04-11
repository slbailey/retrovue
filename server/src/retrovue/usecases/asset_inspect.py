"""
Asset inspect usecase: per-enricher status for a given asset.

INV-ENRICHER-OBSERVABILITY-001: enricher progress MUST be retrievable
per-asset with per-enricher granularity.

INV-CLI-NO-BUSINESS-LOGIC-001 / INV-API-NO-BUSINESS-LOGIC-001:
CLI and API surfaces delegate here — no business logic in the boundary layer.
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

from sqlalchemy.orm import Session

from ..catalog.enrichment_progress import get_enrichment_progress
from ..domain.entities import Asset


def get_enrichment_summary(
    db: Session,
    *,
    asset_id: _uuid.UUID,
) -> dict[str, int]:
    """Return completed/total enrichment counts for an asset.

    Used by existing asset detail API and CLI resolve to add a summary line.
    """
    statuses = get_enrichment_progress(db, asset_id)
    total = len(statuses)
    completed = sum(1 for s in statuses.values() if s.status == "succeeded")
    return {"completed": completed, "total": total}


def get_asset_inspect(
    db: Session,
    *,
    asset_uuid: str,
) -> dict[str, Any]:
    """Full asset inspect: asset state + per-enricher status.

    Returns a dict suitable for JSON serialization or CLI rendering.
    Raises ValueError if asset not found.
    """
    try:
        aid = _uuid.UUID(asset_uuid)
    except Exception as exc:
        raise ValueError("Asset not found") from exc

    asset = db.get(Asset, aid)
    if not asset:
        raise ValueError("Asset not found")

    # Resolve source and container names via relationship
    container = asset.container
    source_name = container.source.name if container and container.source else "unknown"
    container_name = container.name if container else "unknown"

    # Per-enricher status
    statuses = get_enrichment_progress(db, aid)
    enrichers = sorted(
        [
            {
                "name": s.enricher_name,
                "status": s.status,
                "version": s.enricher_version,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "completed_at": s.completed_at.isoformat() if s.completed_at else None,
                "error": s.error,
            }
            for s in statuses.values()
        ],
        key=lambda e: e["name"],
    )

    total = len(enrichers)
    completed = sum(1 for e in enrichers if e["status"] == "succeeded")

    return {
        "uuid": str(asset.uuid),
        "uri": asset.uri,
        "state": asset.state,
        "approved_for_broadcast": bool(asset.approved_for_broadcast),
        "source_name": source_name,
        "container_name": container_name,
        "enrichers": enrichers,
        "enrichment_summary": {
            "completed": completed,
            "total": total,
        },
    }
