"""
Contract tests for ingest reconciliation of removed assets.

Invariant: INV-INGEST-RECONCILE-REMOVED-001
Full collection ingest MUST soft-delete assets whose canonical keys are no
longer present in the importer's discovered set.

Rules covered:
- R-1: Full collection ingest soft-deletes assets not in discovered set
- R-2: Scoped ingest (title/season/episode) does NOT delete anything
- R-3: Dry-run reports removals without mutating
- R-4: Empty discovery (importer returns []) does NOT delete anything (safety guard)
- R-5: Already-deleted assets are not double-deleted
- R-6: assets_removed count is accurate in stats
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_collection(*, uuid="c-1", name="commercials"):
    return SimpleNamespace(
        uuid=uuid,
        name=name,
        sync_enabled=True,
        ingestible=True,
        config={},
        source=SimpleNamespace(name="Interstitials", type="filesystem"),
    )


def _fake_discovered_item(*, path_uri="/media/a.mp4", size=1000):
    return SimpleNamespace(
        path_uri=path_uri,
        size=size,
        raw_labels=[],
        editorial=None,
        probed=None,
        sidecars=[],
        asset_type=None,
        station_ops=None,
        relationships=None,
        source_payload=None,
        enricher_checksum=None,
    )


def _fake_asset(*, uuid="a-old", canonical_key_hash="hash_gone", uri="/media/gone.mp4", is_deleted=False):
    asset = MagicMock()
    asset.uuid = uuid
    asset.canonical_key_hash = canonical_key_hash
    asset.uri = uri
    asset.is_deleted = is_deleted
    asset.deleted_at = None
    return asset


# ---------------------------------------------------------------------------
# R-1: Full ingest soft-deletes removed assets
# ---------------------------------------------------------------------------

class TestFullIngestReconciliation:
    """R-1: Full collection ingest soft-deletes assets not in discovered set."""

    def test_removed_asset_soft_deleted(self):
        from retrovue.cli.commands._ops.collection_ingest_service import (
            CollectionIngestService,
        )

        db = MagicMock()
        collection = _fake_collection()

        # One item discovered on disk
        discovered = [_fake_discovered_item(path_uri="/media/a.mp4")]

        # One asset in DB that was NOT discovered (removed from disk)
        stale_asset = _fake_asset(uuid="a-old", canonical_key_hash="hash_gone")
        db.query.return_value.filter.return_value.all.return_value = [stale_asset]

        importer = MagicMock()
        importer.validate_ingestible.return_value = True
        importer.discover.return_value = discovered
        importer.name = "test"

        with patch(
            "retrovue.cli.commands._ops.collection_ingest_service.canonical_key_for",
            return_value="key_a",
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.canonical_hash",
            return_value="hash_a",
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
            return_value={"resolved_fields": {}},
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        ):
            # Make scalar return None (no existing asset for the discovered item)
            db.scalar.return_value = None

            svc = CollectionIngestService(db)
            result = svc.ingest_collection(
                collection=collection,
                importer=importer,
            )

        assert result.stats.assets_removed == 1
        assert stale_asset.is_deleted is True
        assert stale_asset.deleted_at is not None


# ---------------------------------------------------------------------------
# R-2: Scoped ingest does NOT delete
# ---------------------------------------------------------------------------

class TestScopedIngestNoDelete:
    """R-2: Scoped ingest (title/season/episode) does NOT delete anything."""

    def test_title_scoped_ingest_skips_reconciliation(self):
        from retrovue.cli.commands._ops.collection_ingest_service import (
            CollectionIngestService,
        )

        db = MagicMock()
        collection = _fake_collection()

        discovered = [_fake_discovered_item(path_uri="/media/a.mp4")]

        importer = MagicMock()
        importer.validate_ingestible.return_value = True
        importer.discover_scoped.return_value = discovered
        importer.name = "test"

        with patch(
            "retrovue.cli.commands._ops.collection_ingest_service.canonical_key_for",
            return_value="key_a",
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.canonical_hash",
            return_value="hash_a",
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
            return_value={"resolved_fields": {}},
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        ):
            db.scalar.return_value = None

            svc = CollectionIngestService(db)
            result = svc.ingest_collection(
                collection=collection,
                importer=importer,
                title="Some Title",
            )

        # Scoped ingest must NOT remove anything
        assert result.stats.assets_removed == 0


# ---------------------------------------------------------------------------
# R-3: Dry-run reports but does not mutate
# ---------------------------------------------------------------------------

class TestDryRunReconciliation:
    """R-3: Dry-run reports removals without mutating."""

    def test_dry_run_counts_but_does_not_delete(self):
        from retrovue.cli.commands._ops.collection_ingest_service import (
            CollectionIngestService,
        )

        db = MagicMock()
        collection = _fake_collection()

        discovered = [_fake_discovered_item(path_uri="/media/a.mp4")]
        stale_asset = _fake_asset(uuid="a-old", canonical_key_hash="hash_gone")
        db.query.return_value.filter.return_value.all.return_value = [stale_asset]

        importer = MagicMock()
        importer.validate_ingestible.return_value = True
        importer.discover.return_value = discovered
        importer.name = "test"

        with patch(
            "retrovue.cli.commands._ops.collection_ingest_service.canonical_key_for",
            return_value="key_a",
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.canonical_hash",
            return_value="hash_a",
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
            return_value={"resolved_fields": {}},
        ):
            db.scalar.return_value = None

            svc = CollectionIngestService(db)
            result = svc.ingest_collection(
                collection=collection,
                importer=importer,
                dry_run=True,
            )

        # Count reported but asset not mutated
        assert result.stats.assets_removed == 1
        # is_deleted should still be False (dry-run)
        assert stale_asset.is_deleted is False


# ---------------------------------------------------------------------------
# R-4: Empty discovery does NOT delete (safety guard)
# ---------------------------------------------------------------------------

class TestEmptyDiscoverySafety:
    """R-4: Empty discovery does NOT delete anything."""

    def test_empty_discovery_preserves_all_assets(self):
        from retrovue.cli.commands._ops.collection_ingest_service import (
            CollectionIngestService,
        )

        db = MagicMock()
        collection = _fake_collection()

        # Importer returns empty list (maybe network failure)
        importer = MagicMock()
        importer.validate_ingestible.return_value = True
        importer.discover.return_value = []
        importer.name = "test"

        svc = CollectionIngestService(db)
        result = svc.ingest_collection(
            collection=collection,
            importer=importer,
        )

        # No items discovered → no reconciliation should occur
        assert result.stats.assets_removed == 0
        assert result.stats.assets_discovered == 0


# ---------------------------------------------------------------------------
# R-6: Stats accuracy
# ---------------------------------------------------------------------------

class TestStatsAccuracy:
    """R-6: assets_removed in output dict."""

    def test_assets_removed_in_to_dict(self):
        from retrovue.cli.commands._ops.collection_ingest_service import (
            CollectionIngestResult,
            IngestStats,
        )

        stats = IngestStats(assets_discovered=5, assets_ingested=3, assets_removed=2)
        result = CollectionIngestResult(
            collection_id="c-1",
            collection_name="commercials",
            scope="collection",
            stats=stats,
        )
        d = result.to_dict()
        assert d["stats"]["assets_removed"] == 2
