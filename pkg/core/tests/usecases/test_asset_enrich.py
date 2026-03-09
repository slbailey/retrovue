"""
Unit tests for the unified enrichment lifecycle: usecases/asset_enrich.py

Tests are deterministic (no real DB, no network, no wall-clock sleep).
Uses mock DB sessions and SimpleNamespace stubs to verify the lifecycle
contract without requiring Postgres.

See: docs/contracts/invariants/core/asset/INV-ASSET-REENRICH-RESETS-STALE-001.md
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch
from uuid import UUID, uuid4

import pytest

from retrovue.usecases.asset_enrich import EnrichResult, enrich_asset, _extract_label


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_db():
    """Create a mock DB session that supports get/delete/add/flush."""
    db = MagicMock()
    db.get = MagicMock(return_value=None)  # default: no existing child rows
    db.delete = MagicMock()
    db.add = MagicMock()
    db.flush = MagicMock()
    return db


def _make_asset(**overrides) -> MagicMock:
    """Create a mock Asset with all fields and relationships."""
    asset = MagicMock()
    defaults = dict(
        uuid=uuid4(),
        collection_uuid=uuid4(),
        uri="/media/test/asset.mp4",
        canonical_uri="/media/test/asset.mp4",
        size=1_000_000,
        state="new",
        approved_for_broadcast=False,
        duration_ms=None,
        video_codec=None,
        audio_codec=None,
        container=None,
        markers=[],
        last_enricher_checksum=None,
        updated_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(asset, k, v)
    return asset


def _make_enricher(labels_to_add: list[str] | None = None,
                   editorial: dict | None = None,
                   probed: dict | None = None,
                   should_fail: bool = False):
    """Create a mock enricher that adds labels/metadata to DiscoveredItem."""
    def enrich(item):
        if should_fail:
            raise RuntimeError("enricher failed")
        if labels_to_add:
            existing = list(item.raw_labels or [])
            existing.extend(labels_to_add)
            item.raw_labels = existing
        if editorial:
            item.editorial = dict(item.editorial or {})
            item.editorial.update(editorial)
        if probed:
            item.probed = dict(item.probed or {})
            item.probed.update(probed)
        return item

    enricher = MagicMock()
    enricher.enrich = MagicMock(side_effect=enrich)
    return enricher


class _ChapterMarker:
    """Stub marker for chapter testing."""
    def __init__(self, kind_val="chapter"):
        self.kind = kind_val
        self.start_ms = 0
        self.end_ms = 30_000


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestEnrichAssetClearsMetadata:
    """Verify stale technical metadata is cleared before enrichment."""

    def test_clears_technical_fields(self):
        """Technical metadata fields are set to None before enrichment runs."""
        db = _make_mock_db()
        asset = _make_asset(
            state="ready",
            duration_ms=1_320_000,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        )
        enricher = _make_enricher(labels_to_add=[
            "duration_ms:900000",
            "video_codec:hevc",
            "audio_codec:opus",
            "container:mkv",
        ])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)

        # After enrichment, fields reflect NEW enricher output, not old values
        assert asset.duration_ms == 900_000
        assert asset.video_codec == "hevc"
        assert asset.audio_codec == "opus"
        assert asset.container == "mkv"

    def test_clears_fields_even_when_enricher_produces_nothing(self):
        """If enricher produces no labels, technical fields remain None."""
        db = _make_mock_db()
        asset = _make_asset(
            state="ready",
            duration_ms=1_320_000,
            video_codec="h264",
            audio_codec="aac",
            container="mp4",
        )
        enricher = _make_enricher()  # produces no labels
        pipeline = [(0, "noop", enricher)]

        result = enrich_asset(db, asset, pipeline)

        assert asset.duration_ms is None
        assert asset.video_codec is None
        assert asset.audio_codec is None
        assert asset.container is None


class TestEnrichAssetDeletesProbed:
    """Verify AssetProbed row is deleted before enrichment."""

    def test_deletes_existing_probed_row(self):
        """If AssetProbed exists, it is deleted."""
        db = _make_mock_db()
        probed_row = MagicMock()
        db.get = MagicMock(side_effect=lambda cls, uuid: probed_row if cls.__name__ == "AssetProbed" else None)

        asset = _make_asset(state="new")
        enricher = _make_enricher(labels_to_add=["duration_ms:1000"])
        pipeline = [(0, "ffprobe", enricher)]

        enrich_asset(db, asset, pipeline)

        db.delete.assert_any_call(probed_row)

    def test_no_error_when_probed_absent(self):
        """No error when AssetProbed row doesn't exist."""
        db = _make_mock_db()
        db.get = MagicMock(return_value=None)

        asset = _make_asset(state="new")
        enricher = _make_enricher(labels_to_add=["duration_ms:1000"])
        pipeline = [(0, "ffprobe", enricher)]

        # Should not raise
        result = enrich_asset(db, asset, pipeline)
        assert result.asset_uuid == str(asset.uuid)


