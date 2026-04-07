"""
Workflows package — cross-domain orchestration logic.

Workflows coordinate operations that span multiple domains (e.g. ingest
touches catalog, enrichment, and processor jobs).  Domain-internal operations
remain as usecases; only cross-domain coordination lives here.

Extracted from cli/commands/_ops/ per the Asset Domain Alignment Plan (Phase 1).
"""

from .container_ingest import (
    ContainerIngestResult,
    ContainerIngestService,
    IngestStats,
    get_container_by_id,
    refresh_container,
    resolve_container_selector,
    validate_ingestible_with_importer,
    validate_prerequisites,
)
from .source_ingest import (
    SourceIngestResult,
    SourceIngestService,
    SourceIngestStats,
    resolve_source_selector,
)

__all__ = [
    # Container ingest workflow
    "ContainerIngestResult",
    "ContainerIngestService",
    "IngestStats",
    "get_container_by_id",
    "refresh_container",
    "resolve_container_selector",
    "validate_ingestible_with_importer",
    "validate_prerequisites",
    # Source ingest workflow
    "SourceIngestResult",
    "SourceIngestService",
    "SourceIngestStats",
    "resolve_source_selector",
]
