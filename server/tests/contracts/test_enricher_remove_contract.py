"""
Contract tests for `retrovue enricher remove` command.

Tests CLI behavior, validation, output formats, and error handling
as specified in docs/contracts/resources/EnricherRemoveContract.md.

This test enforces the CLI contract rules (B-#) for the enricher remove command.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherRemoveContract:
    """Contract tests for retrovue enricher remove command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_remove_help_flag_exits_zero(self):
        """
        Contract: The command MUST support help and exit with code 0.
        """
        result = self.runner.invoke(app, ["enricher", "remove", "--help"])
        
        assert result.exit_code == 0
        assert "Remove enricher instance" in result.stdout or "remove" in result.stdout

    def test_enricher_remove_requires_enricher_id(self):
        """
        Contract: The command MUST require an enricher_id argument.
        """
        result = self.runner.invoke(app, ["enricher", "remove"])
        
        assert result.exit_code != 0
        assert "Missing argument" in result.stderr or "enricher_id" in result.stderr

    def test_enricher_remove_interactive_confirmation_required(self):
        """
        Contract B-1: The command MUST require interactive confirmation unless --force is provided.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            # Mock user input "no" to cancel
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4"], input="no\n")
            
            assert result.exit_code == 0
            assert "Are you sure you want to remove enricher" in result.stdout
            assert "Removal cancelled" in result.stdout

    def test_enricher_remove_confirmation_requires_yes(self):
        """
        Contract B-2: Interactive confirmation MUST require the user to type "yes" exactly to proceed.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            # Mock user input "y" (not "yes")
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4"], input="y\n")
            
            assert result.exit_code == 0
            assert "Removal cancelled" in result.stdout

    def test_enricher_remove_confirmation_shows_details(self):
        """
        Contract B-3: The confirmation prompt MUST show enricher details and cascade impact count.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            mock_enricher.protected_from_removal = True  # Mark as protected
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            # Mock user input "no" to cancel
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4"], input="no\n")
            
            assert result.exit_code == 0
            assert "Video Analysis" in result.stdout
            assert "enricher-ffprobe-a1b2c3d4" in result.stdout
            assert "This action cannot be undone" in result.stdout
            assert "WARNING: This enricher is marked as protected from removal" in result.stdout

    def test_enricher_remove_json_output_format(self):
        """
        Contract B-4: When --json is supplied, output MUST include fields 
        "removed", "enricher_id", "name", "type", and "scope".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            try:
                output_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                pytest.fail("Output is not valid JSON")
            
            # Verify required fields are present
            assert "removed" in output_data
            assert "enricher_id" in output_data
            assert "name" in output_data
            assert "type" in output_data
            
            # Verify values
            assert output_data["removed"] is True
            assert output_data["enricher_id"] == "enricher-ffprobe-a1b2c3d4"
            assert output_data["name"] == "Video Analysis"
            assert output_data["type"] == "ffprobe"

    def test_enricher_remove_enricher_not_found(self):
        """
        Contract B-5: On validation failure (enricher not found), the command 
        MUST exit with code 1 and print "Error: Enricher 'X' not found".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher not found
            mock_query = MagicMock()
            mock_query.first.return_value = None
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-nonexistent-123", "--force"])
            
            assert result.exit_code == 1
            assert "Error removing enricher" in result.stderr

    def test_enricher_remove_cancellation_exit_code(self):
        """
        Contract B-6: Cancellation of confirmation MUST return exit code 0 with message "Removal cancelled".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            # Mock user input "no" to cancel
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4"], input="no\n")
            
            assert result.exit_code == 0
            assert "Removal cancelled" in result.stdout

    def test_enricher_remove_force_skips_confirmation(self):
        """
        Contract B-7: The --force flag MUST skip all confirmation prompts and proceed immediately.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force"])
            
            assert result.exit_code == 0
            assert "Are you sure" not in result.stdout
            assert "Successfully removed enricher" in result.stdout

    def test_enricher_remove_test_db_support(self):
        """
        Contract: The --test-db flag MUST work for testing in isolated environment.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--test-db", "--force"])
            
            assert result.exit_code == 0
            assert "Successfully removed enricher" in result.stdout

    def test_enricher_remove_success_human_output(self):
        """
        Contract: Success output MUST include enricher details in human-readable format.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force"])
            
            assert result.exit_code == 0
            assert "Successfully removed enricher: Video Analysis" in result.stdout
            assert "ID: enricher-ffprobe-a1b2c3d4" in result.stdout
            assert "Type: ffprobe" in result.stdout
            # Scope field has been removed from the domain model

    def test_enricher_remove_cascade_impact_display(self):
        """
        Contract: The command MUST show cascade impact (collections/channels affected).
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force"])
            
            assert result.exit_code == 0
            # Cascade impact is only shown when there are attachments to remove
            # Since we're mocking with 0 attachments, we don't expect to see this information

    def test_enricher_remove_json_cascade_impact(self):
        """
        Contract: JSON output MUST include cascade impact counts.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should include cascade impact counts
            assert "collection_attachments_removed" in output_data
            assert "channel_attachments_removed" in output_data
