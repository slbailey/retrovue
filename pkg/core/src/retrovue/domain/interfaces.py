"""Domain interfaces for content importers."""

from abc import ABC, abstractmethod
from typing import Any

from .entities import Collection


class ImporterInterface(ABC):
    """Interface for content importers (Plex, filesystem, etc.)."""

    @abstractmethod
    def validate_ingestible(self, collection: Collection) -> bool:
        """
        Validate whether a collection meets the prerequisites for ingestion.

        This method checks if the collection can be ingested based on importer-specific
        requirements (e.g., valid path mappings for Plex, accessible directories for filesystem).

        Args:
            collection: The Collection to validate

        Returns:
            bool: True if collection can be ingested, False otherwise
        """
        raise NotImplementedError

    @abstractmethod
    def discover_collections(self, source_id: str) -> list[dict[str, Any]]:
        """
        Discover collections from the external source.

        Args:
            source_id: The external source identifier

        Returns:
            List of collection metadata dictionaries
        """
        raise NotImplementedError

    @abstractmethod
    def ingest_collection(self, collection: Collection, scope: str | None = None) -> dict[str, Any]:
        """
        Ingest content from a collection.

        Args:
            collection: The Collection to ingest from
            scope: Optional scope for targeted ingest (title, season, episode)

        Returns:
            Dictionary with ingest results and statistics
        """
        raise NotImplementedError
