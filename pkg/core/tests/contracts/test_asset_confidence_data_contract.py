import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class TestAssetConfidenceDataContract:
    def test_stats_include_confidence_buckets(self):
        runner = CliRunner()

        fake_result = MagicMock()
        fake_result.to_dict.return_value = {
            "status": "success",
            "scope": "collection",
            "collection_id": "col-1",
            "collection_name": "Movies",
            "stats": {
                "assets_discovered": 3,
                "assets_ingested": 3,
                "assets_skipped": 0,
                "assets_changed_content": 0,
                "assets_changed_enricher": 0,
                "assets_updated": 0,
                "duplicates_prevented": 0,
                "assets_auto_ready": 1,
                "assets_needs_enrichment": 1,
                "assets_needs_review": 1,
                "errors": [],
            },
            "thresholds": {"auto_ready": 0.8, "review": 0.5},
        }

        with patch("retrovue.cli.commands.collection.session") as mock_session, \
             patch("retrovue.cli.commands.collection.CollectionIngestService") as mock_service, \
             patch("retrovue.cli.commands.collection.resolve_collection_selector") as mock_resolve:
            mock_session.return_value.__enter__.return_value = MagicMock()
            mock_service.return_value.ingest_collection.return_value = fake_result
            mock_resolve.return_value = MagicMock(uuid="col-1", name="Movies", sync_enabled=True, ingestible=True)

            result = runner.invoke(app, ["collection", "ingest", "Movies", "--json"]) 
            assert result.exit_code == 0
            data = json.loads(result.stdout)
            s = data["stats"]
            total_buckets = (
                s["assets_auto_ready"]
                + s["assets_needs_enrichment"]
                + s["assets_needs_review"]
            )
            assert total_buckets == s["assets_ingested"]


