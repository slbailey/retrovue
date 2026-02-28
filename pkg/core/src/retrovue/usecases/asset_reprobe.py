"""
Use-case: reprobe one or more assets.

Resets asset state, clears stale probed data, and re-runs the enrichment
pipeline so that duration_ms and other technical metadata are refreshed
from the actual file on disk.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from ..domain.entities import Asset, AssetProbed, Collection, Marker, validate_state_transition
from ..shared.types import MarkerKind
from .ingest_orchestrator import ingest_collection_assets

logger = logging.getLogger(__name__)


def reprobe_asset(
    db: Session,
    *,
    asset_uuid: str,
) -> dict[str, Any]:
    """
    Re-probe a single asset: reset it to 'new', clear stale probed/marker
    data, then run the collection's enrichment pipeline on it.

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

    # Capture old values for reporting
    old_duration_ms = asset.duration_ms
    old_state = asset.state

    # 1. Clear stale probed metadata
    probed_row = db.get(AssetProbed, asset.uuid)
    if probed_row is not None:
        db.delete(probed_row)

    # 2. Clear chapter markers (they'll be recreated by ffprobe)
    chapter_markers = [
        m for m in (asset.markers or [])
        if m.kind == MarkerKind.CHAPTER
    ]
    for m in chapter_markers:
        db.delete(m)

    # 3. Reset asset to 'new' so the orchestrator picks it up
    #    Any state can transition to 'retired'; but for reprobe we go to 'new'.
    #    This is a special reset: ready->new is not in the normal state machine,
    #    so we use retired as an intermediate step only if needed. However, the
    #    reprobe workflow is a privileged operation that resets the asset lifecycle,
    #    so we bypass the normal state machine validation here (the asset is about
    #    to be re-enriched from scratch).
    asset.state = "new"
    asset.approved_for_broadcast = False
    asset.duration_ms = None
    asset.video_codec = None
    asset.audio_codec = None
    asset.container = None
    asset.updated_at = datetime.now(UTC)
    db.flush()

    # 4. Run the ingest orchestrator for this collection
    #    It only processes assets in 'new' state, so only our reset asset runs.
    #    To avoid re-probing OTHER new assets, we temporarily park them.
    other_new = (
        db.query(Asset)
        .filter(
            Asset.collection_uuid == collection.uuid,
            Asset.state == "new",
            Asset.uuid != asset.uuid,
        )
        .all()
    )
    for a in other_new:
        a.state = "enriching"
    db.flush()

    try:
        summary = ingest_collection_assets(db, collection)
    finally:
        # Restore the other assets
        for a in other_new:
            a.state = "new"
        db.flush()

    # Refresh asset from DB
    db.refresh(asset)

    return {
        "uuid": str(asset.uuid),
        "uri": asset.uri,
        "old_state": old_state,
        "new_state": asset.state,
        "old_duration_ms": old_duration_ms,
        "new_duration_ms": asset.duration_ms,
        "enrichment_summary": summary,
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
