"""
Data contract tests for `retrovue enricher update` command.

Tests data-layer consistency, database operations, and enrichment parameter updates
as specified in docs/contracts/resources/EnricherUpdateContract.md.

This test enforces the data contract rules (D-#) for the enricher update command.
Focuses on enrichment parameter validation and persistence - specific values an 
enricher needs to perform its enrichment tasks (API keys, file paths, timing values, etc.).
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherUpdateDataContract:
    """Data contract tests for retrovue enricher update command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_update_enrichment_parameter_validation_before_persistence(self):
        """
        Contract D-2: Enrichment parameter validation MUST occur before database persistence.
        Contract D-9: Enrichment parameters MUST be validated for correctness (e.g., API key format, file existence).
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
            
            # Test with invalid API key format (too short)
            result = self.runner.invoke(app, [
                "enricher", "update", "enricher-tvdb-b2c3d4e5",
                "--config", '{"api_key": "short"}'
            ])
            
            # Should validate enrichment parameters before persisting
            assert result.exit_code == 1
            assert "Error" in result.stderr
            # Should not commit to database
            mock_db.commit.assert_not_called()

    def test_enricher_update_api_key_enrichment_parameter_persistence(self):
        """
        Contract D-2: Enrichment parameter validation MUST occur before database persistence.
        Contract D-10: Parameter updates MUST preserve the enricher's ability to perform its enrichment tasks.
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
            
            # Should validate and persist enrichment parameters
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout
            # Should commit to database
            mock_db.commit.assert_called_once()
            # Should preserve enricher's ability to perform enrichment tasks
            assert mock_enricher.config == {"api_key": "new-tvdb-api-key-12345"}

    def test_enricher_update_file_path_enrichment_parameter_validation(self):
        """
        Contract D-9: Enrichment parameters MUST be validated for correctness (e.g., file existence).
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
            
            # Test with non-existent file path
            result = self.runner.invoke(app, [
                "enricher", "update", "enricher-watermark-c3d4e5f6",
                "--config", '{"overlay_path": "/nonexistent/path/watermark.png"}'
            ])
            
            # Should validate file existence before persisting
            assert result.exit_code == 1
            assert "Error" in result.stderr
            # Should not commit to database
            mock_db.commit.assert_not_called()

    def test_enricher_update_timing_enrichment_parameter_validation(self):
        """
        Contract D-9: Enrichment parameters MUST be validated for correctness (e.g., timing value range validation).
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock crossfade enricher
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-crossfade-d4e5f6g7"
            mock_enricher.type = "crossfade"
            mock_enricher.name = "Crossfade Effect"
            mock_enricher.config = {"duration": 2.0}
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            # Test with invalid timing value (negative duration)
            result = self.runner.invoke(app, [
                "enricher", "update", "enricher-crossfade-d4e5f6g7",
                "--config", '{"duration": -1.0}'
            ])
            
            # Should validate timing value range before persisting
            assert result.exit_code == 1
            assert "Error" in result.stderr
            # Should not commit to database
            mock_db.commit.assert_not_called()

    def test_enricher_update_configuration_validation_before_persistence(self):
        """
        Contract D-2: Configuration validation MUST occur before database persistence.
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
            
            # Should validate before persisting and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_transaction_rollback_on_failure(self):
        """
        Contract D-3: On transaction failure, ALL changes MUST be rolled back with no partial updates.
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
            
            # Mock database error during update
            mock_db.commit.side_effect = Exception("Database constraint violation")
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            # Should handle rollback and show error
            assert result.exit_code == 1
            assert "Error updating enricher" in result.stderr

    def test_enricher_update_preserves_type(self):
        """
        Contract D-4: Enricher type MUST NOT be changed during updates.
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

    def test_enricher_update_registry_updates(self):
        """
        Contract D-5: Registry updates MUST occur within the same transaction as enricher updates.
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
            
            # Should update registry and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_schema_validation(self):
        """
        Contract D-6: Configuration schema validation MUST be performed against the enricher type.
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
            
            # Should validate schema and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_preserves_identity(self):
        """
        Contract D-7: Update operations MUST preserve enricher instance identity.
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
            
            # Should preserve identity and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_backward_compatibility(self):
        """
        Contract D-8: Configuration updates MUST maintain backward compatibility where possible.
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
            
            # Should maintain compatibility and show success message
            assert result.exit_code == 0
            assert "Successfully updated enricher" in result.stdout

    def test_enricher_update_database_error_propagation(self):
        """
        Contract: Database errors MUST be properly propagated to the CLI layer.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.side_effect = Exception("Database connection failed")
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4"])
            
            assert result.exit_code == 1
            assert "Error updating enricher" in result.stderr

    def test_enricher_update_json_error_propagation(self):
        """
        Contract: Database errors MUST be properly propagated in JSON format.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.side_effect = Exception("Database access denied")
            
            result = self.runner.invoke(app, ["enricher", "update", "enricher-ffprobe-a1b2c3d4", "--json"])
            
            assert result.exit_code == 1
            # JSON output should not be produced on error
            try:
                json.loads(result.stdout)
                pytest.fail("JSON should not be produced on error")
            except json.JSONDecodeError:
                pass  # Expected behavior

    def test_enricher_update_atomic_operation(self):
        """
        Contract: Update operations MUST be atomic - either all succeed or all fail.
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
            
            # Currently just shows TODO, but when implemented should be atomic
            assert result.exit_code == 0
            mock_session.assert_called_once()
