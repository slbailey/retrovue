"""
Enrichment progress query: per-enricher status for a given asset.

INV-ENRICHER-OBSERVABILITY-001: enricher progress MUST be retrievable
per-asset with per-enricher granularity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc
from sqlalchemy.orm import Session

from ..domain.entities import EnricherRun


@dataclass(frozen=True)
class EnricherStatus:
    """Per-enricher status for a single asset."""

    enricher_name: str
    status: str
    enricher_version: str
    started_at: datetime
    completed_at: datetime | None
    error: str | None
    result_payload: dict[str, Any] | None


def get_enrichment_progress(
    db: Session,
    asset_id: uuid.UUID,
) -> dict[str, EnricherStatus]:
    """Return the latest enricher execution status per enricher for an asset.

    Returns a dict of enricher_name → EnricherStatus, using only the most
    recent run per enricher (by started_at descending).
    """
    # Fetch all runs for this asset, ordered by started_at desc so we can
    # pick the latest per enricher_name.
    runs = (
        db.query(EnricherRun)
        .filter(EnricherRun.asset_id == asset_id)
        .order_by(desc(EnricherRun.started_at))
        .all()
    )

    result: dict[str, EnricherStatus] = {}
    for run in runs:
        if run.enricher_name in result:
            continue  # already have the latest for this enricher
        result[run.enricher_name] = EnricherStatus(
            enricher_name=run.enricher_name,
            status=run.status,
            enricher_version=run.enricher_version,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error=run.error,
            result_payload=run.result_payload,
        )

    return result


def get_stale_enricher_assets(
    db: Session,
    enricher_name: str,
    current_version: str,
) -> list[uuid.UUID]:
    """Return asset IDs where the latest run of enricher_name has a version
    older than current_version.

    INV-ENRICHER-RESULT-VERSIONED-001: version mismatch between current
    enricher version and persisted result version is detectable by query.
    """
    # Get all runs for this enricher, pick the latest per asset.
    runs = (
        db.query(EnricherRun)
        .filter(
            EnricherRun.enricher_name == enricher_name,
            EnricherRun.status == "succeeded",
        )
        .order_by(desc(EnricherRun.started_at))
        .all()
    )

    seen: set[uuid.UUID] = set()
    stale: list[uuid.UUID] = []
    for run in runs:
        if run.asset_id in seen:
            continue
        seen.add(run.asset_id)
        if run.enricher_version != current_version:
            stale.append(run.asset_id)

    return stale
