"""
CLI contract tests for retrovue enricher commands.

Tests the enricher command group against the documented CLI contract in docs/operator/CLI.md.
"""

import pytest

from .utils import run_cli


class TestEnricherCLI:
    """Test suite for retrovue enricher commands."""
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_list_types_help(self):
        """Test that retrovue enricher list-types --help works."""
        exit_code, stdout, stderr = run_cli(["enricher", "list-types", "--help"])
        assert exit_code == 0
        assert "Show all enricher types" in stdout or "Show all enricher types" in stderr
        pytest.skip("not implemented")
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_list_types(self):
        """Test that retrovue enricher list-types command exists."""
        exit_code, stdout, stderr = run_cli(["enricher", "list-types"])
        assert exit_code == 0
        pytest.skip("not implemented")
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_add_help(self):
        """Test that retrovue enricher add --help works."""
        exit_code, stdout, stderr = run_cli(["enricher", "add", "--help"])
        assert exit_code == 0
        assert "--type" in stdout
        assert "--name" in stdout
        pytest.skip("not implemented")
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_add_type_help(self):
        """Test that retrovue enricher add --type <type> --help works."""
        exit_code, stdout, stderr = run_cli(["enricher", "add", "--type", "ffprobe", "--help"])
        assert exit_code == 0
        pytest.skip("not implemented")
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_list_help(self):
        """Test that retrovue enricher list --help works."""
        exit_code, stdout, stderr = run_cli(["enricher", "list", "--help"])
        assert exit_code == 0
        assert "List configured enricher instances" in stdout or "List configured enricher instances" in stderr
        pytest.skip("not implemented")
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_list(self):
        """Test that retrovue enricher list command exists."""
        exit_code, stdout, stderr = run_cli(["enricher", "list"])
        assert exit_code == 0
        pytest.skip("not implemented")
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_update_help(self):
        """Test that retrovue enricher update --help works."""
        exit_code, stdout, stderr = run_cli(["enricher", "update", "--help"])
        assert exit_code == 0
        assert "Update enricher configuration" in stdout or "Update enricher configuration" in stderr
        pytest.skip("not implemented")
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_update_presence(self):
        """Test that retrovue enricher update command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["enricher", "update", "--help"])
        assert exit_code == 0
        pytest.skip("not implemented")
    
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_remove_help(self):
        """Test that retrovue enricher remove --help works."""
        exit_code, stdout, stderr = run_cli(["enricher", "remove", "--help"])
        assert exit_code == 0
        assert "Remove enricher instance" in stdout or "Remove enricher instance" in stderr
        pytest.skip("not implemented")
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    @pytest.mark.xfail(reason="Not implemented yet per CLI contract in docs/operator/CLI.md")
    def test_enricher_remove_presence(self):
        """Test that retrovue enricher remove command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["enricher", "remove", "--help"])
        assert exit_code == 0
        pytest.skip("not implemented")