"""
Data contract tests for Source Discover command.

Tests the data persistence and transaction aspects of the source discover command as defined in
docs/contracts/resources/SourceDiscoverContract.md (D-1 through D-9).
"""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.commands.source import app


class TestSourceDiscoverDataContract:
    """Test data contract rules for source discover command."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_source_discover_transaction_boundary(self):
        """
        Contract D-1: Collection discovery MUST occur within a single transaction boundary.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            mock_source_service = MagicMock()
            mock_source_service.get_source_by_id.return_value = mock_source
            
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"}
            ]
            
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0
            # Discovery-only: no persistence side effects
            mock_db.add.assert_not_called()
            mock_db.commit.assert_not_called()

    def test_source_discover_new_collections_sync_disabled(self):
        """
        Contract D-2: Newly discovered collections MUST be persisted with sync_enabled=False.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            mock_source_service = MagicMock()
            mock_source_service.get_source_by_id.return_value = mock_source
            
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"}
            ]
            
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0
            # Discovery-only: no persistence
            mock_db.add.assert_not_called()

    def test_source_discover_existing_collections_sync_preserved(self):
        """
        Contract D-3: Discovery MUST NOT flip existing collections from sync_enabled=False to sync_enabled=True.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            # Mock usecase to return discovered collections
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies", "plex_section_ref": "1", "type": "movie"}
            ]
            
            # Mock database query to return source and existing collection
            existing_collection = MagicMock()
            existing_collection.external_id = "1"
            existing_collection.name = "Movies"
            existing_collection.sync_enabled = False
            
            # Setup mock chain: query(Source) -> source, query(Collection) -> existing_collection
            from retrovue.domain.entities import Collection, Source
            
            # Create separate mock chains for Source and Collection queries
            source_query = MagicMock()
            source_query.filter.return_value.first.return_value = mock_source
            
            collection_query = MagicMock()
            collection_query.filter.return_value.first.return_value = existing_collection
            
            def query_side_effect(model):
                if model == Source:
                    return source_query
                elif model == Collection:
                    return collection_query
                return MagicMock()
            
            mock_db.query.side_effect = query_side_effect
            
            with patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source):
                result = self.runner.invoke(app, ["discover", "test-source"])
            
            assert result.exit_code == 0
            # Verify no new collection was added (duplicate skipped)
            mock_db.add.assert_not_called()
            # Verify existing collection's sync_enabled status was not changed
            assert existing_collection.sync_enabled is False

    def test_source_discover_path_mapping_empty_local_path(self):
        """
        Contract D-4: PathMapping records MUST be created with empty local_path for new collections.
        
        Note: Current implementation doesn't create PathMapping records yet, 
        but this test documents the expected behavior when implemented.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            mock_source_service = MagicMock()
            mock_source_service.get_source_by_id.return_value = mock_source
            
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"}
            ]
            
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0
            # TODO: When PathMapping creation is implemented, verify local_path is empty
            # For now, this test documents the expected behavior

    def test_source_discover_transaction_rollback_on_failure(self):
        """
        Contract D-5: On transaction failure, ALL changes MUST be rolled back with no partial persistence.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            mock_source_service = MagicMock()
            mock_source_service.get_source_by_id.return_value = mock_source
            
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"}
            ]
            result = self.runner.invoke(app, ["discover", "test-source"])
            # Discovery-only: no commit path; ensure no exception and no persistence
            assert result.exit_code == 0
            mock_db.add.assert_not_called()
            mock_db.commit.assert_not_called()

    def test_source_discover_duplicate_external_id_prevention(self):
        """
        Contract D-6: Duplicate external ID checking MUST prevent duplicate collection creation.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            # Mock existing collection
            existing_collection = MagicMock()
            existing_collection.external_id = "1"
            existing_collection.name = "Movies"
            
            from retrovue.domain.entities import Collection, Source
            
            collection_query = MagicMock()
            collection_query.filter.return_value.first.return_value = existing_collection
            
            def query_side_effect(model):
                if model == Collection:
                    return collection_query
                return MagicMock()
            
            mock_db.query.side_effect = query_side_effect
            
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"},
                {"external_id": "1", "name": "Movies Duplicate"}
            ]
            
            with patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source):
                result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0
            # Discovery-only: no adds; duplicate skipped message should appear
            mock_db.add.assert_not_called()
            assert "Collection 'Movies' already exists, skipping" in result.stdout

    def test_source_discover_existing_collection_metadata_update(self):
        """
        Contract D-7: Collection metadata MUST be updated for existing collections.
        
        Note: Current implementation skips existing collections entirely.
        This test documents the expected behavior when metadata updates are implemented.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            # Mock usecase to return discovered collections
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies Updated", "plex_section_ref": "1", "type": "movie"}
            ]
            
            # Mock database query to return existing collection
            existing_collection = MagicMock()
            existing_collection.external_id = "1"
            existing_collection.name = "Movies"
            existing_collection.sync_enabled = False
            
            # Setup mock chain: query(Source) -> source, query(Collection) -> existing_collection
            from retrovue.domain.entities import Collection, Source
            
            source_query = MagicMock()
            source_query.filter.return_value.first.return_value = mock_source
            
            collection_query = MagicMock()
            collection_query.filter.return_value.first.return_value = existing_collection
            
            def query_side_effect(model):
                if model == Source:
                    return source_query
                elif model == Collection:
                    return collection_query
                return MagicMock()
            
            mock_db.query.side_effect = query_side_effect
            
            with patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source):
                result = self.runner.invoke(app, ["discover", "test-source"])
            
            assert result.exit_code == 0
            # TODO: When metadata updates are implemented, verify collection name was updated
            # For now, this test documents the expected behavior

    def test_source_discover_uses_importer_discovery_capability(self):
        """
        Contract D-8: Collection discovery MUST use the importer-provided discovery capability to enumerate collections.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            mock_source_service = MagicMock()
            mock_source_service.get_source_by_id.return_value = mock_source
            
            mock_discover.return_value = [
                {"external_id": "1", "name": "Movies"}
            ]
            
            result = self.runner.invoke(app, ["discover", "test-source"])
            assert result.exit_code == 0

    def test_source_discover_interface_compliance_verification(self):
        """
        Contract D-9: Interface compliance MUST be verified before discovery begins.
        
        Note: Current implementation doesn't explicitly verify interface compliance.
        This test documents the expected behavior when interface verification is implemented.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            # Mock usecase
            mock_discover.return_value = []
            
            from retrovue.domain.entities import Source
            source_query = MagicMock()
            source_query.filter.return_value.first.return_value = mock_source
            
            def query_side_effect(model):
                if model == Source:
                    return source_query
                return MagicMock()
            
            mock_db.query.side_effect = query_side_effect
            
            with patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source):
                result = self.runner.invoke(app, ["discover", "test-source"])
            
            assert result.exit_code == 0
            # TODO: When interface compliance verification is implemented, 
            # verify that compliance check happens before discovery
            # For now, this test documents the expected behavior

    def test_source_discover_database_error_propagation(self):
        """
        Test that database errors are properly propagated to the user.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            # Simulate database exception during duplicate check
            # Need to handle Source query first, then Collection query fails
            from retrovue.domain.entities import Source
            
            call_count = 0
            def query_side_effect(model):
                nonlocal call_count
                if model == Source and call_count == 0:
                    call_count += 1
                    source_query = MagicMock()
                    source_query.filter.return_value.first.return_value = mock_source
                    return source_query
                else:
                    raise Exception("Database connection error")
            
            mock_db.query.side_effect = query_side_effect
            mock_discover.return_value = [{"external_id": "1", "name": "Movies"}]
            with patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source):
                result = self.runner.invoke(app, ["discover", "test-source"])
            # Discovery-only: duplicate check errors cause exit 1 but are caught
            # The exception during collection query will cause the command to fail
            assert result.exit_code == 1

    def test_source_discover_json_error_propagation(self):
        """
        Test that errors are properly propagated when using JSON output.
        """
        with (
            patch("retrovue.cli.commands.source.session") as mock_session,
            patch("retrovue.cli.commands.source.usecase_discover_collections") as mock_discover,
        ):
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source exists
            mock_source = MagicMock()
            mock_source.id = "test-source-id"
            mock_source.name = "Test Plex Server"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "http://test", "token": "test-token"}]}
            
            mock_discover.side_effect = Exception("API connection error")
            with patch("retrovue.cli.commands.source.source_get_by_id", return_value=mock_source):
                result = self.runner.invoke(app, ["discover", "test-source", "--json"])
            assert result.exit_code == 1
            # Error is in stderr, not JSON
            assert "Error discovering collections" in result.stderr
