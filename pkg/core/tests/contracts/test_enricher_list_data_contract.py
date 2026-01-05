"""
Data contract tests for `retrovue enricher list` command.

Tests data-layer consistency, database queries, and entity retrievability
as specified in docs/contracts/resources/EnricherListContract.md.

This test enforces the data contract rules (D-#) for the enricher list command.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherListDataContract:
    """Data contract tests for retrovue enricher list command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_list_read_only_database_operations(self):
        """
        Contract D-1: Database queries MUST be read-only during listing operations.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instances
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
            
            # Verify only read operations were performed
            mock_db.query.assert_called_once()
            # No write operations should be called
            mock_db.add.assert_not_called()
            mock_db.commit.assert_not_called()
            mock_db.rollback.assert_not_called()

    def test_enricher_list_no_external_modifications(self):
        """
        Contract D-4: Enricher listing MUST NOT modify external systems or database tables.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instances
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
            
            # Verify no external modifications
            mock_db.add.assert_not_called()
            mock_db.delete.assert_not_called()
            mock_db.update.assert_not_called()

    def test_enricher_list_atomic_database_queries(self):
        """
        Contract D-5: Database queries MUST be atomic and consistent.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instances
            mock_enricher1 = MagicMock()
            mock_enricher1.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher1.type = "ffprobe"
            mock_enricher1.name = "Video Analysis"
            mock_enricher1.config = {"ffprobe_path": "ffprobe"}
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
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Verify atomic operation - all enrichers returned together
            assert output_data["total"] == 2
            assert len(output_data["enrichers"]) == 2
            
            # Verify consistency - all enrichers have same structure
            for enricher in output_data["enrichers"]:
                assert "enricher_id" in enricher
                assert "type" in enricher
                assert "name" in enricher
                assert "config" in enricher

    def test_enricher_list_type_availability_validation(self):
        """
        Contract D-2: Enricher instance lookup MUST validate enricher type availability.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instances with different types
            mock_enricher1 = MagicMock()
            mock_enricher1.enricher_id = "enricher-ffprobe-a1b2c3d4"
            mock_enricher1.type = "ffprobe"
            mock_enricher1.name = "Video Analysis"
            mock_enricher1.config = {"ffprobe_path": "ffprobe"}
            mock_enricher1.scope = "ingest"
            
            mock_enricher2 = MagicMock()
            mock_enricher2.enricher_id = "enricher-invalid-b2c3d4e5"
            mock_enricher2.type = "invalid-type"
            mock_enricher2.name = "Invalid Enricher"
            mock_enricher2.config = {}
            mock_enricher2.scope = "unknown"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher1, mock_enricher2]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should handle both valid and invalid types gracefully
            assert output_data["total"] == 2
            assert len(output_data["enrichers"]) == 2

    def test_enricher_list_attachment_status_calculation(self):
        """
        Contract D-3: Attachment status MUST be calculated accurately for each enricher.
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
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should include attachment information
            enricher = output_data["enrichers"][0]
            assert "attachments" in enricher
            assert "collections" in enricher["attachments"]
            assert "channels" in enricher["attachments"]

    def test_enricher_list_registry_state_validation(self):
        """
        Contract D-6: Enricher availability status MUST be validated against registry state.
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
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should include availability status
            enricher = output_data["enrichers"][0]
            assert "status" in enricher
            assert enricher["status"] in ["available", "unavailable"]

    def test_enricher_list_configuration_privacy_settings(self):
        """
        Contract D-7: Configuration display MUST respect privacy settings (redact sensitive data).
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instance with sensitive configuration
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-metadata-b2c3d4e5"
            mock_enricher.type = "metadata"
            mock_enricher.name = "Movie Metadata"
            mock_enricher.config = {"api_key": "secret123", "sources": "imdb,tmdb"}
            mock_enricher.scope = "ingest"
            
            mock_query = MagicMock()
            mock_query.all.return_value = [mock_enricher]
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 0
            
            # Should redact sensitive information
            assert "secret123" not in result.stdout
            assert "***REDACTED***" in result.stdout or "api_key" not in result.stdout

    def test_enricher_list_performance_non_blocking(self):
        """
        Contract D-8: Listing operations MUST be performant and not block other operations.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher instances
            mock_enrichers = []
            for i in range(10):
                mock_enricher = MagicMock()
                mock_enricher.enricher_id = f"enricher-ffprobe-{i:08x}"
                mock_enricher.type = "ffprobe"
                mock_enricher.name = f"Video Analysis {i}"
                mock_enricher.config = {"ffprobe_path": "ffprobe"}
                mock_enricher.scope = "ingest"
                mock_enrichers.append(mock_enricher)
            
            mock_query = MagicMock()
            mock_query.all.return_value = mock_enrichers
            mock_db.query.return_value.order_by.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output_data = json.loads(result.stdout)
            
            # Should handle multiple enrichers efficiently
            assert output_data["total"] == 10
            assert len(output_data["enrichers"]) == 10

    def test_enricher_list_database_error_propagation(self):
        """
        Contract: Database errors MUST be properly propagated to the CLI layer.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.side_effect = Exception("Database connection failed")
            
            result = self.runner.invoke(app, ["enricher", "list"])
            
            assert result.exit_code == 1
            assert "Error listing enrichers" in result.stderr

    def test_enricher_list_json_error_propagation(self):
        """
        Contract: Database errors MUST be properly propagated in JSON format.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.side_effect = Exception("Database access denied")
            
            result = self.runner.invoke(app, ["enricher", "list", "--json"])
            
            assert result.exit_code == 1
            # JSON output should not be produced on error
            try:
                json.loads(result.stdout)
                pytest.fail("JSON should not be produced on error")
            except json.JSONDecodeError:
                pass  # Expected behavior

    def test_enricher_list_database_state_consistency(self):
        """
        Contract: Database state MUST be consistent during listing operations.
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
            
            # First call
            result1 = self.runner.invoke(app, ["enricher", "list", "--json"])
            assert result1.exit_code == 0
            
            # Second call should get same results
            result2 = self.runner.invoke(app, ["enricher", "list", "--json"])
            assert result2.exit_code == 0
            
            # Parse both outputs
            output1 = json.loads(result1.stdout)
            output2 = json.loads(result2.stdout)
            
            # Results should be consistent
            assert output1["total"] == output2["total"]
            assert len(output1["enrichers"]) == len(output2["enrichers"])
            assert output1["enrichers"][0]["enricher_id"] == output2["enrichers"][0]["enricher_id"]
