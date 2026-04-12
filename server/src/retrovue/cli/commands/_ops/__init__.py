"""
Operations package for destructive CLI commands.

This package contains contract-driven helper modules for destructive commands
that implement standardized confirmation and safety logic.

Modules:
- confirmation: Interactive destructive confirmation logic (C-1 through C-14)
- source_delete_ops: Source deletion operations (B-4 through B-8, D-1 through D-10)

Cross-domain ingest workflows were relocated to retrovue.workflows/ in Phase 1
of the Asset Domain Alignment Plan (RETA-69).
"""

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
]
