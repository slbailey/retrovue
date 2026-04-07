"""
Backward-compatibility shim — re-exports from retrovue.workflows.source_ingest.

The canonical implementation was relocated to ``retrovue.workflows.source_ingest``
as part of the Asset Domain Alignment Plan (Phase 1).  This module re-exports all
public names so that existing callers (CLI commands and tests) continue to work
without import changes.  It will be removed in Phase 4 (legacy cleanup).
"""

from retrovue.workflows.source_ingest import (  # noqa: F401
    SourceIngestResult,
    SourceIngestService,
    SourceIngestStats,
    resolve_source_selector,
)

__all__ = [
    "SourceIngestResult",
    "SourceIngestService",
    "SourceIngestStats",
    "resolve_source_selector",
]
