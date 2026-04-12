"""
Source type registry — single dispatch point for source type → importer class.

Invariant: INV-SOURCE-TYPE-REGISTRY-001
All source type dispatch MUST route through SOURCE_TYPE_REGISTRY.
Unknown types are rejected with the invariant violation tag.
"""

from __future__ import annotations

from ..adapters.importers.filesystem_importer import FilesystemImporter
from ..adapters.importers.plex_importer import PlexImporter

# Canonical registry: type identifier → importer class.
# This is the ONLY place source-type-to-importer mapping is defined.
SOURCE_TYPE_REGISTRY: dict[str, type] = {
    "plex": PlexImporter,
    "filesystem": FilesystemImporter,
}


def resolve_importer_class(source_type: str) -> type:
    """Resolve a source type string to its importer class.

    Args:
        source_type: The source type identifier (e.g. "plex", "filesystem").

    Returns:
        The importer class for the given source type.

    Raises:
        ValueError: If source_type is not in the registry, tagged with
            INV-SOURCE-TYPE-REGISTRY-001-VIOLATED.
    """
    cls = SOURCE_TYPE_REGISTRY.get(source_type)
    if cls is None:
        available = ", ".join(sorted(SOURCE_TYPE_REGISTRY.keys()))
        raise ValueError(
            f"INV-SOURCE-TYPE-REGISTRY-001-VIOLATED: unknown source type "
            f"'{source_type}'. Registered types: {available}"
        )
    return cls
