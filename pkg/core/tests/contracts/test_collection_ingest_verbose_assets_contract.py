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

    def resolve_local_uri(self, item: dict[str, Any], *, collection=None, path_mappings=None) -> str:
        # Simulate mapping to a canonical local path (native path, no scheme)
        p = item.get("path") or item.get("path_uri") or item.get("uri") or ""
        return p


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


def _make_db(existing_assets=None):
    """Build a FakeDB seeded with empty stores for all queried models."""
    db = FakeDB()
    db.seed(Asset, existing_assets or [])
    db.seed(Container, [])
    db.seed(Source, [])
    return db


@pytest.mark.usefixtures("suppress_structlog_stdout")
class TestCollectionIngestVerboseAssets:
    def setup_method(self):
        self.runner = CliRunner()

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_container_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_verbose_returns_created_assets(self, mock_get_importer, mock_resolve, mock_session):
        # Arrange DB and collection
        db = _make_db()
        mock_session.return_value.__enter__.return_value = db
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection

        # Importer emits two new items
        items = [
            {"path": "/media/new1.mkv"},
            {"path": "/media/new2.mkv"},
        ]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Act
        result = self.runner.invoke(app, [
            "container", "ingest", str(collection.uuid), "--json", "--verbose-assets"
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
    @patch("retrovue.cli.commands.collection.resolve_container_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_verbose_returns_no_updates_for_existing(self, mock_get_importer, mock_resolve, mock_session):
        # Arrange DB and collection
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)

        # Build existing assets matching the discovery items
        from retrovue.infra.canonical import canonical_hash, canonical_key_for

        items = [
            {"path": "/media/existing1.mkv"},
            {"path": "/media/existing2.mkv"},
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
                last_enricher_checksum=None,
            )
            existing_assets.append(asset)

        db = _make_db(existing_assets=existing_assets)
        mock_session.return_value.__enter__.return_value = db
        mock_resolve.return_value = collection

        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Act
        result = self.runner.invoke(app, [
            "container", "ingest", str(collection.uuid), "--json", "--verbose-assets"
        ])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
        # Under tightened contract, existing assets are skipped and not updated
        assert payload.get("updated_assets") == []

    @patch("retrovue.cli.commands.collection.session")
    @patch("retrovue.cli.commands.collection.resolve_container_selector")
    @patch("retrovue.cli.commands.collection.get_importer")
    def test_collection_ingest_verbose_does_not_affect_default_output(self, mock_get_importer, mock_resolve, mock_session):
        # Arrange DB and collection
        db = _make_db()
        mock_session.return_value.__enter__.return_value = db
        source_id = str(uuid.uuid4())
        collection = _make_collection(source_id)
        mock_resolve.return_value = collection

        # Importer emits one new item
        items = [{"path": "/media/new.mkv"}]
        importer = _FakeImporter("filesystem", items)
        mock_get_importer.return_value = importer

        # Act (without --verbose-assets)
        result = self.runner.invoke(app, [
            "container", "ingest", str(collection.uuid), "--json"
        ])

        # Assert
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["status"] == "success"
        assert "created_assets" not in payload
        assert "updated_assets" not in payload
