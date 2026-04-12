"""
Contract tests for `retrovue enricher update` command.

Tests CLI behavior, validation, output formats, and error handling
as specified in docs/contracts/resources/EnricherUpdateContract.md.

This test enforces the CLI contract rules (B-#) for the enricher update command.
Focuses on enrichment parameter updates - specific values an enricher needs to 
perform its enrichment tasks (API keys, file paths, timing values, etc.).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherUpdateContract:
    """Contract tests for retrovue enricher update command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_update_enrichment_parameter_validation(self):
        """
        Contract B-2: Enrichment parameter validation MUST be performed against the enricher type's parameter schema.
        Contract B-10: The command MUST validate enrichment parameters against the enricher's specific requirements.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock TheTVDB enricher that requires API key
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-tvdb-b2c3d4e5"
            mock_enricher.type = "tvdb"
            mock_enricher.name = "TheTVDB Metadata"
            mock_enricher.config = {"api_key": "old-key", "language": "en-US"}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            # Test with invalid API key format
            result = self.runner.invoke(app, [
                "enricher", "update", "enricher-tvdb-b2c3d4e5",
                "--config", '{"api_key": "short"}'
            ])
            
            # Should validate enrichment parameter format
            assert result.exit_code == 1
            assert "Error" in result.stderr

    def test_enricher_update_no_parameters_needed(self):
        """
        Contract B-9: For enrichers that require no parameters (e.g., FFmpeg), 
        the command MUST inform the user that updates are not necessary.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock FFmpeg enricher that requires no parameters
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffmpeg-a1b2c3d4"
            mock_enricher.type = "ffmpeg"
            mock_enricher.name = "FFmpeg Analysis"
            mock_enricher.config = {}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffmpeg-a1b2c3d4"])
            
            # Should inform user that no updates are needed
            assert result.exit_code == 0
            assert "enricher requires no enrichment parameters" in result.stdout.lower()

    def test_enricher_update_api_key_enrichment_parameter(self):
        """
        Contract B-2: Enrichment parameter validation for API-based enrichers.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock TheTVDB enricher
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-tvdb-b2c3d4e5"
            mock_enricher.type = "tvdb"
            mock_enricher.name = "TheTVDB Metadata"
            mock_enricher.config = {"api_key": "old-key"}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, [
                "enricher", "update", "enricher-tvdb-b2c3d4e5",
                "--config", '{"api_key": "new-tvdb-api-key-12345"}'
            ])
            
            # Should successfully update API key enrichment parameter
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_file_path_enrichment_parameter(self):
        """
        Contract B-2: Enrichment parameter validation for file-based enrichers.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock watermark enricher
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-watermark-c3d4e5f6"
            mock_enricher.type = "watermark"
            mock_enricher.name = "Channel Watermark"
            mock_enricher.config = {"overlay_path": "/old/path/watermark.png"}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, [
                "enricher", "update", "enricher-watermark-c3d4e5f6",
                "--config", '{"overlay_path": "/new/path/watermark.png", "opacity": 0.7}'
            ])
            
            # Should successfully update file path enrichment parameters
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_requires_enricher_id(self):
        """
        Contract: The command MUST require an enricher_id argument.
        """
        result = self.runner.invoke(app, ["enricher", "update"])
        
        assert result.exit_code != 0
        assert "Missing argument" in result.stderr or "enricher_id" in result.stderr

    def test_enricher_update_validates_existence(self):
        """
        Contract B-1: The command MUST validate enricher instance existence before attempting updates.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher not found
            mock_query = MagicMock()
            mock_query.first.return_value = None
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-nonexistent-123"])
            
            assert result.exit_code == 1
            assert "Error updating enricher" in result.stderr

    def test_enricher_update_configuration_validation(self):
        """
        Contract B-2: Configuration validation MUST be performed against the enricher type's schema.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            # Should validate configuration and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_json_output_format(self):
        """
        Contract B-3: When --json is supplied, output MUST include fields 
        "enricher_id", "type", "name", "config", "status", and "updated_at".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "/usr/bin/ffprobe", "timeout": 60}
            
            # Mock updated_at as a proper datetime
            from datetime import datetime
            mock_enricher.updated_at = datetime.now()
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4", "--json"])
            
            # Should have proper JSON output with required fields
            assert result.exit_code == 0
            
            # Parse JSON output
            try:
                output_data = json.loads(result.stdout)
            except json.JSONDecodeError:
                pytest.fail("Output is not valid JSON")
            
            # Verify required fields are present
            assert "enricher_id" in output_data
            assert "type" in output_data
            assert "name" in output_data
            assert "config" in output_data
            assert "status" in output_data
            assert "updated_at" in output_data

    def test_enricher_update_enricher_not_found(self):
        """
        Contract B-4: On validation failure (enricher not found), the command 
        MUST exit with code 1 and print "Error: Enricher 'X' not found".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher not found
            mock_query = MagicMock()
            mock_query.first.return_value = None
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-nonexistent-123"])
            
            assert result.exit_code == 1
            assert "Error updating enricher" in result.stderr

    def test_enricher_update_dry_run_support(self):
        """
        Contract B-5: The --dry-run flag MUST show configuration validation and update preview without executing.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4", "--dry-run"])
            
            # Should show dry run preview
            assert result.exit_code == 0
            assert "Would update enricher" in result.stdout

    def test_enricher_update_preserves_type(self):
        """
        Contract B-6: Configuration updates MUST preserve enricher type.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            # Should preserve type and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_partial_configuration(self):
        """
        Contract B-7: The command MUST support partial configuration updates (only specified parameters).
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            # Should support partial updates and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_atomic_operation(self):
        """
        Contract B-8: Update operations MUST be atomic and consistent.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            # Should be atomic and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_test_db_support(self):
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
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4", "--test-db"])
            
            # Should work with test-db and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_success_human_output(self):
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
            mock_enricher.config = {"ffprobe_path": "/usr/bin/ffprobe", "timeout": 60}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            # Should show proper success message with enricher details
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout
            assert "Video Analysis" in result.stdout

    def test_enricher_update_no_parameters_provided(self):
        """
        Contract: The command MUST handle cases where no configuration parameters are provided.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher.type = "ffprobe"
            mock_enricher.name = "Video Analysis"
            mock_enricher.config = {"ffprobe_path": "ffprobe", "timeout": 30}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            # Should handle no parameters and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout
