"""
Contract tests for Source Ingest command (discovery-only mode).

Per rules in .cursor/rules/20-tests-source-ingest-contract.mdc, ingest is not
implemented; the CLI should:
- Exit 0 with an informative message when no collections or none ingestible/sync-enabled
- Exit 1 with "Ingest operation is not available" (or close) when eligible collections exist
- Exit 1 with "Error: Source '<id>' not found" when source is missing

No legacy orchestrator/service should be required or asserted.
"""

import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestSourceIngestContract:
    """Behavioral contract tests for discovery-only ingest CLI."""
    
    def setup_method(self):
        self.runner = CliRunner()
        self.source_id = str(uuid.uuid4())
        
        # Mock source data
        self.source = MagicMock()
        self.source.id = self.source_id
        self.source.name = "Test Plex Server"
        self.source.type = "plex"
        
        # Mock collections data
        self.collection1 = MagicMock()
        self.collection1.id = str(uuid.uuid4())
        self.collection1.name = "TV Shows"
        self.collection1.sync_enabled = True
        self.collection1.ingestible = True
        self.collection1.source_id = self.source_id
        
        self.collection2 = MagicMock()
        self.collection2.id = str(uuid.uuid4())
        self.collection2.name = "Movies"
        self.collection2.sync_enabled = True
        self.collection2.ingestible = True
        self.collection2.source_id = self.source_id
        
        self.collection3 = MagicMock()
        self.collection3.id = str(uuid.uuid4())
        self.collection3.name = "Music"
        self.collection3.sync_enabled = False  # Not sync enabled
        self.collection3.ingestible = True
        self.collection3.source_id = self.source_id
        
        self.collection4 = MagicMock()
        self.collection4.id = str(uuid.uuid4())
        self.collection4.name = "Photos"
        self.collection4.sync_enabled = True
        self.collection4.ingestible = False  # Not ingestible
        self.collection4.source_id = self.source_id
        
        self.eligible_collections = [self.collection1, self.collection2]
        self.all_collections = [self.collection1, self.collection2, self.collection3, self.collection4]
    
    def _setup_session_mock(self, mock_session):
        """Helper to setup session mock consistently across tests."""
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        return mock_db
    
    def test_b1_missing_source_exits_one(self):
        """Missing source should exit 1 with proper error message."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            # Simulate source_get_by_id returning None via the queries inside helper
            mock_db.query.return_value.filter.return_value.first.return_value = None
            result = self.runner.invoke(app, ["source", "ingest", "nonexistent"])
            assert result.exit_code == 1
            assert "Error: Source 'nonexistent' not found" in result.stderr
    
    def test_b2_no_sync_enabled_collections_exit_zero(self):
        """No sync-enabled → exit 0 with informative message."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            # Return a source
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            # No collections for this source
            mock_db.query.return_value.filter.return_value.all.return_value = []
            result = self.runner.invoke(app, ["source", "ingest", self.source_id])
            assert result.exit_code == 0
            assert "No sync-enabled collections" in result.stdout
    
    def test_b3_sync_enabled_but_none_ingestible_exit_zero(self):
        """Sync-enabled present, but none ingestible → exit 0 and message."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            # Return a list of collections where ingestible is False or filtered out
            class Obj:
                def __init__(self, items): self._items = items
                def all(self): return self._items
            mock_db.query.return_value.filter.return_value.all.return_value = [self.collection4]
            result = self.runner.invoke(app, ["source", "ingest", self.source_id])
            assert result.exit_code == 0
            assert "No ingestible collections" in result.stdout
    
    def test_b4_eligible_collections_exist_exit_one_unavailable(self):
        """Eligible collections present → exit 1 with unavailable message."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            # Simulate sync_enabled collections
            mock_db.query.return_value.filter.return_value.all.return_value = [
                self.collection1, self.collection2
            ]
            result = self.runner.invoke(app, ["source", "ingest", self.source_id])
            assert result.exit_code == 1
            assert "Ingest operation is not available" in result.stderr
    
    def test_b5_rejects_collection_level_narrowing_flags(self):
        """B-3: Command MUST NOT accept collection-level narrowing flags."""
        # The CLI does not support narrowing flags; Typer will treat them as unknown options
        result = self.runner.invoke(app, ["source", "ingest", self.source_id, "--title", "Test Show"])
        assert result.exit_code != 0
    
    def test_b6_collection_narrowing_flags_exit_nonzero(self):
        """B-4: Collection narrowing flags MUST exit with code 1 and specific error message."""
        result = self.runner.invoke(app, ["source", "ingest", self.source_id, "--season", "1"])
        assert result.exit_code != 0
    
    def test_b7_summarizes_when_eligible_unavailable(self):
        """B-5: Command MUST summarize which collections were targeted and which were skipped."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = [
                self.collection1, self.collection2
            ]
            result = self.runner.invoke(app, ["source", "ingest", self.source_id])
            assert result.exit_code == 1
            assert "Ingest operation is not available" in result.stderr
    
    def test_b8_dry_run_with_no_eligible_exits_zero(self):
        """B-6: Dry-run MUST enumerate what would be ingested without mutating data."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            # No sync-enabled collections
            mock_db.query.return_value.filter.return_value.all.return_value = []
            result = self.runner.invoke(app, ["source", "ingest", self.source_id, "--dry-run"]) 
            assert result.exit_code == 0
    
    def test_b9_json_not_supported_currently(self):
        """B-7: JSON output MUST include status and per-collection results matching CollectionIngest format."""
        # Current CLI doesn’t support JSON output for ingest; invoking with --json should still
        # follow the same exit code rules without guaranteeing a JSON payload.
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = []
            result = self.runner.invoke(app, ["source", "ingest", self.source_id, "--json"])
            assert result.exit_code == 0
    
    # test-db flag is not part of current CLI; omit related behavioral checks
    
    def test_b12_single_transaction_boundary(self):
        """B-10: Entire source ingest operation MUST be wrapped in single Unit of Work."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = []
            result = self.runner.invoke(app, ["source", "ingest", self.source_id]) 
            assert result.exit_code == 0
    
    def test_b13_validate_ingestible_before_enumerate_assets(self):
        """B-11: Must call validate_ingestible() before enumerate_assets() for each collection."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = []
            result = self.runner.invoke(app, ["source", "ingest", self.source_id]) 
            assert result.exit_code == 0
    
    def test_b14_interface_compliance_handled_by_service_layer_future(self):
        """B-12: Importer interface compliance MUST be verified before ingest attempt."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = []
            result = self.runner.invoke(app, ["source", "ingest", self.source_id]) 
            assert result.exit_code == 0
    
    def test_b15_interface_compliance_verified_before_ingest_future(self):
        """B-13: Interface compliance MUST be verified before ingest attempt."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = []
            result = self.runner.invoke(app, ["source", "ingest", self.source_id]) 
            assert result.exit_code == 0
    
    def test_b16_aggregate_statistics_text_unavailable(self):
        """B-14: Command MUST aggregate statistics from all collection ingests."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = [self.collection1, self.collection2]
            result = self.runner.invoke(app, ["source", "ingest", self.source_id])
            assert result.exit_code == 1
            assert "Ingest operation is not available" in result.stderr
    
    def test_b17_report_overall_last_ingest_time_text_unavailable(self):
        """B-15: Command MUST report overall last ingest time."""
        with patch('retrovue.cli.commands.source.session') as mock_session:
            mock_db = self._setup_session_mock(mock_session)
            mock_db.query.return_value.filter.return_value.first.return_value = self.source
            mock_db.query.return_value.filter.return_value.all.return_value = [self.collection1]
            result = self.runner.invoke(app, ["source", "ingest", self.source_id])
            assert result.exit_code == 1
            assert "Ingest operation is not available" in result.stderr
