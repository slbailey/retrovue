"""
Adapters module for Retrovue.

This module contains adapters for external systems and services,
including importers, enrichers, and their registry.
"""

from .registry import (
    clear_registries,
    get_enricher,
    get_importer,
    get_registry_stats,
    list_enrichers,
    list_importers,
    register_enricher,
    register_importer,
    unregister_enricher,
    unregister_importer,
)

__all__ = [
    "register_importer",
    "get_importer",
    "list_importers",
    "unregister_importer",
    "register_enricher",
    "get_enricher",
    "list_enrichers",
    "unregister_enricher",
    "clear_registries",
    "get_registry_stats",
]
