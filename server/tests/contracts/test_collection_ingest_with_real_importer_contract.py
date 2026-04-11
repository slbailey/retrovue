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
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from retrovue.cli.main import app
from retrovue.domain.entities import Asset, Container, Source

from ._fakes import FakeDB


class _FakeImporter:
    def __init__(self, name: str, items: list[dict[str, Any]]):
        self.name = name
        self._items = items

    def validate_ingestible(self, _collection) -> bool:
        return True

    def discover(self) -> list[dict[str, Any]]:
        return list(self._items)


def _make_collection(source_id: str):
    coll = SimpleNamespace(
        uuid=uuid.uuid4(),
        id=str(uuid.uuid4()),
        name="Movies",
        sync_enabled=True,
        ingestible=True,
        source_id=source_id,
        config={},
        external_id=str(uuid.uuid4()),
        source=SimpleNamespace(),
    )
    return coll


@pytest.mark.usefixtures("suppress_structlog_stdout")
class TestCollectionIngestWithRealImporter:
    def setup_method(self):
        self.runner = CliRunner()

    def _make_db(self, existing_assets=None):
        """Build a FakeDB seeded with empty stores for all queried models."""
        db = FakeDB()
        db.seed(Asset, existing_assets or [])
        db.seed(Container, [])
        db.seed(Source, [])
        # ProcessorJob, PathMapping, Enricher etc. — empty by default via FakeDB
        return db

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_container_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_with_real_importer_first_run(self, mock_get_importer, mock_resolve, mock_session):
        """First run should ingest items discovered by the importer."""
        # Arrange database/session
        db = self._make_db()
        mock_session.return_value.__enter__.return_value = db

        # Arrange source/collection
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection

        # Arrange importer that emits two items
        items = [
            {"path": "/media/a.mkv"},
            {"path": "/media/b.mkv"},
        ]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Act
        result = self.runner.invoke(app, ["container", "ingest", str(collection.uuid), "--json"])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["stats"]["assets_discovered"] == 2
        assert payload["stats"]["assets_ingested"] == 2
        assert payload["stats"]["assets_skipped"] == 0

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_container_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_with_real_importer_second_run_skips(self, mock_get_importer, mock_resolve, mock_session):
        """Second run should skip existing items (no ingests)."""
        # Arrange source/collection
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)

        # Build existing assets that match what would be discovered
        from retrovue.infra.canonical import canonical_hash, canonical_key_for

        items = [
            {"path": "/media/a.mkv"},
            {"path": "/media/b.mkv"},
        ]

        existing_assets = []
        for item in items:
            ck = canonical_key_for(item, container=collection, provider="filesystem")
            ck_hash = canonical_hash(ck)
            asset = SimpleNamespace(
                uuid=uuid.uuid4(),
                container_id=collection.uuid,
                source_id=source_id,
                canonical_key=ck,
                canonical_key_hash=ck_hash,
                uri=item["path"],
                canonical_uri=item["path"],
                is_deleted=False,
                file_size=None,
                file_mtime=None,
            )
            existing_assets.append(asset)

        db = self._make_db(existing_assets=existing_assets)
        mock_session.return_value.__enter__.return_value = db
        mock_resolve.return_value = collection

        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Act
        result = self.runner.invoke(app, ["container", "ingest", str(collection.uuid), "--json"])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["stats"]["assets_discovered"] == 2
        assert payload["stats"]["assets_ingested"] == 0
        assert payload["stats"]["assets_skipped"] == 2
