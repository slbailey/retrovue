"""
REST API modules for Retrovue web server.
"""

from .assets import router as assets_router
from .catalog import router as catalog_router
from .console import router as console_router  # deprecated — kept for backward compat
from .ingest import router as ingest_router
from .scheduling import router as scheduling_router

__all__ = ["assets_router", "catalog_router", "console_router", "ingest_router", "scheduling_router"]
