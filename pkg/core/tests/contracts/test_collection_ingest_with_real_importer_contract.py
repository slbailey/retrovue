"""
Contract tests for collection ingest using a real importer via the dispatcher.

Covers:
- First run: ingests > 0 from importer discovery
- Second run: skips > 0 and ingested == 0

Rules:
- Importers only discover; persistence is handled by ingest service
- Dispatcher selected by collection/source.type; constructor patchable at
  `retrovue.cli.commands.collection.get_importer`
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from retrovue.cli.main import app


class _FakeImporter:
    def __init__(self, name: str, items: list[dict[str, Any]]):
        self.name = name
        self._items = items

    def validate_ingestible(self, _collection) -> bool:
        return True

    def discover(self) -> list[dict[str, Any]]:
        return list(self._items)


def _make_collection(source_id: str):
    coll = MagicMock()
    coll.uuid = uuid.uuid4()
    coll.name = "Movies"
    coll.sync_enabled = True
    coll.ingestible = True
    coll.source_id = source_id
    return coll


def _make_source(source_type: str, name: str = "Test Source"):
    src = MagicMock()
    src.type = source_type
    src.name = name
    # Minimal config; dispatcher builds kwargs but we patch constructor anyway
    src.config = {}
    return src


class TestCollectionIngestWithRealImporter:
    def setup_method(self):
        self.runner = CliRunner()

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_collection_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_with_real_importer_first_run(self, mock_get_importer, mock_resolve, mock_session):
        """First run should ingest items discovered by the importer."""
        # Arrange database/session
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db

        # Arrange source/collection
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection
        db.query.return_value.filter.return_value.first.return_value = _make_source("filesystem")

        # Arrange importer that emits two items
        items = [
            {"path": "/media/a.mkv"},
            {"path": "/media/b.mkv"},
        ]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Ensure no existing assets found
        db.scalar.return_value = None

        # Act
        result = self.runner.invoke(app, ["collection", "ingest", str(collection.uuid), "--json"])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["stats"]["assets_discovered"] == 2
        assert payload["stats"]["assets_ingested"] == 2
        assert payload["stats"]["assets_skipped"] == 0

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_collection_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_with_real_importer_second_run_skips(self, mock_get_importer, mock_resolve, mock_session):
        """Second run should skip existing items (no ingests)."""
        # Arrange database/session
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db

        # Arrange source/collection
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection
        db.query.return_value.filter.return_value.first.return_value = _make_source("filesystem")

        # Arrange importer that emits two items
        items = [
            {"path": "/media/a.mkv"},
            {"path": "/media/b.mkv"},
        ]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Existing asset objects returned by repository lookup
        existing1 = MagicMock()
        existing2 = MagicMock()
        db.scalar.side_effect = [existing1, existing2]

        # Act
        result = self.runner.invoke(app, ["collection", "ingest", str(collection.uuid), "--json"])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["stats"]["assets_discovered"] == 2
        assert payload["stats"]["assets_ingested"] == 0
        assert payload["stats"]["assets_skipped"] == 2


