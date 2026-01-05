import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class _FakeResult:
    def __init__(self, payload: dict):
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


class TestCollectionIngestConfidenceContract:
    def setup_method(self):
        self.runner = CliRunner()

    @patch("retrovue.cli.commands.collection._get_db_context")
    @patch("retrovue.cli.commands.collection.resolve_collection_selector")
    @patch("retrovue.cli.commands.collection.CollectionIngestService")
    def test_json_includes_thresholds_and_confidence_buckets(
        self, mock_service_cls, mock_resolve, mock_get_db_ctx
    ):
        """
        CONTRACT: Collection ingest JSON MUST include thresholds and confidence bucket stats.
        - thresholds: { "auto_ready": float, "review": float }
        - stats: assets_auto_ready, assets_needs_enrichment, assets_needs_review
        """
        # Arrange minimal DB context and collection
        mock_db_cm = MagicMock()
        mock_db = MagicMock()
        mock_db_cm.__enter__.return_value = mock_db
        mock_get_db_ctx.return_value = mock_db_cm

        collection = SimpleNamespace(
            uuid="11111111-1111-1111-1111-111111111111",
            name="TV Shows",
            sync_enabled=True,
            ingestible=True,
        )
        mock_resolve.return_value = collection

        payload = {
            "status": "success",
            "scope": "collection",
            "collection_id": str(collection.uuid),
            "collection_name": collection.name,
            "thresholds": {"auto_ready": 0.8, "review": 0.5},
            "stats": {
                "assets_discovered": 1000,
                "assets_ingested": 1000,
                "assets_skipped": 0,
                "assets_updated": 0,
                "duplicates_prevented": 0,
                "errors": [],
                "assets_auto_ready": 990,
                "assets_needs_enrichment": 9,
                "assets_needs_review": 1,
            },
        }

        mock_service = MagicMock()
        mock_service.ingest_collection.return_value = _FakeResult(payload)
        mock_service_cls.return_value = mock_service

        # Act
        result = self.runner.invoke(
            app,
            [
                "collection",
                "ingest",
                str(collection.uuid),
                "--json",
            ],
        )

        # Assert
        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["thresholds"] == {"auto_ready": 0.8, "review": 0.5}
        assert data["stats"]["assets_auto_ready"] == 990
        assert data["stats"]["assets_needs_enrichment"] == 9
        assert data["stats"]["assets_needs_review"] == 1

    @patch("retrovue.cli.commands.collection._get_db_context")
    @patch("retrovue.cli.commands.collection.resolve_collection_selector")
    @patch("retrovue.cli.commands.collection.CollectionIngestService")
    def test_verbose_created_assets_include_state_approval_confidence(
        self, mock_service_cls, mock_resolve, mock_get_db_ctx
    ):
        """
        CONTRACT: With --verbose-assets, created_assets SHOULD include
        state, approved_for_broadcast, and confidence values.
        """
        mock_db_cm = MagicMock()
        mock_db = MagicMock()
        mock_db_cm.__enter__.return_value = mock_db
        mock_get_db_ctx.return_value = mock_db_cm

        collection = SimpleNamespace(
            uuid="22222222-2222-2222-2222-222222222222",
            name="Movies",
            sync_enabled=True,
            ingestible=True,
        )
        mock_resolve.return_value = collection

        payload = {
            "status": "success",
            "scope": "collection",
            "collection_id": str(collection.uuid),
            "collection_name": collection.name,
            "thresholds": {"auto_ready": 0.8, "review": 0.5},
            "stats": {
                "assets_discovered": 2,
                "assets_ingested": 2,
                "assets_skipped": 0,
                "assets_updated": 0,
                "duplicates_prevented": 0,
                "errors": [],
                "assets_auto_ready": 2,
                "assets_needs_enrichment": 0,
                "assets_needs_review": 0,
            },
            "created_assets": [
                {
                    "uuid": "a1",
                    "source_uri": "file:///a.mp4",
                    "canonical_uri": "/media/a.mp4",
                    "state": "ready",
                    "approved_for_broadcast": True,
                    "confidence": 0.97,
                },
                {
                    "uuid": "b2",
                    "source_uri": "file:///b.mp4",
                    "canonical_uri": "/media/b.mp4",
                    "state": "ready",
                    "approved_for_broadcast": True,
                    "confidence": 0.91,
                },
            ],
        }

        mock_service = MagicMock()
        mock_service.ingest_collection.return_value = _FakeResult(payload)
        mock_service_cls.return_value = mock_service

        result = self.runner.invoke(
            app,
            [
                "collection",
                "ingest",
                str(collection.uuid),
                "--json",
                "--verbose-assets",
            ],
        )

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert data["created_assets"][0]["state"] == "ready"
        assert data["created_assets"][0]["approved_for_broadcast"] is True
        assert 0.0 <= data["created_assets"][0]["confidence"] <= 1.0

