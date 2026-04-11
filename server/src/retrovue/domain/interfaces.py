"""Domain interfaces for content importers."""

from abc import ABC, abstractmethod
from typing import Any

from .entities import Container


class ImporterInterface(ABC):
    """Interface for content importers (Plex, filesystem, etc.)."""

    @abstractmethod
    def validate_ingestible(self, container: Container) -> bool:
        """
        Validate whether a container meets the prerequisites for ingestion.

        This method checks if the container can be ingested based on importer-specific
        requirements (e.g., valid path mappings for Plex, accessible directories for filesystem).

        Args:
            container: The Container to validate

        Returns:
            bool: True if container can be ingested, False otherwise
        """
        raise NotImplementedError

    @abstractmethod
    def discover_collections(self, source_id: str) -> list[dict[str, Any]]:
        """
        Discover containers from the external source. (Method name kept for compatibility.)

        Args:
            source_id: The external source identifier

        Returns:
            List of container metadata dictionaries
        """
        raise NotImplementedError

    @abstractmethod
    def ingest_collection(self, container: Container, scope: str | None = None) -> dict[str, Any]:
        """
        Ingest content from a container. (Method name kept for compatibility.)

        Args:
            container: The Container to ingest from
            scope: Optional scope for targeted ingest (title, season, episode)

        Returns:
            Dictionary with ingest results and statistics
        """
        raise NotImplementedError
