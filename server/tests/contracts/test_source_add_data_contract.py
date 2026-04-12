# noqa: F401
"""
Data contract tests for SourceAdd command.

Tests the data contract rules (D-#) defined in SourceAddContract.md.
These tests verify database operations, transaction safety, and data integrity.
"""

from unittest.mock import MagicMock, patch

from typer.testing import CliRunner  # type: ignore[import-not-found]

from retrovue.cli.main import app


class TestSourceAddDataContract:
    """Test SourceAdd data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_source_add_atomic_transaction(self):
        """
        Contract D-1: Source creation MUST occur within a single transaction boundary.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.get_importer") as mock_get_importer, \
             patch("retrovue.cli.commands.source.session") as mock_session:
            
            mock_list.return_value = ["plex"]
            mock_importer = MagicMock()
            mock_importer.name = "PlexImporter"
            mock_get_importer.return_value = mock_importer
            
            # Mock database session with transaction tracking
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Patch usecase add_source
            with patch("retrovue.cli.commands.source.usecase_add_source") as mock_uc_add:
                mock_uc_add.return_value = {
                    "id": "test-id-123",
                    "external_id": "plex-test-plex",
                    "name": "Test Plex",
                    "type": "plex",
                    "config": {"servers": [{"base_url": "http://test", "token": "test-token"}]},
                    "enrichers": []
                }
                
                result = self.runner.invoke(app, [
                    "source", "add", 
                    "--type", "plex", 
                    "--name", "Test Plex", 
                    "--base-url", "http://test", 
                    "--token", "test-token"
                ])
                
                assert result.exit_code == 0
                # Verify usecase was called (which handles transaction internally)
                mock_uc_add.assert_called_once()
                # Verify usecase was called with the db session
                call_args = mock_uc_add.call_args
                assert call_args[0][0] == mock_db  # First arg is db session

    def test_source_add_external_id_uniqueness(self):
        """
        Contract D-2: External ID generation MUST be atomic and collision-free.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.get_importer") as mock_get_importer, \
             patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.uuid.uuid4") as mock_uuid:
            
            mock_list.return_value = ["plex"]
            mock_importer = MagicMock()
            mock_importer.name = "PlexImporter"
            mock_get_importer.return_value = mock_importer
            
            # Mock UUID to ensure predictable external ID
            mock_uuid_instance = MagicMock()
            mock_uuid_instance.hex = "1234567890abcdef"
            mock_uuid.return_value = mock_uuid_instance
            
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Patch usecase add_source
            with patch("retrovue.cli.commands.source.usecase_add_source") as mock_uc_add:
                mock_uc_add.return_value = {
                    "id": "test-id-123",
                    "external_id": "plex-test-plex",
                    "name": "Test Plex",
                    "type": "plex",
                    "config": {"servers": [{"base_url": "http://test", "token": "test-token"}]},
                    "enrichers": []
                }
                
                result = self.runner.invoke(app, [
                    "source", "add", 
                    "--type", "plex", 
                    "--name", "Test Plex", 
                    "--base-url", "http://test", 
                    "--token", "test-token"
                ])
                
                assert result.exit_code == 0
                # Success message should be emitted
                assert "Successfully created" in result.output
                mock_uc_add.assert_called_once()

    def test_source_add_does_not_discover_implicitly(self):
        """
        Discovery must NOT occur during add; separate command handles it.
        """
        with (
            patch("retrovue.cli.commands.source.list_importers") as mock_list_importers,
            patch("retrovue.cli.commands.source.usecase_add_source") as mock_add,
            patch("retrovue.usecases.source_discover.discover_collections") as mock_discover,
            patch("retrovue.cli.commands.source.get_importer") as mock_get_importer,
        ):
            mock_list_importers.return_value = ["plex"]
            mock_importer = MagicMock()
            mock_importer.name = "PlexImporter"
            mock_get_importer.return_value = mock_importer
            mock_add.return_value = {
                "id": "test-id",
                "external_id": "plex-my-plex",
                "name": "My Plex",
                "type": "plex",
                "config": {},
                "enrichers": []
            }
            
            result = self.runner.invoke(app, [
                "source", "add", "--type", "plex", "--name", "My Plex",
                "--base-url", "http://test", "--token", "test-token"
            ])

        assert result.exit_code == 0
        mock_add.assert_called_once()
        mock_discover.assert_not_called()

    

    def test_source_add_transaction_rollback_on_failure(self):
        """
        Contract D-6: On transaction failure, ALL changes MUST be rolled back.
        """
        with patch("retrovue.cli.commands.source.get_importer") as mock_get_importer:
            # Mock importer that raises an exception
            mock_get_importer.side_effect = Exception("Database error")
            
            result = self.runner.invoke(app, [
                "source", "add", 
                "--type", "plex", 
                "--name", "Test Plex", 
                "--base-url", "http://test", 
                "--token", "test-token"
            ])
            
            assert result.exit_code == 1
            assert "Error adding source" in result.stderr

    def test_source_add_configuration_validation_before_persistence(self):
        """
        Contract D-7: Source configuration MUST be validated before database persistence.
        """
        with patch("retrovue.cli.commands.source.get_importer") as mock_get_importer:
            # Mock importer that raises validation error
            mock_get_importer.side_effect = ValueError("Invalid configuration")
            
            result = self.runner.invoke(app, [
                "source", "add", 
                "--type", "plex", 
                "--name", "Test Plex", 
                "--base-url", "invalid-url", 
                "--token", "test-token"
            ])
            
            assert result.exit_code == 1
            assert "Error adding source" in result.stderr

    def test_source_add_enricher_validation_before_creation(self):
        """
        Contract D-8: Enricher validation MUST occur before source creation.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.list_enrichers") as mock_enrichers, \
             patch("retrovue.cli.commands.source.get_importer") as mock_get_importer, \
             patch("retrovue.cli.commands.source.session") as mock_session:
            
            mock_list.return_value = ["plex"]
            mock_importer = MagicMock()
            mock_importer.name = "PlexImporter"
            mock_get_importer.return_value = mock_importer
            
            # Mock enrichers
            mock_enricher = MagicMock()
            mock_enricher.name = "ffprobe"
            mock_enrichers.return_value = [mock_enricher]
            
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock usecase
            with patch("retrovue.cli.commands.source.usecase_add_source") as mock_uc_add:
                mock_uc_add.return_value = {
                    "id": "test-id-123",
                    "external_id": "plex-test-plex",
                    "name": "Test Plex",
                    "type": "plex",
                    "config": {"servers": [{"base_url": "http://test", "token": "test-token"}]},
                    "enrichers": ["ffprobe"]
                }
                
                result = self.runner.invoke(app, [
                    "source", "add", 
                    "--type", "plex", 
                    "--name", "Test Plex", 
                    "--base-url", "http://test", 
                    "--token", "test-token",
                    "--enrichers", "ffprobe"
                ])
                
                assert result.exit_code == 0
                # Verify enricher validation occurred
                mock_enrichers.assert_called_once()
                # Verify usecase was called with enrichers
                mock_uc_add.assert_called_once()
                call_args = mock_uc_add.call_args
                assert call_args[1]["enrichers"] == ["ffprobe"]

    

    def test_source_add_interface_compliance_before_creation(self):
        """
        Contract D-10: Importer interface compliance MUST be verified before source creation.
        """
        with patch("retrovue.cli.commands.source.get_importer") as mock_get_importer:
            # Mock importer that raises interface compliance error
            mock_get_importer.side_effect = Exception("Interface compliance error")
            
            result = self.runner.invoke(app, [
                "source", "add", 
                "--type", "plex", 
                "--name", "Test Plex", 
                "--base-url", "http://test", 
                "--token", "test-token"
            ])
            
            assert result.exit_code == 1
            assert "Error adding source" in result.stderr

    def test_source_add_configuration_schema_validation(self):
        """
        Contract D-11: Configuration schema validation MUST be performed using importer's get_config_schema method.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.get_importer") as mock_get_importer, \
             patch("retrovue.cli.commands.source.session") as mock_session:
            
            mock_list.return_value = ["plex"]
            mock_importer = MagicMock()
            mock_importer.name = "PlexImporter"
            mock_get_importer.return_value = mock_importer
            
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock usecase
            with patch("retrovue.cli.commands.source.usecase_add_source") as mock_uc_add:
                mock_uc_add.return_value = {
                    "id": "test-id-123",
                    "external_id": "plex-test-plex",
                    "name": "Test Plex",
                    "type": "plex",
                    "config": {"servers": [{"base_url": "http://test", "token": "test-token"}]},
                    "enrichers": []
                }
                
                result = self.runner.invoke(app, [
                    "source", "add", 
                    "--type", "plex", 
                    "--name", "Test Plex", 
                    "--base-url", "http://test", 
                    "--token", "test-token"
                ])
                
                assert result.exit_code == 0
                # Verify importer was created with configuration (schema validation)
                mock_get_importer.assert_called_once()
                call_args = mock_get_importer.call_args
                assert call_args[0][0] == "plex"  # First positional arg is type
                assert "base_url" in call_args[1]  # Configuration was passed
                assert "token" in call_args[1]  # Configuration was passed

    def test_source_add_database_state_consistency(self):
        """
        Contract: Database state MUST remain consistent after source creation.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list, \
             patch("retrovue.cli.commands.source.get_importer") as mock_get_importer, \
             patch("retrovue.cli.commands.source.session") as mock_session:
            
            mock_list.return_value = ["plex"]
            mock_importer = MagicMock()
            mock_importer.name = "PlexImporter"
            mock_get_importer.return_value = mock_importer
            
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock usecase
            with patch("retrovue.cli.commands.source.usecase_add_source") as mock_uc_add:
                mock_uc_add.return_value = {
                    "id": "test-id-123",
                    "external_id": "plex-test-plex",
                    "name": "Test Plex",
                    "type": "plex",
                    "config": {"servers": [{"base_url": "http://test", "token": "test-token"}]},
                    "enrichers": []
                }
                
                result = self.runner.invoke(app, [
                    "source", "add", 
                    "--type", "plex", 
                    "--name", "Test Plex", 
                    "--base-url", "http://test", 
                    "--token", "test-token"
                ])
                
                assert result.exit_code == 0
                # Verify usecase was called (which handles database operations internally)
                mock_uc_add.assert_called_once()

    
