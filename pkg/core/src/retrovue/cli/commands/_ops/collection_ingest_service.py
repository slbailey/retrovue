"""
Backward-compatibility shim — re-exports from retrovue.workflows.container_ingest.

The canonical implementation was relocated to ``retrovue.workflows.container_ingest``
as part of the Asset Domain Alignment Plan (Phase 1).  This module re-exports all
public names so that existing callers (CLI commands and tests) continue to work
without import changes.  It will be removed in Phase 4 (legacy cleanup).
"""

from retrovue.workflows.container_ingest import (  # noqa: F401
    ContainerIngestResult,
    ContainerIngestService,
    IngestStats,
    get_container_by_id,
    refresh_container,
    resolve_container_selector,
    validate_ingestible_with_importer,
    validate_prerequisites,
)

__all__ = [
    "ContainerIngestResult",
    "ContainerIngestService",
    "IngestStats",
    "get_container_by_id",
    "refresh_container",
    "resolve_container_selector",
    "validate_ingestible_with_importer",
    "validate_prerequisites",
]
