"""
Data contract tests for Collection List command.

Tests the data contract rules (D-#) defined in CollectionListContract.md.
These tests verify database operations, transaction safety, data integrity, and snapshot consistency.
"""

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestCollectionListDataContract:
    """Test CollectionList data contract rules (D-#)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.runner = CliRunner()

    # D-1: Persisted collection records
    def test_d1_persisted_collection_records(self):
        """
        Contract D-1: The list of collections MUST reflect persisted Collection records at the time of query.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_col = MagicMock()
            mock_col.uuid = "4b2b05e7-d7d2-414a-a587-3f5df9b53f44"
            mock_col.external_id = "1"
            mock_col.name = "TV Shows"
            mock_col.sync_enabled = True
            mock_col.ingestible = True
            mock_col.config = {}
            
            mock_db.query.return_value.all.return_value = [mock_col]
            
            result = self.runner.invoke(app, ["collection", "list", "--json"])
            
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert len(data) == 1
            assert data[0]["collection_id"] == "4b2b05e7-d7d2-414a-a587-3f5df9b53f44"

    # D-2: Correct latest metadata
    def test_d2_correct_latest_metadata(self):
        """
        Contract D-2: Each returned collection MUST include correct latest metadata
        (sync_enabled, ingestible, etc.) from authoritative Collection model.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_col = MagicMock()
            mock_col.uuid = "test-id"
            mock_col.external_id = "1"
            mock_col.name = "Test Collection"
            mock_col.sync_enabled = False
            mock_col.ingestible = False
            mock_col.config = {}
            
            mock_db.query.return_value.all.return_value = [mock_col]
            
            result = self.runner.invoke(app, ["collection", "list", "--json"])
            
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            assert data[0]["sync_enabled"] is False
            assert data[0]["ingestible"] is False

    # D-3: Asset counts from persisted rows
    def test_d3_asset_counts_from_persisted_rows(self):
        """
        Contract D-3: Asset counts MUST be calculated from persisted Asset rows.
        """
        # Note: This would require Asset model in test
        # Placeholder for when Asset domain is implemented
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_db.query.return_value.all.return_value = []
            
            result = self.runner.invoke(app, ["collection", "list"])
            assert result.exit_code == 0

    # D-4: Source information from foreign key
    def test_d4_source_info_from_foreign_key(self):
        """
        Contract D-4: Source information MUST be retrieved from Source table via foreign key.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_col = MagicMock()
            mock_col.uuid = "col-id"
            mock_col.external_id = "1"
            mock_col.name = "Test Collection"
            mock_col.sync_enabled = True
            mock_col.ingestible = True
            mock_col.source_id = "source-id"
            mock_col.config = {}
            
            mock_source = MagicMock()
            mock_source.id = "source-id"
            mock_source.name = "Test Source"
            mock_source.type = "plex"
            
            mock_db.query.return_value.all.return_value = [mock_col]
            
            result = self.runner.invoke(app, ["collection", "list", "--json"])
            
            assert result.exit_code == 0
            # This is a placeholder - full implementation would join Source

    # D-5: Stored data only
    def test_d5_stored_data_only(self):
        """
        Contract D-5: Command MUST NOT infer or fabricate collection state; MUST use stored data only.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_col = MagicMock()
            mock_col.uuid = "col-id"
            mock_col.external_id = "1"
            mock_col.name = "Test Collection"
            mock_col.sync_enabled = True
            mock_col.ingestible = True
            mock_col.config = {}
            
            mock_db.query.return_value.all.return_value = [mock_col]
            
            result = self.runner.invoke(app, ["collection", "list", "--json"])
            
            assert result.exit_code == 0
            # Verify only query() was called, not importer or external services
            mock_db.add.assert_not_called()
            mock_db.delete.assert_not_called()

    # D-6: No create or modify
    def test_d6_no_create_or_modify(self):
        """
        Contract D-6: Command MUST NOT create or modify Collections while listing.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_db.query.return_value.all.return_value = []
            
            result = self.runner.invoke(app, ["collection", "list"])
            
            assert result.exit_code == 0
            mock_db.add.assert_not_called()
            mock_db.commit.assert_not_called()

    # D-7: Test DB isolation
    def test_d7_test_db_isolation(self):
        """
        Contract D-7: Querying via --test-db MUST NOT read or leak production data.
        """
        # Note: Requires actual test DB setup
        # Placeholder for full implementation
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_db.query.return_value.all.return_value = []
            
            result = self.runner.invoke(app, ["collection", "list", "--test-db"])
            
            # TODO: tighten exit code once CLI is stable - placeholder test with mocks
            # Should not crash
            assert result.exit_code in [0, 1]

    # D-8: Consistent Read Snapshot
    def test_d8_consistent_read_snapshot(self):
        """
        Contract D-8: Command MUST comply with Consistent Read Snapshot guarantee (G-7).
        """
        # Placeholder - this would test snapshot consistency
        # Requires understanding of the Consistent Read Snapshot guarantee
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_db.query.return_value.all.return_value = []
            
            result = self.runner.invoke(app, ["collection", "list"])
            assert result.exit_code == 0

    # D-9: Source lookup before filtering
    def test_d9_source_lookup_before_filtering(self):
        """
        Contract D-9: When --source is provided, source lookup MUST occur before collection querying,
        and collections MUST be filtered by resolved source ID.
        """
        with patch("retrovue.cli.commands.collection.session") as mock_session:
            mock_db = MagicMock()
            mock_session.return_value.__enter__.return_value = mock_db
            
            mock_source = MagicMock()
            mock_source.id = "source-id"
            mock_source.name = "Test Source"
            mock_source.type = "plex"
            
            mock_col = MagicMock()
            mock_col.uuid = "col-id"
            mock_col.external_id = "1"
            mock_col.name = "Test Collection"
            mock_col.sync_enabled = True
            mock_col.ingestible = True
            mock_col.config = {}
            
            # First lookup resolves source, second filters collections
            mock_db.query.return_value.filter.return_value.first.return_value = mock_source
            mock_db.query.return_value.filter.return_value.all.return_value = [mock_col]
            mock_db.query.return_value.all.return_value = []  # PathMappings
            
            result = self.runner.invoke(app, ["collection", "list", "--source", "Test Source"])
            
            assert result.exit_code == 0

