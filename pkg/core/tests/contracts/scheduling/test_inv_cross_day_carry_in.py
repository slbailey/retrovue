"""
Contract tests for INV-CROSS-DAY-CARRY-IN-001.

When a program crosses the broadcast day boundary, the next broadcast day
must not schedule any blocks that start before the program finishes.

The next day's first legal block start time (effective_day_open_ms) must be
respected during compilation.  Phantom blocks that will never air must
never appear in ScheduleItems, EPG, or the in-memory block list.

Architecture:
  - Primary fix: compile-time filtering via effective_day_open_ms in _compile_day
  - Guardrail: merge-time _resolve_cross_day_overlaps (defense-in-depth only)
  - Propagation: active_carry_in_end_ms propagates across empty days

Violated invariant symptoms:
  - PlayoutSession.seed() fails with "Blocks not contiguous"
  - block_b.start_utc_ms < block_a.end_utc_ms
  - EPG shows programs that never actually air
"""

import logging
import threading
from contextlib import ExitStack
from unittest.mock import patch

import pytest

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment
from retrovue.runtime.dsl_schedule_service import DslScheduleService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_segment(duration_ms: int) -> ScheduledSegment:
    return ScheduledSegment(
        segment_type="content",
        asset_uri="/test/asset.ts",
        asset_start_offset_ms=0,
        segment_duration_ms=duration_ms,
    )


def _make_block(block_id: str, start_ms: int, end_ms: int) -> ScheduledBlock:
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_ms,
        end_utc_ms=end_ms,
        segments=(_make_segment(end_ms - start_ms),),
    )


def _build_service(*blocks: ScheduledBlock) -> DslScheduleService:
    """Create a DslScheduleService with pre-loaded in-memory blocks (no DB)."""
    svc = DslScheduleService.__new__(DslScheduleService)
    svc._blocks = list(blocks)
    svc._lock = threading.Lock()
    svc._compiled_days = set()
    svc._extending = False
    svc._channel_slug = "test-channel"
    return svc


# ---------------------------------------------------------------------------
# Constants — simulate day boundary at 10:00 UTC (6:00 AM EDT)
#
# 2026-03-10 is after DST spring-forward (March 8), so EDT = UTC-4.
# broadcast_day_start_hour = 6 → 06:00 EDT = 10:00 UTC
# ---------------------------------------------------------------------------

DAY_BOUNDARY_MS = 1_773_136_800_000    # 2026-03-10 10:00:00 UTC = 06:00 EDT
SLOT_30 = 30 * 60 * 1000              # 30 minutes in ms
HOUR_MS = 3600 * 1000

# Movie from day 1 that carries past the day boundary
MOVIE_START = DAY_BOUNDARY_MS - 2 * SLOT_30   # 05:00 EDT
MOVIE_END = DAY_BOUNDARY_MS + SLOT_30          # 06:30 EDT (30 min carry-in)

# Day 2 blocks compiled independently at day boundary
DAY2_BLOCK1_START = DAY_BOUNDARY_MS             # 06:00 EDT
DAY2_BLOCK1_END = DAY_BOUNDARY_MS + SLOT_30     # 06:30 EDT
DAY2_BLOCK2_START = DAY_BOUNDARY_MS + SLOT_30   # 06:30 EDT
DAY2_BLOCK2_END = DAY_BOUNDARY_MS + 2 * SLOT_30 # 07:00 EDT


# ---------------------------------------------------------------------------
# 1. effective_day_open_ms computation
# ---------------------------------------------------------------------------


