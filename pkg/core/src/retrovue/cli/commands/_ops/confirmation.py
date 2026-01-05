"""
Confirmation module for destructive operations.

This module implements interactive destructive confirmation logic as defined by
docs/contracts/_ops/DestructiveOperationConfirmation.md (C-1 through C-14).

The module provides:
- A lightweight data structure that summarizes the impact of a pending destructive operation
- Functions to build human-facing confirmation prompt text
- Functions to evaluate confirmation and return a decision

This module is designed to be testable without mocking stdin/stdout.
The CLI wrapper will handle IO; tests will call these helpers directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SourceImpact:
    """Impact summary for a single source being deleted."""

    source_id: str
    source_name: str
    source_type: str
    collections_count: int
    path_mappings_count: int


@dataclass
class PendingDeleteSummary:
    """Summary of pending destructive operation across one or more targets."""

    sources: list[SourceImpact]
    total_sources: int
    total_collections: int
    total_path_mappings: int


def build_confirmation_prompt(summary: PendingDeleteSummary) -> str:
    """
    Build the human-facing confirmation prompt text.

    Satisfies C-2, C-3, C-5, C-6 from DestructiveOperationConfirmation contract.

    Args:
        summary: The impact summary of the pending operation

    Returns:
        The confirmation prompt text that MUST end with "Type 'yes' to confirm:"
    """
    if summary.total_sources == 1:
        # Single-source delete: prompt must include that source's name, ID, and its cascade counts
        source = summary.sources[0]
        prompt = f"""WARNING: This will permanently delete the following:
   - Source: "{source.source_name}" (ID: {source.source_id})
   - Collections: {source.collections_count} collections will be deleted
   - Path mappings: {source.path_mappings_count} path mappings will be deleted

This action cannot be undone. Type 'yes' to confirm:"""
    else:
        # Multi-source deletes (wildcard): prompt must summarize total sources, total collections, and total path mappings
        prompt = f"""WARNING: This will permanently delete {summary.total_sources} sources:"""

        for source in summary.sources:
            prompt += f"""
   - Source: "{source.source_name}" (ID: {source.source_id}) - {source.collections_count} collections, {source.path_mappings_count} path mappings"""

        prompt += f"""

Total impact: {summary.total_collections} collections, {summary.total_path_mappings} path mappings will be removed.
This action cannot be undone. Type 'yes' to confirm:"""

    return prompt


def evaluate_confirmation(
    summary: PendingDeleteSummary,
    force: bool = False,
    confirm: bool = False,
    user_response: str | None = None,
) -> tuple[bool, str | None]:
    """
    Evaluate confirmation and return a decision.

    Satisfies C-1, C-3, C-4, C-7, C-8 from DestructiveOperationConfirmation contract.

    Args:
        summary: The impact summary of the pending operation
        force: Whether --force flag was provided (skips prompting)
        confirm: Whether --confirm flag was provided (skips prompting but not production safety)
        user_response: User's response to confirmation prompt (None on first call)

    Returns:
        Tuple of (proceed: bool, message: str | None) where:
        - If proceed is True, it is safe to perform deletions
        - If proceed is False and message is a prompt string, the caller must show that prompt and collect user input
        - If proceed is False and message is "Deletion cancelled", the caller must print that and exit code 0
    """
    # C-7, C-8: --force skips prompting
    if force:
        return True, None

    # C-7: --confirm skips prompting but does NOT bypass production safety
    if confirm:
        return True, None

    # Without either flag: interactive confirmation required
    if user_response is None:
        # First call (no user_response yet) should tell the caller "ask the user"
        prompt = build_confirmation_prompt(summary)
        return False, prompt

    # Second call (with user_response) should only allow proceed if the response is exactly "yes"
    # C-3, C-4: Only "yes" (lowercase) is accepted as confirmation
    if user_response.strip() == "yes":
        return True, None
    else:
        # Any other response should yield (False, "Deletion cancelled") and that MUST map to exit code 0 per C-4, C-12
        return False, "Deletion cancelled"
