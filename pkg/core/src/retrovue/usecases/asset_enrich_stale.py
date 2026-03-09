"""
Use-case: bulk enrichment of stale assets across source or collection scope.

Orchestrates ``apply_enrichers_to_collection`` across all collections belonging
to a source, or a single collection, with optional dry-run support.

This module MUST NOT commit; the caller owns the transaction boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import Collection
from .collection_enrichers import _resolve_collection, apply_enrichers_to_collection


def _resolve_source(db, selector):
    """Late-import wrapper to avoid circular dependency with CLI layer."""
    from ..cli.commands._ops.source_ingest_service import resolve_source_selector

    return resolve_source_selector(db, selector)


@dataclass
class BulkEnrichResult:
    """Result of a bulk stale-asset enrichment operation."""

    source_name: str | None
    collections_processed: int
    total_assets_considered: int
    total_assets_enriched: int
    total_assets_auto_ready: int
    total_errors: list[str] = field(default_factory=list)
    collection_results: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        status = "success"
        if self.total_errors:
            status = "partial"
        if self.collections_processed == 0:
            status = "no_collections"

        return {
            "status": status,
            "source": self.source_name,
            "dry_run": self.dry_run,
            "collections_processed": self.collections_processed,
            "stats": {
                "assets_considered": self.total_assets_considered,
                "assets_enriched": self.total_assets_enriched,
                "assets_auto_ready": self.total_assets_auto_ready,
                "errors": self.total_errors,
            },
            "collection_results": self.collection_results,
        }


def enrich_stale_assets(
    db: Session,
    *,
    source_selector: str | None = None,
    collection_selector: str | None = None,
    dry_run: bool = False,
    max_assets: int | None = None,
) -> BulkEnrichResult:
    """Enrich stale assets across a source or single collection.

    Exactly one of ``source_selector`` or ``collection_selector`` must be
    provided.

    Args:
        db: Active SQLAlchemy session (caller manages transaction).
        source_selector: Source name, UUID, or external_id.
        collection_selector: Collection name, UUID, or external_id.
        dry_run: If True, count stale assets without enriching.
        max_assets: Max assets to process per collection.

    Returns:
        BulkEnrichResult with aggregated statistics.
    """
    if source_selector and collection_selector:
        raise ValueError("Provide --source or --collection, not both.")
    if not source_selector and not collection_selector:
        raise ValueError("Provide --source or --collection.")

    source_name: str | None = None
    collections: list[Collection] = []

    if source_selector:
        source = _resolve_source(db, source_selector)
        source_name = source.name
        collections = (
            db.query(Collection)
            .filter(Collection.source_id == source.id)
            .all()
        )
    else:
        coll = _resolve_collection(db, collection_selector)
        source_name = getattr(getattr(coll, "source", None), "name", None)
        collections = [coll]

    agg = BulkEnrichResult(
        source_name=source_name,
        collections_processed=0,
        total_assets_considered=0,
        total_assets_enriched=0,
        total_assets_auto_ready=0,
        dry_run=dry_run,
    )

    for coll in collections:
        try:
            result = apply_enrichers_to_collection(
                db,
                collection_selector=str(coll.uuid),
                max_assets=max_assets,
                dry_run=dry_run,
            )
            agg.collection_results.append(result)
            agg.collections_processed += 1

            stats = result.get("stats", {})
            agg.total_assets_considered += stats.get("assets_considered", 0)
            agg.total_assets_enriched += stats.get("assets_enriched", 0)
            agg.total_assets_auto_ready += stats.get("assets_auto_ready", 0)

            for err in stats.get("errors", []):
                agg.total_errors.append(f"{coll.name}: {err}")
        except Exception as exc:
            agg.total_errors.append(f"{coll.name}: {exc}")

    return agg
