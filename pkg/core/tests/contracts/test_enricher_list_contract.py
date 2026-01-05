"""
Contract tests for `retrovue enricher list` command.

Tests CLI behavior, validation, output formats, and error handling
as specified in docs/contracts/resources/EnricherListContract.md.

This test enforces the CLI contract rules (B-#) for the enricher list command.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherListContract:
    """Contract tests for retrovue enricher list command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_list_help_flag_exits_zero(self):
        """
        Contract B-7: The command MUST support help and exit with code 0.
        """
        result = self.runner.invoke(app, ["enricher", "list", "--help"])
        
        assert result.exit_code == 0
        assert "List configured enricher instances" in result.stdout or "list" in result.stdout

    def test_enricher_list_basic_listing(self):
        """
        Contract B-1: The command MUST list all configured enricher instances from the database.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instances
            mock_enricher1 = MagicMock()
            mock_enricher1.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher1.type = "ffprobe"
            mock_enricher1.name = "Video Analysis"
            mock_enricher1.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            mock_enricher1.scope = "ingest"
            
            mock_enricher2 = MagicMock()
            mock_enricher2.enricher_id = "enricher-metadata-b2c3d4e5"
            mock_enricher2.type = "metadata"
            mock_enricher2.name = "Movie Metadata"
            mock_enricher2.config = {"sources": "imdb,tmdb"}
            mock_enricher2.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher1, mock_enricher2]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 0
            assert "Configured enricher instances:" in result.stdout
            assert "enricher-ffprobe-a1b2c3d4" in result.stdout
            assert "enricher-metadata-b2c3d4e5" in result.stdout
            assert "Video Analysis" in result.stdout
            assert "Movie Metadata" in result.stdout

    def test_enricher_list_json_output_format(self):
        """
        Contract B-3: When --json is supplied, output MUST include fields 
        "status", "enrichers", and "total" with appropriate data structures.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instance
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            try:
                output_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                pytest.fail("Output is not valid JSON")
            
            # Verify required fields are present
            assert "status" in output_data
            assert "enrichers" in output_data
            assert "total" in output_data
            
            # Verify values
            assert output_data["status"] == "ok"
            assert isinstance(output_data["enrichers"], list)
            assert output_data["total"] == 1
            
            # Verify enricher structure
            enricher = output_data["enrichers"][0]
            assert "enricher_id" in enricher
            assert "type" in enricher
            assert "name" in enricher
            assert "config" in enricher
            assert "attachments" in enricher
            assert "status" in enricher

    def test_enricher_list_dry_run_support(self):
        """
        Contract B-5: The --dry-run flag MUST show what would be listed 
        without executing database queries.
        """
        result = self.runner.invoke(app, ["enricher", "list", "--dry-run"])
        
        assert result.exit_code == 0
        assert "Would list" in result.stdout or "DRY RUN" in result.stdout
        assert "enricher instances from database" in result.stdout or "enricher instances" in result.stdout

    def test_enricher_list_dry_run_json_output(self):
        """
        Contract B-5: The --dry-run flag MUST show what would be listed 
        without executing database queries, including JSON format.
        """
        result = self.runner.invoke(app, ["enricher", "list", "--dry-run", "--json"])
        
        assert result.exit_code == 0
        
        # Parse JSON output
        try:
            output_data = json.loads(result.stdout)
        except json.JSONDecodeError:
            pytest.fail("Output is not valid JSON")
        
        # Verify dry-run status
        assert output_data["status"] == "dry_run"
        assert "enrichers" in output_data
        assert "total" in output_data

    def test_enricher_list_test_db_support(self):
        """
        Contract: The --test-db flag MUST work for testing in isolated environment.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock empty enricher instances for test database
            mock_query = MagicMock()
            mock_query.all.return_value = []
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list", "--test-db"])
            
            assert result.exit_code == 0
            assert "Using test database environment..." in result.stdout
            assert "No enricher instances configured" in result.stdout

    def test_enricher_list_deterministic_output(self):
        """
        Contract B-6: Enricher listing MUST be deterministic - the same 
        database state MUST produce the same listing results.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock consistent enricher instances
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe"}
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            # Run the command multiple times
            result1 = self.runner.invoke(app, ["enricher", "list"])
            result2 = self.runner.invoke(app, ["enricher", "list"])
            
            assert result1.exit_code == 0
            assert result2.exit_code == 0
            
            # Output should be identical
            assert result1.stdout == result2.stdout

    def test_enricher_list_json_deterministic_output(self):
        """
        Contract B-6: JSON output MUST also be deterministic.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock consistent enricher instances
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe"}
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            # Run the command multiple times with JSON
            result1 = self.runner.invoke(app, ["enricher", "list", "--json"])
            result2 = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result1.exit_code == 0
            assert result2.exit_code == 0
            
            # Parse both outputs
            output1 = json.loads(result1.stdout)
            output2 = json.loads(result2.stdout)
            
            # Output should be identical
            assert output1 == output2

    def test_enricher_list_database_error_handling(self):
        """
        Contract B-4: On listing failure (database access error), the command 
        MUST exit with code 1 and print a human-readable error message.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.side_effect = Exception("Database connection error")
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 1
            assert "Error listing enrichers" in result.stderr

    def test_enricher_list_empty_database_handling(self):
        """
        Contract B-8: Empty listing results (no enricher instances) MUST return 
        exit code 0 with message "No enricher instances configured".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock empty result
            mock_query = MagicMock()
            mock_query.all.return_value = []
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 0
            assert "No enricher instances configured" in result.stdout

    def test_enricher_list_empty_database_json_handling(self):
        """
        Contract B-8: Empty listing results in JSON format MUST return 
        exit code 0 with appropriate JSON structure.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock empty result
            mock_query = MagicMock()
            mock_query.all.return_value = []
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            assert output_data["status"] == "ok"
            assert output_data["enrichers"] == []
            assert output_data["total"] == 0

    def test_enricher_list_human_output_format(self):
        """
        Contract: Human-readable output MUST match the specified format.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instance
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 0
            
            # Check for expected format elements
            assert "Configured enricher instances:" in result.stdout
            assert "Total: 1 enricher instances configured" in result.stdout
            
            # Check that scope information is NOT displayed (per refactoring)
            assert "Scope:" not in result.stdout

    def test_enricher_list_attachment_status_display(self):
        """
        Contract B-7: The command MUST report attachment status for each enricher instance.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instance
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe"}
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 0
            
            # Should display attachment status
            assert "Attached to:" in result.stdout or "attachments" in result.stdout.lower()

    def test_enricher_list_configuration_display(self):
        """
        Contract B-2: The command MUST display enricher type, name, and configuration for each instance.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instance with configuration
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-metadata-b2c3d4e5"
            mock_enricher.type = "metadata"
            mock_enricher.name = "Movie Metadata"
            mock_enricher.config = {"sources": "imdb,tmdb", "api_key": "secret123"}
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 0
            
            # Should display type, name, and configuration
            assert "metadata" in result.stdout
            assert "Movie Metadata" in result.stdout
            assert "Configuration:" in result.stdout or "config" in result.stdout.lower()
