"""
Data contract tests for `retrovue enricher remove` command.

Tests data-layer consistency, database operations, and cascade deletion
as specified in docs/contracts/resources/EnricherRemoveContract.md.

This test enforces the data contract rules (D-#) for the enricher remove command.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherRemoveDataContract:
    """Data contract tests for retrovue enricher remove command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_remove_cascade_collection_attachments(self):
        """
        Contract D-1: Enricher removal MUST cascade delete all associated collection attachment records.
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
            
            # Verify database operations were called
            mock_db.query.assert_called()
            # TODO: Verify cascade deletion when implemented

    def test_enricher_remove_cascade_channel_attachments(self):
        """
        Contract D-2: Enricher removal MUST cascade delete all associated channel attachment records.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock enricher exists
            mock_enricher = MagicMock()
            mock_enricher.enricher_id = "enricher-playout-c3d4e5f6"
            mock_enricher.type = "playout"
            mock_enricher.name = "Channel Branding"
            mock_enricher.scope = "playout"
            
            mock_query = MagicMock()
            mock_query.first.return_value = mock_enricher
            mock_db.query.return_value.filter.return_value = mock_query
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-playout-c3d4e5f6", "--force"])
            
            assert result.exit_code == 0
            
            # Verify database operations were called
            mock_db.query.assert_called()
            # TODO: Verify cascade deletion when implemented

    def test_enricher_remove_transaction_boundary(self):
        """
        Contract D-3: All removal operations MUST occur within a single transaction boundary.
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
            
            # Verify transaction operations
            mock_session.assert_called_once()
            mock_db.delete.assert_called_once_with(mock_enricher)
            mock_db.commit.assert_called_once()

    def test_enricher_remove_transaction_rollback_on_failure(self):
        """
        Contract D-4: On transaction failure, ALL changes MUST be rolled back with no partial deletions.
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
            
            # Mock database error during removal
            mock_db.delete.side_effect = Exception("Database constraint violation")
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force"])
            
            assert result.exit_code == 1
            assert "Error removing enricher" in result.stderr
            
            # Verify rollback was called
            mock_db.rollback.assert_called_once()

    def test_enricher_remove_production_safety_check(self):
        """
        Contract D-5: An enricher MUST NOT be removed in production if its removal would cause harm 
        to running or future operations. Harm means breaking an active process, violating an operational 
        expectation, or leaving the system in an invalid state. --force MUST NOT override this safeguard.
        
        The implementation checks for harm using two criteria:
        1. Whether the enricher is currently in use by an active ingest or playout operation
        2. Whether the enricher is marked protected_from_removal = true
        
        Historical usage is not considered harmful unless the enricher is explicitly protected.
        Non-production environments remain permissive with no safety checks.
        """
        # Test 1: Protected enricher cannot be removed in production
        with patch("retrovue.cli.commands.enricher.session") as mock_session, \
             patch("os.getenv") as mock_getenv:
            
            # Mock production environment
            mock_getenv.side_effect = lambda key, default="": "production" if key == "ENV" else default
            
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Create a protected enricher
            protected_enricher = MagicMock()
            protected_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            protected_enricher.name = "Protected Video Analysis"
            protected_enricher.type = "ffprobe"
            protected_enricher.scope = "ingest"
            protected_enricher.protected_from_removal = True
            
            mock_db.query.return_value.filter.return_value.first.return_value = protected_enricher
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force"])
            
            assert result.exit_code == 1
            assert "Cannot remove enricher in production" in result.stderr
            assert "marked as protected from removal" in result.stderr
        
        # Test 2: Non-protected enricher can be removed in production (when not in active use)
        with patch("retrovue.cli.commands.enricher.session") as mock_session, \
             patch("os.getenv") as mock_getenv:
            
            # Mock production environment
            mock_getenv.side_effect = lambda key, default="": "production" if key == "ENV" else default
            
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Create a non-protected enricher
            normal_enricher = MagicMock()
            normal_enricher.enricher_id = "enricher-metadata-b2c3d4e5"
            normal_enricher.name = "Normal Metadata Enricher"
            normal_enricher.type = "metadata"
            normal_enricher.scope = "ingest"
            normal_enricher.protected_from_removal = False
            
            mock_db.query.return_value.filter.return_value.first.return_value = normal_enricher
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-metadata-b2c3d4e5", "--force"])
            
            # Should succeed since it's not protected and not in active use
            assert result.exit_code == 0
            assert "Successfully removed enricher" in result.stdout
        
        # Test 3: Non-production environments are permissive
        with patch("retrovue.cli.commands.enricher.session") as mock_session, \
             patch("os.getenv") as mock_getenv:
            
            # Mock non-production environment
            mock_getenv.side_effect = lambda key, default="": "development" if key == "ENV" else default
            
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Create a protected enricher
            protected_enricher = MagicMock()
            protected_enricher.enricher_id = "enricher-ffprobe-a1b2c3d4"
            protected_enricher.name = "Protected Video Analysis"
            protected_enricher.type = "ffprobe"
            protected_enricher.scope = "ingest"
            protected_enricher.protected_from_removal = True
            
            mock_db.query.return_value.filter.return_value.first.return_value = protected_enricher
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force"])
            
            # Should succeed in non-production even if protected
            assert result.exit_code == 0
            assert "Successfully removed enricher" in result.stdout

    def test_enricher_remove_audit_logging(self):
        """
        Contract D-6: Removal MUST be logged with enricher details, collection count, and channel count.
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
            
            # TODO: Verify audit logging when implemented

    def test_enricher_remove_verifies_existence(self):
        """
        Contract D-7: The command MUST verify enricher existence before attempting removal.
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
            
            # Verify existence check was performed
            mock_db.query.assert_called()

    def test_enricher_remove_database_error_propagation(self):
        """
        Contract: Database errors MUST be properly propagated to the CLI layer.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.side_effect = Exception("Database connection failed")
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force"])
            
            assert result.exit_code == 1
            assert "Error removing enricher" in result.stderr

    def test_enricher_remove_json_error_propagation(self):
        """
        Contract: Database errors MUST be properly propagated in JSON format.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.side_effect = Exception("Database access denied")
            
            result = self.runner.invoke(app, ["enricher", "remove", "enricher-ffprobe-a1b2c3d4", "--force", "--json"])
            
            assert result.exit_code == 1
            # JSON output should not be produced on error
            try:
                json.loads(result.stdout)
                pytest.fail("JSON should not be produced on error")
            except json.JSONDecodeError:
                pass  # Expected behavior

    def test_enricher_remove_cascade_count_calculation(self):
        """
        Contract: The command MUST calculate and report cascade impact counts accurately.
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
            
            # Should include cascade counts
            assert "collection_attachments_removed" in output_data
            assert "channel_attachments_removed" in output_data
            assert isinstance(output_data["collection_attachments_removed"], int)
            assert isinstance(output_data["channel_attachments_removed"], int)

    def test_enricher_remove_atomic_operation(self):
        """
        Contract: Removal operations MUST be atomic - either all succeed or all fail.
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
            
            # Verify atomic operation
            mock_session.assert_called_once()
            # TODO: Verify commit/rollback when implemented
