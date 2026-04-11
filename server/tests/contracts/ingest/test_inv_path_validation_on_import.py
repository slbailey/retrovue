"""
INV-PATH-VALIDATION-ON-IMPORT-001 — Path validation at container import time.

Contract requirements:
- Path mappings are NOT validated at source registration time.
- At container import, at least one sampled asset path must resolve correctly.
- If all sampled paths fail, import MUST fail with a diagnostic.
- Partial resolution (some pass, some fail) emits a warning but proceeds.

Tests are deterministic (no wall-clock sleep, no real DB, no network).
"""

import pytest
from types import SimpleNamespace


def _make_mapping(source_path, retrovue_path):
    return SimpleNamespace(source_path=source_path, retrovue_path=retrovue_path)


class TestInvPathValidationOnImport001:
    """Contract tests for INV-PATH-VALIDATION-ON-IMPORT-001."""

    def test_no_path_mappings_import_fails_with_diagnostic(self):
        """Source with no path mappings — container import fails with diagnostic."""
        from retrovue.workflows.path_validation import validate_paths_at_import

        sample_paths = ["/media/movies/film.mkv", "/media/movies/film2.mkv"]

        result = validate_paths_at_import(
            effective_mappings=[],
            sample_paths=sample_paths,
            path_exists_fn=lambda _p: False,
        )

        assert result.status == "failed"
        assert "INV-PATH-VALIDATION-ON-IMPORT-001" in result.diagnostic

    def test_valid_mapping_import_succeeds(self):
        """Source with a valid mapping covering assets — import succeeds."""
        from retrovue.workflows.path_validation import validate_paths_at_import

        sample_paths = ["/media/movies/film.mkv"]

        def path_exists(p):
            return p == "/mnt/nfs/movies/film.mkv"

        result = validate_paths_at_import(
            effective_mappings=[("/media/movies", "/mnt/nfs/movies")],
            sample_paths=sample_paths,
            path_exists_fn=path_exists,
        )

        assert result.status == "passed"
        assert result.diagnostic is None

    def test_mapping_not_covering_paths_import_fails(self):
        """Source with a mapping that doesn't cover asset paths — import fails."""
        from retrovue.workflows.path_validation import validate_paths_at_import

        sample_paths = ["/media/tv/show.mkv"]

        result = validate_paths_at_import(
            effective_mappings=[("/media/movies", "/mnt/nfs/movies")],
            sample_paths=sample_paths,
            path_exists_fn=lambda _p: False,
        )

        assert result.status == "failed"
        assert result.diagnostic is not None

    def test_partial_resolution_proceeds_with_warning(self):
        """Partial resolution — some pass, some fail — proceeds with warning."""
        from retrovue.workflows.path_validation import validate_paths_at_import

        sample_paths = ["/media/movies/good.mkv", "/media/movies/missing.mkv"]

        def path_exists(p):
            return p == "/mnt/nfs/movies/good.mkv"

        result = validate_paths_at_import(
            effective_mappings=[("/media/movies", "/mnt/nfs/movies")],
            sample_paths=sample_paths,
            path_exists_fn=path_exists,
        )

        assert result.status == "passed"
        assert len(result.warnings) > 0
        assert any("/media/movies/missing.mkv" in w for w in result.warnings)

    def test_source_add_does_not_validate_paths(self):
        """retrovue source add with invalid path mappings does NOT fail at registration time."""
        from retrovue.workflows.path_mapping import validate_mapping_fields

        # validate_mapping_fields checks field names only, not path accessibility
        # This must NOT raise for valid field names even with non-existent paths
        validate_mapping_fields({
            "source_path": "/nonexistent/source/path",
            "retrovue_path": "/nonexistent/retrovue/path",
        })
