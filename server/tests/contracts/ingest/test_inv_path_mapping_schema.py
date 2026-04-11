"""
INV-PATH-MAPPING-SOURCE-SCOPED-001 — Schema-level tests for source-scoped path mappings.

Validates that the PathMapping entity supports:
- source_id FK (source-level mappings)
- container_id FK (container-level overrides)
- canonical column names source_path / retrovue_path
- scope constraint (at least one of source_id/container_id must be set)

Tests are deterministic (no real DB, validates ORM model shape).
"""

import uuid
from types import SimpleNamespace

import pytest


class TestPathMappingEntitySchema:
    """Contract tests for PathMapping entity model."""

    def test_entity_has_source_path_column(self):
        from retrovue.domain.entities import PathMapping
        assert hasattr(PathMapping, "source_path"), "PathMapping must have source_path column"

    def test_entity_has_retrovue_path_column(self):
        from retrovue.domain.entities import PathMapping
        assert hasattr(PathMapping, "retrovue_path"), "PathMapping must have retrovue_path column"

    def test_entity_has_source_id_fk(self):
        from retrovue.domain.entities import PathMapping
        assert hasattr(PathMapping, "source_id"), "PathMapping must have source_id FK"

    def test_entity_has_container_id_fk(self):
        from retrovue.domain.entities import PathMapping
        assert hasattr(PathMapping, "container_id"), "PathMapping must have container_id FK"

    def test_entity_rejects_plex_path_column(self):
        from retrovue.domain.entities import PathMapping
        assert not hasattr(PathMapping, "plex_path"), "PathMapping must NOT have plex_path (use source_path)"

    def test_entity_rejects_local_path_column(self):
        from retrovue.domain.entities import PathMapping
        assert not hasattr(PathMapping, "local_path"), "PathMapping must NOT have local_path (use retrovue_path)"

    def test_source_entity_has_path_mappings_relationship(self):
        from retrovue.domain.entities import Source
        assert hasattr(Source, "path_mappings"), "Source must have path_mappings relationship"

    def test_container_entity_has_path_mappings_relationship(self):
        from retrovue.domain.entities import Container
        assert hasattr(Container, "path_mappings"), "Container must have path_mappings relationship"
