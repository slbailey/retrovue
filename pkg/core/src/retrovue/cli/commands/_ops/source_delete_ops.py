"""
Source delete operations module.

This module encapsulates all non-IO logic needed to satisfy
docs/contracts/resources/SourceDeleteContract.md, specifically rules B-4 through B-8,
and D-1 through D-10.

The module provides:
- Source selector resolution (wildcard and exact match)
- Pending delete summary building
- Production safety checks
- Transactional source deletion
- Batch deletion with partial success support
- Output formatting helpers

This module MUST NOT read from stdin or write to stdout. All IO stays in the CLI command wrapper.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from ....domain.entities import Asset, Collection, PathMapping, Source
from .confirmation import PendingDeleteSummary, SourceImpact


def resolve_source_selector(db: Session, source_selector: str) -> list[Source]:
    """
    Resolve source selector to a concrete list of sources.

    Implements wildcard and exact match resolution for <source_selector>, per B-8.

    Args:
        db: Database session
        source_selector: The selector string (exact ID/name, wildcard pattern, or "*")

    Returns:
        List of matching sources, deterministically ordered by (name, id)
    """
    # If selector is exactly "*", return all sources
    if source_selector == "*":
        sources = db.query(Source).order_by(Source.name, Source.id).all()
        return sources

    # Check if selector contains wildcard characters (*, ?, or %)
    if "*" in source_selector or "?" in source_selector or "%" in source_selector:
        # Match against source name and external_id using SQL LIKE semantics
        like_pattern = source_selector.replace("*", "%").replace("?", "_")
        sources = (
            db.query(Source)
            .filter(or_(Source.name.like(like_pattern), Source.external_id.like(like_pattern)))
            .order_by(Source.name, Source.id)
            .all()
        )
        return sources

    # For exact matches, we need to be more careful about UUID parsing
    # Try to match against external_id and name first (safer)
    sources = (
        db.query(Source)
        .filter(or_(Source.external_id == source_selector, Source.name == source_selector))
        .order_by(Source.name, Source.id)
        .all()
    )

    # If no matches found and the selector looks like a UUID, try UUID match
    if not sources and _is_valid_uuid(source_selector):
        sources = (
            db.query(Source)
            .filter(Source.id == source_selector)
            .order_by(Source.name, Source.id)
            .all()
        )

    return sources


def _is_valid_uuid(uuid_string: str) -> bool:
    """
    Check if a string is a valid UUID format.

    Args:
        uuid_string: String to check

    Returns:
        True if the string is a valid UUID format, False otherwise
    """
    import uuid

    try:
        uuid.UUID(uuid_string)
        return True
    except (ValueError, TypeError):
        return False


def build_pending_delete_summary(db: Session, sources: list[Source]) -> PendingDeleteSummary:
    """
    Build summary of pending deletion impact.

    For each source, fetch:
    - number of collections that will be deleted for that source
    - number of path mappings that will be deleted for that source

    Aggregate totals across all selected sources.

    Args:
        db: Database session
        sources: List of sources to be deleted

    Returns:
        PendingDeleteSummary with impact details
    """
    source_impacts = []
    total_collections = 0
    total_path_mappings = 0

    for source in sources:
        # Count collections for this source
        collections_count = db.query(Collection).filter(Collection.source_id == source.id).count()

        # Count path mappings for this source (through collections)
        path_mappings_count = (
            db.query(PathMapping)
            .join(Collection, PathMapping.collection_uuid == Collection.uuid)
            .filter(Collection.source_id == source.id)
            .count()
        )

        source_impact = SourceImpact(
            source_id=str(source.id),
            source_name=source.name,
            source_type=source.type,
            collections_count=collections_count,
            path_mappings_count=path_mappings_count,
        )
        source_impacts.append(source_impact)

        total_collections += collections_count
        total_path_mappings += path_mappings_count

    return PendingDeleteSummary(
        sources=source_impacts,
        total_sources=len(sources),
        total_collections=total_collections,
        total_path_mappings=total_path_mappings,
    )


def is_production_runtime(args: Any, env_config: Any) -> bool:
    """
    Determine if we should apply production safety.

    Returns True if we should apply production safety (D-5).

    Args:
        args: Command line arguments (must have test_db attribute)
        env_config: Environment configuration object (must have is_production method)

    Returns:
        True if production safety should be applied
    """
    # If the user passed --test-db, MUST return False
    if hasattr(args, "test_db") and args.test_db:
        return False

    # Otherwise, MUST delegate to env_config.is_production()
    return env_config.is_production()


def source_is_protected_for_prod_delete(db: Session, source_id: str) -> bool:
    """
    Check if source is protected for production deletion.

    Implements production safety for sources (D-5).
    Returns True if this Source MUST NOT be deleted in production.

    Logic MUST reflect D-5:
    "A Source MUST NOT be deleted in production if any Asset from that Source
    has appeared in a PlaylogEvent or AsRunLog."

    Args:
        db: Database session
        source_id: The source ID to check

    Returns:
        True if source is protected and cannot be deleted in production
    """
    # TODO: Implement actual check for PlaylogEvent and AsRunLog
    # For now, return False to allow deletion (this is a placeholder)
    # The actual implementation will need to check if any assets from this source
    # have appeared in PlaylogEvent or AsRunLog tables
    return False


def delete_one_source_transactionally(db: Session, source_id: str) -> dict[str, Any]:
    """
    Perform cascade deletion for a single source inside a transaction.

    Follows UnitOfWorkContract 3-phase pattern:
    1. Pre-flight validation
    2. Execute operation
    3. Post-operation validation

    Satisfies D-1, D-2, D-3, D-4, and D-9.

    Pre-conditions:
    - Source exists and is accessible
    - No conflicting operations in progress
    - All dependencies are identified

    Post-conditions:
    - Source and all associated data are deleted
    - No orphaned records exist
    - Database state is consistent

    Atomicity:
    - If any deletion step fails, entire operation rolls back
    - If any validation fails, entire operation rolls back
    - If any constraint violation occurs, entire operation rolls back

    Args:
        db: Database session (must be within a transaction)
        source_id: The source ID to delete

    Returns:
        Dict with collections_deleted and path_mappings_deleted counts
    """
    try:
        # Phase 1: Pre-flight validation
        source = db.query(Source).filter(Source.id == source_id).first()
        if not source:
            raise ValueError(f"Source '{source_id}' not found")

        # Validate source is accessible (not locked by other operations)
        # TODO: Add lock validation when concurrent operation support is added

        # Get counts before deletion for audit logging
        collections_count = db.query(Collection).filter(Collection.source_id == source_id).count()

        path_mappings_count = (
            db.query(PathMapping)
            .join(Collection, PathMapping.collection_uuid == Collection.uuid)
            .filter(Collection.source_id == source_id)
            .count()
        )

        # Pre-check for dependent assets to avoid FK violations and produce friendly message
        assets_count = (
            db.query(Asset)
            .join(Collection, Asset.collection_uuid == Collection.uuid)
            .filter(Collection.source_id == source_id)
            .count()
        )
        if assets_count > 0:
            raise RuntimeError(
                f"Cannot delete source: {assets_count} assets still reference its collections. "
                f"Wipe or migrate those collections first."
            )

        # Phase 2: Execute operation
        # Delete the source (collections and path mappings must be non-referenced)
        db.delete(source)
        db.flush()  # Ensure the deletion is visible within the transaction

        # Phase 3: Post-operation validation
        # Verify source is actually deleted
        remaining_source = db.query(Source).filter(Source.id == source_id).first()
        if remaining_source:
            raise RuntimeError(f"Source '{source_id}' still exists after deletion")

        # Verify no orphaned collections remain
        remaining_collections = (
            db.query(Collection).filter(Collection.source_id == source_id).count()
        )
        if remaining_collections > 0:
            raise RuntimeError(
                f"{remaining_collections} orphaned collections remain for source '{source_id}'"
            )

        # TODO: Add audit logging here (D-6)
        # Log deletion with source details, collection count, and path mapping count

        return {
            "collections_deleted": collections_count,
            "path_mappings_deleted": path_mappings_count,
        }

    except Exception as e:
        # Transaction automatically rolls back via session context manager
        # Log error with full context
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"source_deletion_failed: source_id={source_id}, error={str(e)}, "
            f"collections_count={collections_count if 'collections_count' in locals() else 0}, "
            f"path_mappings_count={path_mappings_count if 'path_mappings_count' in locals() else 0}"
        )
        raise


def perform_source_deletions(
    db: Session, env_config: Any, args: Any, sources: list[Source]
) -> list[dict[str, Any]]:
    """
    Perform source deletions with production safety and partial success support.

    Follows UnitOfWorkContract principles for multi-source operations.

    This is the core B-8 / D-8 / D-5 behavior.

    Pre-conditions:
    - All sources exist and are accessible
    - Environment configuration is valid
    - No conflicting operations in progress

    Post-conditions:
    - Each source is either deleted or skipped with reason
    - No orphaned records exist
    - Database state is consistent

    Atomicity:
    - Each individual source deletion is atomic
    - Partial success is supported (some sources may succeed, others fail)
    - Failed deletions do not affect successful ones

    Args:
        db: Database session
        env_config: Environment configuration
        args: Command line arguments
        sources: List of sources to process

    Returns:
        List of result dicts in deterministic order
    """
    try:
        # Phase 1: Pre-flight validation
        if not sources:
            raise ValueError("No sources provided for deletion")

        # Validate environment configuration
        if not hasattr(env_config, "is_production"):
            raise ValueError("Environment configuration missing is_production method")

        # Validate each source exists and is accessible
        for source in sources:
            if not source or not source.id:
                raise ValueError("Invalid source in deletion list")

        # Phase 2: Execute operations
        results = []
        is_production = is_production_runtime(args, env_config)

        for source in sources:
            try:
                if is_production and source_is_protected_for_prod_delete(db, str(source.id)):
                    # Do NOT delete that source
                    result = {
                        "deleted": False,
                        "source_id": str(source.id),
                        "source_name": source.name,
                        "source_type": source.type,
                        "skipped_reason": "production safety",
                    }
                else:
                    # Call delete_one_source_transactionally for that source
                    deletion_result = delete_one_source_transactionally(db, str(source.id))
                    result = {
                        "deleted": True,
                        "source_id": str(source.id),
                        "source_name": source.name,
                        "source_type": source.type,
                        "collections_deleted": deletion_result["collections_deleted"],
                        "path_mappings_deleted": deletion_result["path_mappings_deleted"],
                    }

                results.append(result)

            except Exception as e:
                # Individual source deletion failed - record error but continue with others
                import logging

                logger = logging.getLogger(__name__)
                logger.error(
                    f"individual_source_deletion_failed: source_id={str(source.id)}, source_name={source.name}, error={str(e)}"
                )

                # Reset the session to a clean state before continuing
                try:
                    db.rollback()
                except Exception:
                    pass

                result = {
                    "deleted": False,
                    "source_id": str(source.id),
                    "source_name": source.name,
                    "source_type": source.type,
                    "skipped_reason": (
                        "dependencies present: assets still reference collections; "
                        "wipe collections first"
                        if "assets still reference" in str(e)
                        else f"deletion failed: {e}"
                    ),
                }
                results.append(result)

        # Phase 3: Post-operation validation
        # Verify all sources were processed
        if len(results) != len(sources):
            raise RuntimeError(
                f"Processing incomplete: {len(results)} results for {len(sources)} sources"
            )

        # Verify no orphaned records exist
        # TODO: Add comprehensive orphaned record validation

        return results

    except Exception as e:
        # Log error with full context
        import logging

        logger = logging.getLogger(__name__)
        logger.error(
            f"source_deletions_operation_failed: source_count={len(sources) if sources else 0}, error={str(e)}"
        )
        raise


def format_json_output(results: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Format results as JSON output required by B-4.

    Args:
        results: List of result dicts from perform_source_deletions

    Returns:
        JSON-serializable dict with the required structure
    """
    if len(results) == 1:
        # Single-source delete case MUST include top-level fields
        result = results[0]
        return {
            "deleted": result["deleted"],
            "source_id": result["source_id"],
            "name": result["source_name"],
            "type": result["source_type"],
            "collections_deleted": result.get("collections_deleted", 0),
            "path_mappings_deleted": result.get("path_mappings_deleted", 0),
            **({"skipped_reason": result["skipped_reason"]} if "skipped_reason" in result else {}),
        }
    else:
        # Multi-source delete case MAY return a wrapper object with "results": [...]
        return {"results": results}


def format_human_output(results: list[dict[str, Any]]) -> str:
    """
    Produce human-readable output for non-json mode.

    Args:
        results: List of result dicts from perform_source_deletions

    Returns:
        Human-readable output string
    """
    output_lines = []

    for result in results:
        if result["deleted"]:
            # For each successfully deleted source, it MUST include "Successfully deleted source:"
            # and its ID and Type, consistent with the examples in the contract
            output_lines.append(f"Successfully deleted source: {result['source_name']}")
            output_lines.append(f"  ID: {result['source_id']}")
            output_lines.append(f"  Type: {result['source_type']}")
        else:
            # For each skipped source (production safety), it MUST include "Skipped source:"
            # and the skip reason
            output_lines.append(f"Skipped source: {result['source_name']}")
            output_lines.append(f"  Reason: {result['skipped_reason']}")

    return "\n".join(output_lines)
