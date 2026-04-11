"""
REST API modules for Retrovue web server.
"""

from .catalog import router as catalog_router
from .console import router as console_router
from .ingest import router as ingest_router
from .scheduling import router as scheduling_router

__all__ = ["catalog_router", "console_router", "ingest_router", "scheduling_router"]