class TestEnrichAssetChapterMarkers:
    """Verify chapter marker handling."""

    def test_deletes_chapter_markers_preserves_others(self):
        """CHAPTER markers are deleted; non-CHAPTER markers survive."""
        db = _make_mock_db()
        chapter = _ChapterMarker("chapter")
        avail = _ChapterMarker("avail")
        asset = _make_asset(state="new", markers=[chapter, avail])
        enricher = _make_enricher(labels_to_add=["duration_ms:1000"])
        pipeline = [(0, "ffprobe", enricher)]

        enrich_asset(db, asset, pipeline)

        # Only the chapter marker should have been deleted
        db.delete.assert_any_call(chapter)
        # The avail marker should NOT be in delete calls (beyond the chapter)
        delete_args = [c[0][0] for c in db.delete.call_args_list]
        assert avail not in delete_args

    def test_creates_chapter_markers_from_probed(self):
        """Chapter markers are recreated from probed data when valid."""
        db = _make_mock_db()
        db.get = MagicMock(return_value=None)
        asset = _make_asset(state="new")
        enricher = _make_enricher(
            labels_to_add=["duration_ms:1320000"],
            probed={
                "duration_ms": 1_320_000,
                "chapters": [
                    {"start_ms": 0, "end_ms": 30_000, "title": "Intro"},
                    {"start_ms": 30_000, "end_ms": 60_000, "title": "Act 1"},
                ],
            },
        )
        pipeline = [(0, "ffprobe", enricher)]

        enrich_asset(db, asset, pipeline)

        # Two markers should have been added
        add_calls = [c[0][0] for c in db.add.call_args_list]
        marker_adds = [c for c in add_calls if hasattr(c, "kind") and hasattr(c, "start_ms")]
        assert len(marker_adds) == 2

    def test_skips_invalid_chapter_bounds(self):
        """Out-of-bounds chapters are logged and skipped, not created."""
        db = _make_mock_db()
        db.get = MagicMock(return_value=None)
        asset = _make_asset(state="new")
        enricher = _make_enricher(
            labels_to_add=["duration_ms:1320000"],
            probed={
                "duration_ms": 1_320_000,
                "chapters": [
                    {"start_ms": 0, "end_ms": 2_000_000, "title": "Too Long"},
                ],
            },
        )
        pipeline = [(0, "ffprobe", enricher)]

        enrich_asset(db, asset, pipeline)

        # No marker should have been added (only asset itself via add)
        add_calls = [c[0][0] for c in db.add.call_args_list]
        marker_adds = [c for c in add_calls if hasattr(c, "kind") and hasattr(c, "start_ms")]
        assert len(marker_adds) == 0


class TestEnrichAssetApprovalReset:
    """Verify approved_for_broadcast is always reset to False."""

    def test_resets_approved_for_broadcast(self):
        """approved_for_broadcast is False after enrichment regardless of outcome."""
        db = _make_mock_db()
        asset = _make_asset(
            state="ready",
            approved_for_broadcast=True,
            duration_ms=1_320_000,
        )
        enricher = _make_enricher(labels_to_add=["duration_ms:900000"])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)

        assert asset.approved_for_broadcast is False

    def test_never_sets_approved_true(self):
        """Even with successful enrichment, approved stays False."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        enricher = _make_enricher(labels_to_add=[
            "duration_ms:1320000",
            "video_codec:h264",
            "audio_codec:aac",
            "container:mp4",
        ])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)

        assert asset.state == "ready"
        assert asset.approved_for_broadcast is False


class TestEnrichAssetStateTransitions:
    """Verify state machine transitions are followed."""

    def test_transitions_through_enriching_to_ready(self):
        """Asset goes new → enriching → ready when duration is valid."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        enricher = _make_enricher(labels_to_add=["duration_ms:1320000"])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)

        assert result.old_state == "new"
        assert result.new_state == "ready"
        assert asset.state == "ready"

    def test_transitions_through_enriching_to_new_on_missing_duration(self):
        """Asset goes new → enriching → new when duration is missing."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        enricher = _make_enricher()  # no duration
        pipeline = [(0, "noop", enricher)]

        result = enrich_asset(db, asset, pipeline)

        assert result.new_state == "new"
        assert asset.state == "new"

    def test_handles_ready_asset_entry_state(self):
        """Asset starting in 'ready' is properly reset and re-enriched."""
        db = _make_mock_db()
        asset = _make_asset(
            state="ready",
            approved_for_broadcast=True,
            duration_ms=1_320_000,
        )
        enricher = _make_enricher(labels_to_add=["duration_ms:900000"])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)

        assert result.old_state == "ready"
        assert result.new_state == "ready"
        assert asset.duration_ms == 900_000
        assert asset.approved_for_broadcast is False


class TestEnrichAssetDurationGate:
    """Verify INV-ASSET-DURATION-REQUIRED-FOR-READY-001."""

    def test_promotes_to_ready_when_duration_positive(self):
        """duration_ms > 0 → state = 'ready'."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        enricher = _make_enricher(labels_to_add=["duration_ms:1320000"])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)
        assert asset.state == "ready"

    def test_reverts_to_new_when_duration_none(self):
        """duration_ms = None → state = 'new'."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        enricher = _make_enricher()
        pipeline = [(0, "noop", enricher)]

        result = enrich_asset(db, asset, pipeline)
        assert asset.state == "new"

    def test_reverts_to_new_when_duration_zero(self):
        """duration_ms = 0 → state = 'new'."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        enricher = _make_enricher(labels_to_add=["duration_ms:0"])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)
        assert asset.state == "new"


