"""
Contract tests for `retrovue enricher add` command.

Tests CLI behavior, validation, output formats, and error handling
as specified in docs/contracts/resources/EnricherAddContract.md.

This test enforces the CLI contract rules (B-#) for the enricher add command.
Focuses on enrichment parameter validation - specific values an enricher needs to 
perform its enrichment tasks (API keys, file paths, timing values, etc.).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherAddContract:
    """Contract tests for retrovue enricher add command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_add_enrichment_parameter_validation(self):
        """
        Contract: Enrichment parameter validation MUST be performed against the enricher type's parameter schema.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock TheTVDB enricher that requires API key
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "tvdb", "--name", "TheTVDB Metadata",
                "--api-key", "short"  # Invalid API key format
            ])
            
            # Should validate enrichment parameter format
            assert result.exit_code == 1
            assert "Error" in result.stderr

    def test_enricher_add_api_key_enrichment_parameter(self):
        """
        Contract: API-based enrichers MUST validate API key enrichment parameters.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "tvdb", "--name", "TheTVDB Metadata",
                "--api-key", "valid-tvdb-api-key-12345"
            ])
            
            # Should successfully create enricher with valid API key
            assert result.exit_code == 0
            assert "Successfully created" in result.stdout

    def test_enricher_add_file_path_enrichment_parameter(self):
        """
        Contract: File-based enrichers MUST validate file path enrichment parameters.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "watermark", "--name", "Channel Watermark",
                "--overlay-path", "/path/to/watermark.png"
            ])
            
            # Should successfully create enricher with valid file path
            assert result.exit_code == 0
            assert "Successfully created" in result.stdout

    def test_enricher_add_no_parameters_needed(self):
        """
        Contract: Enrichers that require no enrichment parameters should work with minimal input.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ffmpeg", "--name", "FFmpeg Analysis"
            ])
            
            # Should successfully create enricher without additional parameters
            assert result.exit_code == 0
            assert "Successfully created" in result.stdout

    def test_enricher_add_help_without_type_shows_general_help(self):
        """
        Contract B-7: The --help flag MUST display detailed help for the specified 
        enricher type and MUST exit with code 0 without creating any enricher instances.
        """
        result = self.runner.invoke(app, ["enricher", "add", "--help"])
        
        assert result.exit_code == 0
        assert "--type" in result.stdout
        assert "--name" in result.stdout

    def test_enricher_add_requires_type_parameter(self):
        """
        Contract B-2: Required parameters MUST be validated before any database operations.
        """
        result = self.runner.invoke(app, ["enricher", "add", "--name", "Test Enricher"])
        
        assert result.exit_code == 1
        assert "Missing required parameter" in result.stdout or "required" in result.stdout

    def test_enricher_add_requires_name_parameter(self):
        """
        Contract B-2: Required parameters MUST be validated before any database operations.
        """
        result = self.runner.invoke(app, ["enricher", "add", "--type", "ingest"])
        
        assert result.exit_code == 1
        assert "Missing required parameter" in result.stderr or "required" in result.stderr

    def test_enricher_add_invalid_type_returns_error(self):
        """
        Contract B-5: On validation failure, the command MUST exit with code 1 
        and print a human-readable error message.
        """
        result = self.runner.invoke(app, [
            "enricher", "add", "--type", "invalid-type", "--name", "Test"
        ])
        
        assert result.exit_code == 1
        assert "Invalid enricher type" in result.stderr or "not found" in result.stderr

    def test_enricher_add_dry_run_shows_validation(self):
        """
        Contract B-6: The --dry-run flag MUST show configuration validation 
        and enricher ID generation without executing.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--dry-run"
            ])
            
            assert result.exit_code == 0
            assert "DRY RUN" in result.stdout
            assert "Would create enricher:" in result.stdout or "Configuration validation:" in result.stdout
            assert "enricher-ingest-" in result.stdout  # Generated ID format uses type as enricher_type

    def test_enricher_add_dry_run_json_output(self):
        """
        Contract B-4: When --json is supplied, output MUST include fields 
        "enricher_id", "type", "name", "config", and "status".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", 
                "--dry-run", "--json"
            ])
            
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
            
            # Verify values
            assert output_data["type"] == "ingest"  # Type parameter becomes the enricher type
            assert output_data["name"] == "Test Enricher"
            assert output_data["status"] == "dry_run"

    def test_enricher_add_success_output_format(self):
        """
        Contract B-4: When --json is supplied, output MUST include fields 
        "enricher_id", "type", "name", "config", and "status".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock successful creation
            mock_db.add.return_value = None
            mock_db.commit.return_value = None
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
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
            
            # Verify values
            assert output_data["type"] == "ingest"  # Type parameter becomes the enricher type
            assert output_data["name"] == "Test Enricher"
            assert output_data["status"] == "created"

    def test_enricher_add_success_human_output(self):
        """
        Contract: Success output MUST include enricher details in human-readable format.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock successful creation
            mock_db.add.return_value = None
            mock_db.commit.return_value = None
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher"
            ])
            
            assert result.exit_code == 0
            assert "Successfully created ingest enricher: Test Enricher" in result.stdout
            assert "ID: enricher-ingest-" in result.stdout
            assert "Type: ingest" in result.stdout
            assert "Name: Test Enricher" in result.stdout

    def test_enricher_add_config_parameter(self):
        """
        Contract: Both ingest and playout enrichers MUST accept --config parameter.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock successful creation
            mock_db.add.return_value = None
            mock_db.commit.return_value = None
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Custom Ingest",
                "--config", '{"ingest_path": "/usr/bin/ingest", "timeout": 60}'
            ])
            
            assert result.exit_code == 0
            assert "Successfully created ingest enricher: Custom Ingest" in result.stdout

    def test_enricher_add_configuration_validation(self):
        """
        Contract B-8: Configuration validation MUST be performed against the enricher type's schema.
        """
        result = self.runner.invoke(app, [
            "enricher", "add", "--type", "ingest", "--name", "Test",
            "--timeout", "invalid-timeout"  # Invalid timeout value
        ])
        
        assert result.exit_code == 2  # Typer parameter parsing error
        # Typer handles parameter type validation before our code runs

    def test_enricher_add_unique_id_generation(self):
        """
        Contract B-3: Enricher ID MUST be generated in format "enricher-{type}-{hash}" 
        and MUST be unique.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock successful creation
            mock_db.add.return_value = None
            mock_db.commit.return_value = None
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            enricher_id = output_data["enricher_id"]
            
            # Verify ID format
            assert enricher_id.startswith("enricher-ingest-")  # Uses type as enricher_type
            assert len(enricher_id) > len("enricher-ingest-")  # Has hash suffix
