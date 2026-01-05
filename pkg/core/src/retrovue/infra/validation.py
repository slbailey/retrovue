"""
Unit of Work validation functions for RetroVue operations.

This module provides validation functions that ensure operations follow
the Unit of Work paradigm with proper pre-flight and post-operation validation.
"""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..domain.entities import (
    Asset,
    Collection,
    PathMapping,
)
from ..infra.exceptions import ValidationError


def validate_collection_exists(db: Session, collection_id: str) -> Collection:
    """
    Validate collection exists and return it.

    Args:
        db: Database session
        collection_id: Collection identifier (UUID, external_id, or name)

    Returns:
        Collection: The found collection

    Raises:
        ValidationError: If collection not found or ambiguous
    """
    # Try UUID first
    try:
        import uuid

        uuid.UUID(collection_id)
        collection = db.query(Collection).filter(Collection.uuid == collection_id).first()
        if collection:
            return collection
    except ValueError:
        pass

    # Try external_id
    collection = db.query(Collection).filter(Collection.external_id == collection_id).first()
    if collection:
        return collection

    # Try name (case-insensitive)
    collections = db.query(Collection).filter(Collection.name.ilike(collection_id)).all()

    if len(collections) == 0:
        raise ValidationError(f"Collection '{collection_id}' not found")
    elif len(collections) > 1:
        names = [c.name for c in collections]
        raise ValidationError(f"Multiple collections match '{collection_id}': {names}")

    return collections[0]


def validate_collection_enabled(collection: Collection) -> None:
    """
    Validate collection is enabled for operations.

    Args:
        collection: Collection to validate

    Raises:
        ValidationError: If collection is not enabled
    """
    if not collection.sync_enabled:
        raise ValidationError(f"Collection '{collection.name}' is not enabled")


def validate_path_mappings(db: Session, collection: Collection) -> None:
    """
    Validate collection has valid path mappings.

    Args:
        db: Database session
        collection: Collection to validate

    Raises:
        ValidationError: If path mappings are invalid
    """
    mappings = db.query(PathMapping).filter(PathMapping.collection_uuid == collection.uuid).all()

    if not mappings:
        raise ValidationError(f"Collection '{collection.name}' has no path mappings")

    # Check if at least one mapping has a valid local path
    valid_mappings = [m for m in mappings if m.local_path and m.local_path.strip()]
    if not valid_mappings:
        raise ValidationError(f"Collection '{collection.name}' has no valid local paths")


def validate_source_connectivity(db: Session, source_id: str) -> None:
    """
    Validate source is reachable and authenticated.

    Args:
        db: Database session
        source_id: Source identifier

    Raises:
        ValidationError: If source is not accessible
    """
    from ..domain.entities import Source

    source = db.query(Source).filter(Source.id == source_id).first()

    if not source:
        raise ValidationError(f"Source '{source_id}' not found")

    # TODO: Add actual connectivity check
    # This would involve testing the source connection
    # For now, we just validate the source exists


def validate_no_conflicting_operations(db: Session, collection_id: str) -> None:
    """
    Validate no conflicting operations are in progress.

    Args:
        db: Database session
        collection_id: Collection identifier

    Raises:
        ValidationError: If conflicting operations exist
    """
    # TODO: Implement operation locking mechanism
    # This would check for active ingest/wipe operations
    # For now, we just validate the collection exists
    pass


def validate_wipe_prerequisites(db: Session, collection: Collection) -> None:
    """
    Validate all prerequisites for wipe operation.

    Args:
        db: Database session
        collection: Collection to validate

    Raises:
        ValidationError: If prerequisites not met
    """
    # Validate collection is accessible
    validate_collection_enabled(collection)

    # Validate no critical dependencies
    # TODO: Add checks for critical dependencies

    # Validate business rules allow wipe
    # TODO: Add business rule validation


def validate_no_orphaned_records(db: Session) -> None:
    """
    Validate no orphaned records exist.
    If orphaned records are found, attempt to clean them up automatically.

    Args:
        db: Database session

    Raises:
        ValidationError: If orphaned records cannot be cleaned up
    """
    # Note: Title/Season/Episode orphaned record checks removed - these tables have been dropped
    # Series/episode data is stored in asset_editorial.payload instead
    # TODO: Add validation for orphaned assets if needed


