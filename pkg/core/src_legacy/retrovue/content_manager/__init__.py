"""
Content Manager package - unified interface for content management operations.

This package provides the public API for content management services including
library operations, source management, and content ingestion.
"""

from .ingest_orchestrator import IngestOrchestrator, IngestReport
from .library_service import LibraryService
from .path_service import PathResolutionError, PathResolverService
from .source_service import (
    CollectionUpdateDTO,
    ContentSourceDTO,
    SourceCollectionDTO,
    SourceService,
)

__all__ = [
    # Services
    "LibraryService",
    "SourceService",
    "IngestOrchestrator",
    "PathResolverService",
    # DTOs
    "SourceCollectionDTO",
    "ContentSourceDTO",
    "CollectionUpdateDTO",
    "IngestReport",
    # Exceptions
    "PathResolutionError",
]
