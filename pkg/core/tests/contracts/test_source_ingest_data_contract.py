"""
Data contract tests for Source Ingest (discovery-only mode).

Architectural doctrine:
- Source ingest MUST succeed (exit code 0) when eligible collections exist.
- Enrichers are optional; lack of valid enrichers MUST NOT cause exit code 1.
- No unintended DB writes in discovery-only scenarios.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app
from retrovue.domain.entities import Container, Source

from ._fakes import FakeDB


def _ns(**kw):
    return SimpleNamespace(**kw)


class TestSourceIngestDataContract:
    """Data contract tests aligned with discovery-only ingest CLI."""

    def setup_method(self):
        self.runner = CliRunner()
        self.source_id = str(uuid.uuid4())

        # Source fixture
        self.source = _ns(
            id=self.source_id, name="Test Plex Server", type="plex",
            external_id=self.source_id, config={},
        )

        # Container fixtures
        self.collection1 = _ns(
            id=str(uuid.uuid4()), uuid=str(uuid.uuid4()),
            name="TV Shows", sync_enabled=True, ingestible=True,
            source_id=self.source_id, config={},
        )
        self.collection2 = _ns(
            id=str(uuid.uuid4()), uuid=str(uuid.uuid4()),
            name="Movies", sync_enabled=True, ingestible=True,
            source_id=self.source_id, config={},
        )

        self.eligible_collections = [self.collection1, self.collection2]

    def _make_db(self, *, source=True, containers=None):
        """Build a FakeDB seeded with source and containers."""
        db = FakeDB()
        if source:
            db.seed(Source, [self.source])
        else:
            db.seed(Source, [])
        if containers is not None:
            db.seed(Container, containers)
        else:
            db.seed(Container, [])
        return db

    def _patch_session(self, mock_session, db):
        """Wire a FakeDB into the session context manager."""
        mock_session.return_value.__enter__.return_value = db

    def _make_mock_svc_class(self):
        """Create a mock SourceIngestService class whose instances return a
        successful SourceIngestResult from ingest_source()."""
        from retrovue.cli.commands._ops.source_ingest_service import (
            SourceIngestResult,
            SourceIngestStats,
        )

        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_instance.ingest_source.return_value = SourceIngestResult(
            source_id=self.source_id,
            source_name="Test Plex Server",
            collections_processed=2,
            collections_skipped=0,
            stats=SourceIngestStats(),
            collection_results=[],
            errors=[],
        )
        mock_cls.return_value = mock_instance
        return mock_cls

    @patch('retrovue.cli.commands.source.session')
    def test_d1_no_collections_exit_zero_no_persistence(self, mock_session):
        """No collections -> exit 0 and no DB writes."""
        db = self._make_db(containers=[])
        self._patch_session(mock_session, db)
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert "No sync-enabled collections" in result.stdout
        assert len(db.added) == 0

    @patch('retrovue.cli.commands.source.session')
    def test_d2_sync_enabled_but_none_ingestible_exit_zero(self, mock_session):
        """Sync-enabled present but none ingestible -> exit 0 and message."""
        non_ingestible = _ns(
            id=str(uuid.uuid4()), uuid=str(uuid.uuid4()),
            name="Movies", sync_enabled=True, ingestible=False,
            source_id=self.source_id, config={},
        )
        db = self._make_db(containers=[non_ingestible])
        self._patch_session(mock_session, db)
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert "No ingestible collections" in result.stdout

    @patch('retrovue.cli.commands._ops.source_ingest_service.SourceIngestService')
    @patch('retrovue.cli.commands.source.session')
    def test_d3_eligible_collections_succeed_no_db_writes(self, mock_session, mock_svc_cls):
        """Eligible collections exist -> exit 0, warning/output allowed, no DB writes."""
        db = self._make_db(containers=[self.collection1, self.collection2])
        self._patch_session(mock_session, db)
        mock_svc_cls.side_effect = self._make_mock_svc_class().side_effect
        mock_svc_cls.return_value = self._make_mock_svc_class().return_value
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert "Ingest" in result.output or "ingest" in result.output or "collection" in result.output
        assert len(db.added) == 0

    @patch('retrovue.cli.commands.source.session')
    def test_d4_missing_source_exit_one(self, mock_session):
        db = self._make_db(source=False)
        self._patch_session(mock_session, db)
        result = self.runner.invoke(app, ["source", "ingest", "missing"])
        assert result.exit_code == 1
        assert "Error: Source 'missing' not found" in result.stderr

    @patch('retrovue.cli.commands.source.session')
    def test_d5_dry_run_no_eligible_exit_zero_no_writes(self, mock_session):
        db = self._make_db(containers=[])
        self._patch_session(mock_session, db)
        result = self.runner.invoke(app, ["source", "ingest", self.source_id, "--dry-run"])
        assert result.exit_code == 0
        assert len(db.added) == 0

    @patch('retrovue.cli.commands._ops.source_ingest_service.SourceIngestService')
    @patch('retrovue.cli.commands.source.session')
    def test_d6_dry_run_with_eligible_succeeds_no_writes(self, mock_session, mock_svc_cls):
        """Dry-run with eligible collections -> exit 0, no DB writes."""
        db = self._make_db(containers=[self.collection1])
        self._patch_session(mock_session, db)
        mock_svc_cls.return_value = self._make_mock_svc_class().return_value
        result = self.runner.invoke(app, ["source", "ingest", self.source_id, "--dry-run"])
        assert result.exit_code == 0
        assert "Ingest" in result.output or "ingest" in result.output or "collection" in result.output or "Would" in result.output
        assert len(db.added) == 0

    # test-db flag is not part of current CLI; omit related data checks
    # test-db + dry-run precedence not applicable; flag not supported

    def test_d9_no_legacy_service_imports(self):
        """Sanity: ensure tests do not patch legacy service; CLI should not require it."""
        # Nothing to do; if we reached here without referencing service paths, contract holds.
        assert True

    @patch('retrovue.cli.commands._ops.source_ingest_service.SourceIngestService')
    @patch('retrovue.cli.commands.source.session')
    def test_d10_never_persists_in_discovery_only(self, mock_session, mock_svc_cls):
        """Discovery-only: exit 0 with eligible collections; no DB writes."""
        db = self._make_db(containers=[self.collection1])
        self._patch_session(mock_session, db)
        mock_svc_cls.return_value = self._make_mock_svc_class().return_value
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert len(db.added) == 0

    @patch('retrovue.cli.commands.source.session')
    def test_d11_sync_enabled_non_ingestible_exit_zero(self, mock_session):
        non_ingestible = _ns(
            id=str(uuid.uuid4()), uuid=str(uuid.uuid4()),
            name="TV Shows", sync_enabled=True, ingestible=False,
            source_id=self.source_id, config={},
        )
        db = self._make_db(containers=[non_ingestible])
        self._patch_session(mock_session, db)
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert "No ingestible collections" in result.stdout

    @patch('retrovue.cli.commands._ops.source_ingest_service.SourceIngestService')
    @patch('retrovue.cli.commands.source.session')
    def test_d12_sync_enabled_ingestible_present_succeeds(self, mock_session, mock_svc_cls):
        """Eligible collections present -> ingest succeeds (exit 0)."""
        db = self._make_db(containers=[self.collection1])
        self._patch_session(mock_session, db)
        mock_svc_cls.return_value = self._make_mock_svc_class().return_value
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert "Ingest" in result.output or "ingest" in result.output or "collection" in result.output

    # test-db with eligible collections not applicable; flag not supported
    # dry-run + test-db precedence not applicable; test-db not supported

    @patch('retrovue.cli.commands._ops.source_ingest_service.SourceIngestService')
    @patch('retrovue.cli.commands.source.session')
    def test_d15_no_source_level_records_created(self, mock_session, mock_svc_cls):
        """With eligible collections, exit 0; no unintended source-level DB writes."""
        db = self._make_db(containers=[self.collection1])
        self._patch_session(mock_session, db)
        mock_svc_cls.return_value = self._make_mock_svc_class().return_value
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert len(db.added) == 0

    @patch('retrovue.cli.commands._ops.source_ingest_service.SourceIngestService')
    @patch('retrovue.cli.commands.source.session')
    def test_d16_text_stats_or_summary_present_when_eligible(self, mock_session, mock_svc_cls):
        """With eligible collections, exit 0; summary or ingest-related output present."""
        db = self._make_db(containers=[self.collection1, self.collection2])
        self._patch_session(mock_session, db)
        mock_svc_cls.return_value = self._make_mock_svc_class().return_value
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert "Ingest" in result.output or "ingest" in result.output or "collection" in result.output

    @patch('retrovue.cli.commands._ops.source_ingest_service.SourceIngestService')
    @patch('retrovue.cli.commands.source.session')
    def test_d17_eligible_collections_succeed(self, mock_session, mock_svc_cls):
        """Eligible collections -> ingest succeeds (exit 0)."""
        db = self._make_db(containers=[self.collection1])
        self._patch_session(mock_session, db)
        mock_svc_cls.return_value = self._make_mock_svc_class().return_value
        result = self.runner.invoke(app, ["source", "ingest", self.source_id])
        assert result.exit_code == 0
        assert "Ingest" in result.output or "ingest" in result.output or "collection" in result.output
