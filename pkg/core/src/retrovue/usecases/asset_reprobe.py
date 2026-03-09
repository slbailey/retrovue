"""
Use-case: reprobe one or more assets.

Delegates to the unified enrichment lifecycle in ``asset_enrich.enrich_asset()``
so that reprobe and stale re-enrichment share the same contract:
  - INV-ASSET-REPROBE-RESETS-APPROVAL-001
  - INV-ASSET-REENRICH-RESETS-STALE-001
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..adapters.registry import ENRICHERS
from ..domain.entities import Asset, Collection
from .asset_enrich import EnrichResult, enrich_asset

logger = logging.getLogger(__name__)


def _build_pipeline_for_collection(
    db: Session, collection: Collection
) -> list[tuple[int, str, Any]]:
    """Build the enricher pipeline from a collection's config.

    Returns a sorted list of (priority, enricher_id, instance) tuples.
    """
    from ..domain.entities import Enricher as EnricherRow

    cfg = dict(getattr(collection, "config", {}) or {})
    configured = cfg.get("enrichers", []) if isinstance(cfg.get("enrichers"), list) else []

    pipeline: list[tuple[int, str, Any]] = []
    for entry in configured:
        try:
            enricher_id = entry.get("enricher_id") if isinstance(entry, dict) else None
            priority = int(entry.get("priority", 0)) if isinstance(entry, dict) else 0
            if not enricher_id:
                continue
            row = (
                db.query(EnricherRow)
                .filter(EnricherRow.enricher_id == enricher_id)
                .first()
            )
            if not row or getattr(row, "scope", "ingest") != "ingest":
                continue
            cls = ENRICHERS.get(row.type)
            instance = cls(**(row.config or {})) if cls else None
            if instance is None:
                continue
            pipeline.append((priority, enricher_id, instance))
        except Exception:
            continue

    pipeline.sort(key=lambda t: (t[0], t[1]))
    return pipeline


def reprobe_asset(
    db: Session,
    *,
    asset_uuid: str,
) -> dict[str, Any]:
    """
    Re-probe a single asset: delegates to enrich_asset() which handles
    the full lifecycle (clear stale data, re-enrich, promote/revert).

    Returns a summary dict with the asset uuid and result status.
    """
    try:
        asset_id = UUID(asset_uuid)
    except Exception as exc:
        raise ValueError(f"Invalid asset UUID: {asset_uuid}") from exc

    asset = db.get(Asset, asset_id)
    if asset is None:
        raise ValueError(f"Asset not found: {asset_uuid}")

    collection = asset.collection
    if collection is None:
        raise ValueError(f"Asset {asset_uuid} has no collection")

    # Build the enricher pipeline from collection config
    pipeline = _build_pipeline_for_collection(db, collection)

    # Delegate to the unified lifecycle
    result: EnrichResult = enrich_asset(db, asset, pipeline)

    return {
        "uuid": str(asset.uuid),
        "uri": asset.uri,
        "old_state": result.old_state,
        "new_state": result.new_state,
        "old_duration_ms": result.old_duration_ms,
        "new_duration_ms": result.new_duration_ms,
        "enrichment_summary": {
            "enriched": 1 if result.new_state in ("ready", "new") else 0,
            "errors": result.enricher_errors,
        },
    }


def reprobe_collection(
    db: Session,
    *,
    collection_uuid: str,
    include_ready: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    """
    Re-probe all assets in a collection.

    By default only re-probes assets that are NOT in 'ready' state.
    Pass include_ready=True to force re-probe of ready assets too.
    """
    try:
        coll_id = UUID(collection_uuid)
    except Exception as exc:
        raise ValueError(f"Invalid collection UUID: {collection_uuid}") from exc

    collection = db.get(Collection, coll_id)
    if collection is None:
        raise ValueError(f"Collection not found: {collection_uuid}")

    query = db.query(Asset).filter(Asset.collection_uuid == collection.uuid)

    if not include_ready:
        query = query.filter(Asset.state != "ready")

    if limit:
        query = query.limit(limit)

    assets = query.all()

    if not assets:
        return {
            "collection_uuid": collection_uuid,
            "collection_name": collection.name,
            "total": 0,
            "results": [],
        }

    results = []
    for asset in assets:
        try:
            result = reprobe_asset(db, asset_uuid=str(asset.uuid))
            results.append(result)
        except Exception as e:
            logger.error(f"Failed to reprobe asset {asset.uuid}: {e}")
            results.append({
                "uuid": str(asset.uuid),
                "uri": asset.uri,
                "error": str(e),
            })

    succeeded = sum(1 for r in results if "error" not in r and r.get("new_state") == "ready")
    failed = sum(1 for r in results if "error" in r)

    return {
        "collection_uuid": collection_uuid,
        "collection_name": collection.name,
        "total": len(results),
        "succeeded": succeeded,
        "failed": failed,
        "results": results,
    }
