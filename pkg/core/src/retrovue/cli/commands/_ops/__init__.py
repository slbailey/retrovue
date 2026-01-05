"""
Operations package for destructive CLI commands.

This package contains contract-driven helper modules for destructive commands
that implement standardized confirmation and safety logic.

Modules:
- confirmation: Interactive destructive confirmation logic (C-1 through C-14)
- source_delete_ops: Source deletion operations (B-4 through B-8, D-1 through D-10)
"""

from .collection_ingest_service import (
    CollectionIngestResult,
    CollectionIngestService,
    IngestStats,
    resolve_collection_selector,
    validate_ingestible_with_importer,
    validate_prerequisites,
)
from .confirmation import (
    PendingDeleteSummary,
    SourceImpact,
    build_confirmation_prompt,
    evaluate_confirmation,
)
from .source_delete_ops import (
    build_pending_delete_summary,
    delete_one_source_transactionally,
    format_human_output,
    format_json_output,
    is_production_runtime,
    perform_source_deletions,
    resolve_source_selector,
    source_is_protected_for_prod_delete,
)
from .source_ingest_service import (
    CollectionIngestResult as SourceCollectionIngestResult,
)
from .source_ingest_service import (
    SourceIngestResult,
    SourceIngestService,
)
from .source_ingest_service import (
    resolve_source_selector as resolve_source_selector_for_ingest,
)

__all__ = [
    # Confirmation module exports
    "PendingDeleteSummary",
    "SourceImpact",
    "build_confirmation_prompt",
    "evaluate_confirmation",
    # Source delete ops module exports
    "build_pending_delete_summary",
    "delete_one_source_transactionally",
    "format_human_output",
    "format_json_output",
    "is_production_runtime",
    "perform_source_deletions",
    "resolve_source_selector",
    "source_is_protected_for_prod_delete",
    # Collection ingest service exports
    "CollectionIngestResult",
    "CollectionIngestService",
    "IngestStats",
    "resolve_collection_selector",
    "validate_ingestible_with_importer",
    "validate_prerequisites",
    # Source ingest service exports
    "SourceIngestResult",
    "SourceIngestService",
    "SourceCollectionIngestResult",
    "resolve_source_selector_for_ingest",
]
