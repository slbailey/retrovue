"""
Contract tests for SourceList command.

Tests the behavioral contract rules (B-#) defined in SourceListContract.md.
These tests verify CLI behavior, filtering, output formats, and read-only operation guarantees.
"""

import json
from unittest.mock import ANY, MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestSourceListContract:
    """Test SourceList contract behavioral rules (B-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    def test_source_list_help_flag_exits_zero(self):
        """
        Contract: Help flag MUST exit with code 0.
        """
        result = self.runner.invoke(app, ["source", "list", "--help"])
        assert result.exit_code == 0
        assert "List all configured sources" in result.stdout

    def test_source_list_successful_execution_exits_zero(self):
        """
        Contract B-1: The command MUST return all known sources unless filtered.
        """
        with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_source_list:
            mock_source_list.return_value = [
                {
                    "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
                    "name": "My Plex Server",
                    "type": "plex",
                    "enabled_collections": 2,
                    "ingestible_collections": 1,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                },
                {
                    "id": "8c3d12f4-e9a1-4b2c-d6e7-1f8a9b0c2d3e",
                    "name": "Local Media Library",
                    "type": "filesystem",
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                    "created_at": "2024-01-10T09:15:00+00:00",
                    "updated_at": "2024-01-18T16:20:00+00:00",
                },
            ]

            result = self.runner.invoke(app, ["source", "list"])

            assert result.exit_code == 0
            assert "My Plex Server" in result.stdout
            assert "Local Media Library" in result.stdout
            assert "Total: 2 sources configured" in result.stdout
            mock_source_list.assert_called_once_with(ANY, source_type=None)

    def test_source_list_type_filter_valid_type(self):
        """
        Contract B-2: --type MUST restrict results to sources whose type exactly matches a known importer type.
        """
        with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_source_list:
            mock_source_list.return_value = [
                {
                    "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
                    "name": "My Plex Server",
                    "type": "plex",
                    "enabled_collections": 2,
                    "ingestible_collections": 1,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]

            result = self.runner.invoke(app, ["source", "list", "--type", "plex"])

            assert result.exit_code == 0
            assert "My Plex Server" in result.stdout
            assert "plex" in result.stdout
            assert "Total: 1 plex source configured" in result.stdout
            mock_source_list.assert_called_once_with(ANY, source_type="plex")

    def test_source_list_type_filter_invalid_type_exits_one(self):
        """
        Contract B-3: --type with an unknown type MUST produce no data changes and MUST exit 1 with an error message.
        """
        with patch("retrovue.cli.commands.source.list_importers") as mock_list_importers:
            mock_list_importers.return_value = ["plex", "filesystem"]
            
            result = self.runner.invoke(app, ["source", "list", "--type", "unknown"])
            
            assert result.exit_code == 1
            assert "Unknown source type 'unknown'" in result.stderr
            assert "Available types: plex, filesystem" in result.stderr

    def test_source_list_json_output_format(self):
        """
        Contract B-4: --json MUST return valid JSON output with the required fields (status, total, sources).
        """
        with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_source_list:
            mock_source_list.return_value = [
                {
                    "id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
                    "name": "My Plex Server",
                    "type": "plex",
                    "enabled_collections": 2,
                    "ingestible_collections": 1,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]

            result = self.runner.invoke(app, ["source", "list", "--json"])

            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            # Check required top-level fields
            assert "status" in output
            assert "total" in output
            assert "sources" in output
            
            assert output["status"] == "ok"
            assert output["total"] == 1
            assert len(output["sources"]) == 1
            
            # Check source object fields
            source = output["sources"][0]
            assert "id" in source
            assert "name" in source
            assert "type" in source
            assert "enabled_collections" in source
            assert "ingestible_collections" in source
            assert "created_at" in source
            assert "updated_at" in source
            mock_source_list.assert_called_once_with(ANY, source_type=None)

    def test_source_list_deterministic_ordering(self):
        """
        Contract B-5: The output MUST be deterministic. Results MUST be sorted by source name ascending (case-insensitive).
        """
        # Mock the source_list function to return unsorted data
        mock_sources_data = [
            {
                "id": "1",
                "name": "Zebra Server",
                "type": "plex",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-20T14:45:00Z",
                "enabled_collections": 0,
                "ingestible_collections": 0
            },
            {
                "id": "2", 
                "name": "apple server",
                "type": "filesystem",
                "created_at": "2024-01-10T09:15:00Z",
                "updated_at": "2024-01-18T16:20:00Z",
                "enabled_collections": 0,
                "ingestible_collections": 0
            },
            {
                "id": "3",
                "name": "Apple Server",  # Same name as source2, different case
                "type": "plex", 
                "created_at": "2024-01-12T11:20:00Z",
                "updated_at": "2024-01-19T13:30:00Z",
                "enabled_collections": 0,
                "ingestible_collections": 0
            }
        ]
        
        with patch("retrovue.cli.commands.source.usecase_list_sources", return_value=mock_sources_data):
            result = self.runner.invoke(app, ["source", "list"])
            
            assert result.exit_code == 0
            
            # Check that sources appear in alphabetical order by name
            output_lines = result.stdout.split('\n')
            source_lines = [line for line in output_lines if 'Name:' in line]
            
            assert len(source_lines) == 3
            assert "apple server" in source_lines[0]
            assert "Apple Server" in source_lines[1]
            assert "Zebra Server" in source_lines[2]

    def test_source_list_no_results_human_readable(self):
        """
        Contract B-6: When there are no results, output MUST still be structurally valid (empty table in human mode).
        """
        # Mock empty results
        with patch("retrovue.cli.commands.source.usecase_list_sources", return_value=[]):
            result = self.runner.invoke(app, ["source", "list"])
            
            assert result.exit_code == 0
            assert "No sources configured" in result.stdout

    def test_source_list_no_results_json(self):
        """
        Contract B-6: When there are no results, output MUST still be structurally valid (empty list in JSON mode).
        """
        with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_source_list:
            mock_source_list.return_value = []

            result = self.runner.invoke(app, ["source", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            assert output["status"] == "ok"
            assert output["total"] == 0
            assert output["sources"] == []
            mock_source_list.assert_called_once_with(ANY, source_type=None)

    def test_source_list_read_only_operation(self):
        """
        Contract B-7: The command MUST be read-only and MUST NOT mutate database state, importer registry state, or collection ingest state.
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
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]

            result = self.runner.invoke(app, ["source", "list"])

            assert result.exit_code == 0

            # Verify usecase was called (read-only operation)
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)
            # Verify no mutations occurred (usecase handles queries internally)
            mock_db.add.assert_not_called()
            mock_db.commit.assert_not_called()
            mock_db.delete.assert_not_called()

    def test_source_list_test_db_mode(self):
        """
        Contract B-8: --test-db MUST query the test DB session instead of production.
        Contract B-9: --test-db MUST keep response shape and exit code behavior identical to production mode.
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
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]

            result = self.runner.invoke(app, ["source", "list", "--test-db"])

            assert result.exit_code == 0
            assert "Test Source" in result.stdout
            assert "Total: 1 source configured" in result.stdout
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_test_db_json_mode(self):
        """
        Contract B-9: --test-db MUST keep response shape and exit code behavior identical to production mode.
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
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]

            result = self.runner.invoke(app, ["source", "list", "--test-db", "--json"])

            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            assert output["status"] == "ok"
            assert output["total"] == 1
            assert len(output["sources"]) == 1
            assert output["sources"][0]["name"] == "Test Source"
            mock_list_sources.assert_called_once_with(mock_db, source_type=None)

    def test_source_list_no_external_system_calls(self):
        """
        Contract B-10: The command MUST NOT call external systems (importers, Plex APIs, filesystem scans, etc.). It is metadata-only.
        """
        with patch("retrovue.cli.commands.source.usecase_list_sources") as mock_source_list, \
             patch("retrovue.cli.commands.source.get_importer") as mock_get_importer:
            mock_source_list.return_value = [
                {
                    "id": "test-id",
                    "name": "Test Source",
                    "type": "plex",
                    "enabled_collections": 0,
                    "ingestible_collections": 0,
                    "created_at": "2024-01-15T10:30:00+00:00",
                    "updated_at": "2024-01-20T14:45:00+00:00",
                }
            ]

            result = self.runner.invoke(app, ["source", "list"])

            assert result.exit_code == 0

            mock_get_importer.assert_not_called()
            mock_source_list.assert_called_once_with(ANY, source_type=None)

    def test_source_list_test_db_session_failure_exits_one(self):
        """
        Contract: --test-db session failure MUST exit with code 1.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            # Mock session failure
            mock_session.side_effect = Exception("Test database connection failed")
            
            result = self.runner.invoke(app, ["source", "list", "--test-db"])
            
            assert result.exit_code == 1
            assert "Error" in result.stderr

    def test_source_list_database_query_failure_exits_one(self):
        """
        Contract: Database query failure MUST exit with code 1.
        """
        with patch("retrovue.cli.commands.source.session") as mock_session:
            # Mock database session
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            # Mock query failure
            mock_db.query.side_effect = Exception("Database query failed")
            
            result = self.runner.invoke(app, ["source", "list"])
            
            assert result.exit_code == 1
            assert "Error" in result.stderr

    def test_source_list_collection_counting_accuracy(self):
        """
        Contract: enabled_collections and ingestible_collections counts MUST be accurate.
        """
        # Mock the source_list function to return data with specific collection counts
        mock_sources_data = [
            {
                "id": "test-id",
                "name": "Test Source",
                "type": "plex",
                "enabled_collections": 3,
                "ingestible_collections": 2,
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-20T14:45:00Z"
            }
        ]
        
        with patch("retrovue.cli.commands.source.usecase_list_sources", return_value=mock_sources_data):
            result = self.runner.invoke(app, ["source", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            source = output["sources"][0]
            assert source["enabled_collections"] == 3
            assert source["ingestible_collections"] == 2

    def test_source_list_multiple_sources_json_output(self):
        """
        Contract: JSON output MUST handle multiple sources correctly.
        """
        # Mock multiple sources data
        mock_sources_data = [
            {
                "id": "id1",
                "name": "Source 1",
                "type": "plex",
                "created_at": "2024-01-15T10:30:00Z",
                "updated_at": "2024-01-20T14:45:00Z",
                "enabled_collections": 0,
                "ingestible_collections": 0
            },
            {
                "id": "id2",
                "name": "Source 2",
                "type": "filesystem",
                "created_at": "2024-01-10T09:15:00Z",
                "updated_at": "2024-01-18T16:20:00Z",
                "enabled_collections": 0,
                "ingestible_collections": 0
            }
        ]
        
        with patch("retrovue.cli.commands.source.usecase_list_sources", return_value=mock_sources_data):
            result = self.runner.invoke(app, ["source", "list", "--json"])
            
            assert result.exit_code == 0
            
            # Parse JSON output
            output = json.loads(result.stdout)
            
            assert output["status"] == "ok"
            assert output["total"] == 2
            assert len(output["sources"]) == 2
            
            # Check that both sources are present
            source_names = [source["name"] for source in output["sources"]]
            assert "Source 1" in source_names
            assert "Source 2" in source_names
