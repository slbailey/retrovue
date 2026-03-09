"""
Contract tests for ``retrovue asset enrich --stale``.

Rules covered:
- Stale flag is required
- Source and collection are mutually exclusive
- At least one scope (source or collection) is required
- Source resolution iterates all collections under the source
- Collection resolution targets a single collection
- Dry-run counts stale assets without calling enrich_asset
- Non-dry-run delegates to apply_enrichers_to_collection
- Limit is passed through to apply_enrichers_to_collection
- JSON output matches expected shape
- No stale assets produces zero counts
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from retrovue.usecases.asset_enrich_stale import (
    BulkEnrichResult,
    enrich_stale_assets,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_source(*, source_id="s-1", name="Interstitials"):
    return SimpleNamespace(id=source_id, name=name)


def _fake_collection(*, uuid="c-1", name="commercials", source_id="s-1"):
    ns = SimpleNamespace(
        uuid=uuid,
        name=name,
        source_id=source_id,
        config={"enrichers": []},
        source=SimpleNamespace(name="Interstitials"),
    )
    return ns


def _apply_result(*, collection_name="commercials", considered=10, enriched=5, auto_ready=3):
    return {
        "collection_id": "c-1",
        "collection_name": collection_name,
        "pipeline_checksum": "abc123",
        "stats": {
            "assets_considered": considered,
            "assets_enriched": enriched,
            "assets_auto_ready": auto_ready,
            "errors": [],
        },
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    """Mutually exclusive flags and required scope."""

    def test_both_source_and_collection_raises(self):
        db = MagicMock()
        with pytest.raises(ValueError, match="not both"):
            enrich_stale_assets(
                db,
                source_selector="Interstitials",
                collection_selector="commercials",
            )

    def test_neither_source_nor_collection_raises(self):
        db = MagicMock()
        with pytest.raises(ValueError, match="--source or --collection"):
            enrich_stale_assets(db)


# ---------------------------------------------------------------------------
# Source scoping
# ---------------------------------------------------------------------------

class TestSourceScoping:
    """Source resolution iterates all collections under the source."""

    def test_iterates_source_collections(self):
        db = MagicMock()
        c1 = _fake_collection(uuid="c-1", name="commercials")
        c2 = _fake_collection(uuid="c-2", name="bumpers")
        db.query.return_value.filter.return_value.all.return_value = [c1, c2]

        with patch(
            "retrovue.usecases.asset_enrich_stale._resolve_source"
        ) as mock_resolve, patch(
            "retrovue.usecases.asset_enrich_stale.apply_enrichers_to_collection"
        ) as mock_apply:
            mock_resolve.return_value = _fake_source()
            mock_apply.side_effect = [
                _apply_result(collection_name="commercials", considered=10, enriched=5),
                _apply_result(collection_name="bumpers", considered=8, enriched=4),
            ]

            result = enrich_stale_assets(db, source_selector="Interstitials")

        assert result.collections_processed == 2
        assert result.total_assets_considered == 18
        assert result.total_assets_enriched == 9
        assert mock_apply.call_count == 2

    def test_source_with_no_collections(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []

        with patch(
            "retrovue.usecases.asset_enrich_stale._resolve_source"
        ) as mock_resolve:
            mock_resolve.return_value = _fake_source()

            result = enrich_stale_assets(db, source_selector="Interstitials")

        assert result.collections_processed == 0
        assert result.total_assets_considered == 0
        assert result.to_dict()["status"] == "no_collections"


# ---------------------------------------------------------------------------
# Collection scoping
# ---------------------------------------------------------------------------

class TestCollectionScoping:
    """Collection resolution targets a single collection."""

    def test_single_collection(self):
        db = MagicMock()

        with patch(
            "retrovue.usecases.asset_enrich_stale._resolve_collection"
        ) as mock_resolve, patch(
            "retrovue.usecases.asset_enrich_stale.apply_enrichers_to_collection"
        ) as mock_apply:
            mock_resolve.return_value = _fake_collection()
            mock_apply.return_value = _apply_result(considered=10, enriched=5)

            result = enrich_stale_assets(db, collection_selector="commercials")

        assert result.collections_processed == 1
        assert result.total_assets_enriched == 5
        mock_apply.assert_called_once()


# ---------------------------------------------------------------------------
# Dry-run
# ---------------------------------------------------------------------------

class TestDryRun:
    """Dry-run counts stale assets without enriching."""

    def test_dry_run_passes_through(self):
        db = MagicMock()

        with patch(
            "retrovue.usecases.asset_enrich_stale._resolve_collection"
        ) as mock_resolve, patch(
            "retrovue.usecases.asset_enrich_stale.apply_enrichers_to_collection"
        ) as mock_apply:
            mock_resolve.return_value = _fake_collection()
            mock_apply.return_value = {
                "collection_id": "c-1",
                "collection_name": "commercials",
                "pipeline_checksum": "abc",
                "stats": {
                    "assets_considered": 10,
                    "assets_enriched": 0,
                    "assets_auto_ready": 0,
                    "errors": [],
                },
                "stale_assets": [
                    {"uuid": "a-1", "uri": "/path/a.mp4", "state": "new"},
                ],
            }

            result = enrich_stale_assets(db, collection_selector="commercials", dry_run=True)

        assert result.dry_run is True
        assert result.total_assets_enriched == 0
        assert result.total_assets_considered == 10
        # Verify dry_run was forwarded
        call_kwargs = mock_apply.call_args
        assert call_kwargs.kwargs.get("dry_run") is True


# ---------------------------------------------------------------------------
# Limit
# ---------------------------------------------------------------------------

class TestLimit:
    """Limit is passed through to apply_enrichers_to_collection."""

    def test_limit_forwarded(self):
        db = MagicMock()

        with patch(
            "retrovue.usecases.asset_enrich_stale._resolve_collection"
        ) as mock_resolve, patch(
            "retrovue.usecases.asset_enrich_stale.apply_enrichers_to_collection"
        ) as mock_apply:
            mock_resolve.return_value = _fake_collection()
            mock_apply.return_value = _apply_result(considered=5, enriched=5)

            enrich_stale_assets(db, collection_selector="commercials", max_assets=50)

        call_kwargs = mock_apply.call_args
        assert call_kwargs.kwargs.get("max_assets") == 50


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------

class TestOutputShape:
    """JSON output matches expected shape."""

    def test_to_dict_has_required_keys(self):
        result = BulkEnrichResult(
            source_name="Interstitials",
            collections_processed=1,
            total_assets_considered=10,
            total_assets_enriched=5,
            total_assets_auto_ready=3,
            dry_run=False,
        )
        d = result.to_dict()

        assert "status" in d
        assert "source" in d
        assert "dry_run" in d
        assert "collections_processed" in d
        assert "stats" in d
        assert "collection_results" in d

        assert d["status"] == "success"
        assert d["source"] == "Interstitials"
        assert d["stats"]["assets_considered"] == 10
        assert d["stats"]["assets_enriched"] == 5

    def test_errors_produce_partial_status(self):
        result = BulkEnrichResult(
            source_name="Interstitials",
            collections_processed=2,
            total_assets_considered=10,
            total_assets_enriched=5,
            total_assets_auto_ready=3,
            total_errors=["commercials: enricher boom"],
        )
        assert result.to_dict()["status"] == "partial"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestErrorHandling:
    """Collection-level errors are captured, not raised."""

    def test_collection_error_captured(self):
        db = MagicMock()

        with patch(
            "retrovue.usecases.asset_enrich_stale._resolve_collection"
        ) as mock_resolve, patch(
            "retrovue.usecases.asset_enrich_stale.apply_enrichers_to_collection"
        ) as mock_apply:
            mock_resolve.return_value = _fake_collection()
            mock_apply.side_effect = RuntimeError("pipeline crashed")

            result = enrich_stale_assets(db, collection_selector="commercials")

        assert len(result.total_errors) == 1
        assert "pipeline crashed" in result.total_errors[0]
        assert result.collections_processed == 0