def validate_collection_preserved(db: Session, collection: Collection) -> None:
    """
    Validate collection is preserved after operation.

    Args:
        db: Database session
        collection: Collection to validate

    Raises:
        ValidationError: If collection was deleted
    """
    preserved_collection = db.query(Collection).filter(Collection.uuid == collection.uuid).first()
    if not preserved_collection:
        raise ValidationError("Collection was deleted during operation")


def validate_path_mappings_preserved(db: Session, collection: Collection) -> None:
    """
    Validate path mappings are preserved after operation.

    Args:
        db: Database session
        collection: Collection to validate

    Raises:
        ValidationError: If path mappings were deleted
    """
    path_mappings = (
        db.query(PathMapping).filter(PathMapping.collection_uuid == collection.uuid).count()
    )
    if path_mappings == 0:
        raise ValidationError("Path mappings were deleted during operation")


def validate_database_consistency(db: Session) -> None:
    """
    Validate overall database consistency.

    Args:
        db: Database session

    Raises:
        ValidationError: If database is inconsistent
    """
    # Check foreign key constraints
    try:
        db.flush()
    except IntegrityError as e:
        raise ValidationError(f"Database constraint violation: {e}")

    # Check business rule compliance
    # TODO: Add business rule validation

    # Check data integrity
    # TODO: Add data integrity checks


def validate_asset_draft(asset_draft) -> None:
    """
    Validate asset draft is valid and complete.

    Args:
        asset_draft: Asset draft to validate

    Raises:
        ValidationError: If asset draft is invalid
    """
    if not asset_draft.file_path:
        raise ValidationError("Asset draft missing file path")

    if not asset_draft.series_title:
        raise ValidationError("Asset draft missing series title")

    if asset_draft.season_number is None:
        raise ValidationError("Asset draft missing season number")

    if asset_draft.episode_number is None:
        raise ValidationError("Asset draft missing episode number")


def validate_collection_accessible(db: Session, collection: Collection) -> None:
    """
    Validate collection is accessible for operations.

    Args:
        db: Database session
        collection: Collection to validate

    Raises:
        ValidationError: If collection is not accessible
    """
    validate_collection_enabled(collection)
    validate_path_mappings(db, collection)


def validate_enrichers_available(db: Session, collection: Collection) -> None:
    """
    Validate all required enrichers are available.

    Args:
        db: Database session
        collection: Collection to validate

    Raises:
        ValidationError: If enrichers are not available
    """
    # TODO: Implement enricher validation
    # This would check that all required enrichers are available
    pass


def validate_asset_relationships(db: Session, asset: Asset) -> None:
    """
    Validate asset has proper relationships.

    Args:
        db: Database session
        asset: Asset to validate

    Raises:
        ValidationError: If relationships are invalid
    """
    # Check asset has collection
    if not asset.collection_id:
        raise ValidationError("Asset missing collection relationship")

    # Check collection exists
    collection = db.query(Collection).filter(Collection.uuid == asset.collection_id).first()
    if not collection:
        raise ValidationError("Asset references non-existent collection")


def validate_hierarchy_integrity(db: Session, result) -> None:
    """
    Validate hierarchy integrity after asset processing.

    Args:
        db: Database session
        result: Processing result to validate

    Raises:
        ValidationError: If hierarchy is invalid
    """
    # TODO: Implement hierarchy validation
    # This would check that all hierarchy relationships are correct
    pass


def validate_no_duplicates(db: Session, asset: Asset) -> None:
    """
    Validate no duplicate assets exist.

    Args:
        db: Database session
        asset: Asset to validate

    Raises:
        ValidationError: If duplicates exist
    """
    duplicates = db.query(Asset).filter(Asset.uri == asset.uri, Asset.id != asset.id).count()

    if duplicates > 0:
        raise ValidationError(f"Duplicate asset found with URI: {asset.uri}")


def validate_all_relationships(db: Session, entities: list) -> None:
    """
    Validate all entities have proper relationships.

    Args:
        db: Database session
        entities: List of entities to validate

    Raises:
        ValidationError: If relationships are invalid
    """
    for entity in entities:
        if isinstance(entity, Asset):
            validate_asset_relationships(db, entity)


def validate_business_rules(db: Session, result) -> None:
    """
    Validate business rules are satisfied.

    Args:
        db: Database session
        result: Operation result to validate

    Raises:
        ValidationError: If business rules are violated
    """
    # TODO: Implement business rule validation
    # This would check that all business rules are satisfied
    pass
