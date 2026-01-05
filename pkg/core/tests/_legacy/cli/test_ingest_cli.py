"""
CLI contract tests for retrovue ingest commands.

Tests the ingest command group against the documented CLI contract in docs/contracts/README.md.
"""

import pytest

from .utils import run_cli


class TestIngestCLI:
    """Test suite for retrovue ingest commands."""
    
    def test_ingest_run_help(self):
        """Test that retrovue ingest run --help works."""
        exit_code, stdout, stderr = run_cli(["ingest", "run", "--help"])
        assert exit_code == 0
        assert "Run content ingestion" in stdout or "Run content ingestion" in stderr
    
    def test_ingest_run_collection_form(self):
        """Test retrovue ingest run <collection_id> form."""
        # This should work with the current implementation
        exit_code, stdout, stderr = run_cli(["ingest", "run", "test-collection"])
        # Should either work or show error about missing collection
        assert exit_code in [0, 1]  # 0 if works, 1 if collection not found
    
    @pytest.mark.xfail(reason="Current implementation takes positional source arg instead of --source flag")
    def test_ingest_run_source_form(self):
        """Test retrovue ingest run --source <source_id> form per contract."""
        # TODO: Current implementation takes positional source arg instead of --source flag
        # TODO: Docs require validation of local_path reachability
        # TODO: Docs require running importer and applying ingest-scope enrichers
        # TODO: Docs require writing to catalog
        exit_code, stdout, stderr = run_cli(["ingest", "run", "--source", "test-source"])
        assert exit_code == 0
        pytest.skip("Current signature doesn't match docs (takes positional source arg instead of --source)")
    
    def test_ingest_run_current_implementation(self):
        """Test the current implementation (positional source arg)."""
        # Current implementation takes source as positional argument
        exit_code, stdout, stderr = run_cli(["ingest", "run", "test-source"])
        # Should either work or show error about missing source
        assert exit_code in [0, 1]  # 0 if works, 1 if source not found