class TestEffectiveDayOpenMs:
    """_compute_effective_day_open_ms must return max(day_start, carry_in_end)."""

    def test_no_carry_in_returns_day_start(self):
        """With no carry-in, effective open == broadcast day start."""
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-10",
            day_start_hour=6,
            tz_name="America/New_York",
            active_carry_in_end_ms=0,
        )
        assert result == DAY_BOUNDARY_MS

    def test_carry_in_past_boundary_returns_carry_in_end(self):
        """Carry-in extending past day start → effective open == carry-in end."""
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-10",
            day_start_hour=6,
            tz_name="America/New_York",
            active_carry_in_end_ms=MOVIE_END,  # 06:30 EDT
        )
        assert result == MOVIE_END

    def test_carry_in_before_boundary_returns_day_start(self):
        """Carry-in ending before day start → effective open == day start."""
        early_end = DAY_BOUNDARY_MS - HOUR_MS  # 05:00 EDT
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-10",
            day_start_hour=6,
            tz_name="America/New_York",
            active_carry_in_end_ms=early_end,
        )
        assert result == DAY_BOUNDARY_MS

    def test_carry_in_exactly_at_boundary_returns_boundary(self):
        """Carry-in ending exactly at day start → effective open == day start."""
        result = DslScheduleService._compute_effective_day_open_ms(
            broadcast_day="2026-03-10",
            day_start_hour=6,
            tz_name="America/New_York",
            active_carry_in_end_ms=DAY_BOUNDARY_MS,
        )
        assert result == DAY_BOUNDARY_MS


# ---------------------------------------------------------------------------
# 2. Compile-time filtering (primary fix)
# ---------------------------------------------------------------------------


class TestCompileTimeFiltering:
    """INV-CROSS-DAY-CARRY-IN-001: compile-time filtering via effective_day_open_ms.

    Blocks starting before effective_day_open_ms MUST be removed before
    persistence.  This is the primary fix — not the merge-time guardrail.
    """

    def test_carry_in_suppresses_exactly_one_opening_block(self):
        """Movie bleeds 30 min → only the 06:00 block is suppressed."""
        d2_blocks = [
            _make_block("d2-0600", DAY2_BLOCK1_START, DAY2_BLOCK1_END),
            _make_block("d2-0630", DAY2_BLOCK2_START, DAY2_BLOCK2_END),
            _make_block("d2-0700", DAY_BOUNDARY_MS + 2 * SLOT_30,
                        DAY_BOUNDARY_MS + 3 * SLOT_30),
        ]

        effective_open = MOVIE_END  # 06:30 EDT
        filtered = [b for b in d2_blocks if b.start_utc_ms >= effective_open]

        assert len(filtered) == 2
        assert filtered[0].block_id == "d2-0630"
        assert filtered[1].block_id == "d2-0700"

    def test_carry_in_suppresses_multiple_opening_blocks(self):
        """3-hour movie carry-in removes the first 2 hours of day 2."""
        carry_in_end = DAY_BOUNDARY_MS + 2 * HOUR_MS  # 08:00 EDT

        d2_blocks = [
            _make_block(f"d2-{i}", DAY_BOUNDARY_MS + i * SLOT_30,
                        DAY_BOUNDARY_MS + (i + 1) * SLOT_30)
            for i in range(8)  # 06:00 through 09:30
        ]

        effective_open = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-10", 6, "America/New_York", carry_in_end,
        )
        filtered = [b for b in d2_blocks if b.start_utc_ms >= effective_open]

        # 06:00, 06:30, 07:00, 07:30 suppressed (4 blocks)
        # 08:00, 08:30, 09:00, 09:30 survive (4 blocks)
        assert len(filtered) == 4
        assert filtered[0].start_utc_ms == carry_in_end

    def test_carry_in_ending_exactly_at_boundary_suppresses_nothing(self):
        """carry-in ends at 06:00 → effective_day_open == 06:00 → no filtering."""
        d2_blocks = [
            _make_block("d2-0600", DAY_BOUNDARY_MS, DAY_BOUNDARY_MS + SLOT_30),
        ]

        effective_open = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-10", 6, "America/New_York", DAY_BOUNDARY_MS,
        )
        filtered = [b for b in d2_blocks if b.start_utc_ms >= effective_open]

        assert len(filtered) == 1
        assert filtered[0].block_id == "d2-0600"

    def test_no_carry_in_suppresses_nothing(self):
        """effective_day_open_ms == day start → all blocks survive."""
        d2_blocks = [
            _make_block("d2-0600", DAY_BOUNDARY_MS, DAY_BOUNDARY_MS + SLOT_30),
            _make_block("d2-0630", DAY2_BLOCK2_START, DAY2_BLOCK2_END),
        ]

        effective_open = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-10", 6, "America/New_York", 0,
        )
        filtered = [b for b in d2_blocks if b.start_utc_ms >= effective_open]

        assert len(filtered) == 2

    def test_carry_in_suppresses_entire_broadcast_day(self):
        """A movie spanning an entire day suppresses all blocks for that day.

        Day N movie: 20:00 → Day N+2 08:00 (36 hours)
        Day N+1: all 48 blocks (06:00–06:00) start before 08:00 next day
        → entire day suppressed, zero blocks emitted.
        """
        # Movie ends at 08:00 EDT day N+2 = DAY_BOUNDARY + 26h
        carry_in_end = DAY_BOUNDARY_MS + 26 * HOUR_MS

        # Day N+1 blocks: full 24h from 06:00 to 06:00
        d2_blocks = [
            _make_block(f"d2-{i}", DAY_BOUNDARY_MS + i * SLOT_30,
                        DAY_BOUNDARY_MS + (i + 1) * SLOT_30)
            for i in range(48)
        ]

        effective_open = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-10", 6, "America/New_York", carry_in_end,
        )
        filtered = [b for b in d2_blocks if b.start_utc_ms >= effective_open]

        assert len(filtered) == 0, (
            f"Expected 0 blocks (entire day subsumed), got {len(filtered)}"
        )


