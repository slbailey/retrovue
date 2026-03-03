# pkg/core/tests/contracts/test_tier2_window_uuid_propagation.py
#
# Contract tests for INV-TIER2-WINDOW-UUID-PROPAGATION-001.
#
# Verifies that PlaylistBuilderDaemon propagates window_uuid from Tier 1
# block dicts into PlaylistEvent.window_uuid column when writing Tier 2 rows.
#
# Strategy:
#   - Unit-test _write_to_txlog directly with a mock DB session.
#   - Verify window_uuid appears as a top-level column on the row.
#   - Verify legacy blocks (no window_uuid) produce NULL column value.
#   - Verify window_uuid does NOT leak into segment dicts.

from __future__ import annotations

import uuid as uuid_mod
from datetime import date
from unittest.mock import MagicMock

import pytest

from retrovue.runtime.playlist_builder_daemon import PlaylistBuilderDaemon
from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_daemon() -> PlaylistBuilderDaemon:
    """Create a minimal daemon instance for unit testing."""
    return PlaylistBuilderDaemon(channel_id="test-ch")


def _make_block(block_id: str = "block-001") -> ScheduledBlock:
    """Create a minimal ScheduledBlock with two segments."""
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=1709510400000,  # 2024-03-04 00:00 UTC
        end_utc_ms=1709517600000,    # 2024-03-04 02:00 UTC
        segments=(
            ScheduledSegment(
                segment_type="content",
                asset_uri="/assets/movie.mp4",
                asset_start_offset_ms=0,
                segment_duration_ms=7200000,
            ),
            ScheduledSegment(
                segment_type="filler",
                asset_uri="/assets/filler.mp4",
                asset_start_offset_ms=0,
                segment_duration_ms=30000,
            ),
        ),
    )


class _MockDB:
    """Captures PlaylistEvent rows passed to db.merge()."""

    def __init__(self) -> None:
        self.merged: list = []

    def merge(self, obj):
        self.merged.append(obj)

    def commit(self):
        pass


# ─────────────────────────────────────────────────────────────────────────────
# INV-TIER2-WINDOW-UUID-PROPAGATION-001 — Rule 1: Propagation (column)
# ─────────────────────────────────────────────────────────────────────────────


class TestTier2WindowUuidPropagation:
    """INV-TIER2-WINDOW-UUID-PROPAGATION-001: window_uuid flows from Tier 1
    block dicts into PlaylistEvent.window_uuid column."""

    def test_window_uuid_set_on_row(self):
        """Rule 1: When window_uuid is provided, the PlaylistEvent row
        must have window_uuid set as a top-level column."""
        daemon = _make_daemon()
        block = _make_block()
        db = _MockDB()
        test_uuid = str(uuid_mod.uuid4())

        daemon._write_to_txlog(block, date(2024, 3, 4), window_uuid=test_uuid, db=db)

        assert len(db.merged) == 1
        row = db.merged[0]
        assert row.window_uuid == test_uuid

    def test_window_uuid_exact_match(self):
        """Rule 2: The propagated UUID must exactly match the input value."""
        daemon = _make_daemon()
        block = _make_block()
        db = _MockDB()
        test_uuid = "550e8400-e29b-41d4-a716-446655440000"

        daemon._write_to_txlog(block, date(2024, 3, 4), window_uuid=test_uuid, db=db)

        row = db.merged[0]
        assert row.window_uuid == test_uuid

    def test_window_uuid_not_in_segment_dicts(self):
        """Rule 4: window_uuid must NOT be injected into segment dicts —
        it lives on the row column only."""
        daemon = _make_daemon()
        block = _make_block()
        db = _MockDB()
        test_uuid = str(uuid_mod.uuid4())

        daemon._write_to_txlog(block, date(2024, 3, 4), window_uuid=test_uuid, db=db)

        row = db.merged[0]
        for seg in row.segments:
            assert "window_uuid" not in seg, (
                f"window_uuid should not be in segment dict: {seg}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# INV-TIER2-WINDOW-UUID-PROPAGATION-001 — Rule 3: Legacy compatibility
# ─────────────────────────────────────────────────────────────────────────────


class TestTier2LegacyCompatibility:
    """INV-TIER2-WINDOW-UUID-PROPAGATION-001 Rule 3: Legacy blocks without
    window_uuid produce PlaylistEvent rows with NULL window_uuid column."""

    def test_no_window_uuid_when_not_provided(self):
        """Legacy path: _write_to_txlog without window_uuid produces
        a row with window_uuid=None."""
        daemon = _make_daemon()
        block = _make_block()
        db = _MockDB()

        daemon._write_to_txlog(block, date(2024, 3, 4), db=db)

        row = db.merged[0]
        assert row.window_uuid is None

    def test_segments_structure_preserved(self):
        """Legacy path: segment dicts retain all existing fields unchanged."""
        daemon = _make_daemon()
        block = _make_block()
        db = _MockDB()

        daemon._write_to_txlog(block, date(2024, 3, 4), db=db)

        row = db.merged[0]
        seg0 = row.segments[0]
        assert seg0["segment_index"] == 0
        assert seg0["segment_type"] == "content"
        assert seg0["asset_uri"] == "/assets/movie.mp4"
        assert seg0["segment_duration_ms"] == 7200000


# ─────────────────────────────────────────────────────────────────────────────
# INV-TIER2-WINDOW-UUID-PROPAGATION-001 — Provenance distinctness
# ─────────────────────────────────────────────────────────────────────────────


class TestTier2ProvenanceDistinctness:
    """Future-proof: different Tier 1 window_uuids produce distinct UUID
    values on PlaylistEvent rows. This proves provenance chains are
    independent — prerequisite for future staleness detection."""

    def test_different_windows_produce_different_uuids(self):
        """Two blocks with different window_uuids produce PlaylistEvent
        rows carrying their respective distinct UUID values."""
        daemon = _make_daemon()
        db = _MockDB()

        uuid_a = str(uuid_mod.uuid4())
        uuid_b = str(uuid_mod.uuid4())
        assert uuid_a != uuid_b  # sanity

        block_a = _make_block(block_id="block-a")
        block_b = _make_block(block_id="block-b")

        daemon._write_to_txlog(block_a, date(2024, 3, 4), window_uuid=uuid_a, db=db)
        daemon._write_to_txlog(block_b, date(2024, 3, 4), window_uuid=uuid_b, db=db)

        assert len(db.merged) == 2
        row_a = db.merged[0]
        row_b = db.merged[1]

        # Each row carries its own UUID on the column
        assert row_a.window_uuid == uuid_a
        assert row_b.window_uuid == uuid_b
        assert row_a.window_uuid != row_b.window_uuid
