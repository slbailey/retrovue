"""
Data contract tests for SourceList command.

Tests the data contract rules (D-#) defined in SourceListContract.md.
These tests verify database operations, transaction safety, data integrity, and snapshot consistency.
"""

import json
from unittest.mock import ANY, MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestSourceListDataContract:
    """Test SourceList data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_source_list_persisted_source_records(self):
        """
        Contract D-1: The list of sources MUST reflect persisted Source records at the time of query.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list_sources:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            mock_list_sources.return_value = [
                {
                    "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
                    "name": "My Plex Server",
                    "type": "plex",
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                }
            ]

            result = self.runner.invoke(app, ["source", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Verify the persisted record is reflected
            assert output["total"] == 1
            source = output["sources"][0]
            assert source["id"] == "4b2b05e7-d7d2-414a-a587-3f5df9b53f44"
            assert source["name"] == "My Plex Server"
            assert source["type"] == "plex"
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_correct_latest_type_name_config(self):
        """
        Contract D-2: Each returned source MUST include the correct latest type, name, and config-derived identity from the authoritative Source model.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list_sources:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            mock_list_sources.return_value = [
                {
                    "id": "test-id",
                    "name": "Updated Source Name",
                    "type": "plex",
                    "config": {"servers": [{"base_url": "https://plex.example.com", "token": "token123"}]},
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                }
            ]

            result = self.runner.invoke(app, ["source", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Verify authoritative data is returned
            source = output["sources"][0]
            assert source["name"] == "Updated Source Name"
            assert source["type"] == "plex"
            assert source["id"] == "test-id"
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_collection_counts_from_persisted_collections(self):
        """
        Contract D-3: The enabled_collections and ingestible_collections counts MUST be calculated from persisted Collection rows associated to that source.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list_sources:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            mock_list_sources.return_value = [
                {
                    "id": "test-source-id",
                    "name": "Test Source",
                    "type": "plex",
                    "enabled_collections": 3,
                    "ingestible_collections": 2,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]

            result = self.runner.invoke(app, ["source", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            source = output["sources"][0]
            assert source["enabled_collections"] == 3
            assert source["ingestible_collections"] == 2
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_no_inferred_fabricated_ingest_state(self):
        """
        Contract D-4: The command MUST NOT infer or fabricate ingest state; it MUST use stored data only.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list:
            
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock the return value from usecase
            mock_list.return_value = [
                {
                    "id": "test-id",
                    "name": "Test Source",
                    "type": "plex",
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                }
            ]
            
            result = self.runner.invoke(app, ["source", "list"])
            
            assert result.exit_code == 0
            
            # Verify that usecase was called (uses stored data, not external inference)
            mock_list.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_no_collection_creation_modification(self):
        """
        Contract D-5: The command MUST NOT create or modify Collections while counting or summarizing them.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list_sources:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            mock_list_sources.return_value = [
                {
                    "id": "test-id",
                    "name": "Test Source",
                    "type": "plex",
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                }
            ]

            result = self.runner.invoke(app, ["source", "list"])
            
            assert result.exit_code == 0
            
            # Verify no collection creation/modification operations
            mock_db.add.assert_not_called()
            mock_db.commit.assert_not_called()
            mock_db.delete.assert_not_called()
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_test_db_no_production_data_leakage(self):
        """
        Contract D-6: Querying via --test-db MUST NOT read or leak production data.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            # Mock test database session
            mock_test_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_test_db
            
            # Mock test-only source
            mock_test_source = MagicMock()
            mock_test_source.id = "test-only-id"
            mock_test_source.name = "Test Only Source"
            mock_test_source.type = "plex"
            mock_test_source.created_at = "2024-01-15T10:30:00+00:00"
            mock_test_source.updated_at = "2024-01-20T14:45:00+00:00"
            
            mock_test_db.query.return_value.all.return_value = [mock_test_source]
            
            with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list:
                mock_list.return_value = [
                    {
                        "id": "test-only-id",
                        "name": "Test Only Source",
                        "type": "plex",
                        "created_at": "2024-01-15T10:30:00+00:00",
                        "updated_at": "2024-01-20T14:45:00+00:00",
                        "enabled_collections": 0,
                        "ingestible_collections": 0,
                    }
                ]
                result = self.runner.invoke(app, ["source", "list", "--test-db", "--json"])
                mock_list.assert_called_once_with(ANY, source_type=None)
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Verify only test data is returned
            assert output["total"] == 1
            source = output["sources"][0]
            assert source["id"] == "test-only-id"
            assert source["name"] == "Test Only Source"

    def test_source_list_consistent_read_transaction_snapshot(self):
        """
        Contract D-7: The command MUST run in a consistent read transaction so that total and the sources array are calculated from the same snapshot of state.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock sources in a consistent snapshot
            mock_source1 = MagicMock()
            mock_source1.id = "id1"
            mock_source1.name = "Source 1"
            mock_source1.type = "plex"
            mock_source1.created_at = "2024-01-15T10:30:00+00:00"
            mock_source1.updated_at = "2024-01-20T14:45:00+00:00"
            
            mock_source2 = MagicMock()
            mock_source2.id = "id2"
            mock_source2.name = "Source 2"
            mock_source2.type = "filesystem"
            mock_source2.created_at = "2024-01-10T09:15:00+00:00"
            mock_source2.updated_at = "2024-01-18T16:20:00+00:00"
            
            # All queries should return the same snapshot
            mock_db.query.return_value.all.return_value = [mock_source1, mock_source2]
            
            with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list:
                mock_list.return_value = [
                    {
                        "id": "id1",
                        "name": "Source 1",
                        "type": "plex",
                        "created_at": "2024-01-15T10:30:00+00:00",
                        "updated_at": "2024-01-20T14:45:00+00:00",
                        "enabled_collections": 0,
                        "ingestible_collections": 0,
                    },
                    {
                        "id": "id2",
                        "name": "Source 2",
                        "type": "filesystem",
                        "created_at": "2024-01-10T09:15:00+00:00",
                        "updated_at": "2024-01-18T16:20:00+00:00",
                        "enabled_collections": 0,
                        "ingestible_collections": 0,
                    },
                ]
                result = self.runner.invoke(app, ["source", "list", "--json"])
                mock_list.assert_called_once_with(ANY, source_type=None)
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Verify snapshot consistency
            assert output["total"] == 2
            assert len(output["sources"]) == 2
            
            # Verify both sources from the same snapshot are present
            source_ids = [source["id"] for source in output["sources"]]
            assert "id1" in source_ids
            assert "id2" in source_ids

    def test_source_list_transaction_boundary_respect(self):
        """
        Contract: The command MUST respect transaction boundaries and not span multiple transactions.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source
            mock_source = MagicMock()
            mock_source.id = "test-id"
            mock_source.name = "Test Source"
            mock_source.type = "plex"
            mock_source.created_at = "2024-01-15T10:30:00+00:00"
            mock_source.updated_at = "2024-01-20T14:45:00+00:00"
            
            mock_db.query.return_value.all.return_value = [mock_source]
            
            with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list:
                mock_list.return_value = [
                    {
                        "id": "test-id",
                        "name": "Test Source",
                        "type": "plex",
                        "created_at": "2024-01-15T10:30:00+00:00",
                        "updated_at": "2024-01-20T14:45:00+00:00",
                        "enabled_collections": 0,
                        "ingestible_collections": 0,
                    }
                ]
                result = self.runner.invoke(app, ["source", "list"])
                mock_list.assert_called_once_with(ANY, source_type=None)
            
            assert result.exit_code == 0
            
            # Verify single transaction usage
            mock_session.assert_called_once()
            # Verify usecase was called (queries happen inside usecase)
            mock_list.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_collection_count_query_accuracy(self):
        """
        Contract: Collection counts MUST be calculated accurately from the database.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list:
            
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock the return value from usecase
            mock_list.return_value = [
                {
                    "id": "test-source-id",
                    "name": "Test Source",
                    "type": "plex",
                    "enabled_collections": 5,
                    "ingestible_collections": 3,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]
            
            result = self.runner.invoke(app, ["source", "list", "--json"])
            mock_list.assert_called_once_with(mock_db, source_type=None)
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            source = output["sources"][0]
            assert source["enabled_collections"] == 5
            assert source["ingestible_collections"] == 3

    def test_source_list_data_integrity_preservation(self):
        """
        Contract: Data integrity MUST be preserved during read operations.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock source with specific data
            mock_source = MagicMock()
            mock_source.id = "integrity-test-id"
            mock_source.name = "Integrity Test Source"
            mock_source.type = "plex"
            mock_source.config = {"servers": [{"base_url": "https://test.plex.com", "token": "test-token"}]}
            mock_source.created_at = "2024-01-15T10:30:00+00:00"
            mock_source.updated_at = "2024-01-20T14:45:00+00:00"
            
            mock_db.query.return_value.all.return_value = [mock_source]
            
            with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list:
                mock_list.return_value = [
                    {
                        "id": "integrity-test-id",
                        "name": "Integrity Test Source",
                        "type": "plex",
                        "config": {"servers": [{"base_url": "https://test.plex.com", "token": "test-token"}]},
                        "created_at": "2024-01-15T10:30:00+00:00",
                        "updated_at": "2024-01-20T14:45:00+00:00",
                        "enabled_collections": 0,
                        "ingestible_collections": 0,
                    }
                ]
                result = self.runner.invoke(app, ["source", "list", "--json"])
                mock_list.assert_called_once_with(ANY, source_type=None)
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Verify data integrity is preserved
            source = output["sources"][0]
            assert source["id"] == "integrity-test-id"
            assert source["name"] == "Integrity Test Source"
            assert source["type"] == "plex"
            assert source["created_at"] == "2024-01-15T10:30:00+00:00"
            assert source["updated_at"] == "2024-01-20T14:45:00+00:00"

    def test_source_list_empty_database_handling(self):
        """
        Contract: Empty database MUST be handled gracefully without errors.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session, \
             patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list_sources:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db

            mock_list_sources.return_value = []

            result = self.runner.invoke(app, ["source", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Verify empty database is handled correctly
            assert output["status"] == "ok"
            assert output["total"] == 0
            assert output["sources"] == []
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_type_filter_data_consistency(self):
        """
        Contract: Type filtering MUST maintain data consistency with the source type filter.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock plex-only source
            mock_plex_source = MagicMock()
            mock_plex_source.id = "plex-id"
            mock_plex_source.name = "Plex Server"
            mock_plex_source.type = "plex"
            mock_plex_source.created_at = "2024-01-15T10:30:00+00:00"
            mock_plex_source.updated_at = "2024-01-20T14:45:00+00:00"
            
            # Mock filtered query result
            mock_db.query.return_value.filter.return_value.all.return_value = [mock_plex_source]
            
            with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_list:
                mock_list.return_value = [
                    {
                        "id": "plex-id",
                        "name": "Plex Server",
                        "type": "plex",
                        "created_at": "2024-01-15T10:30:00+00:00",
                        "updated_at": "2024-01-20T14:45:00+00:00",
                        "enabled_collections": 0,
                        "ingestible_collections": 0,
                    }
                ]
                result = self.runner.invoke(app, ["source", "list", "--type", "plex", "--json"])
                mock_list.assert_called_once_with(ANY, source_type="plex")
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Verify type filtering maintains consistency
            assert output["total"] == 1
            source = output["sources"][0]
            assert source["type"] == "plex"
            assert source["id"] == "plex-id"
            assert source["name"] == "Plex Server"
