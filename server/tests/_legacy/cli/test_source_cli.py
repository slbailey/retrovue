"""
CLI contract tests for retrovue source commands.

Tests the source command group against the documented CLI contract in docs/contracts/README.md.
"""

import pytest

from .utils import run_cli


class TestSourceCLI:
    """Test suite for retrovue source commands."""
    
    def test_source_list_types_help(self):
        """Test that retrovue source list-types --help works."""
        exit_code, stdout, stderr = run_cli(["source", "list-types", "--help"])
        assert exit_code == 0
        assert "List all available source types" in stdout or "List all available source types" in stderr
    
    def test_source_list_types(self):
        """Test that retrovue source list-types command exists and works."""
        exit_code, stdout, stderr = run_cli(["source", "list-types"])
        assert exit_code == 0
        # Should show available source types
        assert "plex" in stdout or "filesystem" in stdout
    
    def test_source_add_help(self):
        """Test that retrovue source add --help works."""
        exit_code, stdout, stderr = run_cli(["source", "add", "--help"])
        assert exit_code == 0
        assert "--type" in stdout
        assert "--name" in stdout
    
    def test_source_add_type_help(self):
        """Test that retrovue source add --type <type> --help works."""
        exit_code, stdout, stderr = run_cli(["source", "add", "--type", "plex", "--help"])
        assert exit_code == 0
        # Should show plex-specific parameters
        assert "plex" in stdout.lower() or "base_url" in stdout or "token" in stdout
    
    def test_source_list_help(self):
        """Test that retrovue source list --help works."""
        exit_code, stdout, stderr = run_cli(["source", "list", "--help"])
        assert exit_code == 0
        assert "List all configured sources" in stdout or "List all configured sources" in stderr
    
    def test_source_list(self):
        """Test that retrovue source list command exists and works."""
        exit_code, stdout, stderr = run_cli(["source", "list"])
        assert exit_code == 0
        # Should show sources or empty list
        assert "sources" in stdout.lower() or "found" in stdout.lower()
    
    def test_source_update_help(self):
        """Test that retrovue source update --help works."""
        exit_code, stdout, stderr = run_cli(["source", "update", "--help"])
        assert exit_code == 0
        assert "Update a source configuration" in stdout or "Update a source configuration" in stderr
    
    def test_source_remove_help(self):
        """Test that retrovue source remove --help works."""
        exit_code, stdout, stderr = run_cli(["source", "remove", "--help"])
        assert exit_code == 0
        assert "Delete a source" in stdout or "Delete a source" in stderr
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    def test_source_remove_presence(self):
        """Test that retrovue source remove command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["source", "remove", "--help"])
        assert exit_code == 0
    
    def test_source_sync_collections_help(self):
        """Test that retrovue source sync-collections --help works."""
        # TODO: This command is documented as sync-collections but may be implemented as discover
        # Check if sync-collections exists first
        exit_code, stdout, stderr = run_cli(["source", "sync-collections", "--help"])
        if exit_code != 0:
            # If sync-collections doesn't exist, check if discover exists (current implementation)
            exit_code, stdout, stderr = run_cli(["source", "discover", "--help"])
            assert exit_code == 0
            assert "Discover collections" in stdout or "Discover collections" in stderr
        else:
            assert exit_code == 0
            assert "sync-collections" in stdout or "sync collections" in stdout
    
    def test_source_sync_collections_current_implementation(self):
        """Test the current implementation (discover command)."""
        exit_code, stdout, stderr = run_cli(["source", "discover", "--help"])
        assert exit_code == 0
        assert "Discover collections" in stdout or "Discover collections" in stderr
    
    @pytest.mark.xfail(reason="Command should be named sync-collections per CLI contract")
    def test_source_sync_collections_contract_compliance(self):
        """Test that sync-collections command exists per contract."""
        exit_code, stdout, stderr = run_cli(["source", "sync-collections", "--help"])
        assert exit_code == 0
        # TODO: Either rename discover to sync-collections in code or update docs
        pytest.skip("Naming mismatch: docs say sync-collections but code has discover")