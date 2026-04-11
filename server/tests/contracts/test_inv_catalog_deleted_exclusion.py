"""Contract tests: INV-CATALOG-DELETED-EXCLUSION-001

Soft-deleted assets (is_deleted=True) MUST NOT appear in the
CatalogAssetResolver's in-memory catalog or be eligible for pool
resolution.  Violation of this invariant causes block plans to
reference files that no longer exist on disk, producing undecodable
blocks that wedge AIR at fence boundaries.

Root cause incident 2026-03-27:
  Trailer files were renamed on disk, causing old asset records to be
  soft-deleted.  CatalogAssetResolver._load() filtered only on
  state='ready', not is_deleted=False, so the deleted records leaked
  into the pool.  Two consecutive HBO blocks referenced non-existent
  files, and AIR stuck on the last frame of the prior station ID.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

try:
    from retrovue.runtime.catalog_resolver import CatalogAssetResolver
except ImportError:
    pytest.skip(
        "retrovue.runtime dependencies not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_asset(
    *,
    uuid: str = "aaaa-1111",
    uri: str = "file:///mnt/data/trailers/Good.mkv",
    canonical_uri: str | None = None,
    state: str = "ready",
    is_deleted: bool = False,
    approved_for_broadcast: bool = True,
    duration_ms: int = 90_000,
    container_id: str = "container-1",
):
    a = MagicMock()
    a.uuid = uuid
    a.uri = uri
    a.canonical_uri = canonical_uri
    a.state = state
    a.is_deleted = is_deleted
    a.approved_for_broadcast = approved_for_broadcast
    a.duration_ms = duration_ms
    a.container_id = container_id
    return a


def _mock_session(assets):
    """Build a mock Session whose query(Asset).filter(...).all() returns *assets*."""
    session = MagicMock()

    def _query_side_effect(model):
        chain = MagicMock()
        if model.__name__ == "Asset":
            chain.filter.return_value.all.return_value = assets
        else:
            # Editorial, Probed, Tag, Marker, Container queries return empty
            chain.all.return_value = []
            chain.filter.return_value.all.return_value = []
            chain.filter.return_value.order_by.return_value.all.return_value = []
        return chain

    session.query.side_effect = _query_side_effect
    return session


# ===========================================================================
# INV-CATALOG-DELETED-EXCLUSION-001
# ===========================================================================


class TestDeletedAssetsExcludedFromCatalog:
    """Soft-deleted assets must never appear in the resolver catalog."""

    # Tier: 1 | Structural invariant — data integrity gate
    def test_deleted_asset_not_in_catalog(self):
        """An asset with is_deleted=True must not appear in _catalog."""
        deleted = _fake_asset(uuid="del-1", is_deleted=True, uri="file:///gone.mkv")
        alive = _fake_asset(uuid="alive-1", is_deleted=False, uri="file:///exists.mkv")
        session = _mock_session([deleted, alive])

        resolver = CatalogAssetResolver(session)

        catalog_ids = {e.canonical_id for e in resolver._catalog}
        assert "alive-1" in catalog_ids, "Live asset must be in catalog"
        assert "del-1" not in catalog_ids, (
            "INV-CATALOG-DELETED-EXCLUSION-001: soft-deleted asset appeared in catalog"
        )

    # Tier: 1 | Structural invariant — lookup gate
    def test_deleted_asset_not_resolvable_by_uuid(self):
        """Deleted assets must not be resolvable via lookup()."""
        deleted = _fake_asset(uuid="del-2", is_deleted=True, uri="file:///gone2.mkv")
        session = _mock_session([deleted])

        resolver = CatalogAssetResolver(session)

        with pytest.raises(KeyError):
            resolver.lookup("del-2")

    # Tier: 1 | Structural invariant — pool query gate
    def test_deleted_asset_excluded_from_pool_query(self):
        """Deleted assets must not appear in pool query results."""
        deleted = _fake_asset(
            uuid="del-3", is_deleted=True,
            uri="file:///mnt/data/trailers/Deleted.mkv",
        )
        alive = _fake_asset(
            uuid="alive-2", is_deleted=False,
            uri="file:///mnt/data/trailers/Alive.mkv",
        )
        session = _mock_session([deleted, alive])

        resolver = CatalogAssetResolver(session)
        resolver.register_pools({
            "all_trailers": {"match": {}},  # match everything
        })

        match = resolver._pools["all_trailers"]["match"]
        result = resolver.query(match)
        assert "del-3" not in result, (
            "INV-CATALOG-DELETED-EXCLUSION-001: deleted asset in pool query result"
        )
        assert "alive-2" in result

    # Tier: 1 | Structural invariant — zero deleted, all alive
    def test_all_deleted_yields_empty_catalog(self):
        """If every asset is deleted, the catalog must be empty."""
        d1 = _fake_asset(uuid="d1", is_deleted=True, uri="file:///d1.mkv")
        d2 = _fake_asset(uuid="d2", is_deleted=True, uri="file:///d2.mkv")
        session = _mock_session([d1, d2])

        resolver = CatalogAssetResolver(session)

        assert len(resolver._catalog) == 0
        assert len(resolver._assets) == 0
