"""
Path Resolution Service - centralized path mapping and resolution.

This module provides the single source of truth for translating external source
file paths into local playable file paths using configured PathMapping records.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class PathResolutionError(Exception):
    """Raised when a path cannot be resolved using available mappings."""

    def __init__(self, provider_path: str, available_mappings: list[tuple[str, str]] | None = None):
        self.provider_path = provider_path
        self.available_mappings = available_mappings or []
        super().__init__(f"Cannot resolve provider path: {provider_path}")


class PathResolverService:
    """
    Service / Capability Provider

    Responsible for translating external source file paths into local playable
    file paths using configured PathMapping records.

    This logic must not be reimplemented elsewhere in ad hoc string manipulation.
    All path translation must go through this service to ensure consistency
    and prevent duplication of mapping logic.

    **Architectural Role:** Service / Capability Provider

    **Responsibilities:**
    - Translate provider paths (e.g., Plex paths) to local filesystem paths
    - Validate that resolved paths exist on the local filesystem
    - Provide clear error messages when path resolution fails
    - Maintain consistency across all path mapping operations

    **Critical Rule:** Other code must not implement path mapping logic.
    All path translation must use this service.
    """

    def __init__(self, mapping_pairs: list[tuple[str, str]] | None = None):
        """
        Initialize the path resolver with mapping pairs.

        Args:
            mapping_pairs: List of (provider_path_prefix, local_path_prefix) tuples.
                          Mappings are sorted by prefix length (longest first) for proper matching.
        """
        self.mapping_pairs = mapping_pairs or []
        # Sort mappings by prefix length (longest first) for proper matching
        self.mapping_pairs.sort(key=lambda x: len(x[0]), reverse=True)

    def resolve_path(self, provider_path: str, validate_exists: bool = True) -> str:
        """
        Resolve a provider path to a local filesystem path.

        Args:
            provider_path: The provider file path to resolve (e.g., Plex path)
            validate_exists: If True, validate that the resolved path exists on disk

        Returns:
            The resolved local filesystem path

        Raises:
            PathResolutionError: If the path cannot be resolved or doesn't exist
        """
        if not self.mapping_pairs:
            raise PathResolutionError(provider_path, available_mappings=self.mapping_pairs)

        # Find the first matching mapping
        for provider_prefix, local_prefix in self.mapping_pairs:
            if provider_path.startswith(provider_prefix):
                # Replace the provider prefix with the local prefix
                local_path = provider_path.replace(provider_prefix, local_prefix, 1)

                # Validate that the resolved path exists if requested
                if validate_exists and not Path(local_path).exists():
                    raise PathResolutionError(provider_path, available_mappings=self.mapping_pairs)

                logger.debug(
                    "path_resolved",
                    provider_path=provider_path,
                    local_path=local_path,
                    mapping_used=(provider_prefix, local_prefix),
                )

                return local_path

        # No mapping found
        raise PathResolutionError(provider_path, available_mappings=self.mapping_pairs)

    def add_mapping(self, provider_prefix: str, local_prefix: str) -> None:
        """
        Add a new path mapping.

        Args:
            provider_prefix: The provider path prefix
            local_prefix: The local path prefix
        """
        self.mapping_pairs.append((provider_prefix, local_prefix))
        # Re-sort to maintain longest-first order
        self.mapping_pairs.sort(key=lambda x: len(x[0]), reverse=True)

        logger.debug("mapping_added", provider_prefix=provider_prefix, local_prefix=local_prefix)

    def remove_mapping(self, provider_prefix: str) -> bool:
        """
        Remove a path mapping.

        Args:
            provider_prefix: The provider prefix to remove

        Returns:
            True if mapping was removed, False if not found
        """
        for i, (src, _) in enumerate(self.mapping_pairs):
            if src == provider_prefix:
                del self.mapping_pairs[i]
                logger.debug("mapping_removed", provider_prefix=provider_prefix)
                return True
        return False

    def get_mappings(self) -> list[tuple[str, str]]:
        """
        Get all current path mappings.

        Returns:
            List of (provider_prefix, local_prefix) tuples
        """
        return self.mapping_pairs.copy()

    def clear_mappings(self) -> None:
        """Clear all path mappings."""
        self.mapping_pairs.clear()
        logger.debug("mappings_cleared")

    def __str__(self) -> str:
        """String representation of the service."""
        return f"PathResolverService(mappings={len(self.mapping_pairs)})"

    def __repr__(self) -> str:
        """Detailed string representation of the service."""
        return f"PathResolverService(mapping_pairs={self.mapping_pairs})"
