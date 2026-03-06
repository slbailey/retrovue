# pkg/core/tests/domain/test_preview_filler_args.py
#
# Contract test: preview_at reads Tier-2 PlaylistEvent directly.
#
# Invariant: preview_at must show what the daemon wrote to Tier-2,
# not re-expand from Tier-1. Filler args are no longer relevant
# because preview reads pre-filled data.

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest


def _setup_db(db, row):
    mock_query = MagicMock()
    mock_filter = MagicMock()
    mock_filter.first.return_value = row
    mock_query.filter.return_value = mock_filter
    db.query.return_value = mock_query


class TestPreviewReadsTier2:
    """preview_at must read directly from PlaylistEvent (Tier-2 truth)."""

    def test_returns_tier2_segments(self):
        """preview_at returns segments from PlaylistEvent, not re-expanded."""
        from retrovue.usecases.schedule_preview import preview_at

        at = datetime(2026, 3, 6, 12, 0, 0, tzinfo=timezone.utc)
        at_ms = int(at.timestamp() * 1000)

        row = MagicMock()
        row.block_id = "test-block"
        row.start_utc_ms = at_ms - 1000
        row.end_utc_ms = at_ms + 3_600_000
        row.segments = [
            {"segment_type": "content", "asset_uri": "/movie.mp4",
             "asset_start_offset_ms": 0, "segment_duration_ms": 3_000_000},
            {"segment_type": "promo", "asset_uri": "/promo-01.mp4",
             "asset_start_offset_ms": 0, "segment_duration_ms": 30_000},
        ]

        db = MagicMock()
        _setup_db(db, row)

        result = preview_at(db, channel_slug="hbo-classics", at=at)

        assert "error" not in result
        assert result["block_id"] == "test-block"
        assert result["segment_count"] == 2
        types = [s["segment_type"] for s in result["segments"]]
        assert types == ["content", "promo"]

    def test_returns_error_when_no_tier2_block(self):
        """preview_at returns error when no PlaylistEvent covers the time."""
        from retrovue.usecases.schedule_preview import preview_at

        at = datetime(2026, 3, 6, 12, 0, 0, tzinfo=timezone.utc)

        db = MagicMock()
        _setup_db(db, None)

        result = preview_at(db, channel_slug="hbo-classics", at=at)

        assert "error" in result
