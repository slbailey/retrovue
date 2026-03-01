"""
Contract tests for INV-TIER2-COMPILATION-CONSISTENCY-001.

Time-to-block resolution MUST use the current in-memory compilation.
TransmissionLog MUST be queried by block_id only, never by time range.
Stale TransmissionLog entries from a prior compilation MUST NOT corrupt
block contiguity.
"""

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
    """Create a minimal test segment."""
    return ScheduledSegment(
        segment_type="content",
        asset_uri="/test/asset.ts",
        asset_start_offset_ms=0,
        segment_duration_ms=duration_ms,
    )


def _make_block(block_id: str, start_ms: int, end_ms: int) -> ScheduledBlock:
    """Create a minimal test block."""
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
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvTier2CompilationConsistency001:
    """INV-TIER2-COMPILATION-CONSISTENCY-001 contract tests."""

    def test_get_block_at_returns_current_compilation_not_stale_txlog(self):
        """get_block_at() MUST return a block from the current in-memory
        compilation, not a stale TransmissionLog entry from a prior compilation.

        Scenario:
          C2 (current) in-memory: block_A [T, T+30min), block_B [T+30min, T+60min)
          C1 (stale) in TransmissionLog: block_X [T, T+25min)
          get_block_at(T+100) MUST return C2's block_A, not C1's block_X.
        """
        T = 1_772_380_800_000  # arbitrary epoch ms
        SLOT_30 = 30 * 60 * 1000

        # C2 (current compilation) — contiguous
        c2_a = _make_block("c2-a", T, T + SLOT_30)
        c2_b = _make_block("c2-b", T + SLOT_30, T + 2 * SLOT_30)

        # C1 (stale) — different end time
        c1_stale = _make_block("c1-x", T, T + 25 * 60 * 1000)

        svc = _build_service(c2_a, c2_b)

        def stale_time_lookup(channel_id, utc_ms):
            """Simulate TransmissionLog time-range query returning stale C1 data."""
            if c1_stale.start_utc_ms <= utc_ms < c1_stale.end_utc_ms:
                return c1_stale
            return None

        with ExitStack() as stack:
            stack.enter_context(patch.object(svc, "_maybe_extend_horizon"))
            stack.enter_context(
                patch.object(
                    svc, "ensure_block_compiled", side_effect=lambda ch, blk: blk
                )
            )

            # Inject stale data into the old time-range method if it exists
            if hasattr(DslScheduleService, "_get_filled_block_at"):
                stack.enter_context(
                    patch.object(
                        svc, "_get_filled_block_at", side_effect=stale_time_lookup
                    )
                )

            # After fix: block_id method returns None (C2 not yet in TransmissionLog)
            if hasattr(DslScheduleService, "_get_filled_block_by_id"):
                stack.enter_context(
                    patch.object(svc, "_get_filled_block_by_id", return_value=None)
                )

            result = svc.get_block_at("test-channel", T + 100)

        assert result is not None
        assert result.block_id == "c2-a", (
            f"INV-TIER2-COMPILATION-CONSISTENCY-001 violated: "
            f"get_block_at() returned block_id={result.block_id} from stale "
            f"TransmissionLog instead of c2-a from current compilation"
        )

    def test_consecutive_blocks_are_contiguous(self):
        """Consecutive get_block_at() calls MUST return contiguous blocks,
        even when stale TransmissionLog entries exist from a prior compilation.

        This is the exact runtime failure: the seed phase generates two
        consecutive blocks and asserts block_a.end_utc_ms == block_b.start_utc_ms.
        Stale TransmissionLog entries cause this check to fail.

        Scenario:
          C2 (current): block_A [T, T+30min), block_B [T+30min, T+60min)
          C1 (stale) in TransmissionLog: block_X [T, T+25min)
          get_block_at(T+100)             → block_a
          get_block_at(block_a.end_utc_ms) → block_b
          Assert: block_a.end_utc_ms == block_b.start_utc_ms
        """
        T = 1_772_380_800_000
        SLOT_30 = 30 * 60 * 1000

        c2_a = _make_block("c2-a", T, T + SLOT_30)
        c2_b = _make_block("c2-b", T + SLOT_30, T + 2 * SLOT_30)

        c1_stale = _make_block("c1-x", T, T + 25 * 60 * 1000)

        svc = _build_service(c2_a, c2_b)

        def stale_time_lookup(channel_id, utc_ms):
            if c1_stale.start_utc_ms <= utc_ms < c1_stale.end_utc_ms:
                return c1_stale
            return None

        with ExitStack() as stack:
            stack.enter_context(patch.object(svc, "_maybe_extend_horizon"))
            stack.enter_context(
                patch.object(
                    svc, "ensure_block_compiled", side_effect=lambda ch, blk: blk
                )
            )

            if hasattr(DslScheduleService, "_get_filled_block_at"):
                stack.enter_context(
                    patch.object(
                        svc, "_get_filled_block_at", side_effect=stale_time_lookup
                    )
                )

            if hasattr(DslScheduleService, "_get_filled_block_by_id"):
                stack.enter_context(
                    patch.object(svc, "_get_filled_block_by_id", return_value=None)
                )

            block_a = svc.get_block_at("test-channel", T + 100)
            block_b = svc.get_block_at("test-channel", block_a.end_utc_ms)

        assert block_a is not None
        assert block_b is not None
        assert block_a.end_utc_ms == block_b.start_utc_ms, (
            f"INV-TIER2-COMPILATION-CONSISTENCY-001 violated: "
            f"Blocks not contiguous: {block_a.block_id} ends at "
            f"{block_a.end_utc_ms}, {block_b.block_id} starts at "
            f"{block_b.start_utc_ms}"
        )
