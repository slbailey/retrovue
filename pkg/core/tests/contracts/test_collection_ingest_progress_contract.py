import uuid
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


def test_dry_run_emits_early_feedback():
    runner = CliRunner()
    collection_id = str(uuid.uuid4())

    with patch("retrovue.cli.commands.collection.session") as mock_session, \
         patch("retrovue.cli.commands.collection.resolve_collection_selector") as mock_resolve, \
         patch("retrovue.cli.commands.collection.get_importer") as mock_get_importer, \
         patch("retrovue.cli.commands._ops.collection_ingest_service.CollectionIngestService") as mock_service:

        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db

        mock_collection = MagicMock()
        mock_collection.uuid = uuid.uuid4()
        mock_collection.name = "Movies"
        mock_collection.sync_enabled = True
        mock_collection.ingestible = True
        mock_collection.source_id = uuid.uuid4()
        mock_resolve.return_value = mock_collection

        importer = MagicMock()
        importer.validate_ingestible.return_value = True
        mock_get_importer.return_value = importer

        # Minimal result to satisfy formatting
        result = MagicMock()
        result.stats.assets_discovered = 0
        result.stats.assets_ingested = 0
        result.stats.assets_skipped = 0
        result.stats.assets_updated = 0
        result.collection_name = "Movies"
        result.scope = "collection"
        mock_service.return_value.ingest_collection.return_value = result

        res = runner.invoke(app, ["collection", "ingest", collection_id, "--dry-run"])  # no --json
        assert res.exit_code == 0
        # Early message should appear before the summary lines
        assert "Starting ingest: validating and ingesting assets" in res.stdout
