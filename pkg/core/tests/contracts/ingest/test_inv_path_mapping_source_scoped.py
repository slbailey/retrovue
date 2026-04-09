"""
INV-PATH-MAPPING-SOURCE-SCOPED-001 — Path mappings are source-scoped with container inheritance.

Contract requirements:
- Sources declare path mappings with canonical fields source_path / retrovue_path.
- Containers inherit source-level mappings automatically.
- Per-container overrides are optional; source-level inheritance is the default.
- Provider-specific field names (plex_path, local_path) are rejected at schema level.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

import pytest
from types import SimpleNamespace


def _make_source(*, path_mappings=None):
    return SimpleNamespace(
        id="source-001",
        name="test-source",
        type="filesystem",
        path_mappings=path_mappings or [],
    )


def _make_container(*, source=None, path_mappings=None):
    return SimpleNamespace(
        uuid="container-001",
        name="test-container",
        source=source,
        path_mappings=path_mappings or [],
    )


def _make_mapping(source_path, retrovue_path):
    return SimpleNamespace(source_path=source_path, retrovue_path=retrovue_path)


class TestInvPathMappingSourceScoped001:
    """Contract tests for INV-PATH-MAPPING-SOURCE-SCOPED-001."""

    def test_container_inherits_source_mapping(self):
        """Source with mapping — container under that source inherits the mapping."""
        from retrovue.workflows.path_mapping import resolve_effective_mappings

        source_mappings = [_make_mapping("/media/movies", "/mnt/nfs/movies")]
        source = _make_source(path_mappings=source_mappings)
        container = _make_container(source=source)

        effective = resolve_effective_mappings(source=source, container=container)
        assert len(effective) == 1
        assert effective[0] == ("/media/movies", "/mnt/nfs/movies")

    def test_container_no_overrides_uses_source_mapping(self):
        """Container with no container-level overrides inherits source-level mapping."""
        from retrovue.workflows.path_mapping import resolve_effective_mappings

        source_mappings = [
            _make_mapping("/media/movies", "/mnt/nfs/movies"),
            _make_mapping("/media/tv", "/mnt/nfs/tv"),
        ]
        source = _make_source(path_mappings=source_mappings)
        container = _make_container(source=source)

        effective = resolve_effective_mappings(source=source, container=container)
        assert len(effective) == 2
        prefixes = {m[0] for m in effective}
        assert prefixes == {"/media/movies", "/media/tv"}

    def test_container_override_takes_precedence_for_its_prefix(self):
        """Container-level override for a prefix takes precedence; source mapping for other prefixes still applies."""
        from retrovue.workflows.path_mapping import resolve_effective_mappings

        source_mappings = [
            _make_mapping("/media/movies", "/mnt/nfs/movies"),
            _make_mapping("/media/tv", "/mnt/nfs/tv"),
        ]
        container_mappings = [
            _make_mapping("/media/movies", "/mnt/local/movies"),  # override
        ]
        source = _make_source(path_mappings=source_mappings)
        container = _make_container(source=source, path_mappings=container_mappings)

        effective = resolve_effective_mappings(source=source, container=container)
        mapping_dict = {m[0]: m[1] for m in effective}

        # Container override wins for /media/movies
        assert mapping_dict["/media/movies"] == "/mnt/local/movies"
        # Source mapping preserved for /media/tv
        assert mapping_dict["/media/tv"] == "/mnt/nfs/tv"

    def test_provider_specific_field_names_rejected(self):
        """Provider-specific field names (plex_path, local_path) are rejected."""
        from retrovue.workflows.path_mapping import validate_mapping_fields

        with pytest.raises(ValueError, match="INV-PATH-MAPPING-SOURCE-SCOPED-001-VIOLATED"):
            validate_mapping_fields({"plex_path": "/foo", "local_path": "/bar"})

        with pytest.raises(ValueError, match="INV-PATH-MAPPING-SOURCE-SCOPED-001-VIOLATED"):
            validate_mapping_fields({"local_path": "/bar", "source_path": "/foo"})

    def test_canonical_field_names_accepted(self):
        """Canonical field names (source_path, retrovue_path) are accepted."""
        from retrovue.workflows.path_mapping import validate_mapping_fields

        # Should not raise
        validate_mapping_fields({"source_path": "/media/movies", "retrovue_path": "/mnt/nfs/movies"})
