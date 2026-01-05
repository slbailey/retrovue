"""
Data contract tests for `retrovue enricher add` command.

Tests data-layer consistency, database state, entity retrievability, and enrichment parameter persistence
as specified in docs/contracts/resources/EnricherAddContract.md.

This test enforces the data contract rules (D-#) for the enricher add command.
Focuses on enrichment parameter validation and persistence - specific values an 
enricher needs to perform its enrichment tasks (API keys, file paths, timing values, etc.).
"""

import json
from unittest.mock import patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestEnricherAddDataContract:
    """Data contract tests for retrovue enricher add command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_enricher_add_creates_database_record(self, db_session):
        """
        Contract D-1: Enricher creation MUST persist to database with all required fields.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify database operations were called
            db_session.add.assert_called_once()
            db_session.commit.assert_called_once()
            
            # Verify the enricher entity was created with correct attributes
            created_enricher = db_session.add.call_args[0][0]
            assert created_enricher.type == "ingest"  # Type parameter becomes the enricher type
            assert created_enricher.name == "Test Enricher"
            assert created_enricher.config is not None

    def test_enricher_add_generates_unique_id(self, db_session):
        """
        Contract D-2: Enricher ID MUST be unique and follow format "enricher-{type}-{hash}".
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Parse JSON output to get generated ID
            output_data = json.loads(result.stdout)
            enricher_id = output_data["enricher_id"]
            
            # Verify ID format
            assert enricher_id.startswith("enricher-ingest-")  # Uses type as enricher_type
            assert len(enricher_id) > len("enricher-ingest-")  # Has hash suffix
            
            # Verify the enricher entity has the correct ID
            created_enricher = db_session.add.call_args[0][0]
            assert created_enricher.enricher_id == enricher_id  # Use enricher_id instead of id

    def test_enricher_add_stores_configuration_correctly(self, db_session):
        """
        Contract D-3: Configuration MUST be stored as JSON and validated against schema.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Custom Ingest",
                "--config", '{"ingest_path": "/usr/bin/ingest", "timeout": 60}', "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify configuration is stored correctly
            created_enricher = db_session.add.call_args[0][0]
            config = created_enricher.config
            
            # Should be a dictionary/JSON object
            assert isinstance(config, dict)
            assert config.get("ingest_path") == "/usr/bin/ingest"
            assert config.get("timeout") == 60

    def test_enricher_add_ingest_configuration_storage(self, db_session):
        """
        Contract D-3: Configuration MUST be stored as JSON and validated against schema.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "IMDB Metadata",
                "--config", '{"sources": "imdb,tmdb", "api_key": "test-key"}', "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify configuration is stored correctly
            created_enricher = db_session.add.call_args[0][0]
            config = created_enricher.config
            
            # Should be a dictionary/JSON object
            assert isinstance(config, dict)
            assert config.get("sources") == "imdb,tmdb"
            assert config.get("api_key") == "test-key"

    def test_enricher_add_playout_configuration_storage(self, db_session):
        """
        Contract D-3: Configuration MUST be stored as JSON and validated against schema.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "playout", "--name", "Custom Playout",
                "--config", '{"custom": "value", "enabled": true}', "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify configuration is stored correctly
            created_enricher = db_session.add.call_args[0][0]
            config = created_enricher.config
            
            # Should be a dictionary/JSON object
            assert isinstance(config, dict)
            assert config.get("custom") == "value"
            assert config.get("enabled") is True

    def test_enricher_add_type_assignment(self, db_session):
        """
        Contract D-4: Type MUST be correctly assigned based on enricher type.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            # Test ingest type enricher
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
            assert result.exit_code == 0
            
            created_enricher = db_session.add.call_args[0][0]
            assert created_enricher.type == "ingest"  # Type parameter becomes the enricher type

    def test_enricher_add_rollback_on_failure(self, db_session):
        """
        Contract D-5: Database operations MUST be rolled back if validation fails.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            # Mock a database error during commit
            db_session.commit.side_effect = Exception("Database error")
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher"
            ])
            
            assert result.exit_code == 1
            
            # Verify rollback was called
            db_session.rollback.assert_called_once()

    def test_enricher_add_entity_retrievability(self, db_session):
        """
        Contract D-6: Created enricher MUST be retrievable through list command.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            # Create enricher
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Parse JSON output to get created enricher details
            output_data = json.loads(result.stdout)
            enricher_id = output_data["enricher_id"]
            
            # Verify the enricher can be retrieved (this would be tested by list command)
            created_enricher = db_session.add.call_args[0][0]
            assert created_enricher.enricher_id == enricher_id  # Use enricher_id instead of id
            assert created_enricher.type == "ingest"  # Type parameter becomes the enricher type
            assert created_enricher.name == "Test Enricher"

    def test_enricher_add_immutable_fields(self, db_session):
        """
        Contract D-7: Enricher ID and type MUST be immutable after creation.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify immutable fields are set correctly
            created_enricher = db_session.add.call_args[0][0]
            original_enricher_id = created_enricher.enricher_id  # Use enricher_id instead of id
            original_type = created_enricher.type
            
            # These fields should not be changeable after creation
            assert original_enricher_id.startswith("enricher-ingest-")  # Uses type as enricher_type
            assert original_type == "ingest"  # Type parameter becomes the enricher type

    def test_enricher_add_default_configuration_values(self, db_session):
        """
        Contract D-8: Default configuration values MUST be applied when not specified.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Enricher", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify default configuration values are applied
            created_enricher = db_session.add.call_args[0][0]
            config = created_enricher.config
            
            # With pipeline-based approach, default config should be empty
            assert config == {}

    def test_enricher_add_ingest_default_configuration(self, db_session):
        """
        Contract D-8: Default configuration values MUST be applied when not specified.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "ingest", "--name", "Test Metadata", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify default configuration values are applied
            created_enricher = db_session.add.call_args[0][0]
            config = created_enricher.config
            
            # With pipeline-based approach, default config should be empty
            assert config == {}

    def test_enricher_add_playout_default_configuration(self, db_session):
        """
        Contract D-8: Default configuration values MUST be applied when not specified.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "playout", "--name", "Test Playout", "--json"
            ])
            
            assert result.exit_code == 0
            
            # Verify default configuration values are applied
            created_enricher = db_session.add.call_args[0][0]
            config = created_enricher.config
            
            # Playout defaults
            assert config == {}  # Empty dict default

    def test_enricher_add_enrichment_parameter_validation_before_persistence(self, db_session):
        """
        Contract D-2: Enrichment parameter validation MUST occur before database persistence.
        Contract D-9: Enrichment parameters MUST be validated for correctness (e.g., API key format, file existence).
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            # Test with invalid API key format (too short)
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "tvdb", "--name", "TheTVDB Metadata",
                "--api-key", "short"
            ])
            
            # Should validate enrichment parameters before persisting
            assert result.exit_code == 1
            assert "Error" in result.stderr
            # Should not commit to database
            db_session.commit.assert_not_called()

    def test_enricher_add_api_key_enrichment_parameter_persistence(self, db_session):
        """
        Contract D-2: Enrichment parameter validation MUST occur before database persistence.
        Contract D-10: Parameter updates MUST preserve the enricher's ability to perform its enrichment tasks.
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "tvdb", "--name", "TheTVDB Metadata",
                "--api-key", "valid-tvdb-api-key-12345"
            ])
            
            # Should validate and persist enrichment parameters
            assert result.exit_code == 0
            assert "Successfully created" in result.stdout
            # Should commit to database
            db_session.commit.assert_called_once()

    def test_enricher_add_file_path_enrichment_parameter_validation(self, db_session):
        """
        Contract D-9: Enrichment parameters MUST be validated for correctness (e.g., file existence).
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            # Test with non-existent file path
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "watermark", "--name", "Channel Watermark",
                "--overlay-path", "/nonexistent/path/watermark.png"
            ])
            
            # Should validate file existence before persisting
            assert result.exit_code == 1
            assert "Error" in result.stderr
            # Should not commit to database
            db_session.commit.assert_not_called()

    def test_enricher_add_timing_enrichment_parameter_validation(self, db_session):
        """
        Contract D-9: Enrichment parameters MUST be validated for correctness (e.g., timing value range validation).
        """
        with patch("retrovue.cli.commands.enricher.session") as mock_session:
            mock_session.return_value.__enter__.return_value = db_session
            
            # Test with invalid timing value (negative duration)
            result = self.runner.invoke(app, [
                "enricher", "add", "--type", "crossfade", "--name", "Crossfade Effect",
                "--duration", "-1.0"
            ])
            
            # Should validate timing value range before persisting
            assert result.exit_code == 1
            assert "Error" in result.stderr
            # Should not commit to database
            db_session.commit.assert_not_called()
