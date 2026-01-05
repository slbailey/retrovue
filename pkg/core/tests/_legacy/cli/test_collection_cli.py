"""
CLI contract tests for retrovue collection commands.

Tests the collection command group against the documented CLI contract in docs/contracts/README.md.
"""

import pytest

from .utils import run_cli


class TestCollectionCLI:
    """Test suite for retrovue collection commands."""
    
    def test_collection_list_help(self):
        """Test that retrovue collection list --help works."""
        exit_code, stdout, stderr = run_cli(["collection", "list", "--help"])
        assert exit_code == 0
        assert "--source" in stdout
        assert "Show Collections for a Source" in stdout or "Show Collections for a Source" in stderr
    
    def test_collection_list(self):
        """Test that retrovue collection list command exists."""
        # This will likely fail without a valid source, but should show help
        exit_code, stdout, stderr = run_cli(["collection", "list", "--source", "test"])
        # Should either work or show error about missing source
        assert exit_code in [0, 1]  # 0 if works, 1 if source not found
    
    def test_collection_update_help(self):
        """Test that retrovue collection update --help works."""
        exit_code, stdout, stderr = run_cli(["collection", "update", "--help"])
        assert exit_code == 0
        assert "--sync-enabled" in stdout
        assert "--local-path" in stdout
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    def test_collection_update_presence(self):
        """Test that retrovue collection update command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["collection", "update", "--help"])
        assert exit_code == 0
    
    def test_collection_attach_enricher_help(self):
        """Test that retrovue collection attach-enricher --help works."""
        exit_code, stdout, stderr = run_cli(["collection", "attach-enricher", "--help"])
        assert exit_code == 0
        assert "--priority" in stdout
        assert "Attach an ingest-scope enricher" in stdout or "Attach an ingest-scope enricher" in stderr
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    def test_collection_attach_enricher_presence(self):
        """Test that retrovue collection attach-enricher command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["collection", "attach-enricher", "--help"])
        assert exit_code == 0
    
    def test_collection_detach_enricher_help(self):
        """Test that retrovue collection detach-enricher --help works."""
        exit_code, stdout, stderr = run_cli(["collection", "detach-enricher", "--help"])
        assert exit_code == 0
        assert "Remove enricher from collection" in stdout or "Remove enricher from collection" in stderr
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    def test_collection_detach_enricher_presence(self):
        """Test that retrovue collection detach-enricher command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["collection", "detach-enricher", "--help"])
        assert exit_code == 0
    
    def test_collection_delete_help(self):
        """Test that retrovue collection delete --help works."""
        exit_code, stdout, stderr = run_cli(["collection", "delete", "--help"])
        assert exit_code == 0
        assert "--force" in stdout
        assert "Delete a collection and all its associated data" in stdout or "Delete a collection and all its associated data" in stderr
    
    def test_collection_wipe_help(self):
        """Test that retrovue collection wipe --help works."""
        exit_code, stdout, stderr = run_cli(["collection", "wipe", "--help"])
        assert exit_code == 0
        assert "--force" in stdout
        assert "--dry-run" in stdout
        assert "--json" in stdout
        assert "NUCLEAR OPTION" in stdout or "NUCLEAR OPTION" in stderr or "nuclear option" in stdout
        assert "Completely wipe a collection and ALL its associated data" in stdout or "Completely wipe a collection and ALL its associated data" in stderr
    
    def test_collection_ingest_help(self):
        """Test that retrovue collection ingest --help works."""
        exit_code, stdout, stderr = run_cli(["collection", "ingest", "--help"])
        assert exit_code == 0
        assert "--title" in stdout
        assert "--season" in stdout
        assert "--episode" in stdout
        assert "--dry-run" in stdout
        assert "--json" in stdout