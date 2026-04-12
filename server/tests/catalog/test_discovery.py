"""
Unit tests for catalog discovery: DiscoveredLocator and discover_locators().

Contract: docs/contracts/core/ContainerDiscoveryContract_v0.1.md
Discovery returns locators without catalog writes; locator is deterministic per item.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from retrovue.catalog.discovery import (
    DiscoveredLocator,
    Fingerprint,
    discover_locators,
)


def _fake_collection(*, source_id="s-1", uuid="c-1"):
    return SimpleNamespace(source_id=source_id, uuid=uuid)


def _fake_item(*, path_uri="/media/a.mp4", provider_key=None, size=1000, last_modified=None):
    return SimpleNamespace(
        path_uri=path_uri,
        provider_key=provider_key,
        size=size,
        last_modified=last_modified,
    )


class TestDiscoverLocators:
    """Unit tests for discover_locators()."""

    def test_returns_one_discovered_locator_per_item(self):
        """discover_locators returns one DiscoveredLocator per importer item."""
        collection = _fake_collection()
        item1 = _fake_item(path_uri="/media/a.mp4")
        item2 = _fake_item(path_uri="/media/b.mp4")
        importer = MagicMock()
        importer.name = "test"
        importer.discover.return_value = [item1, item2]

        result = discover_locators(collection, importer)

        assert len(result) == 2
        assert all(isinstance(pair[0], DiscoveredLocator) for pair in result)
        assert result[0][1] is item1
        assert result[1][1] is item2

    def test_source_id_and_container_id_match_collection(self):
        """source_id and container_id on each DiscoveredLocator match the collection."""
        collection = _fake_collection(source_id="src-99", uuid="coll-88")
        item = _fake_item(path_uri="/media/x.mp4")
        importer = MagicMock()
        importer.name = "fs"
        importer.discover.return_value = [item]

        result = discover_locators(collection, importer)

        assert len(result) == 1
        loc, _ = result[0]
        assert loc.source_id == "src-99"
        assert loc.container_id == "coll-88"

    def test_locator_deterministic_for_same_item(self):
        """For the same item, the derived locator string is identical across calls."""
        collection = _fake_collection()
        item = _fake_item(path_uri="/media/same.mp4", provider_key="pk-1")
        importer = MagicMock()
        importer.name = "test"
        importer.discover.return_value = [item]

        r1 = discover_locators(collection, importer)
        r2 = discover_locators(collection, importer)

        assert len(r1) == 1 and len(r2) == 1
        assert r1[0][0].locator == r2[0][0].locator

    def test_fingerprint_populated_when_item_has_size_or_mtime(self):
        """Fingerprint is set from item size and last_modified when present."""
        from datetime import datetime, timezone

        collection = _fake_collection()
        item = _fake_item(size=5000, last_modified=datetime(2025, 1, 15, tzinfo=timezone.utc))
        importer = MagicMock()
        importer.name = "test"
        importer.discover.return_value = [item]

        result = discover_locators(collection, importer)

        assert len(result) == 1
        loc, _ = result[0]
        assert loc.fingerprint is not None
        assert loc.fingerprint.size == 5000
        assert loc.fingerprint.mtime is not None

    def test_fingerprint_none_when_item_has_no_size_or_mtime(self):
        """Fingerprint is None when item has no size or last_modified."""
        collection = _fake_collection()
        item = _fake_item(size=None, last_modified=None)
        importer = MagicMock()
        importer.name = "test"
        importer.discover.return_value = [item]

        result = discover_locators(collection, importer)

        assert len(result) == 1
        assert result[0][0].fingerprint is None

    def test_discovery_scope_passed_to_importer_when_supported(self):
        """When scope (title/season/episode) is provided and importer has discover_scoped, scope is used."""
        collection = _fake_collection()
        item = _fake_item(path_uri="/media/scoped.mp4")
        importer = MagicMock()
        importer.name = "plex"
        importer.discover_scoped = MagicMock(return_value=[item])

        discover_locators(
            collection,
            importer,
            title="Show",
            season=1,
            episode=2,
        )

        importer.discover_scoped.assert_called_once_with(
            title="Show", season=1, episode=2
        )
        importer.discover.assert_not_called()

    def test_fallback_to_discover_when_discover_scoped_raises(self):
        """When discover_scoped raises, fallback to discover()."""
        collection = _fake_collection()
        item = _fake_item(path_uri="/media/a.mp4")
        importer = MagicMock()
        importer.name = "test"
        importer.discover_scoped = MagicMock(side_effect=RuntimeError("scoped failed"))
        importer.discover = MagicMock(return_value=[item])

        result = discover_locators(
            collection, importer, title="Show", season=1
        )

        assert len(result) == 1
        importer.discover.assert_called_once()

    def test_raises_when_collection_missing_source_id(self):
        """Raises ValueError when collection has no source_id."""
        collection = SimpleNamespace(uuid="c-1")  # no source_id
        importer = MagicMock()
        importer.discover.return_value = []

        with pytest.raises(ValueError, match="source_id"):
            discover_locators(collection, importer)
