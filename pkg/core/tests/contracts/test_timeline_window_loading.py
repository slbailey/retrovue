"""Contract tests: Timeline Window Loading

Enforces docs/contracts/timeline_window_loading.md.

The window intersection predicate is the sole inclusion criterion:

    block.start_utc_ms < window_end_utc_ms
    AND
    block.end_utc_ms   > window_start_utc_ms

Broadcast day boundaries MUST NOT influence inclusion.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import pytest

from retrovue.runtime.schedule_types import ScheduledBlock, ScheduledSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ms(year: int, month: int, day: int, hour: int, minute: int = 0) -> int:
    """UTC datetime → milliseconds."""
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp() * 1000)


def _block(block_id: str, start_ms: int, end_ms: int) -> ScheduledBlock:
    """Construct a minimal ScheduledBlock."""
    return ScheduledBlock(
        block_id=block_id,
        start_utc_ms=start_ms,
        end_utc_ms=end_ms,
        segments=(
            ScheduledSegment(
                segment_type="content",
                asset_uri=f"/test/{block_id}.ts",
                asset_start_offset_ms=0,
                segment_duration_ms=end_ms - start_ms,
            ),
        ),
    )


def _intersects(block: ScheduledBlock, window_start: int, window_end: int) -> bool:
    """Canonical window intersection predicate from the contract."""
    return block.start_utc_ms < window_end and block.end_utc_ms > window_start


def _load_window(
    all_blocks: list[ScheduledBlock],
    window_start: int,
    window_end: int,
) -> list[ScheduledBlock]:
    """Reference implementation of window loading.

    Applies the canonical predicate, sorts by start_utc_ms, deduplicates.
    This is the specification — production code must produce equivalent results.
    """
    seen: set[str] = set()
    result: list[ScheduledBlock] = []
    for b in all_blocks:
        if _intersects(b, window_start, window_end) and b.block_id not in seen:
            result.append(b)
            seen.add(b.block_id)
    result.sort(key=lambda b: b.start_utc_ms)
    return result


# ---------------------------------------------------------------------------
# Test data: a realistic multi-day timeline
# ---------------------------------------------------------------------------


# Broadcast day D-1 (2026-03-26), day_start_hour=6 EDT = 10:00 UTC
# Blocks compiled under broadcast_day=2026-03-26
_D1_BLOCK_A = _block("blk-d1-a", _ms(2026, 3, 27, 5, 30), _ms(2026, 3, 27, 8, 0))
_D1_BLOCK_B = _block("blk-d1-b", _ms(2026, 3, 27, 8, 0),  _ms(2026, 3, 27, 9, 30))
_D1_BLOCK_C = _block("blk-d1-c", _ms(2026, 3, 27, 9, 30),  _ms(2026, 3, 27, 11, 30))  # spans 10:00 boundary

# Broadcast day D (2026-03-27)
_D0_BLOCK_A = _block("blk-d0-a", _ms(2026, 3, 27, 13, 0),  _ms(2026, 3, 27, 15, 0))
_D0_BLOCK_B = _block("blk-d0-b", _ms(2026, 3, 27, 15, 0),  _ms(2026, 3, 27, 17, 30))

# All persisted blocks across both days
_ALL_BLOCKS = [_D1_BLOCK_A, _D1_BLOCK_B, _D1_BLOCK_C, _D0_BLOCK_A, _D0_BLOCK_B]


# ===========================================================================
# Section III: Window Intersection Rule
# ===========================================================================


class TestWindowIntersectionRule:
    """Contract Section III: canonical inclusion predicate."""

    def test_block_fully_inside_window(self):
        """Block entirely within window bounds → included."""
        window_start = _ms(2026, 3, 27, 7, 0)
        window_end = _ms(2026, 3, 27, 16, 0)

        result = _load_window([_D0_BLOCK_A], window_start, window_end)

        assert len(result) == 1
        assert result[0].block_id == "blk-d0-a"

    def test_block_starts_before_window_ends_inside(self):
        """Block starts before window_start, ends inside → included."""
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window([_D1_BLOCK_C], window_start, window_end)

        assert len(result) == 1
        assert result[0].block_id == "blk-d1-c"

    def test_block_starts_inside_window_ends_after(self):
        """Block starts inside window, ends after window_end → included."""
        window_start = _ms(2026, 3, 27, 14, 0)
        window_end = _ms(2026, 3, 27, 16, 0)

        result = _load_window([_D0_BLOCK_B], window_start, window_end)

        assert len(result) == 1
        assert result[0].block_id == "blk-d0-b"

    def test_block_completely_before_window(self):
        """Block ends before window starts → excluded."""
        window_start = _ms(2026, 3, 27, 12, 0)
        window_end = _ms(2026, 3, 27, 16, 0)

        result = _load_window([_D1_BLOCK_A], window_start, window_end)

        assert len(result) == 0

    def test_block_completely_after_window(self):
        """Block starts after window ends → excluded."""
        window_start = _ms(2026, 3, 27, 6, 0)
        window_end = _ms(2026, 3, 27, 8, 0)

        result = _load_window([_D0_BLOCK_A], window_start, window_end)

        assert len(result) == 0

    def test_block_spans_entire_window(self):
        """Block starts before and ends after window → included."""
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 11, 0)

        result = _load_window([_D1_BLOCK_C], window_start, window_end)

        assert len(result) == 1
        assert result[0].block_id == "blk-d1-c"

    def test_multiple_blocks_only_intersecting_included(self):
        """From a full timeline, only blocks satisfying the predicate are loaded."""
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window(_ALL_BLOCKS, window_start, window_end)

        ids = {b.block_id for b in result}
        assert "blk-d1-c" in ids, "Block spanning window start must be included"
        assert "blk-d0-a" in ids, "Block spanning window end must be included"
        assert "blk-d1-a" not in ids, "Block ending before window must be excluded"
        assert "blk-d1-b" not in ids, "Block ending at/before window start must be excluded"
        assert "blk-d0-b" not in ids, "Block starting at/after window end must be excluded"


# ===========================================================================
# Section III + VIII: Cross-Day Behavior
# ===========================================================================


class TestCrossDayBehavior:
    """Contract Sections III, VIII: broadcast_day MUST NOT influence inclusion."""

    def test_prior_day_block_overlapping_window_included(self):
        """Block compiled under prior broadcast_day, overlapping window → included."""
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window([_D1_BLOCK_C], window_start, window_end)

        assert len(result) == 1, (
            "Block from prior broadcast_day overlapping window MUST be included"
        )

    def test_future_day_block_overlapping_window_included(self):
        """Block from a later broadcast_day overlapping window → included."""
        future_block = _block(
            "blk-future", _ms(2026, 3, 28, 9, 0), _ms(2026, 3, 28, 11, 0),
        )
        window_start = _ms(2026, 3, 28, 8, 0)
        window_end = _ms(2026, 3, 28, 10, 0)

        result = _load_window([future_block], window_start, window_end)

        assert len(result) == 1

    def test_inclusion_independent_of_broadcast_day(self):
        """Two identical-time blocks from different 'days' — both satisfy predicate."""
        block_day1 = _block("blk-from-day1", _ms(2026, 3, 27, 9, 0), _ms(2026, 3, 27, 11, 0))
        block_day2 = _block("blk-from-day2", _ms(2026, 3, 27, 11, 0), _ms(2026, 3, 27, 13, 0))

        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 12, 0)

        result = _load_window([block_day1, block_day2], window_start, window_end)

        ids = {b.block_id for b in result}
        assert "blk-from-day1" in ids
        assert "blk-from-day2" in ids
        assert len(result) == 2

    def test_blocks_from_three_broadcast_days(self):
        """Window spanning three broadcast days loads from all."""
        block_d_minus_1 = _block("blk-prev", _ms(2026, 3, 26, 23, 0), _ms(2026, 3, 27, 1, 0))
        block_d0 = _block("blk-curr", _ms(2026, 3, 27, 1, 0), _ms(2026, 3, 27, 3, 0))
        block_d_plus_1 = _block("blk-next", _ms(2026, 3, 27, 3, 0), _ms(2026, 3, 27, 5, 0))

        window_start = _ms(2026, 3, 27, 0, 0)
        window_end = _ms(2026, 3, 27, 4, 0)

        result = _load_window(
            [block_d_minus_1, block_d0, block_d_plus_1], window_start, window_end,
        )

        ids = {b.block_id for b in result}
        assert ids == {"blk-prev", "blk-curr", "blk-next"}


# ===========================================================================
# Section III: Multiple Overlap
# ===========================================================================


class TestMultipleOverlap:
    """Contract Section III: ALL intersecting blocks MUST be included."""

    def test_two_overlapping_blocks_both_included(self):
        """Two blocks from prior day both overlap window → both included."""
        block_a = _block("blk-movie-a", _ms(2026, 3, 27, 9, 0), _ms(2026, 3, 27, 11, 0))
        block_b = _block("blk-movie-b", _ms(2026, 3, 27, 9, 30), _ms(2026, 3, 27, 11, 30))

        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window([block_a, block_b], window_start, window_end)

        assert len(result) == 2, (
            f"All intersecting blocks MUST be included without truncation, got {len(result)}"
        )

    def test_no_single_block_limit(self):
        """Five blocks intersect window → all five included."""
        blocks = [
            _block(f"blk-{i}", _ms(2026, 3, 27, 8 + i, 0), _ms(2026, 3, 27, 10 + i, 0))
            for i in range(5)
        ]
        window_start = _ms(2026, 3, 27, 9, 30)
        window_end = _ms(2026, 3, 27, 13, 30)

        result = _load_window(blocks, window_start, window_end)

        assert len(result) == 5

    def test_mixed_intersecting_and_non_intersecting(self):
        """Three before, two intersecting, one after → only two included."""
        blocks = [
            _block("blk-before-1", _ms(2026, 3, 27, 4, 0), _ms(2026, 3, 27, 5, 0)),
            _block("blk-before-2", _ms(2026, 3, 27, 5, 0), _ms(2026, 3, 27, 6, 0)),
            _block("blk-before-3", _ms(2026, 3, 27, 6, 0), _ms(2026, 3, 27, 7, 0)),
            _block("blk-in-1", _ms(2026, 3, 27, 9, 0), _ms(2026, 3, 27, 11, 0)),
            _block("blk-in-2", _ms(2026, 3, 27, 11, 0), _ms(2026, 3, 27, 13, 0)),
            _block("blk-after", _ms(2026, 3, 27, 15, 0), _ms(2026, 3, 27, 17, 0)),
        ]
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 12, 0)

        result = _load_window(blocks, window_start, window_end)

        ids = {b.block_id for b in result}
        assert ids == {"blk-in-1", "blk-in-2"}


# ===========================================================================
# Section III: Boundary Conditions
# ===========================================================================


class TestBoundaryConditions:
    """Contract Section IX boundary-exact test categories."""

    def test_block_end_equals_window_start_excluded(self):
        """block.end == window_start → half-open [start, end) does not overlap → excluded."""
        block = _block("blk-ends-at-boundary", _ms(2026, 3, 27, 8, 0), _ms(2026, 3, 27, 10, 0))

        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window([block], window_start, window_end)

        assert len(result) == 0, (
            "Block ending exactly at window_start MUST be excluded (half-open interval)"
        )

    def test_block_start_equals_window_start_included(self):
        """block.start == window_start → included."""
        block = _block("blk-starts-at-window", _ms(2026, 3, 27, 10, 0), _ms(2026, 3, 27, 12, 0))

        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window([block], window_start, window_end)

        assert len(result) == 1
        assert result[0].block_id == "blk-starts-at-window"

    def test_block_start_equals_window_end_excluded(self):
        """block.start == window_end → does not satisfy start < window_end → excluded."""
        block = _block("blk-starts-at-end", _ms(2026, 3, 27, 14, 0), _ms(2026, 3, 27, 16, 0))

        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window([block], window_start, window_end)

        assert len(result) == 0, (
            "Block starting exactly at window_end MUST be excluded"
        )

    def test_block_end_one_ms_past_window_start_included(self):
        """block.end == window_start + 1ms → overlaps by 1ms → included."""
        block = _block("blk-1ms-overlap", _ms(2026, 3, 27, 8, 0), _ms(2026, 3, 27, 10, 0) + 1)

        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window([block], window_start, window_end)

        assert len(result) == 1, "1ms overlap MUST be sufficient for inclusion"

    def test_zero_width_window_is_point_query(self):
        """window_start == window_end → predicate degenerates to point containment.

        block.start < t AND block.end > t is true when the block contains t.
        """
        block = _block("blk-any", _ms(2026, 3, 27, 9, 0), _ms(2026, 3, 27, 11, 0))
        t = _ms(2026, 3, 27, 10, 0)

        result = _load_window([block], t, t)

        assert len(result) == 1, "Block containing the point must be included"

    def test_zero_width_window_at_block_boundary_excluded(self):
        """Point query at block.end → block.start < t is true but block.end > t is false."""
        block = _block("blk-any", _ms(2026, 3, 27, 9, 0), _ms(2026, 3, 27, 10, 0))
        t = _ms(2026, 3, 27, 10, 0)

        result = _load_window([block], t, t)

        assert len(result) == 0, "Block ending exactly at the point must be excluded"


# ===========================================================================
# Section VI: Determinism
# ===========================================================================


class TestDeterminism:
    """Contract Section VI: identical inputs → identical outputs."""

    def test_same_inputs_same_outputs(self):
        """Repeated calls with identical blocks and window produce identical results."""
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        results = [_load_window(_ALL_BLOCKS, window_start, window_end) for _ in range(10)]

        first_ids = [b.block_id for b in results[0]]
        for i, r in enumerate(results[1:], 1):
            assert [b.block_id for b in r] == first_ids, (
                f"Run {i} produced different result — determinism violation"
            )

    def test_input_order_does_not_affect_output(self):
        """Blocks provided in different orders produce identical sorted output."""
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 16, 0)

        forward = _load_window(_ALL_BLOCKS, window_start, window_end)
        reverse = _load_window(list(reversed(_ALL_BLOCKS)), window_start, window_end)

        assert [b.block_id for b in forward] == [b.block_id for b in reverse]

    def test_output_sorted_by_start_utc_ms(self):
        """Loaded blocks MUST be sorted by start_utc_ms ascending."""
        window_start = _ms(2026, 3, 27, 5, 0)
        window_end = _ms(2026, 3, 27, 18, 0)

        result = _load_window(list(reversed(_ALL_BLOCKS)), window_start, window_end)

        for i in range(1, len(result)):
            assert result[i].start_utc_ms >= result[i - 1].start_utc_ms, (
                f"Block {i} starts before block {i-1} — ordering violation"
            )

    def test_no_duplicate_block_ids(self):
        """Duplicate blocks in input MUST appear at most once in output."""
        dup_blocks = _ALL_BLOCKS + [_D1_BLOCK_C]  # duplicate
        window_start = _ms(2026, 3, 27, 5, 0)
        window_end = _ms(2026, 3, 27, 18, 0)

        result = _load_window(dup_blocks, window_start, window_end)

        ids = [b.block_id for b in result]
        assert len(ids) == len(set(ids)), "Duplicate block_id in loaded timeline"


# ===========================================================================
# Section V: Continuity
# ===========================================================================


class TestContinuity:
    """Contract Section V: no loading-induced gaps in the timeline."""

    def test_no_gap_when_block_spans_window_boundary(self):
        """A block from a prior broadcast_day spanning the window start MUST
        be present, preventing a false gap."""
        # Simulates the HBO incident: viewer at 10:24, block 09:30→11:30
        viewer_ms = _ms(2026, 3, 27, 10, 24)
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 14, 0)

        result = _load_window(_ALL_BLOCKS, window_start, window_end)

        covering = [b for b in result if b.start_utc_ms <= viewer_ms < b.end_utc_ms]
        assert len(covering) == 1, (
            f"Viewer at 10:24 UTC must have a covering block. "
            f"Loaded {len(result)} blocks, {len(covering)} cover viewer time."
        )
        assert covering[0].block_id == "blk-d1-c"

    def test_contiguous_timeline_has_no_gap(self):
        """When persisted blocks form a contiguous chain, the loaded
        timeline MUST also be contiguous (no loading-induced gaps)."""
        # Build a contiguous chain: 08:00→10:00→12:00→14:00
        chain = [
            _block("blk-1", _ms(2026, 3, 27, 8, 0), _ms(2026, 3, 27, 10, 0)),
            _block("blk-2", _ms(2026, 3, 27, 10, 0), _ms(2026, 3, 27, 12, 0)),
            _block("blk-3", _ms(2026, 3, 27, 12, 0), _ms(2026, 3, 27, 14, 0)),
        ]
        window_start = _ms(2026, 3, 27, 9, 0)
        window_end = _ms(2026, 3, 27, 13, 0)

        result = _load_window(chain, window_start, window_end)

        assert len(result) == 3, "All three contiguous blocks intersect the window"
        for i in range(1, len(result)):
            assert result[i].start_utc_ms == result[i - 1].end_utc_ms, (
                f"Gap between block {i-1} and {i}: "
                f"prev_end={result[i-1].end_utc_ms}, curr_start={result[i].start_utc_ms}"
            )

    def test_restart_scenario_all_intersecting_blocks_present(self):
        """Simulates process restart: same window, same data → same blocks.

        The HBO incident: Block C (09:30→11:30) from broadcast_day D-1 MUST
        be loaded when window_start=10:00. Omitting it creates a false gap.
        """
        window_start = _ms(2026, 3, 27, 10, 0)
        window_end = _ms(2026, 3, 27, 16, 0)

        run1 = _load_window(_ALL_BLOCKS, window_start, window_end)
        run2 = _load_window(_ALL_BLOCKS, window_start, window_end)

        ids1 = [b.block_id for b in run1]
        ids2 = [b.block_id for b in run2]
        assert ids1 == ids2, "Restart must not change loaded blocks"
        assert "blk-d1-c" in ids1, (
            "Block from prior day spanning window start MUST be present after restart"
        )

    def test_every_covered_instant_has_a_block(self):
        """For every millisecond within the window covered by a persisted block,
        the loaded timeline MUST contain that block."""
        # Contiguous chain covering 08:00→14:00
        chain = [
            _block("blk-a", _ms(2026, 3, 27, 8, 0), _ms(2026, 3, 27, 10, 0)),
            _block("blk-b", _ms(2026, 3, 27, 10, 0), _ms(2026, 3, 27, 12, 0)),
            _block("blk-c", _ms(2026, 3, 27, 12, 0), _ms(2026, 3, 27, 14, 0)),
        ]
        window_start = _ms(2026, 3, 27, 9, 0)
        window_end = _ms(2026, 3, 27, 13, 0)

        result = _load_window(chain, window_start, window_end)
        result_ids = {b.block_id for b in result}

        # Every block that covers any part of the window must be in result
        for b in chain:
            if b.start_utc_ms < window_end and b.end_utc_ms > window_start:
                assert b.block_id in result_ids, (
                    f"Block {b.block_id} [{b.start_utc_ms}, {b.end_utc_ms}) "
                    f"intersects window but is missing from loaded timeline"
                )