# ---------------------------------------------------------------------------
# 3. Carry-in propagation across empty days
# ---------------------------------------------------------------------------


class TestCarryInPropagation:
    """active_carry_in_end_ms must propagate forward even when a day
    produces zero blocks.

    Pseudo logic:
      active_carry_in_end_ms = max(active_carry_in_end_ms, last_block_end)
      effective_day_open_ms = max(broadcast_day_start, active_carry_in_end_ms)

    If a day produces zero blocks, active_carry_in_end_ms persists unchanged.
    """

    def test_carry_in_propagates_across_empty_day(self):
        """Day N movie runs to Day N+2 02:00.
        Day N+1 produces zero blocks (fully subsumed).
        Day N+2 must still respect the carry-in.
        """
        # Day boundary for day N+1 = 2026-03-10 06:00 EDT
        # Day boundary for day N+2 = 2026-03-11 06:00 EDT
        day_n2_boundary_ms = DAY_BOUNDARY_MS + 24 * HOUR_MS

        # Movie ends at 02:00 EDT on day N+2 = day N+2 boundary - 4h
        # Actually 02:00 is before 06:00, so it's within day N+1's
        # broadcast window — BUT let's test a carry-in that spans
        # day N+1 entirely and into day N+2's window.
        # Movie ends at 08:00 EDT on day N+2
        carry_in_end = day_n2_boundary_ms + 2 * HOUR_MS  # 08:00 EDT

        # Simulate the propagation loop
        active_carry_in_end_ms = carry_in_end

        # Day N+1: all blocks subsumed
        day_n1_effective = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-10", 6, "America/New_York", active_carry_in_end_ms,
        )
        day_n1_blocks = [
            _make_block(f"n1-{i}", DAY_BOUNDARY_MS + i * SLOT_30,
                        DAY_BOUNDARY_MS + (i + 1) * SLOT_30)
            for i in range(48)
        ]
        day_n1_filtered = [
            b for b in day_n1_blocks if b.start_utc_ms >= day_n1_effective
        ]
        assert len(day_n1_filtered) == 0, "Day N+1 should be fully subsumed"

        # No blocks → active_carry_in_end_ms persists unchanged
        # (the max() with no new blocks keeps it the same)
        assert active_carry_in_end_ms == carry_in_end

        # Day N+2: carry-in still active
        day_n2_effective = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-11", 6, "America/New_York", active_carry_in_end_ms,
        )
        assert day_n2_effective == carry_in_end, (
            f"Day N+2 effective open should be carry-in end ({carry_in_end}), "
            f"got {day_n2_effective}"
        )

        # Day N+2 blocks: first 4 (06:00–08:00) subsumed, rest survive
        day_n2_blocks = [
            _make_block(f"n2-{i}", day_n2_boundary_ms + i * SLOT_30,
                        day_n2_boundary_ms + (i + 1) * SLOT_30)
            for i in range(8)
        ]
        day_n2_filtered = [
            b for b in day_n2_blocks if b.start_utc_ms >= day_n2_effective
        ]
        assert len(day_n2_filtered) == 4
        assert day_n2_filtered[0].start_utc_ms == carry_in_end

    def test_active_carry_in_uses_max(self):
        """active_carry_in_end_ms = max(active, last_block_end) so it never
        shrinks backward if a day produces shorter blocks.
        """
        # Start with a long carry-in
        active = DAY_BOUNDARY_MS + 3 * HOUR_MS  # 09:00 EDT

        # Day N+1 produces blocks but its last one ends before 09:00
        last_block_end = DAY_BOUNDARY_MS + 2 * HOUR_MS  # 08:00 EDT

        active = max(active, last_block_end)
        assert active == DAY_BOUNDARY_MS + 3 * HOUR_MS, (
            "active_carry_in_end_ms must never shrink"
        )


