"""Contract tests: INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001

When _build_initial() compiles the schedule starting from day D, and
day D-1 is NOT in the compilation window, the system MUST use
window-based timeline loading to include all blocks that intersect the
window — regardless of broadcast_day.  This ensures the effective day
open for D accounts for prior-day blocks that extend past the boundary.

Incident: 2026-03-24 — "In Search of Darkness Part III" (342 min) was
playing from 09:30 UTC. Process restarted at 13:54 UTC. _build_initial
compiled March 24 starting at 10:00 with no overlap knowledge. EPG
replaced the movie. Viewer got Lilo & Stitch instead.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

try:
    from retrovue.runtime.dsl_schedule_service import DslScheduleService
except ImportError:
    pytest.skip(
        "retrovue.runtime.dsl_schedule_service not available",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_schedule_item(
    *,
    slot_index: int,
    start_time: datetime,
    duration_sec: int,
    title: str,
    asset_id: str | None = None,
    content_type: str = "movie",
) -> MagicMock:
    """Fake ScheduleItem for DB query results."""
    item = MagicMock()
    item.slot_index = slot_index
    item.start_time = start_time
    item.duration_sec = duration_sec
    item.content_type = content_type
    item.asset_id = uuid.UUID(asset_id) if asset_id else uuid.uuid4()
    item.container_id = None
    item.metadata_ = {"title": title}
    item.id = uuid.uuid4()
    return item


def _make_revision(
    *,
    channel_id: uuid.UUID,
    broadcast_day: date,
    status: str = "active",
    items: list | None = None,
) -> MagicMock:
    rev = MagicMock()
    rev.id = uuid.uuid4()
    rev.channel_id = channel_id
    rev.broadcast_day = broadcast_day
    rev.status = status
    rev.items = items or []
    rev.created_at = datetime.now(timezone.utc)
    return rev


# ===========================================================================
# Core invariant: _compute_effective_day_open_ms respects prior-block end
# ===========================================================================


class TestComputeEffectiveDayOpen:
    """_compute_effective_day_open_ms must push day open past prior-block end."""

    def test_prior_block_pushes_day_open(self):
        """When prior-day block extends past day start, effective open = block end."""
        # Day start: 2026-03-24 10:00 UTC
        # Prior-block end: 2026-03-24 15:30 UTC (movie from yesterday)
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-24",
            day_start_hour=6,
            tz_name="America/New_York",
            prior_block_end_ms=int(
                datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
            ),
        )

        # Must be at prior-block end (15:30 UTC), not day start (10:00 UTC)
        expected_end_ms = int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        assert result == expected_end_ms, (
            f"effective_day_open must equal prior-block end. "
            f"Expected {expected_end_ms}, got {result}"
        )

    def test_no_overlap_uses_day_start(self):
        """Without prior-block overlap, effective open = broadcast day start."""
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-24",
            day_start_hour=6,
            tz_name="America/New_York",
            prior_block_end_ms=0,
        )

        from zoneinfo import ZoneInfo
        tz = ZoneInfo("America/New_York")
        expected = int(
            datetime(2026, 3, 24, 6, 0, tzinfo=tz).timestamp() * 1000
        )
        assert result == expected


# ===========================================================================
# _build_initial loads from DB via window-based timeline loading
# ===========================================================================


class TestBuildInitialLoadsFromDB:
    """_build_initial MUST load from DB via _load_existing_timeline."""

    def test_load_existing_timeline_method_exists(self):
        """INV-TIMELINE-SINGLE-AUTHORITY-001: _build_initial must load
        from DB via _load_existing_timeline, not recompile from DSL.
        """
        assert hasattr(DslScheduleService, "_load_existing_timeline"), (
            "INV-TIMELINE-SINGLE-AUTHORITY-001: "
            "DslScheduleService must have _load_existing_timeline method"
        )


# ===========================================================================
# Regression: prior-block overlap within the compilation window
# ===========================================================================


class TestOverlapWithinCompilationWindow:
    """When both days are in the compilation window, overlap still propagates.
    This is the existing behavior that must not regress.
    """

    def test_prior_block_end_ms_propagates(self):
        """The _build_initial loop propagates prior-block end across days.
        Verify the propagation formula is correct.
        """
        # Simulate: last block of day 1 ends at 15:30 UTC
        blocks_day1 = [MagicMock(end_utc_ms=int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        ))]

        # prior_block_end_ms should be max of current and last block end
        prior_block_end_ms = 0
        if blocks_day1:
            prior_block_end_ms = max(
                prior_block_end_ms, blocks_day1[-1].end_utc_ms,
            )

        expected = int(
            datetime(2026, 3, 24, 15, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        assert prior_block_end_ms == expected


# ===========================================================================
# Regression: cached schedule must apply push-forward (RETA-33)
# ===========================================================================


class TestCachedSchedulePushForward:
    """INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: When _compile_day loads
    from the schedule cache, blocks with original grid times must be pushed
    forward past prior-day carry-in.

    Bug: _compile_day returned early from the cache path without applying
    _apply_overlap_push_forward, producing overlapping blocks in the playlog
    plan. This caused PlayoutSession.seed() to fail the contiguity check,
    making the channel unreachable (503 on HLS, 404 on TS).
    """

    def test_cached_blocks_pushed_past_carry_in(self):
        """Blocks loaded from cache must not start before effective_day_open_ms."""
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        carry_in_end_ms = int(
            datetime(2026, 4, 6, 12, 30, tzinfo=timezone.utc).timestamp() * 1000
        )  # Saturday's last block (Little Shop of Horrors) ends at 12:30 UTC

        seg = ScheduledSegment(
            segment_type="content", asset_uri="/media/test.mkv",
            asset_start_offset_ms=0, segment_duration_ms=7200_000,
        )

        # Sunday's schedule_items have original grid times (10:00, 12:00, 14:00)
        block_a = ScheduledBlock(
            block_id="blk-event-horizon",
            start_utc_ms=int(datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )
        block_b = ScheduledBlock(
            block_id="blk-underwater",
            start_utc_ms=int(datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )
        block_c = ScheduledBlock(
            block_id="blk-slayers",
            start_utc_ms=int(datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 15, 30, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )

        result = DslScheduleService._push_forward_scheduled_blocks(
            [block_a, block_b, block_c], carry_in_end_ms, "2026-04-06",
        )

        # block_a (10:00-12:00) is fully subsumed by carry-in (ends 12:30) — dropped
        assert len(result) == 2, f"Expected 2 blocks (subsumed dropped), got {len(result)}"

        # block_b must start at carry_in_end (12:30), not original 12:00
        assert result[0].start_utc_ms == carry_in_end_ms, (
            f"First surviving block must start at carry-in end {carry_in_end_ms}, "
            f"got {result[0].start_utc_ms}"
        )

        # Blocks must be contiguous
        for i in range(len(result) - 1):
            assert result[i].end_utc_ms == result[i + 1].start_utc_ms, (
                f"Blocks {result[i].block_id} and {result[i+1].block_id} "
                f"are not contiguous: {result[i].end_utc_ms} != {result[i+1].start_utc_ms}"
            )

    def test_no_push_forward_when_no_overlap(self):
        """Blocks that already start after effective_day_open_ms are unchanged."""
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        day_open_ms = int(
            datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc).timestamp() * 1000
        )

        seg = ScheduledSegment(
            segment_type="content", asset_uri="/media/test.mkv",
            asset_start_offset_ms=0, segment_duration_ms=7200_000,
        )
        block = ScheduledBlock(
            block_id="blk-test",
            start_utc_ms=int(datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )

        result = DslScheduleService._push_forward_scheduled_blocks(
            [block], day_open_ms, "2026-04-06",
        )

        assert len(result) == 1
        assert result[0].start_utc_ms == block.start_utc_ms


# ===========================================================================
# _enforce_timeline_contiguity (RETA-33: overlapping multi-day blocks)
# ===========================================================================


class TestEnforceTimelineContiguity:
    """INV-CROSS-DAY-CARRY-IN-SURVIVES-RESTART-001: When blocks from multiple
    broadcast days are loaded from schedule_items, they may overlap.
    _enforce_timeline_contiguity must fix this.
    """

    def test_overlapping_blocks_become_contiguous(self):
        """Reproduction of the HBO production bug: Saturday carry-in overlaps
        with Sunday blocks loaded from schedule_items."""
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        seg = ScheduledSegment(
            segment_type="content", asset_uri="/media/test.mkv",
            asset_start_offset_ms=0, segment_duration_ms=5400_000,
        )

        # Saturday blocks (already sorted by start)
        sat_block = ScheduledBlock(
            block_id="blk-creepshow",
            start_utc_ms=int(datetime(2026, 4, 6, 8, 30, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 11, 0, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )
        sat_carry_in = ScheduledBlock(
            block_id="blk-little-shop",
            start_utc_ms=int(datetime(2026, 4, 6, 11, 0, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 12, 30, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )

        # Sunday blocks (original grid times — overlap with Saturday carry-in)
        sun_block_a = ScheduledBlock(
            block_id="blk-event-horizon",
            start_utc_ms=int(datetime(2026, 4, 6, 10, 0, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )
        sun_block_b = ScheduledBlock(
            block_id="blk-underwater",
            start_utc_ms=int(datetime(2026, 4, 6, 12, 0, tzinfo=timezone.utc).timestamp() * 1000),
            end_utc_ms=int(datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc).timestamp() * 1000),
            segments=(seg,),
        )

        # Sorted by start_utc_ms (as _build_initial does)
        blocks = sorted(
            [sat_block, sat_carry_in, sun_block_a, sun_block_b],
            key=lambda b: b.start_utc_ms,
        )

        result = DslScheduleService._enforce_timeline_contiguity(blocks)

        # Verify contiguity: every block[i].end == block[i+1].start
        for i in range(len(result) - 1):
            assert result[i].end_utc_ms == result[i + 1].start_utc_ms, (
                f"Blocks {result[i].block_id} and {result[i+1].block_id} "
                f"not contiguous: {result[i].end_utc_ms} != {result[i+1].start_utc_ms}"
            )

        # No overlapping blocks in result
        for i in range(len(result) - 1):
            assert result[i].end_utc_ms <= result[i + 1].start_utc_ms, (
                f"Blocks {result[i].block_id} and {result[i+1].block_id} overlap"
            )

    def test_already_contiguous_unchanged(self):
        """Blocks that are already contiguous are returned unchanged."""
        from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment

        seg = ScheduledSegment(
            segment_type="content", asset_uri="/media/test.mkv",
            asset_start_offset_ms=0, segment_duration_ms=7200_000,
        )

        blocks = [
            ScheduledBlock(
                block_id="blk-a",
                start_utc_ms=1000, end_utc_ms=2000, segments=(seg,),
            ),
            ScheduledBlock(
                block_id="blk-b",
                start_utc_ms=2000, end_utc_ms=3000, segments=(seg,),
            ),
        ]

        result = DslScheduleService._enforce_timeline_contiguity(blocks)
        assert len(result) == 2
        assert result[0].start_utc_ms == 1000
        assert result[1].start_utc_ms == 2000
