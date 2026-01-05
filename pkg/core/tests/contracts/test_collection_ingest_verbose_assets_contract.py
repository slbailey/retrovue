"""
Contract tests for per-run asset change detail when using --verbose-assets.

Covers:
- Created assets list with {uuid, source_uri, canonical_uri}
- Updated assets list with {uuid, source_uri, canonical_uri, reason}
- Default output unchanged when flag not provided
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

    def resolve_local_uri(self, item: dict[str, Any], *, collection=None, path_mappings=None) -> str:
        # Simulate mapping to a canonical local path (native path, no scheme)
        p = item.get("path") or item.get("path_uri") or item.get("uri") or ""
        return p


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
    src.config = {}
    return src


class TestCollectionIngestVerboseAssets:
    def setup_method(self):
        self.runner = CliRunner()

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_collection_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_verbose_returns_created_assets(self, mock_get_importer, mock_resolve, mock_session):
        # Arrange DB and collection
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection
        db.query.return_value.filter.return_value.first.return_value = _make_source("filesystem")

        # Importer emits two new items
        items = [
            {"path": "/media/new1.mkv"},
            {"path": "/media/new2.mkv"},
        ]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # No existing assets
        db.scalar.return_value = None

        # Act
        result = self.runner.invoke(app, [
            "collection", "ingest", str(collection.uuid), "--json", "--verbose-assets"
        ])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
        assert "created_assets" in payload
        assert "updated_assets" in payload
        assert len(payload["created_assets"]) == 2
        # URIs present and correct (canonical is native path)
        src_uris = {a["source_uri"] for a in payload["created_assets"]}
        canon_uris = {a["canonical_uri"] for a in payload["created_assets"]}
        assert src_uris == {"/media/new1.mkv", "/media/new2.mkv"}
        assert canon_uris == {"/media/new1.mkv", "/media/new2.mkv"}
        # UUIDs should be present and non-empty strings
        for a in payload["created_assets"]:
            assert isinstance(a.get("uuid"), str) and len(a["uuid"]) > 0

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_collection_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_verbose_returns_no_updates_for_existing(self, mock_get_importer, mock_resolve, mock_session):
        # Arrange DB and collection
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection
        db.query.return_value.filter.return_value.first.return_value = _make_source("filesystem")

        # Importer emits two existing items with different changes
        items = [
            {"path": "/media/existing1.mkv"},  # content change scenario not used anymore
            {"path": "/media/existing2.mkv", "enricher_checksum": "e2"},  # enricher change
        ]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Existing assets returned in order: two lookups
        existing1 = MagicMock()
        existing1.uuid = uuid.uuid4()
        existing1.last_enricher_checksum = None

        existing2 = MagicMock()
        existing2.uuid = uuid.uuid4()
        existing2.last_enricher_checksum = "e1"

        db.scalar.side_effect = [existing1, existing2]

        # Act
        result = self.runner.invoke(app, [
            "collection", "ingest", str(collection.uuid), "--json", "--verbose-assets"
        ])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
        # Under tightened contract, existing assets are skipped and not updated
        assert payload.get("updated_assets") == []

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_collection_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_verbose_does_not_affect_default_output(self, mock_get_importer, mock_resolve, mock_session):
        # Arrange DB and collection
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection
        db.query.return_value.filter.return_value.first.return_value = _make_source("filesystem")

        # Importer emits one new item
        items = [{"path": "/media/new.mkv"}]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # No existing assets
        db.scalar.return_value = None

        # Act (without --verbose-assets)
        result = self.runner.invoke(app, [
            "collection", "ingest", str(collection.uuid), "--json"
        ])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
        assert "created_assets" not in payload
        assert "updated_assets" not in payload






