"""
Enricher domain package — execution mode contracts and base class.

This package defines the domain-level enricher contract per
INV-ENRICHER-EXECUTION-MODE-001 and INV-ENRICHER-IDEMPOTENT-001.

Adapter-level enricher implementations (ffprobe, loudness, etc.) live in
``retrovue.adapters.enrichers``. This package provides the domain contract
that those adapters must satisfy.
"""

from .base import DomainEnricher, ExecutionMode

__all__ = [
    "DomainEnricher",
    "ExecutionMode",
]
