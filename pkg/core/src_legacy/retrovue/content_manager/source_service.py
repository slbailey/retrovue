"""
Source service for managing content sources and collections.

This service handles the configuration and management of content sources
like Plex servers and filesystem collections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from ..domain.entities import Collection, PathMapping, Source


@dataclass
class ContentSourceDTO:
    """
    Data Transfer Object for content sources.

    Represents a content source like a Plex server or filesystem.
    """

    id: str
    """Unique identifier for the source"""

    external_id: str
    """External identifier for the source"""

    kind: str
    """Type of source (e.g., 'plex', 'filesystem')"""

    name: str
    """Human-readable name of the source"""

    status: str
    """Status of the source (e.g., 'connected', 'disconnected')"""

    base_url: str | None
    """Base URL for the source (if applicable)"""

    config: dict[str, Any] | None = None
    """Additional configuration for the source"""


@dataclass
class CollectionUpdateDTO:
    """
    Data Transfer Object for collection updates.

    Represents updates to a collection's configuration.
    """

    external_id: str
    """External identifier for the collection"""

    sync_enabled: bool
    """Whether the collection is enabled for sync"""

    mapping_pairs: list[tuple[str, str]]
    """Path mapping pairs [(source_prefix, local_prefix), ...]"""


@dataclass
class CollectionDTO:
    """
    Data Transfer Object for source collections.

    Represents a collection (e.g., Plex library, filesystem directory)
    within a content source.
    """

    external_id: str
    """External identifier (e.g., Plex library key)"""

    name: str
    """Human-readable name of the collection"""

    sync_enabled: bool
    """Whether this collection is enabled for ingestion"""

    mapping_pairs: list[tuple[str, str]]
    """Path mapping pairs [(source_prefix, local_prefix), ...]"""

    source_type: str
    """Type of source (e.g., 'plex', 'filesystem')"""

    config: dict[str, Any] | None = None
    """Additional configuration for the collection"""

    locations: list[str] = field(default_factory=list)
    """Filesystem locations for this collection (e.g., Plex library paths)"""


class SourceService:
    """
    Authority for external sources, source collections, and path mappings.

    This service is the single source of truth for all external content sources,
    their collections, and path mapping configurations. It provides the
    authoritative interface for source management and path translation.

    **Architectural Role:** Authority + Service/Capability Provider

    **Responsibilities:**
    - Manage external content sources (Plex, filesystem, etc.)
    - Handle source collection configuration
    - Provide path mapping services
    - Discover and configure collections from external sources

    **Critical Rule:** Other code must not guess path mappings itself.
    All path translation and source configuration must go through this
    service to maintain consistency and avoid duplication of mapping logic.
    """

    def __init__(self, db: Session):
        """Initialize the source service with a database session."""
        self.db = db

    def get_source_by_external_id(self, external_id: str) -> Source | None:
        """Get a content source by its external ID."""
        return self.db.query(Source).filter(Source.external_id == external_id).first()

    def get_source_by_name(self, name: str) -> Source | None:
        """Get a content source by its name."""
        return self.db.query(Source).filter(Source.name == name).first()

    def list_sources(self) -> list[ContentSourceDTO]:
        """
        List all content sources.

        Returns:
            List of all content sources as DTOs
        """
        sources = self.db.query(Source).all()
        return [
            ContentSourceDTO(
                id=str(source.id),
                external_id=source.external_id,
                kind=source.type,
                name=source.name,
                status="connected",  # TODO: Implement actual status checking
                base_url=source.config.get("base_url") if source.config else None,
                config=source.config,
            )
            for source in sources
        ]

    def list_sources_with_collection_counts(
        self, source_type: str | None = None
    ) -> list[dict[str, Any]]:
        """
        List all content sources with collection counts for contract compliance.

        Implements consistent read snapshot guarantee (G-7) by using a single transaction
        to ensure all data comes from the same consistent state.

        Args:
            source_type: Optional filter by source type

        Returns:
            List of dictionaries with source data and collection counts
        """
        from ..domain.entities import Collection, Source

        # Use a single transaction to ensure consistent read snapshot
        # First, get all sources in one query
        sources_query = self.db.query(Source)
        if source_type:
            sources_query = sources_query.filter(Source.type == source_type)

        sources = sources_query.all()

        # Then get all collection counts in a single query to maintain consistency
        if sources:
            source_ids = [source.id for source in sources]

            # Get all collection counts for all sources in one query
            collection_counts = (
                self.db.query(Collection.source_id, Collection.sync_enabled, Collection.ingestible)
                .filter(Collection.source_id.in_(source_ids))
                .all()
            )

            # Build counts dictionary for efficient lookup
            counts_by_source = {}
            for count_row in collection_counts:
                source_id = count_row.source_id
                if source_id not in counts_by_source:
                    counts_by_source[source_id] = {"enabled": 0, "ingestible": 0}

                if count_row.sync_enabled:
                    counts_by_source[source_id]["enabled"] += 1
                if count_row.ingestible:
                    counts_by_source[source_id]["ingestible"] += 1
        else:
            counts_by_source = {}

        # Format results
        result = []
        for source in sources:
            source_counts = counts_by_source.get(source.id, {"enabled": 0, "ingestible": 0})

            # Format timestamps as ISO 8601 strings
            if isinstance(source.created_at, str):
                created_at = source.created_at
            else:
                created_at = source.created_at.isoformat() + "Z" if source.created_at else None

            if isinstance(source.updated_at, str):
                updated_at = source.updated_at
            else:
                updated_at = source.updated_at.isoformat() + "Z" if source.updated_at else None

            result.append(
                {
                    "id": str(source.id),
                    "name": source.name,
                    "type": source.type,
                    "enabled_collections": source_counts["enabled"],
                    "ingestible_collections": source_counts["ingestible"],
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )

        return result

    def get_source_by_id(self, source_id: str) -> ContentSourceDTO | None:
        """
        Get a content source by its ID.

        Args:
            source_id: The source ID (can be internal ID, external ID, or name)

        Returns:
            ContentSourceDTO or None if not found
        """
        import uuid

        # Try to find by internal ID first (if it's a valid UUID)
        try:
            if len(source_id) == 36 and source_id.count("-") == 4:  # Basic UUID format check
                source_uuid = uuid.UUID(source_id)
                source = self.db.query(Source).filter(Source.id == source_uuid).first()
                if source:
                    return ContentSourceDTO(
                        id=str(source.id),
                        external_id=source.external_id,
                        kind=source.type,
                        name=source.name,
                        status="connected",
                        base_url=source.config.get("base_url") if source.config else None,
                        config=source.config,
                    )
        except (ValueError, TypeError):
            pass

        # Try to find by external ID
        source = self.get_source_by_external_id(source_id)
        if source:
            return ContentSourceDTO(
                id=str(source.id),
                external_id=source.external_id,
                kind=source.type,
                name=source.name,
                status="connected",
                base_url=source.config.get("base_url") if source.config else None,
                config=source.config,
            )

        # Try to find by name
        source = self.get_source_by_name(source_id)
        if source:
            return ContentSourceDTO(
                id=str(source.id),
                external_id=source.external_id,
                kind=source.type,
                name=source.name,
                status="connected",
                base_url=source.config.get("base_url") if source.config else None,
                config=source.config,
            )

        return None

    def update_source(self, source_id: str, **updates) -> ContentSourceDTO | None:
        """
        Update a content source.

        Args:
            source_id: The source ID to update (can be internal ID, external ID, or name)
            **updates: Fields to update (name, config, etc.)

        Returns:
            Updated ContentSourceDTO or None if not found
        """
        import uuid

        # Try to find by internal ID first (if it's a valid UUID)
        source = None
        try:
            if len(source_id) == 36 and source_id.count("-") == 4:  # Basic UUID format check
                source_uuid = uuid.UUID(source_id)
                source = self.db.query(Source).filter(Source.id == source_uuid).first()
        except (ValueError, TypeError):
            pass

        if not source:
            # Try to find by external ID
            source = self.get_source_by_external_id(source_id)

        if not source:
            # Try to find by name
            source = self.get_source_by_name(source_id)

        if not source:
            return None

        # Update fields
        if "name" in updates:
            source.name = updates["name"]
        if "config" in updates:
            source.config = updates["config"]

        self.db.commit()
        self.db.refresh(source)

        return ContentSourceDTO(
            id=str(source.id),
            external_id=source.external_id,
            kind=source.type,
            name=source.name,
            status="connected",
            base_url=source.config.get("base_url") if source.config else None,
            config=source.config,
        )

    def delete_source(self, source_id: str) -> bool:
        """
        Delete a content source and all related data.

        This will cascade delete:
        - Collections (and their path mappings)
        - PathMappings
        - Any other related data through foreign key constraints

        Args:
            source_id: The source ID to delete (can be internal ID, external ID, or name)

        Returns:
            True if deleted, False if not found
        """
        import uuid

        # Try to find by internal ID first (if it's a valid UUID)
        source = None
        try:
            if len(source_id) == 36 and source_id.count("-") == 4:  # Basic UUID format check
                source_uuid = uuid.UUID(source_id)
                source = self.db.query(Source).filter(Source.id == source_uuid).first()
        except (ValueError, TypeError):
            pass

        if not source:
            # Try to find by external ID
            source = self.get_source_by_external_id(source_id)

        if not source:
            # Try to find by name
            source = self.get_source_by_name(source_id)

        if not source:
            return False

        # Count related data before deletion for logging
        collections_count = (
            self.db.query(Collection).filter(Collection.source_id == source.id).count()
        )
        path_mappings_count = 0
        for collection in self.db.query(Collection).filter(Collection.source_id == source.id).all():
            path_mappings_count += (
                self.db.query(PathMapping)
                .filter(PathMapping.collection_id == collection.id)
                .count()
            )

        # Delete the source (cascade will handle related data)
        self.db.delete(source)
        self.db.commit()

        # Log what was deleted (for debugging/auditing)
        import structlog

        logger = structlog.get_logger(__name__)
        logger.info(
            "source_deleted",
            source_id=str(source.id),
            source_name=source.name,
            source_kind=source.type,
            collections_deleted=collections_count,
            path_mappings_deleted=path_mappings_count,
        )

        return True

    def list_enabled_collections(self, source_id: str) -> list[CollectionDTO]:
        """
        List enabled collections for a specific source.

        Args:
            source_id: Identifier for the content source

        Returns:
            List of enabled collections for the source
        """
        # Query the database for enabled collections
        source = self.db.query(Source).filter(Source.external_id == source_id).first()
        if not source:
            return []

        collections = (
            self.db.query(Collection)
            .filter(Collection.source_id == source.id, Collection.sync_enabled)
            .all()
        )

        result = []
        for collection in collections:
            # Get path mappings for this collection
            mappings = (
                self.db.query(PathMapping).filter(PathMapping.collection_id == collection.id).all()
            )

            mapping_pairs = [(m.plex_path, m.local_path) for m in mappings]

            result.append(
                CollectionDTO(
                    external_id=collection.external_id,
                    name=collection.name,
                    sync_enabled=collection.sync_enabled,
                    mapping_pairs=mapping_pairs,
                    source_type=source.type,
                    config=collection.config,
                )
            )

        return result

    def list_all_collections(self, source_id: str | None = None) -> list[CollectionDTO]:
        """
        List all collections, optionally filtered by source.

        Args:
            source_id: Optional source ID to filter by

        Returns:
            List of all collections
        """
        query = self.db.query(Collection)

        if source_id:
            # Find source by external ID, name, or UUID
            source = self.get_source_by_id(source_id)
            if not source:
                return []
            query = query.filter(Collection.source_id == source.id)

        collections = query.all()

        result = []
        for collection in collections:
            # Get path mappings
            mappings = (
                self.db.query(PathMapping).filter(PathMapping.collection_id == collection.id).all()
            )

            mapping_pairs = [(m.plex_path, m.local_path) for m in mappings]

            result.append(
                CollectionDTO(
                    external_id=collection.external_id,
                    name=collection.name,
                    sync_enabled=collection.sync_enabled,
                    mapping_pairs=mapping_pairs,
                    source_type=collection.source.type,
                    config=collection.config or {},
                )
            )

        return result

    def update_collection_sync_enabled(
        self, source_type: str, external_id: str, sync_enabled: bool
    ) -> bool:
        """
        Update the enabled status of a collection.

        Args:
            source_type: The source type (e.g., 'plex')
            external_id: The collection external ID
            sync_enabled: Whether to enable or disable the collection

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the collection by external_id across all sources of this type
            collection = (
                self.db.query(Collection)
                .join(Source)
                .filter(Source.type == source_type, Collection.external_id == external_id)
                .first()
            )

            if not collection:
                return False

            collection.sync_enabled = sync_enabled
            self.db.commit()
            return True

        except Exception as e:
            self.db.rollback()
            print(f"Error updating collection enabled status: {e}")
            return False

    def get_collection(self, source_id: str, external_id: str) -> CollectionDTO | None:
        """
        Get a specific collection by source and external ID.

        Args:
            source_id: Identifier for the content source
            external_id: External identifier for the collection

        Returns:
            Collection DTO or None if not found
        """
        collections = self.list_enabled_collections(source_id)
        for collection in collections:
            if collection.external_id == external_id:
                return collection
        return None

    def update_source_enrichers(self, source_id: str, enrichers: list[str]) -> bool:
        """
        Update the enrichers for a source.

        Args:
            source_id: The source ID (UUID, external ID, or name)
            enrichers: List of enricher names to use

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the source
            source = self.get_source_by_id(source_id)
            if not source:
                return False

            # Update the enrichers in the source config
            if not source.config:
                source.config = {}

            source.config["enrichers"] = enrichers

            # Update the source in the database
            db_source = self.db.query(Source).filter(Source.id == source.id).first()
            if db_source:
                db_source.config = source.config
                self.db.commit()
                return True

            return False

        except Exception as e:
            self.db.rollback()
            print(f"Error updating source enrichers: {e}")
            return False

    def update_collection_mapping(
        self, source_id: str, external_id: str, mapping_pairs: list[tuple[str, str]]
    ) -> bool:
        """
        Update path mapping pairs for a collection.

        Args:
            source_id: Identifier for the content source
            external_id: External identifier for the collection
            mapping_pairs: New mapping pairs

        Returns:
            True if updated successfully, False otherwise
        """
        try:
            # Find the source and collection
            source = self.db.query(Source).filter(Source.external_id == source_id).first()
            if not source:
                return False

            collection = (
                self.db.query(Collection)
                .filter(Collection.source_id == source.id, Collection.external_id == external_id)
                .first()
            )
            if not collection:
                return False

            # Delete existing mappings
            self.db.query(PathMapping).filter(PathMapping.collection_id == collection.id).delete()

            # Add new mappings
            for plex_path, local_path in mapping_pairs:
                mapping = PathMapping(
                    collection_id=collection.id, plex_path=plex_path, local_path=local_path
                )
                self.db.add(mapping)

            self.db.flush()
            return True
        except Exception:
            self.db.rollback()
            return False

    def create_plex_source(self, name: str, base_url: str, token: str) -> ContentSourceDTO:
        """
        Create a new Plex source.

        Args:
            name: Friendly name for the source
            base_url: Plex server base URL
            token: Plex authentication token

        Returns:
            ContentSourceDTO for the created source
        """
        import uuid

        # Create external ID
        external_id = f"plex-{uuid.uuid4().hex[:8]}"

        # Create the source entity
        source = Source(
            external_id=external_id,
            type="plex",
            name=name,
            config={"base_url": base_url, "token": token},
        )

        self.db.add(source)
        self.db.flush()
        self.db.refresh(source)

        return ContentSourceDTO(
            id=source.external_id,
            external_id=source.external_id,
            kind=source.type,
            name=source.name,
            status="connected",
            base_url=base_url,
            config=source.config,
        )

    def create_filesystem_source(self, name: str, base_path: str) -> ContentSourceDTO:
        """
        Create a new filesystem source.

        Args:
            name: Friendly name for the source
            base_path: Base filesystem path to scan

        Returns:
            ContentSourceDTO for the created source
        """
        import os
        import uuid

        # Create external ID
        external_id = f"filesystem-{uuid.uuid4().hex[:8]}"

        # Validate the path exists
        if not os.path.exists(base_path):
            raise ValueError(f"Path does not exist: {base_path}")

        if not os.path.isdir(base_path):
            raise ValueError(f"Path is not a directory: {base_path}")

        # Create the source entity
        source = Source(
            external_id=external_id, type="filesystem", name=name, config={"base_path": base_path}
        )

        self.db.add(source)
        self.db.flush()
        self.db.refresh(source)

        return ContentSourceDTO(
            id=source.external_id,
            external_id=source.external_id,
            kind=source.type,
            name=source.name,
            status="connected",
            base_url=base_path,
            config=source.config,
        )

    def discover_collections(self, source_id: str) -> list[CollectionDTO]:
        """
        Discover collections from a source without persisting.

        Args:
            source_id: Identifier for the content source

        Returns:
            List of discovered collections
        """
        try:
            # Get the source from database
            source = self.db.query(Source).filter(Source.external_id == source_id).first()
            if not source:
                return []

            # Import Plex importer
            from ..adapters.importers.plex_importer import PlexImporter

            # Create importer with source config
            # Handle both old and new config formats
            if "servers" in source.config:
                # New format with servers array
                servers = source.config["servers"]
            else:
                # Old format with direct base_url and token
                servers = [
                    {"base_url": source.config.get("base_url"), "token": source.config.get("token")}
                ]

            # Extract base_url and token from first server
            if servers and len(servers) > 0:
                server = servers[0]
                importer = PlexImporter(base_url=server["base_url"], token=server["token"])
            else:
                raise ValueError("No servers configured for Plex source")

            # Discover libraries
            libraries = importer.discover()

            # Convert to DTOs
            collections = []
            for lib in libraries:
                collections.append(
                    CollectionDTO(
                        external_id=lib.get("key", ""),
                        name=lib.get("title", ""),
                        sync_enabled=False,  # Newly discovered collections start disabled
                        mapping_pairs=[],  # No mappings by default
                        source_type=source.type,
                        config={
                            "plex_path": f"/plex/{lib.get('title', '').lower().replace(' ', '_')}",
                            "type": lib.get("type", "movie"),
                        },
                    )
                )
            return collections

        except Exception as e:
            print(f"Error in discover_collections: {e}")
            return []

    def persist_collections(self, source_id: str, collections: list[CollectionDTO]) -> bool:
        """
        Persist discovered collections to the database.

        Args:
            source_id: The source external ID
            collections: List of collections to persist

        Returns:
            True if successful, False otherwise
        """
        try:
            # Get the source
            source = self.db.query(Source).filter(Source.external_id == source_id).first()
            if not source:
                return False

            # NOTE: this entire block runs under a single unit-of-work / transaction. If any insert fails, we roll back the whole sync.

            # Persist each collection
            for collection_dto in collections:
                # Check if collection already exists
                existing = (
                    self.db.query(Collection)
                    .filter(
                        Collection.source_id == source.id,
                        Collection.external_id == collection_dto.external_id,
                    )
                    .first()
                )

                if existing:
                    # Update existing collection
                    existing.name = collection_dto.name
                    existing.config = collection_dto.config
                    collection = existing
                else:
                    # Create new collection
                    collection = Collection(
                        source_id=source.id,
                        external_id=collection_dto.external_id,
                        name=collection_dto.name,
                        sync_enabled=collection_dto.sync_enabled,
                        config=collection_dto.config,
                    )
                    self.db.add(collection)
                    self.db.flush()  # Get the ID for PathMapping creation

                # Create PathMapping rows for each filesystem location
                # Get the locations from the original collection data
                locations = getattr(collection_dto, "locations", [])
                if not locations:
                    # Try to get from the original collections data if available
                    # This is a fallback for when locations aren't passed in the DTO
                    locations = []

                # For each location, create or update PathMapping
                for plex_path in locations:
                    # Check if PathMapping already exists
                    existing_mapping = (
                        self.db.query(PathMapping)
                        .filter(
                            PathMapping.collection_id == collection.id,
                            PathMapping.plex_path == plex_path,
                        )
                        .first()
                    )

                    if not existing_mapping:
                        # Create new PathMapping with empty local_path
                        new_mapping = PathMapping(
                            collection_id=collection.id,
                            plex_path=plex_path,
                            local_path="",  # Initially empty until operator maps it
                        )
                        self.db.add(new_mapping)

            self.db.commit()
            return True

        except Exception as e:
            self.db.rollback()
            print(f"Error persisting collections: {e}")
            return False

    def delete_collection(self, collection_id: str) -> bool:
        """
        Delete a collection and all its associated data.

        Args:
            collection_id: Collection ID, external ID, or UUID to delete

        Returns:
            True if successful, False otherwise
        """
        try:
            # Find the collection by ID (try UUID first, then external_id)
            import uuid

            collection = None

            # Try to find by UUID first
            try:
                if len(collection_id) == 36 and collection_id.count("-") == 4:
                    collection_uuid = uuid.UUID(collection_id)
                    collection = (
                        self.db.query(Collection).filter(Collection.id == collection_uuid).first()
                    )
            except (ValueError, TypeError):
                pass

            # If not found by UUID, try by external_id
            if not collection:
                collection = (
                    self.db.query(Collection)
                    .filter(Collection.external_id == collection_id)
                    .first()
                )

            # If not found by external_id, try by name (case-insensitive)
            if not collection:
                name_matches = (
                    self.db.query(Collection).filter(Collection.name.ilike(collection_id)).all()
                )
                if len(name_matches) == 1:
                    collection = name_matches[0]
                elif len(name_matches) > 1:
                    # Multiple matches - cannot delete
                    return False

            if not collection:
                return False

            # Delete the collection (cascade will handle PathMapping deletion)
            self.db.delete(collection)
            self.db.commit()
            return True

        except Exception as e:
            self.db.rollback()
            print(f"Error deleting collection: {e}")
            return False

    def save_collections(self, source_id: str, updates: list[CollectionUpdateDTO]) -> bool:
        """
        Save collection updates (enabled status and mapping pairs).

        Args:
            source_id: Identifier for the content source
            updates: List of collection updates

        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Find the source
            source = self.db.query(Source).filter(Source.external_id == source_id).first()
            if not source:
                return False

            for update in updates:
                # Find or create the collection
                collection = (
                    self.db.query(Collection)
                    .filter(
                        Collection.source_id == source.id,
                        Collection.external_id == update.external_id,
                    )
                    .first()
                )

                if not collection:
                    # Create new collection
                    collection = Collection(
                        source_id=source.id,
                        external_id=update.external_id,
                        name=update.external_id,  # Use external_id as name if not provided
                        sync_enabled=update.sync_enabled,
                    )
                    self.db.add(collection)
                    self.db.flush()
                    self.db.refresh(collection)
                else:
                    # Update existing collection
                    collection.sync_enabled = update.sync_enabled

                # Update path mappings
                # Delete existing mappings
                self.db.query(PathMapping).filter(
                    PathMapping.collection_id == collection.id
                ).delete()

                # Add new mappings
                for plex_path, local_path in update.mapping_pairs:
                    mapping = PathMapping(
                        collection_id=collection.id, plex_path=plex_path, local_path=local_path
                    )
                    self.db.add(mapping)

            self.db.flush()
            return True

        except Exception:
            self.db.rollback()
            return False