class TestEnrichAssetChecksum:
    """Verify last_enricher_checksum update."""

    def test_updates_checksum_when_provided(self):
        """Checksum is stored on asset when provided."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        enricher = _make_enricher(labels_to_add=["duration_ms:1000"])
        pipeline = [(0, "ffprobe", enricher)]
        checksum = "a" * 64

        result = enrich_asset(db, asset, pipeline, pipeline_checksum=checksum)

        assert asset.last_enricher_checksum == checksum
        assert result.checksum_applied == checksum

    def test_no_checksum_when_not_provided(self):
        """Checksum is not modified when not provided."""
        db = _make_mock_db()
        asset = _make_asset(state="new", last_enricher_checksum="old_checksum")
        enricher = _make_enricher(labels_to_add=["duration_ms:1000"])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline)

        assert asset.last_enricher_checksum == "old_checksum"
        assert result.checksum_applied is None


class TestEnrichAssetPipelineExecution:
    """Verify enricher pipeline execution behavior."""

    def test_enricher_error_continues_pipeline(self):
        """One enricher failure doesn't abort the rest."""
        db = _make_mock_db()
        asset = _make_asset(state="new")
        failing = _make_enricher(should_fail=True)
        succeeding = _make_enricher(labels_to_add=["duration_ms:1320000"])
        pipeline = [
            (0, "failing_enricher", failing),
            (1, "ffprobe", succeeding),
        ]

        result = enrich_asset(db, asset, pipeline)

        assert len(result.enricher_errors) == 1
        assert "failing_enricher" in result.enricher_errors[0]
        assert asset.duration_ms == 1_320_000
        assert asset.state == "ready"

    def test_empty_pipeline_no_crash(self):
        """Empty pipeline produces no enrichment; asset stays new."""
        db = _make_mock_db()
        asset = _make_asset(state="new")

        result = enrich_asset(db, asset, [])

        assert asset.state == "new"
        assert result.enricher_errors == []


class TestEnrichAssetResult:
    """Verify EnrichResult shape."""

    def test_returns_enrich_result(self):
        """Return type is EnrichResult with correct field values."""
        db = _make_mock_db()
        asset = _make_asset(state="ready", duration_ms=1_320_000)
        enricher = _make_enricher(labels_to_add=["duration_ms:900000"])
        pipeline = [(0, "ffprobe", enricher)]

        result = enrich_asset(db, asset, pipeline, pipeline_checksum="abc123")

        assert isinstance(result, EnrichResult)
        assert result.asset_uuid == str(asset.uuid)
        assert result.old_state == "ready"
        assert result.new_state == "ready"
        assert result.old_duration_ms == 1_320_000
        assert result.new_duration_ms == 900_000
        assert result.checksum_applied == "abc123"


class TestEnrichAssetEditorialMerge:
    """Verify editorial metadata is merged, not replaced."""

    def test_merges_editorial_into_existing(self):
        """Enricher editorial is merged into existing AssetEditorial payload."""
        db = _make_mock_db()
        existing_ed = MagicMock()
        existing_ed.payload = {"title": "Original Title", "series_title": "My Show"}

        def mock_get(cls, uuid):
            name = cls.__name__ if hasattr(cls, "__name__") else str(cls)
            if name == "AssetEditorial":
                return existing_ed
            return None

        db.get = MagicMock(side_effect=mock_get)

        asset = _make_asset(state="new")
        enricher = _make_enricher(
            labels_to_add=["duration_ms:1000"],
            editorial={"interstitial_type": "bumper"},
        )
        pipeline = [(0, "type_enricher", enricher)]

        enrich_asset(db, asset, pipeline)

        # existing_ed.payload should be merged (original + new)
        assert existing_ed.payload["title"] == "Original Title"
        assert existing_ed.payload["series_title"] == "My Show"
        assert existing_ed.payload["interstitial_type"] == "bumper"


class TestExtractLabel:
    """Unit tests for the label extraction helper."""

    def test_extracts_known_key(self):
        assert _extract_label(["duration_ms:1320000", "video_codec:h264"], "duration_ms") == "1320000"

    def test_returns_none_for_missing_key(self):
        assert _extract_label(["video_codec:h264"], "duration_ms") is None

    def test_returns_none_for_empty_list(self):
        assert _extract_label([], "duration_ms") is None

    def test_handles_colon_in_value(self):
        assert _extract_label(["path:/media/file:2.mp4"], "path") == "/media/file:2.mp4"