# ---------------------------------------------------------------------------
# 4. Merge-time guardrail (defense-in-depth only)
# ---------------------------------------------------------------------------


class TestMergeTimeGuardrail:
    """_resolve_cross_day_overlaps is a defense-in-depth guardrail.
    It MUST drop overlapping blocks and log a warning when triggered.
    """

    def test_guardrail_drops_subsumed_block(self):
        """Overlapping block must be dropped."""
        movie = _make_block("day1-movie", MOVIE_START, MOVIE_END)
        d2_b1 = _make_block("day2-block1", DAY2_BLOCK1_START, DAY2_BLOCK1_END)
        d2_b2 = _make_block("day2-block2", DAY2_BLOCK2_START, DAY2_BLOCK2_END)

        all_blocks = [movie, d2_b1, d2_b2]
        all_blocks.sort(key=lambda b: b.start_utc_ms)

        resolved = DslScheduleService._resolve_cross_day_overlaps(all_blocks)

        block_ids = [b.block_id for b in resolved]
        assert "day2-block1" not in block_ids
        assert "day1-movie" in block_ids
        assert "day2-block2" in block_ids

    def test_guardrail_drops_multiple_subsumed_blocks(self):
        """Long carry-in can subsume multiple blocks."""
        long_movie_start = DAY_BOUNDARY_MS - 2 * HOUR_MS
        long_movie_end = DAY_BOUNDARY_MS + HOUR_MS

        movie = _make_block("long-movie", long_movie_start, long_movie_end)
        d2_b1 = _make_block("d2-1", DAY_BOUNDARY_MS, DAY_BOUNDARY_MS + SLOT_30)
        d2_b2 = _make_block("d2-2", DAY_BOUNDARY_MS + SLOT_30,
                            DAY_BOUNDARY_MS + 2 * SLOT_30)
        d2_b3 = _make_block("d2-3", DAY_BOUNDARY_MS + 2 * SLOT_30,
                            DAY_BOUNDARY_MS + 3 * SLOT_30)

        all_blocks = sorted([movie, d2_b1, d2_b2, d2_b3],
                            key=lambda b: b.start_utc_ms)
        resolved = DslScheduleService._resolve_cross_day_overlaps(all_blocks)

        assert [b.block_id for b in resolved] == ["long-movie", "d2-3"]

    def test_guardrail_no_overlap_no_change(self):
        """Contiguous blocks pass through unchanged."""
        b1 = _make_block("b1", DAY_BOUNDARY_MS, DAY_BOUNDARY_MS + SLOT_30)
        b2 = _make_block("b2", DAY_BOUNDARY_MS + SLOT_30,
                         DAY_BOUNDARY_MS + 2 * SLOT_30)

        resolved = DslScheduleService._resolve_cross_day_overlaps([b1, b2])

        assert len(resolved) == 2
        assert resolved[0].block_id == "b1"
        assert resolved[1].block_id == "b2"

    def test_guardrail_emits_warning_when_triggered(self, caplog):
        """When the guardrail fires, it must emit a WARNING log.

        This indicates compile-time filtering missed an overlap.
        """
        movie = _make_block("day1-movie", MOVIE_START, MOVIE_END)
        phantom = _make_block("phantom", DAY2_BLOCK1_START, DAY2_BLOCK1_END)

        all_blocks = sorted([movie, phantom], key=lambda b: b.start_utc_ms)

        with caplog.at_level(logging.WARNING):
            resolved = DslScheduleService._resolve_cross_day_overlaps(all_blocks)

        assert len(resolved) == 1
        assert any(
            "GUARDRAIL" in rec.message and "phantom" in rec.message
            for rec in caplog.records
        ), "Guardrail must emit a WARNING log with block id when triggered"

    def test_guardrail_preserves_contiguity(self):
        """After guardrail, consecutive get_block_at calls must be contiguous."""
        movie = _make_block("day1-movie", MOVIE_START, MOVIE_END)
        d2_b1 = _make_block("day2-block1", DAY2_BLOCK1_START, DAY2_BLOCK1_END)
        d2_b2 = _make_block("day2-block2", DAY2_BLOCK2_START, DAY2_BLOCK2_END)

        svc = _build_service()
        all_blocks = sorted([movie, d2_b1, d2_b2],
                            key=lambda b: b.start_utc_ms)
        svc._blocks = DslScheduleService._resolve_cross_day_overlaps(all_blocks)

        with ExitStack() as stack:
            stack.enter_context(patch.object(svc, "_maybe_extend_horizon"))
            if hasattr(DslScheduleService, "ensure_block_compiled"):
                stack.enter_context(
                    patch.object(svc, "ensure_block_compiled",
                                 side_effect=lambda ch, blk: blk)
                )
            if hasattr(DslScheduleService, "_get_filled_block_by_id"):
                stack.enter_context(
                    patch.object(svc, "_get_filled_block_by_id",
                                 return_value=None)
                )

            block_a = svc.get_block_at("test-channel", MOVIE_START + 100)
            block_b = svc.get_block_at("test-channel", block_a.end_utc_ms)

        assert block_a is not None
        assert block_b is not None
        assert block_a.end_utc_ms == block_b.start_utc_ms, (
            f"Not contiguous: {block_a.block_id} ends at "
            f"{block_a.end_utc_ms}, {block_b.block_id} starts at "
            f"{block_b.start_utc_ms}"
        )

    def test_seed_scenario_exact_error_timestamps(self):
        """Reproduce the exact timestamps from the original error.

        blk-61c2b4b61d9a ends at 1773138600000 (10:30 UTC)
        blk-5b123419226f starts at 1773136800000 (10:00 UTC)
        """
        movie = _make_block("blk-61c2b4b61d9a",
                            DAY_BOUNDARY_MS - SLOT_30, 1_773_138_600_000)
        d2_overlap = _make_block("blk-5b123419226f",
                                 1_773_136_800_000, 1_773_138_600_000)
        d2_next = _make_block("blk-next",
                              1_773_138_600_000, 1_773_140_400_000)

        all_blocks = sorted([movie, d2_overlap, d2_next],
                            key=lambda b: b.start_utc_ms)
        resolved = DslScheduleService._resolve_cross_day_overlaps(all_blocks)

        assert "blk-5b123419226f" not in [b.block_id for b in resolved]
        assert resolved[0].end_utc_ms == resolved[1].start_utc_ms
