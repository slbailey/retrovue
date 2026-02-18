"""
Ingest orchestrator for processing assets through enrichment pipeline.

This module orchestrates the enrichment of assets in the "new" state,
running configured enrichers and persisting results back to the database.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.orm import Session

from ..adapters.importers.base import DiscoveredItem
from ..domain.entities import Asset, Collection, Marker, PathMapping
from .asset_path_resolver import AssetPathResolver
from ..infra.metadata.persistence import persist_asset_metadata
from ..shared.types import MarkerKind

if TYPE_CHECKING:
    from ..domain.entities import AssetEditorial

logger = logging.getLogger(__name__)


def ingest_collection_assets(
    db: Session,
    collection: Collection,
) -> dict[str, int]:
    """
    Ingest all assets in "new" state for a given collection.

    This function:
    1. Finds all assets in "new" state for the collection
    2. Resolves their local file URIs using path mappings
    3. Runs configured enrichers on each asset
    4. Persists enrichment results (probed data, markers, etc.)
    5. Transitions assets to "ready" state

    Args:
        db: Database session
        collection: Collection to ingest assets from

    Returns:
        Summary dict with counts:
            - total: Total assets processed
            - enriched: Successfully enriched assets
            - skipped: Assets skipped (no local file, etc.)
            - failed: Assets that failed enrichment
    """
    summary = {
        "total": 0,
        "enriched": 0,
        "skipped": 0,
        "failed": 0,
    }

    # Get source for the collection
    source = collection.source

    # Get path mappings for this collection
    path_mappings_list = db.query(PathMapping).filter(
        PathMapping.collection_uuid == collection.uuid
    ).all()
    path_mappings = [(pm.plex_path, pm.local_path) for pm in path_mappings_list]

    # Get assets in "new" state for this collection
    assets = db.query(Asset).filter(
        Asset.collection_uuid == collection.uuid,
        Asset.state == "new"
    ).all()

    summary["total"] = len(assets)

    if not assets:
        logger.info(f"No assets in new state for collection {collection.name}")
        return summary

    # Get enrichers from collection config
    enrichers_config = (collection.config or {}).get("enrichers", [])
    if not enrichers_config:
        logger.warning(f"No enrichers configured for collection {collection.name}")
        # Still count as skipped rather than failed
        summary["skipped"] = len(assets)
        return summary

    # Instantiate enrichers (sorted by priority if present)
    # Collection config stores enricher references as {"enricher_id": "...", "priority": N}
    # We look up the enricher_id in the enrichers table to get the type, then
    # instantiate from the ENRICHERS registry.
    from ..domain.entities import Enricher as EnricherEntity
    from ..adapters.registry import ENRICHERS

    enrichers = []
    for enricher_conf in enrichers_config:
        try:
            enricher_id = enricher_conf.get("enricher_id")
            enricher_type = enricher_conf.get("type")  # direct type override

            if not enricher_type and enricher_id:
                # Look up enricher in the enrichers table
                enricher_row = db.query(EnricherEntity).filter(
                    EnricherEntity.enricher_id == enricher_id
                ).first()
                if enricher_row:
                    enricher_type = enricher_row.type
                else:
                    logger.error(f"Enricher not found in DB: {enricher_id}")
                    continue

            enricher_config = enricher_conf.get("config", {})

            if enricher_type not in ENRICHERS:
                logger.error(f"Unknown enricher type: {enricher_type}")
                continue

            # Instantiate the enricher class with config
            enricher_class = ENRICHERS[enricher_type]
            enricher = enricher_class(**enricher_config)
            enrichers.append((enricher_conf.get("priority", 999), enricher))
        except Exception as e:
            logger.error(f"Failed to instantiate enricher {enricher_conf}: {e}")
            continue

    # Sort by priority (lower numbers first)
    enrichers.sort(key=lambda x: x[0])
    enrichers = [e[1] for e in enrichers]

    if not enrichers:
        logger.warning(f"No valid enrichers for collection {collection.name}")
        summary["skipped"] = len(assets)
        return summary

    # Get importer for path resolution
    from ..adapters.registry import get_importer

    importer_config = {k: v for k, v in (source.config or {}).items() if k != "enrichers"}
    importer = get_importer(source.type, **importer_config)

    # Process each asset
    for asset in assets:
        try:
            # Transition to "enriching" state
            asset.state = "enriching"
            db.flush()

            # Get editorial data for this asset
            from ..domain.entities import AssetEditorial
            editorial_obj = db.query(AssetEditorial).filter(
                AssetEditorial.asset_uuid == asset.uuid
            ).first()
            editorial_data = editorial_obj.payload if editorial_obj else {}

            # Create DiscoveredItem from existing asset data
            discovered_item = DiscoveredItem(
                path_uri=asset.uri,
                provider_key=asset.uri,  # Use URI as provider key for now
                raw_labels=[],  # Labels not needed for re-enrichment
                last_modified=asset.discovered_at,
                size=asset.size,
                editorial=editorial_data,
            )

            # Resolve local file path via AssetPathResolver
            try:
                collection_locations = (collection.config or {}).get("locations", [])
                plex_client = getattr(importer, "client", None)
                resolver = AssetPathResolver(
                    path_mappings=path_mappings,
                    plex_client=plex_client,
                    collection_locations=collection_locations,
                )
                local_path = resolver.resolve(
                    uri=asset.uri,
                    canonical_uri=asset.canonical_uri,
                )
            
                if not local_path:
                    logger.warning(
                        "Could not resolve local path for asset %s (uri=%s)",
                        asset.uuid, asset.uri,
                    )
                    summary["skipped"] += 1
                    asset.state = "new"
                    continue
            
                discovered_item.path_uri = local_path
                asset.canonical_uri = local_path
                db.flush()
            
            except Exception as e:
                logger.error("Error resolving path for asset %s: %s", asset.uuid, e)
                summary["skipped"] += 1
                asset.state = "new"
                continue


            # Run enrichers in sequence
            enriched_item = discovered_item
            for enricher in enrichers:
                try:
                    enriched_item = enricher.enrich(enriched_item)
                except Exception as e:
                    logger.error(f"Enricher {enricher.name} failed for asset {asset.uuid}: {e}")
                    # Continue with next enricher rather than failing the whole asset
                    continue

            # Extract probed data
            probed_data = enriched_item.probed or {}

            # Update asset fields from probed data
            if probed_data.get("duration_ms"):
                asset.duration_ms = probed_data["duration_ms"]

            if probed_data.get("video"):
                video_data = probed_data["video"]
                asset.video_codec = video_data.get("codec")

            if probed_data.get("audio"):
                audio_data = probed_data["audio"]
                if isinstance(audio_data, list) and len(audio_data) > 0:
                    asset.audio_codec = audio_data[0].get("codec")

            if probed_data.get("container"):
                asset.container = probed_data["container"]

            # Persist probed data to asset_probed table
            persist_asset_metadata(
                db,
                asset,
                probed=probed_data
            )

            # Extract and create chapter markers
            chapters = probed_data.get("chapters", [])
            if chapters:
                for ch in chapters:
                    marker = Marker(
                        id=uuid4(),
                        asset_uuid=asset.uuid,
                        kind=MarkerKind.CHAPTER,
                        start_ms=ch.get("start_ms", 0),
                        end_ms=ch.get("end_ms", 0),
                        payload={"title": ch.get("title", "")}
                    )
                    db.add(marker)

            # Only promote to ready if we got meaningful probe data
            if asset.duration_ms and asset.duration_ms > 0:
                asset.state = "ready"
            else:
                asset.state = "new"
                asset.approved_for_broadcast = False
                logger.warning(f"Asset {asset.uuid} enriched but missing valid duration, keeping in new state")
            db.flush()

            summary["enriched"] += 1
            logger.info(f"Successfully enriched asset {asset.uuid}")

        except Exception as e:
            logger.error(f"Failed to enrich asset {asset.uuid}: {e}")
            summary["failed"] += 1
            # Revert state on failure
            try:
                asset.state = "new"
                db.flush()
            except Exception:
                pass
            continue

    # Commit all changes
    db.commit()

    logger.info(
        f"Ingest complete for collection {collection.name}: "
        f"{summary["enriched"]} enriched, {summary["skipped"]} skipped, {summary["failed"]} failed"
    )

    return summary
