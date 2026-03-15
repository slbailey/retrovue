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
- R-7: Re-added asset (same canonical_key_hash as soft-deleted row) is restored and enqueued
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

def _fake_collection(*, uuid="c-1", name="commercials", source_id="s-1"):
    return SimpleNamespace(
        uuid=uuid,
        source_id=source_id,
        name=name,
        sync_enabled=True,
        ingestible=True,
        config={},
        source=SimpleNamespace(name="Interstitials", type="filesystem"),
    )


def _fake_discovered_item(*, path_uri="/media/a.mp4", size=1000, provider_key=None):
    return SimpleNamespace(
        path_uri=path_uri,
        provider_key=provider_key,
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
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.load_catalog_state_for_collection",
            return_value={"hash_gone": stale_asset},
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.enqueue_processor_jobs",
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
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.enqueue_processor_jobs",
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
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.load_catalog_state_for_collection",
            return_value={"hash_gone": stale_asset},
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
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

# ---------------------------------------------------------------------------
# R-7: Re-add restores soft-deleted asset
# ---------------------------------------------------------------------------


class TestReAddRestoresAsset:
    """R-7: When a discovered item matches a soft-deleted asset by canonical_key_hash, restore and enqueue."""

    def test_restored_asset_counted_as_ingested(self):
        from retrovue.cli.commands._ops.collection_ingest_service import (
            CollectionIngestService,
        )

        db = MagicMock()
        collection = _fake_collection()

        # One discovered item; catalog state empty so outcome is "create"
        loc = SimpleNamespace(locator="/media/a.mp4", fingerprint=None)
        item = _fake_discovered_item(path_uri="/media/a.mp4")
        soft_deleted_asset = _fake_asset(
            uuid="a-old",
            canonical_key_hash="hash_a",
            uri="/media/a.mp4",
            is_deleted=True,
        )
        soft_deleted_asset.deleted_at = datetime.now(UTC)

        importer = MagicMock()
        importer.validate_ingestible.return_value = True
        importer.name = "test"

        with patch(
            "retrovue.cli.commands._ops.collection_ingest_service.discover_locators",
            return_value=[(loc, item)],
        ), patch(
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
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.load_catalog_state_for_collection",
            return_value={},
        ), patch(
            "retrovue.cli.commands._ops.collection_ingest_service.enqueue_processor_jobs",
        ):
            # Repo finds the soft-deleted row when checking duplicate by canonical_key_hash
            db.scalar.return_value = soft_deleted_asset

            svc = CollectionIngestService(db)
            result = svc.ingest_collection(
                collection=collection,
                importer=importer,
            )

        assert result.stats.assets_ingested == 1
        assert soft_deleted_asset.is_deleted is False
        assert soft_deleted_asset.deleted_at is None


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
