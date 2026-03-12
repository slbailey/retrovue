"""
Contract tests for INV-CROSS-DAY-CARRY-IN-001.

Broadcast days are accounting constructs, not scheduling constructs.
The schedule is a continuous linked list — each block starts where the
previous one ended.

When a program crosses the broadcast day boundary, the subsequent day's
program blocks are pushed forward (not trimmed or dropped) so that:
  1. Fully subsumed blocks (ending before carry-in end) are removed.
  2. The first surviving block starts at the carry-in end.
  3. Subsequent blocks cascade forward to maintain contiguity.
  4. No block content is trimmed — only start times shift.

Architecture:
  - Primary fix: _apply_carry_in_push_forward() at program-block level
  - Guardrail: _resolve_cross_day_overlaps() at merge time (defense-in-depth)
  - Propagation: active_carry_in_end_ms propagates across empty days
"""

import logging
import threading
from contextlib import ExitStack
from datetime import datetime, timezone, timedelta
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


def _make_program_block(title: str, start_iso: str, slot_duration_sec: float) -> dict:
    """Create a program_block dict matching compile_schedule output format."""
    return {
        "title": title,
        "start_at": start_iso,
        "slot_duration_sec": slot_duration_sec,
    }


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

# ISO timestamps for program block construction
DAY_BOUNDARY_DT = datetime.fromtimestamp(DAY_BOUNDARY_MS / 1000, tz=timezone.utc)


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
# 2. Push-forward at program-block level (primary fix)
# ---------------------------------------------------------------------------


