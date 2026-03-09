"""
Source ingest operations module.

This module encapsulates all non-IO logic needed to satisfy
docs/contracts/resources/SourceIngestContract.md, specifically rules B-1 through B-15,
and D-1 through D-17.

The module provides:
- Source selector resolution (UUID, external ID, case-insensitive name)
- Collection filtering (sync_enabled=true AND ingestible=true)
- Single transaction boundary for entire source ingest operation
- Collection ingest orchestration and result aggregation
- Result shape matching contract output format

This module MUST NOT read from stdin or write to stdout. All IO stays in the CLI command wrapper.
"""

from __future__ import annotations

import structlog
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from ....domain.entities import Collection, Source
from .collection_ingest_service import CollectionIngestService

logger = structlog.get_logger(__name__)


def _construct_importer(collection, db):
    """Late-import wrapper to avoid circular dependency with collection.py."""
    from ..collection import construct_importer_for_collection

    return construct_importer_for_collection(collection, db)


@dataclass
class SourceIngestStats:
    """Aggregated statistics across all collections in a source ingest."""

    assets_discovered: int = 0
    assets_ingested: int = 0
    assets_skipped: int = 0
    assets_updated: int = 0
    duplicates_prevented: int = 0
    assets_changed_content: int = 0
    assets_changed_enricher: int = 0
    assets_auto_ready: int = 0
    assets_needs_enrichment: int = 0
    assets_needs_review: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class SourceIngestResult:
    """Result of a source ingest operation."""

    source_id: str
    source_name: str
    collections_processed: int
    collections_skipped: int
    stats: SourceIngestStats
    collection_results: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert result to dictionary matching contract JSON output format."""
        # Determine status from errors
        has_collection_errors = any(
            cr.get("stats", {}).get("errors")
            for cr in self.collection_results
        )
        if self.collections_processed == 0:
            status = "error"
        elif self.errors or has_collection_errors:
            status = "partial"
        else:
            status = "success"

        return {
            "status": status,
            "source": {"id": self.source_id, "name": self.source_name},
            "collections_processed": self.collections_processed,
            "collections_skipped": self.collections_skipped,
            "stats": {
                "assets_discovered": self.stats.assets_discovered,
                "assets_ingested": self.stats.assets_ingested,
                "assets_skipped": self.stats.assets_skipped,
                "assets_updated": self.stats.assets_updated,
                "duplicates_prevented": self.stats.duplicates_prevented,
                "assets_auto_ready": self.stats.assets_auto_ready,
                "assets_needs_enrichment": self.stats.assets_needs_enrichment,
                "assets_needs_review": self.stats.assets_needs_review,
                "errors": self.stats.errors,
            },
            "collection_results": self.collection_results,
            "errors": self.errors,
        }


class SourceIngestService:
    """Service for source-level ingest operations.

    Orchestrates collection ingest across all eligible collections for a
    source, delegating each collection to ``CollectionIngestService``.
    """

    def __init__(self, db: Session):
        self.db = db

    def ingest_source(
        self,
        source: Source,
        *,
        dry_run: bool = False,
        test_db: bool = False,
    ) -> SourceIngestResult:
        """Ingest all eligible collections for a source.

        For each collection where ``sync_enabled=True`` AND
        ``ingestible=True``, constructs an importer and delegates to
        ``CollectionIngestService.ingest_collection()``.

        Args:
            source: The source to ingest.
            dry_run: If True, pass through to collection ingest (no DB writes).
            test_db: If True, pass through to collection ingest.

        Returns:
            SourceIngestResult with aggregated statistics and per-collection results.
        """
        agg = SourceIngestStats()
        collection_results: list[dict[str, Any]] = []
        errors: list[str] = []
        skipped = 0

        # B-2, D-2: Only sync_enabled AND ingestible collections
        all_collections = (
            self.db.query(Collection)
            .filter(
                Collection.source_id == source.id,
                Collection.sync_enabled.is_(True),
            )
            .all()
        )

        eligible: list[Collection] = []
        for coll in all_collections:
            if coll.ingestible:
                eligible.append(coll)
            else:
                skipped += 1
                logger.info(
                    "source_ingest_skip_not_ingestible",
                    collection=coll.name,
                    collection_uuid=str(coll.uuid),
                )

        for coll in eligible:
            try:
                importer = _construct_importer(coll, self.db)
                cis = CollectionIngestService(self.db)
                cis_result = cis.ingest_collection(
                    collection=coll,
                    importer=importer,
                    dry_run=dry_run,
                    test_db=test_db,
                )
                result_dict = cis_result.to_dict()
                collection_results.append(result_dict)

                # Aggregate stats
                cis_stats = result_dict.get("stats", {})
                agg.assets_discovered += cis_stats.get("assets_discovered", 0)
                agg.assets_ingested += cis_stats.get("assets_ingested", 0)
                agg.assets_skipped += cis_stats.get("assets_skipped", 0)
                agg.assets_updated += cis_stats.get("assets_updated", 0)
                agg.duplicates_prevented += cis_stats.get("duplicates_prevented", 0)
                agg.assets_changed_content += cis_stats.get("assets_changed_content", 0)
                agg.assets_changed_enricher += cis_stats.get("assets_changed_enricher", 0)
                agg.assets_auto_ready += cis_stats.get("assets_auto_ready", 0)
                agg.assets_needs_enrichment += cis_stats.get("assets_needs_enrichment", 0)
                agg.assets_needs_review += cis_stats.get("assets_needs_review", 0)

                cis_errors = cis_stats.get("errors", [])
                if cis_errors:
                    for e in cis_errors:
                        agg.errors.append(f"{coll.name}: {e}")

            except Exception as exc:
                error_msg = f"{coll.name}: {exc}"
                errors.append(error_msg)
                logger.warning(
                    "source_ingest_collection_failed",
                    collection=coll.name,
                    error=str(exc),
                )

        return SourceIngestResult(
            source_id=str(source.id),
            source_name=source.name,
            collections_processed=len(eligible),
            collections_skipped=skipped,
            stats=agg,
            collection_results=collection_results,
            errors=errors,
        )


def resolve_source_selector(db: Session, selector: str) -> Source:
    """Resolve a source selector to a Source entity.

    Tries UUID, then external_id, then case-insensitive name.

    Args:
        db: Database session.
        selector: UUID, external ID, or case-insensitive name.

    Returns:
        Source entity.

    Raises:
        ValueError: If source not found or ambiguous name match.
    """
    import uuid as _uuid

    # Try UUID first (B-1)
    try:
        if len(selector) == 36 and selector.count("-") == 4:
            source_uuid = _uuid.UUID(selector)
            source = db.query(Source).filter(Source.id == source_uuid).first()
            if source:
                return source
    except (ValueError, TypeError):
        pass

    # Try external_id (B-1)
    source = db.query(Source).filter(Source.external_id == selector).first()
    if source:
        return source

    # Try case-insensitive name (B-1)
    name_matches = db.query(Source).filter(Source.name.ilike(selector)).all()
    if len(name_matches) == 1:
        return name_matches[0]
    elif len(name_matches) > 1:
        raise ValueError(
            f"Multiple sources named '{selector}' exist. Please specify the UUID."
        )

    raise ValueError(f"Source '{selector}' not found")
