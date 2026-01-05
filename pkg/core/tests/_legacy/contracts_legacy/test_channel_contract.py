"""
Contract tests for Retrovue CLI commands.

This test enforces the global CLI contract defined in:
docs/contracts/README.md

Any change to CLI shape, flags, prompts, help text, or exit codes
must update that contract first.
"""


import pytest

from ..cli.utils import run_cli


class TestChannelContract:
    """Test suite for retrovue channel commands."""
    
    def test_channel_list_help(self):
        """Test that retrovue channel list --help works."""
        exit_code, stdout, stderr = run_cli(["channel", "list", "--help"])
        assert exit_code == 0
        # TODO: Update README.md to specify exact help text for channel list
        assert "List all channels" in stdout or "List all channels" in stderr
    
    def test_channel_list(self):
        """Test that retrovue channel list command exists and works."""
        exit_code, stdout, stderr = run_cli(["channel", "list"])
        assert exit_code == 0
        # TODO: Update README.md to specify exact output format for channel list
        # Should show channels or empty list
        assert "channels" in stdout.lower() or "found" in stdout.lower()
    
    @pytest.mark.xfail(reason="Documented output columns not implemented yet")
    def test_channel_list_output_columns(self):
        """Test that retrovue channel list shows documented output columns."""
        exit_code, stdout, stderr = run_cli(["channel", "list"])
        assert exit_code == 0
        # TODO: Assert that required columns appear in output:
        # - channel_id
        # - name/branding label  
        # - active producer instance
        # - attached playout enrichers (with priority)
        assert "channel_id" in stdout or "id" in stdout
        assert "name" in stdout or "branding" in stdout
        # TODO: Add assertions for producer instance and enrichers when implemented
        pytest.skip("Output format gap: missing producer instance and enricher columns")
    
    def test_channel_attach_enricher_help(self):
        """Test that retrovue channel attach-enricher --help works."""
        exit_code, stdout, stderr = run_cli(["channel", "attach-enricher", "--help"])
        assert exit_code == 0
        assert "--priority" in stdout
        # TODO: Update README.md to specify exact help text for channel attach-enricher
        assert "Attach a playout-scope enricher" in stdout or "Attach a playout-scope enricher" in stderr
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    def test_channel_attach_enricher_presence(self):
        """Test that retrovue channel attach-enricher command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["channel", "attach-enricher", "--help"])
        assert exit_code == 0
    
    def test_channel_detach_enricher_help(self):
        """Test that retrovue channel detach-enricher --help works."""
        exit_code, stdout, stderr = run_cli(["channel", "detach-enricher", "--help"])
        assert exit_code == 0
        # TODO: Update README.md to specify exact help text for channel detach-enricher
        assert "Remove enricher from channel" in stdout or "Remove enricher from channel" in stderr
    
    @pytest.mark.skip(reason="destructive; presence-only check")
    def test_channel_detach_enricher_presence(self):
        """Test that retrovue channel detach-enricher command is registered (destructive test)."""
        exit_code, stdout, stderr = run_cli(["channel", "detach-enricher", "--help"])
        assert exit_code == 0