class TestPushForward:
    """INV-CROSS-DAY-CARRY-IN-001: _apply_carry_in_push_forward pushes
    program blocks forward past the carry-in end rather than trimming them.
    """

    def test_carry_in_pushes_first_block_forward(self):
        """15-min carry-in pushes the 06:00 block to start at 06:15.

        Movie A: 06:00-07:00 (3600s) — starts before carry-in end (06:15),
        ends after → pushed forward to 06:15.
        Movie B: 07:00-07:30 — cascades to 07:15.
        """
        b1_start = DAY_BOUNDARY_DT
        b2_start = DAY_BOUNDARY_DT + timedelta(minutes=60)

        schedule = {
            "program_blocks": [
                _make_program_block("Movie A", b1_start.isoformat(), 3600),
                _make_program_block("Movie B", b2_start.isoformat(), 1800),
            ],
        }

        # Carry-in ends at 06:15 EDT = DAY_BOUNDARY + 15 min
        effective_open = DAY_BOUNDARY_MS + 15 * 60 * 1000
        DslScheduleService._apply_carry_in_push_forward(
            schedule, effective_open, "2026-03-10",
        )

        blocks = schedule["program_blocks"]
        assert len(blocks) == 2
        # First block pushed from 06:00 to 06:15
        expected_b1_start = datetime.fromtimestamp(
            effective_open / 1000, tz=timezone.utc,
        )
        assert blocks[0]["start_at"] == expected_b1_start.isoformat()
        assert blocks[0]["slot_duration_sec"] == 3600  # duration preserved
        # Second block cascades: 06:15 + 3600s = 07:15
        expected_b2_start = expected_b1_start + timedelta(seconds=3600)
        assert blocks[1]["start_at"] == expected_b2_start.isoformat()

    def test_carry_in_drops_fully_subsumed_blocks(self):
        """Blocks ending before carry-in end are removed entirely."""
        # Block: 06:00-06:15 (15 min) — ends before 06:30 carry-in end
        b1_start = DAY_BOUNDARY_DT
        # Block: 06:15-06:30 — ends exactly at carry-in end
        b2_start = DAY_BOUNDARY_DT + timedelta(minutes=15)
        # Block: 06:30-07:00 — starts at carry-in end
        b3_start = DAY_BOUNDARY_DT + timedelta(minutes=30)

        schedule = {
            "program_blocks": [
                _make_program_block("Short A", b1_start.isoformat(), 900),
                _make_program_block("Short B", b2_start.isoformat(), 900),
                _make_program_block("Feature", b3_start.isoformat(), 1800),
            ],
        }

        effective_open = MOVIE_END  # 06:30 EDT
        DslScheduleService._apply_carry_in_push_forward(
            schedule, effective_open, "2026-03-10",
        )

        blocks = schedule["program_blocks"]
        # Short A (ends 06:15) and Short B (ends 06:30) are subsumed
        assert len(blocks) == 1
        assert blocks[0]["title"] == "Feature"

    def test_carry_in_preserves_slot_duration(self):
        """Push-forward changes start_at but never slot_duration_sec."""
        b1_start = DAY_BOUNDARY_DT

        schedule = {
            "program_blocks": [
                _make_program_block("Movie", b1_start.isoformat(), 5400),
            ],
        }

        effective_open = MOVIE_END
        DslScheduleService._apply_carry_in_push_forward(
            schedule, effective_open, "2026-03-10",
        )

        assert schedule["program_blocks"][0]["slot_duration_sec"] == 5400

    def test_no_carry_in_no_change(self):
        """When effective_day_open_ms <= first block start, no push-forward."""
        b1_start = DAY_BOUNDARY_DT

        schedule = {
            "program_blocks": [
                _make_program_block("Movie", b1_start.isoformat(), 1800),
            ],
        }

        # effective_day_open == day boundary == first block start
        DslScheduleService._apply_carry_in_push_forward(
            schedule, DAY_BOUNDARY_MS, "2026-03-10",
        )

        assert schedule["program_blocks"][0]["start_at"] == b1_start.isoformat()

    def test_cascade_maintains_contiguity(self):
        """All blocks after the pushed block cascade to remain contiguous."""
        blocks_data = []
        for i in range(5):
            start = DAY_BOUNDARY_DT + timedelta(minutes=30 * i)
            blocks_data.append(
                _make_program_block(f"Block-{i}", start.isoformat(), 1800),
            )

        schedule = {"program_blocks": blocks_data}

        # 1-hour carry-in: effective open = 07:00
        effective_open = DAY_BOUNDARY_MS + HOUR_MS
        DslScheduleService._apply_carry_in_push_forward(
            schedule, effective_open, "2026-03-10",
        )

        pbs = schedule["program_blocks"]
        # Block-0 (06:00-06:30) and Block-1 (06:30-07:00) subsumed
        assert len(pbs) == 3

        # Verify contiguity: each block starts where the previous ends
        for i in range(len(pbs) - 1):
            this_start = datetime.fromisoformat(pbs[i]["start_at"])
            this_end_ms = int(this_start.timestamp() * 1000) + int(pbs[i]["slot_duration_sec"] * 1000)
            next_start = datetime.fromisoformat(pbs[i + 1]["start_at"])
            next_start_ms = int(next_start.timestamp() * 1000)
            assert this_end_ms == next_start_ms, (
                f"Gap between block {i} end ({this_end_ms}) and "
                f"block {i+1} start ({next_start_ms})"
            )

    def test_carry_in_subsuming_entire_day(self):
        """A carry-in spanning the entire day drops all blocks."""
        blocks_data = []
        for i in range(48):  # 24h of 30-min blocks
            start = DAY_BOUNDARY_DT + timedelta(minutes=30 * i)
            blocks_data.append(
                _make_program_block(f"Block-{i}", start.isoformat(), 1800),
            )

        schedule = {"program_blocks": blocks_data}

        # Carry-in ends 26h after day boundary
        effective_open = DAY_BOUNDARY_MS + 26 * HOUR_MS
        DslScheduleService._apply_carry_in_push_forward(
            schedule, effective_open, "2026-03-10",
        )

        assert len(schedule["program_blocks"]) == 0

    def test_empty_schedule_is_noop(self):
        """Empty program_blocks list is handled gracefully."""
        schedule = {"program_blocks": []}
        DslScheduleService._apply_carry_in_push_forward(
            schedule, MOVIE_END, "2026-03-10",
        )
        assert schedule["program_blocks"] == []

    def test_push_forward_logs_info(self, caplog):
        """Push-forward MUST log INV-CROSS-DAY-CARRY-IN-001 at INFO level."""
        b1_start = DAY_BOUNDARY_DT
        schedule = {
            "program_blocks": [
                _make_program_block("Movie", b1_start.isoformat(), 1800),
            ],
        }

        with caplog.at_level(logging.INFO):
            DslScheduleService._apply_carry_in_push_forward(
                schedule, MOVIE_END, "2026-03-10",
            )

        assert any(
            "INV-CROSS-DAY-CARRY-IN-001" in rec.message
            for rec in caplog.records
        ), "Push-forward must log with invariant ID"


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
        """Day N movie runs to Day N+2 08:00.
        Day N+1 produces zero blocks (fully subsumed).
        Day N+2 must still respect the carry-in.
        """
        day_n2_boundary_ms = DAY_BOUNDARY_MS + 24 * HOUR_MS

        # Movie ends at 08:00 EDT on day N+2
        carry_in_end = day_n2_boundary_ms + 2 * HOUR_MS

        active_carry_in_end_ms = carry_in_end

        # Day N+1: all blocks subsumed
        day_n1_effective = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-10", 6, "America/New_York", active_carry_in_end_ms,
        )

        # Push-forward drops all day N+1 blocks
        day_n1_blocks = []
        for i in range(48):
            start = DAY_BOUNDARY_DT + timedelta(minutes=30 * i)
            day_n1_blocks.append(
                _make_program_block(f"n1-{i}", start.isoformat(), 1800),
            )
        schedule_n1 = {"program_blocks": day_n1_blocks}
        DslScheduleService._apply_carry_in_push_forward(
            schedule_n1, day_n1_effective, "2026-03-10",
        )
        assert len(schedule_n1["program_blocks"]) == 0, "Day N+1 should be fully subsumed"

        # No blocks → active_carry_in_end_ms persists unchanged
        assert active_carry_in_end_ms == carry_in_end

        # Day N+2: carry-in still active
        day_n2_effective = DslScheduleService._compute_effective_day_open_ms(
            "2026-03-11", 6, "America/New_York", active_carry_in_end_ms,
        )
        assert day_n2_effective == carry_in_end

    def test_active_carry_in_uses_max(self):
        """active_carry_in_end_ms = max(active, last_block_end) so it never
        shrinks backward if a day produces shorter blocks.
        """
        active = DAY_BOUNDARY_MS + 3 * HOUR_MS  # 09:00 EDT
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
    If push-forward works correctly, this guardrail should never fire.
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
        """When the guardrail fires, it must emit a WARNING log."""
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
