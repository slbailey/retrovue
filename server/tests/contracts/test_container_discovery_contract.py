"""
Contract tests for ContainerDiscoveryContract.

Contract: docs/contracts/core/ContainerDiscoveryContract_v0.1.md
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from retrovue.catalog.discovery import DiscoveredLocator, discover_locators


def _fake_collection(*, source_id="s-1", uuid="c-1"):
    return SimpleNamespace(source_id=source_id, uuid=uuid)


def _fake_item(*, path_uri="/media/a.mp4", provider_key=None):
    return SimpleNamespace(path_uri=path_uri, provider_key=provider_key, size=100)


class TestContainerDiscoveryContract:
    """Verify ContainerDiscoveryContract guarantees."""

    def test_discovery_occurs_through_containers(self):
        """Media discovery is performed per container; no path bypasses a container."""
        collection = _fake_collection(source_id="src-1", uuid="cont-1")
        item = _fake_item(path_uri="/media/video.mp4")
        importer = MagicMock()
        importer.name = "test"
        importer.discover.return_value = [item]

        result = discover_locators(collection, importer)

        assert len(result) == 1
        loc, _ = result[0]
        assert isinstance(loc, DiscoveredLocator)
        assert loc.container_id == "cont-1"
        assert loc.source_id == "src-1"
        # Discovery is only available via (collection, importer); no bypass.

    def test_source_may_have_multiple_containers(self):
        """A source can have multiple collections/containers; discovery is invoked per container."""
        source_id = "same-source"
        coll1 = _fake_collection(source_id=source_id, uuid="cont-a")
        coll2 = _fake_collection(source_id=source_id, uuid="cont-b")
        item1 = _fake_item(path_uri="/media/a.mp4")
        item2 = _fake_item(path_uri="/media/b.mp4")
        importer = MagicMock()
        importer.name = "test"
        importer.discover.side_effect = [[item1], [item2]]

        r1 = discover_locators(coll1, importer)
        r2 = discover_locators(coll2, importer)

        assert len(r1) == 1 and r1[0][0].container_id == "cont-a"
        assert len(r2) == 1 and r2[0][0].container_id == "cont-b"

    def test_discovery_returns_locators_without_catalog_writes(self):
        """Discovery step returns locator-like data and does not write to the catalog."""
        collection = _fake_collection()
        item = _fake_item(path_uri="/media/x.mp4")
        importer = MagicMock()
        importer.name = "test"
        importer.discover.return_value = [item]

        result = discover_locators(collection, importer)

        assert len(result) == 1
        loc, raw = result[0]
        assert isinstance(loc, DiscoveredLocator)
        assert loc.locator
        assert raw is item
        # discover_locators has no db/session parameter; it cannot write to the catalog.

    def test_locator_deterministic_for_same_item(self):
        """For the same importer item, the derived locator string is identical across calls."""
        collection = _fake_collection()
        item = _fake_item(path_uri="/media/same.mp4", provider_key="pk-42")
        importer = MagicMock()
        importer.name = "test"
        importer.discover.return_value = [item]

        r1 = discover_locators(collection, importer)
        r2 = discover_locators(collection, importer)

        assert r1[0][0].locator == r2[0][0].locator
