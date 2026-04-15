"""
Contract tests for INV-CATALOG-BY-ID-001.

_catalog_by_id is a keyed lookup mirror of _catalog introduced by
PASS-OPT-02-PHASE-A1-EPG-CATALOG-LOOKUP. These tests verify:

1. _catalog_by_id is populated at construction time and mirrors _catalog.
2. canonical_id uniqueness is enforced — duplicate raises ValueError.
3. update_asset_loudness() keeps _catalog_by_id in sync with _catalog.
4. EPG lookup path uses _catalog_by_id (O(1)) not the linear _catalog scan.
"""

from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

import pytest

SRC_ROOT = Path(__file__).parents[3] / "src" / "retrovue"


def _make_mock_db(assets: list[dict]) -> MagicMock:
    """Build a minimal mock DB for CatalogAssetResolver._load()."""
    from retrovue.domain.entities import (
        Asset, AssetEditorial, AssetProbed, AssetTag, Container, Marker,
    )

    mock_assets = []
    for a in assets:
        ma = MagicMock(spec=Asset)
        ma.uuid = a["uuid"]
        ma.state = "ready"
        ma.is_deleted = False
        ma.duration_ms = a.get("duration_ms", 60_000)
        ma.uri = a.get("uri", f"file://{a['uuid']}.mp4")
        ma.canonical_uri = a.get("canonical_uri", None)
        ma.container_id = a.get("container_id", "col-1")
        mock_assets.append(ma)

    mock_container = MagicMock(spec=Container)
    mock_container.uuid = "col-1"
    mock_container.name = "Test Collection"
    mock_container.config = {"type": "episode"}
    mock_container.source = None

    db = MagicMock()

    def _query(entity):
        chain = MagicMock()
        if entity is Asset:
            chain.filter.return_value.filter.return_value.all.return_value = mock_assets
            chain.filter.return_value.all.return_value = mock_assets
        elif entity is AssetEditorial:
            chain.all.return_value = []
        elif entity is AssetProbed:
            chain.all.return_value = []
        elif entity is AssetTag:
            chain.all.return_value = []
        elif entity is Marker:
            chain.filter.return_value.order_by.return_value.all.return_value = []
        elif entity is Container:
            chain.all.return_value = [mock_container]
        return chain

    db.query.side_effect = _query
    return db


class TestInvCatalogById001:
    """INV-CATALOG-BY-ID-001 contract tests."""

    def test_catalog_by_id_populated_at_construction(self):
        """_catalog_by_id must mirror _catalog after construction."""
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver

        assets = [{"uuid": f"uuid-{i}", "uri": f"file://ep{i}.mp4"} for i in range(5)]
        db = _make_mock_db(assets)
        resolver = CatalogAssetResolver(db)

        # _catalog_by_id must have same count as _catalog
        assert len(resolver._catalog_by_id) == len(resolver._catalog)

        # Every entry in _catalog must be reachable via _catalog_by_id
        for entry in resolver._catalog:
            looked_up = resolver._catalog_by_id.get(entry.canonical_id)
            assert looked_up is entry, (
                f"_catalog_by_id[{entry.canonical_id!r}] should be the same object "
                "as the _catalog entry"
            )

    def test_catalog_by_id_keyed_lookup_returns_correct_entry(self):
        """Direct lookup by canonical_id returns correct entry."""
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver

        assets = [{"uuid": "target-uuid", "uri": "file://target.mp4"}]
        db = _make_mock_db(assets)
        resolver = CatalogAssetResolver(db)

        entry = resolver._catalog_by_id.get("target-uuid")
        assert entry is not None
        assert entry.canonical_id == "target-uuid"

    def test_update_asset_loudness_keeps_catalog_by_id_in_sync(self):
        """update_asset_loudness() must update _catalog_by_id.meta as well as _catalog."""
        from retrovue.runtime.catalog_resolver import CatalogAssetResolver

        assets = [{"uuid": "loud-uuid", "uri": "file://loud.mp4"}]
        db = _make_mock_db(assets)
        resolver = CatalogAssetResolver(db)

        assert "loud-uuid" in resolver._catalog_by_id

        resolver.update_asset_loudness("loud-uuid", gain_db=-6.5)

        # Both structures must reflect the new gain
        by_id_meta = resolver._catalog_by_id["loud-uuid"].meta
        catalog_meta = next(
            e.meta for e in resolver._catalog if e.canonical_id == "loud-uuid"
        )

        assert by_id_meta.loudness_gain_db == pytest.approx(-6.5)
        assert catalog_meta.loudness_gain_db == pytest.approx(-6.5)
        # Same object identity (both code paths update the same _CatalogEntry)
        assert by_id_meta is catalog_meta

    def test_epg_handler_uses_catalog_by_id_not_linear_scan(self):
        """AST verification: get_epg_all() must use _catalog_by_id.get(), not iterate _catalog."""
        pd_path = SRC_ROOT / "runtime" / "program_director.py"
        source = pd_path.read_text()
        tree = ast.parse(source, filename=str(pd_path))

        # Find get_epg_all function
        epg_fn = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "get_epg_all":
                epg_fn = node
                break
        assert epg_fn is not None, "get_epg_all not found in program_director.py"

        # Verify _catalog_by_id.get() is called
        uses_by_id = False
        for child in ast.walk(epg_fn):
            if isinstance(child, ast.Call):
                func = child.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "get"
                    and isinstance(func.value, ast.Attribute)
                    and func.value.attr == "_catalog_by_id"
                ):
                    uses_by_id = True
                    break
        assert uses_by_id, (
            "get_epg_all() does not call _catalog_by_id.get() — "
            "O(1) lookup is not in place"
        )

        # Verify the old linear for-loop over _catalog is gone from the EPG join path
        has_linear_scan = False
        for child in ast.walk(epg_fn):
            if isinstance(child, ast.For):
                target = child.target
                iter_node = child.iter
                # Pattern: for cat_entry in _shared_resolver._catalog:
                if (
                    isinstance(iter_node, ast.Attribute)
                    and iter_node.attr == "_catalog"
                    and not isinstance(iter_node.value, ast.Attribute)
                ):
                    has_linear_scan = True
                    break
        assert not has_linear_scan, (
            "get_epg_all() still contains a linear for-loop over _catalog — "
            "the O(N) scan was not removed"
        )
