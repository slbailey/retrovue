"""
Contract tests for SourceIngestService (service-level).

Rules covered:
- B-2: Only sync_enabled AND ingestible collections processed
- B-5: Partial failure produces partial status
- B-6: dry-run forwarded to CollectionIngestService
- B-10: Service does not commit (caller owns transaction)
- B-14: Stats aggregation across collections
- D-4: Delegates to CollectionIngestService (full collection scope)
- D-7: New assets start in state="new", never auto-approved (via CIS)
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from retrovue.cli.commands._ops.source_ingest_service import (
    SourceIngestService,
    SourceIngestResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_source(*, source_id="s-1", name="Test Plex") -> SimpleNamespace:
    return SimpleNamespace(id=source_id, name=name, type="plex")


def _fake_collection(
    *,
    uuid="c-1",
    name="TV Shows",
    source_id="s-1",
    sync_enabled=True,
    ingestible=True,
) -> SimpleNamespace:
    return SimpleNamespace(
        uuid=uuid,
        name=name,
        source_id=source_id,
        sync_enabled=sync_enabled,
        ingestible=ingestible,
        external_id=None,
        config={},
    )


class _FakeCISResult:
    """Mimics CollectionIngestResult.to_dict()."""

    def __init__(
        self,
        *,
        collection_name: str,
        discovered: int,
        ingested: int,
        skipped: int = 0,
        errors: list | None = None,
    ):
        self._name = collection_name
        self._discovered = discovered
        self._ingested = ingested
        self._skipped = skipped
        self._errors = errors or []

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "success",
            "scope": "collection",
            "collection_id": "cid",
            "collection_name": self._name,
            "stats": {
                "assets_discovered": self._discovered,
                "assets_ingested": self._ingested,
                "assets_skipped": self._skipped,
                "assets_updated": 0,
                "assets_changed_content": 0,
                "assets_changed_enricher": 0,
                "duplicates_prevented": 0,
                "assets_auto_ready": self._ingested,
                "assets_needs_enrichment": 0,
                "assets_needs_review": 0,
                "errors": self._errors,
            },
        }


# ---------------------------------------------------------------------------
# B-2: Only eligible collections processed
# ---------------------------------------------------------------------------

class TestEligibleCollectionFiltering:
    """B-2, D-2: Only sync_enabled=True AND ingestible=True collections processed."""

    def test_skips_not_ingestible(self):
        db = MagicMock()
        c_ok = _fake_collection(uuid="c-ok", name="OK", ingestible=True)
        c_skip = _fake_collection(uuid="c-skip", name="Skip", ingestible=False)
        db.query.return_value.filter.return_value.all.return_value = [c_ok, c_skip]

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_cis = MagicMock()
            mock_cis.ingest_collection.return_value = _FakeCISResult(
                collection_name="OK", discovered=10, ingested=5
            )
            mock_cis_cls.return_value = mock_cis
            mock_cif.return_value = MagicMock()

            svc = SourceIngestService(db)
            result = svc.ingest_source(_fake_source())

        assert result.collections_processed == 1
        assert result.collections_skipped == 1
        mock_cis.ingest_collection.assert_called_once()

    def test_no_eligible_collections(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        svc = SourceIngestService(db)
        result = svc.ingest_source(_fake_source())

        assert result.collections_processed == 0
        assert result.stats.assets_discovered == 0


# ---------------------------------------------------------------------------
# B-14: Stats aggregation
# ---------------------------------------------------------------------------

class TestStatsAggregation:
    """B-14: Source ingest aggregates stats across all collection ingests."""

    def test_aggregates_across_two_collections(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="TV")
        c2 = _fake_collection(uuid="c-2", name="Movies")
        db.query.return_value.filter.return_value.all.return_value = [c1, c2]

        call_count = {"n": 0}

        def _make_result(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _FakeCISResult(collection_name="TV", discovered=100, ingested=80, skipped=20)
            return _FakeCISResult(collection_name="Movies", discovered=50, ingested=40, skipped=10)

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_cis = MagicMock()
            mock_cis.ingest_collection.side_effect = _make_result
            mock_cis_cls.return_value = mock_cis
            mock_cif.return_value = MagicMock()

            svc = SourceIngestService(db)
            result = svc.ingest_source(_fake_source())

        assert result.collections_processed == 2
        assert result.stats.assets_discovered == 150
        assert result.stats.assets_ingested == 120
        assert result.stats.assets_skipped == 30


# ---------------------------------------------------------------------------
# D-4: Delegates to CollectionIngestService
# ---------------------------------------------------------------------------

class TestDelegatesToCIS:
    """D-4: Source ingest delegates to the same pipeline as collection ingest."""

    def test_calls_collection_ingest_service(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="TV")
        db.query.return_value.filter.return_value.all.return_value = [c1]

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_importer = MagicMock()
            mock_cif.return_value = mock_importer
            mock_cis = MagicMock()
            mock_cis.ingest_collection.return_value = _FakeCISResult(
                collection_name="TV", discovered=10, ingested=5
            )
            mock_cis_cls.return_value = mock_cis

            svc = SourceIngestService(db)
            svc.ingest_source(_fake_source())

        mock_cis.ingest_collection.assert_called_once()
        call_kwargs = mock_cis.ingest_collection.call_args
        assert call_kwargs.kwargs.get("collection") is c1


# ---------------------------------------------------------------------------
# B-6: dry-run behavior
# ---------------------------------------------------------------------------

class TestDryRun:
    """B-6: dry-run passes through to collection ingest."""

    def test_dry_run_forwarded_to_cis(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="TV")
        db.query.return_value.filter.return_value.all.return_value = [c1]

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_cif.return_value = MagicMock()
            mock_cis = MagicMock()
            mock_cis.ingest_collection.return_value = _FakeCISResult(
                collection_name="TV", discovered=10, ingested=0
            )
            mock_cis_cls.return_value = mock_cis

            svc = SourceIngestService(db)
            svc.ingest_source(_fake_source(), dry_run=True)

        call_kwargs = mock_cis.ingest_collection.call_args
        assert call_kwargs.kwargs.get("dry_run") is True


# ---------------------------------------------------------------------------
# B-5: Partial failure
# ---------------------------------------------------------------------------

class TestPartialFailure:
    """B-5: Partial failure when one collection fails."""

    def test_partial_failure_status(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="TV")
        c2 = _fake_collection(uuid="c-2", name="Movies")
        db.query.return_value.filter.return_value.all.return_value = [c1, c2]

        call_count = {"n": 0}

        def _side_effect(**kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _FakeCISResult(collection_name="TV", discovered=10, ingested=5)
            raise RuntimeError("Importer unreachable")

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_cif.return_value = MagicMock()
            mock_cis = MagicMock()
            mock_cis.ingest_collection.side_effect = _side_effect
            mock_cis_cls.return_value = mock_cis

            svc = SourceIngestService(db)
            result = svc.ingest_source(_fake_source())

        rd = result.to_dict()
        assert rd["status"] == "partial"
        assert len(result.errors) == 1
        assert "Movies" in result.errors[0]
        assert len(result.collection_results) == 1

    def test_all_collections_fail_still_partial(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="TV")
        db.query.return_value.filter.return_value.all.return_value = [c1]

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_cif.return_value = MagicMock()
            mock_cis = MagicMock()
            mock_cis.ingest_collection.side_effect = RuntimeError("boom")
            mock_cis_cls.return_value = mock_cis

            svc = SourceIngestService(db)
            result = svc.ingest_source(_fake_source())

        rd = result.to_dict()
        assert rd["status"] == "partial"
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# B-10: Transaction boundary
# ---------------------------------------------------------------------------

class TestTransactionBoundary:
    """B-10: Service does not commit; caller owns transaction."""

    def test_service_does_not_commit(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        svc = SourceIngestService(db)
        svc.ingest_source(_fake_source())

        db.commit.assert_not_called()


# ---------------------------------------------------------------------------
# JSON output shape
# ---------------------------------------------------------------------------

class TestOutputShape:
    """B-7: JSON output matches contract shape."""

    def test_to_dict_has_required_keys(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="TV")
        db.query.return_value.filter.return_value.all.return_value = [c1]

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_cif.return_value = MagicMock()
            mock_cis = MagicMock()
            mock_cis.ingest_collection.return_value = _FakeCISResult(
                collection_name="TV", discovered=10, ingested=5
            )
            mock_cis_cls.return_value = mock_cis

            svc = SourceIngestService(db)
            result = svc.ingest_source(_fake_source())

        rd = result.to_dict()

        assert "status" in rd
        assert "source" in rd
        assert "collections_processed" in rd
        assert "stats" in rd
        assert "collection_results" in rd
        assert "errors" in rd

        assert rd["source"]["id"] == "s-1"
        assert rd["source"]["name"] == "Test Plex"

        stats = rd["stats"]
        assert "assets_discovered" in stats
        assert "assets_ingested" in stats
        assert "assets_skipped" in stats

    def test_success_status_when_all_ok(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="TV")
        db.query.return_value.filter.return_value.all.return_value = [c1]

        with patch(
            "retrovue.cli.commands._ops.source_ingest_service._construct_importer"
        ) as mock_cif, patch(
            "retrovue.cli.commands._ops.source_ingest_service.CollectionIngestService"
        ) as mock_cis_cls:
            mock_cif.return_value = MagicMock()
            mock_cis = MagicMock()
            mock_cis.ingest_collection.return_value = _FakeCISResult(
                collection_name="TV", discovered=10, ingested=5
            )
            mock_cis_cls.return_value = mock_cis

            svc = SourceIngestService(db)
            result = svc.ingest_source(_fake_source())

        assert result.to_dict()["status"] == "success"

    def test_error_status_when_no_collections(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        svc = SourceIngestService(db)
        result = svc.ingest_source(_fake_source())

        assert result.to_dict()["status"] == "error"
