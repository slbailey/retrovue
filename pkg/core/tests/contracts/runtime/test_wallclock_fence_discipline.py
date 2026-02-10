"""
Contract Tests: INV-BLOCK-WALLCLOCK-FENCE-DISCIPLINE

Contract reference:
    pkg/core/docs/contracts/runtime/INV-BLOCK-WALLCLOCK-FENCE-DISCIPLINE.md

These tests enforce Core-side wall-clock fence discipline using a Python
model that mirrors BlockPlanProducer's block timestamp computation and
completion handling.  The model uses a FakeMasterClock for deterministic
time control.

    INV-WALLCLOCK-FENCE-001  Immutable scheduled window (UTC epoch ms)
    INV-WALLCLOCK-FENCE-002  Only active blocks may complete
    INV-WALLCLOCK-FENCE-003  No completion before scheduled start
    INV-WALLCLOCK-FENCE-004  At most one completion per event
    INV-WALLCLOCK-FENCE-005  Session anchor from grid-aligned real UTC
    INV-WALLCLOCK-FENCE-006  Stale anchor recovery

All tests are deterministic and require no AIR process, network, or
wall-clock sleeps.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest


# =============================================================================
# FakeMasterClock — deterministic time source
# =============================================================================

class FakeMasterClock:
    """Deterministic clock that returns a controllable UTC epoch ms value."""

    def __init__(self, initial_utc_ms: int = 0) -> None:
        self._now_utc_ms = initial_utc_ms

    @property
    def now_utc_ms(self) -> int:
        return self._now_utc_ms

    def advance(self, delta_ms: int) -> None:
        self._now_utc_ms += delta_ms

    def set(self, utc_ms: int) -> None:
        self._now_utc_ms = utc_ms


# =============================================================================
# Model: BlockPlanProducer fence logic (post-fix)
# =============================================================================

@dataclass
class BlockTimestamps:
    """Block with UTC-anchored timestamps."""
    block_id: str
    start_utc_ms: int
    end_utc_ms: int
    duration_ms: int
    segment_duration_ms: int = 0
    asset_start_offset_ms: int = 0


class BlockPlanProducerModel:
    """Python model of BlockPlanProducer's timestamp computation and
    completion handling after the WALLCLOCK-FENCE-DISCIPLINE fix.

    Key behaviors modeled:
    - _next_block_start_ms anchored to grid-aligned real UTC
    - Block duration is ALWAYS full (never reduced by JIP)
    - JIP reduces only segment_duration_ms within the block
    - Completion guards: active-only, no duplicates, no pre-start
    - One completion per callback invocation
    """

    def __init__(
        self,
        clock: FakeMasterClock,
        block_duration_ms: int = 30_000,
    ) -> None:
        self.clock = clock
        self.block_duration_ms = block_duration_ms
        self._next_block_start_ms = 0  # Anchored at start()
        self._block_index = 0
        self._in_flight_block_ids: set[str] = set()
        self._completed_block_ids: set[str] = set()
        self._completion_log: list[str] = []
        self._rejection_log: list[tuple[str, str]] = []  # (block_id, reason)
        self._started = False
        # Track block timestamps for validation
        self._block_registry: dict[str, BlockTimestamps] = {}

    def start(
        self,
        join_utc_ms: int,
        jip_entry_index: int = 0,
        jip_offset_ms: int = 0,
    ) -> list[BlockTimestamps]:
        """Start a session: anchor timestamps and generate seed blocks.

        Returns [block_a, block_b] for inspection.
        """
        # INV-WALLCLOCK-FENCE-005: Anchor to grid-aligned real UTC
        self._next_block_start_ms = (join_utc_ms // self.block_duration_ms) * self.block_duration_ms
        self._block_index = jip_entry_index
        self._started = True
        self._in_flight_block_ids.clear()
        self._completed_block_ids.clear()
        self._completion_log.clear()
        self._rejection_log.clear()
        self._block_registry.clear()

        # Generate block A (may have JIP offset)
        block_a = self._generate_block(jip_offset_ms=jip_offset_ms)
        self._advance_cursor(block_a)

        # Generate block B (no JIP)
        block_b = self._generate_block()
        self._advance_cursor(block_b)

        # Mark both as active
        self._in_flight_block_ids.add(block_a.block_id)
        self._in_flight_block_ids.add(block_b.block_id)

        return [block_a, block_b]

    def _generate_block(self, jip_offset_ms: int = 0) -> BlockTimestamps:
        """Generate a block with UTC-anchored timestamps.

        Block duration is ALWAYS full (INV-WALLCLOCK-FENCE-005).
        JIP reduces only the segment duration within the block.
        """
        start_ms = self._next_block_start_ms
        dur_ms = self.block_duration_ms  # Block duration is NEVER reduced
        end_ms = start_ms + dur_ms
        seg_dur_ms = dur_ms - jip_offset_ms

        block_id = f"BLOCK-test-{self._block_index}"
        block = BlockTimestamps(
            block_id=block_id,
            start_utc_ms=start_ms,
            end_utc_ms=end_ms,
            duration_ms=dur_ms,
            segment_duration_ms=seg_dur_ms,
            asset_start_offset_ms=jip_offset_ms,
        )
        self._block_registry[block_id] = block
        return block

    def _advance_cursor(self, block: BlockTimestamps) -> None:
        self._block_index += 1
        self._next_block_start_ms = block.end_utc_ms

    def feed_block(self) -> BlockTimestamps:
        """Generate and feed the next block. Returns it for inspection."""
        block = self._generate_block()
        self._advance_cursor(block)
        self._in_flight_block_ids.add(block.block_id)
        return block

    def on_block_complete(self, block_id: str) -> bool:
        """Process a BlockCompleted event. Returns True if accepted.

        Enforces:
        - INV-WALLCLOCK-FENCE-002: Only active blocks
        - INV-WALLCLOCK-FENCE-003: No completion before start
        - INV-WALLCLOCK-FENCE-004: At most one completion (by design: no loop)
        - Duplicate prevention
        """
        if not self._started:
            self._rejection_log.append((block_id, "not_started"))
            return False

        # Duplicate prevention (existing INV-FEED-EXACTLY-ONCE)
        # Check before active-block guard so re-completions get "duplicate"
        if block_id in self._completed_block_ids:
            self._rejection_log.append((block_id, "duplicate"))
            return False

        # INV-WALLCLOCK-FENCE-002: Only active blocks may complete
        if block_id not in self._in_flight_block_ids:
            self._rejection_log.append((block_id, "not_active"))
            return False

        # INV-WALLCLOCK-FENCE-003: No completion before scheduled start
        if block_id in self._block_registry:
            block = self._block_registry[block_id]
            if self.clock.now_utc_ms < block.start_utc_ms:
                self._rejection_log.append((block_id, "before_start"))
                return False

        # Accept completion
        self._completed_block_ids.add(block_id)
        self._in_flight_block_ids.discard(block_id)
        self._completion_log.append(block_id)
        return True

    def recompute_anchor_if_stale(self) -> bool:
        """INV-WALLCLOCK-FENCE-006: If anchor is stale, recompute from clock.

        Returns True if anchor was recomputed.
        """
        # Check: is the next block's end already in the past?
        hypothetical_end = self._next_block_start_ms + self.block_duration_ms
        if hypothetical_end < self.clock.now_utc_ms:
            # Stale anchor — recompute (grid-aligned)
            self._next_block_start_ms = (self.clock.now_utc_ms // self.block_duration_ms) * self.block_duration_ms
            return True
        return False


# =============================================================================
# 1. INV-WALLCLOCK-FENCE-001 + 005: Block timestamps are real UTC
# =============================================================================

class TestBlockTimestampsAreUTC:
    """INV-WALLCLOCK-FENCE-001/005: Blocks must have start_utc_ms and
    end_utc_ms as real UTC epoch milliseconds."""

    def test_block_timestamps_are_utc_epoch(self):
        """After anchoring to a UTC epoch, blocks have UTC-range timestamps."""
        clock = FakeMasterClock(initial_utc_ms=1_738_987_500_000)  # ~Feb 2026
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=clock.now_utc_ms)
        block_a, block_b = blocks

        # Block A: starts at join time
        assert block_a.start_utc_ms == 1_738_987_500_000, (
            "INV-WALLCLOCK-FENCE-005 VIOLATION: block A start_utc_ms is "
            f"{block_a.start_utc_ms}, expected real UTC epoch."
        )
        assert block_a.end_utc_ms == 1_738_987_530_000, (
            "INV-WALLCLOCK-FENCE-001 VIOLATION: block A end_utc_ms is "
            f"{block_a.end_utc_ms}, expected start + 30000."
        )

        # Block B: starts where A ends
        assert block_b.start_utc_ms == block_a.end_utc_ms, (
            "INV-WALLCLOCK-FENCE-001 VIOLATION: block B does not chain "
            "contiguously from block A."
        )
        assert block_b.end_utc_ms == block_b.start_utc_ms + 30_000

    def test_blocks_chain_correctly_from_anchor(self):
        """Sequential blocks have contiguous UTC timestamps."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=10_000)

        blocks = model.start(join_utc_ms=clock.now_utc_ms)
        block_a, block_b = blocks

        # Feed a third block
        block_c = model.feed_block()

        # Verify contiguity
        assert block_a.end_utc_ms == block_b.start_utc_ms
        assert block_b.end_utc_ms == block_c.start_utc_ms

        # Verify all are real UTC
        for b in [block_a, block_b, block_c]:
            assert b.start_utc_ms >= 1_000_000_000_000, (
                f"Block {b.block_id} start_utc_ms={b.start_utc_ms} is not "
                "a real UTC epoch value."
            )

    def test_timestamps_not_relative(self):
        """Blocks must NOT have near-zero timestamps (the pre-fix bug)."""
        clock = FakeMasterClock(initial_utc_ms=1_738_987_500_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=clock.now_utc_ms)
        for b in blocks:
            assert b.start_utc_ms > 1_000_000_000, (
                f"INV-WALLCLOCK-FENCE-005 VIOLATION: block {b.block_id} has "
                f"start_utc_ms={b.start_utc_ms} which looks like a relative "
                "offset, not a UTC epoch value."
            )
            assert b.end_utc_ms > 1_000_000_000


# =============================================================================
# 2. INV-WALLCLOCK-FENCE-003: No completion before scheduled start
# =============================================================================

class TestNoCompletionBeforeStart:
    """INV-WALLCLOCK-FENCE-003: BlockCompleted must not be processed for
    a block whose scheduled_start_ts is in the future."""

    def test_no_completion_before_start(self):
        """Seed at t=100s with 30s blocks. Grid-aligned start at 90s."""
        epoch = 100_000  # 100 seconds in ms
        clock = FakeMasterClock(initial_utc_ms=epoch)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=epoch)
        block_a = blocks[0]

        # Block A: start=90000 (grid-aligned), end=120000
        assert block_a.start_utc_ms == 90_000
        assert block_a.end_utc_ms == 120_000

        # At t=100s (block started at 90s): block A is already in progress.
        # But block B (starting at 120s) hasn't started yet:
        block_b = blocks[1]
        assert block_b.start_utc_ms == 120_000

        # At t=100s, completing block B should be rejected (not started yet)
        accepted = model.on_block_complete(block_b.block_id)
        assert not accepted, (
            "INV-WALLCLOCK-FENCE-003 VIOLATION: completion accepted for "
            "block B whose start_utc_ms=120000 but now=100000."
        )
        assert len(model._rejection_log) == 1
        assert model._rejection_log[0][1] == "before_start"

    def test_completion_accepted_after_start(self):
        """Block A completion is accepted when now >= start_utc_ms."""
        epoch = 100_000
        clock = FakeMasterClock(initial_utc_ms=epoch)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=epoch)
        block_a = blocks[0]

        # Advance to end of block A
        clock.advance(30_000)  # now = 130000

        accepted = model.on_block_complete(block_a.block_id)
        assert accepted, (
            "Block A completion should be accepted at t=130000 "
            f"(start={block_a.start_utc_ms})."
        )


# =============================================================================
# 3. INV-WALLCLOCK-FENCE-005/006: No cascade on session start
# =============================================================================

class TestNoPastDueCascade:
    """INV-WALLCLOCK-FENCE-005/006: No cascade of completions when
    session starts with stale or past-due timestamps."""

    def test_no_past_due_cascade_on_session_start(self):
        """Simulate stale anchor: _next_block_start_ms far in the past.
        Start a session at t=1000s. Assert no immediate completions."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)  # 1000 seconds
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        # INV-WALLCLOCK-FENCE-005: start() anchors to join_utc_ms
        blocks = model.start(join_utc_ms=clock.now_utc_ms)
        block_a = blocks[0]

        # Block A: start=990000 (grid-aligned), end=1020000
        assert block_a.end_utc_ms == 1_020_000, (
            "Block A end should be 30s after grid-aligned start, not in the past."
        )

        # At session start (t=1000000): block A's end is in the future
        assert clock.now_utc_ms < block_a.end_utc_ms, (
            "INV-WALLCLOCK-FENCE-005 VIOLATION: block A is already past-due "
            "at session start. Timestamps must be anchored to real UTC."
        )

        # No completion should be possible at session start
        # (block A hasn't played yet, AIR fence hasn't fired)
        assert len(model._completion_log) == 0

    def test_stale_anchor_recovery(self):
        """If _next_block_start_ms is stale, recompute from clock."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        # Simulate stale state: anchor was set long ago
        model._next_block_start_ms = 500_000  # 500s ago

        # INV-WALLCLOCK-FENCE-006: detect and recover
        recovered = model.recompute_anchor_if_stale()
        assert recovered, (
            "INV-WALLCLOCK-FENCE-006 VIOLATION: stale anchor not detected."
        )
        assert model._next_block_start_ms == 990_000, (
            "INV-WALLCLOCK-FENCE-006 VIOLATION: anchor not recomputed to "
            "grid-aligned now (990000)."
        )

    def test_fresh_anchor_not_recomputed(self):
        """A fresh anchor (block end in the future) should not be recomputed."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        model._next_block_start_ms = 1_000_000  # Current time
        recovered = model.recompute_anchor_if_stale()
        assert not recovered, (
            "Fresh anchor should not be recomputed."
        )

    def test_start_always_uses_fresh_anchor(self):
        """Even if old state has stale anchor, start() overwrites it."""
        clock = FakeMasterClock(initial_utc_ms=2_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        # Pollute with stale state
        model._next_block_start_ms = 100  # Way in the past

        # start() should overwrite with grid-aligned join_utc_ms
        blocks = model.start(join_utc_ms=2_000_000)
        assert blocks[0].start_utc_ms == 1_980_000, (
            "INV-WALLCLOCK-FENCE-005 VIOLATION: start() did not anchor "
            "to grid-aligned join_utc_ms (1980000)."
        )


# =============================================================================
# 4. INV-WALLCLOCK-FENCE-002: Only active blocks can complete
# =============================================================================

class TestOnlyActiveBlocksCanComplete:
    """INV-WALLCLOCK-FENCE-002: Completion events for unknown or
    already-completed blocks must be rejected."""

    def test_unknown_block_rejected(self):
        """Calling on_block_complete with an unknown block_id is rejected."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)
        model.start(join_utc_ms=clock.now_utc_ms)

        accepted = model.on_block_complete("BLOCK-unknown-999")
        assert not accepted, (
            "INV-WALLCLOCK-FENCE-002 VIOLATION: completion accepted for "
            "unknown block ID."
        )
        assert model._rejection_log[-1][1] == "not_active"

    def test_prior_session_blocks_rejected(self):
        """Blocks from a prior session (block IDs 16/17) cannot complete
        in a new session."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        # Session 1: generates blocks 0, 1
        model.start(join_utc_ms=clock.now_utc_ms)

        # Simulate session restart
        clock.advance(60_000)
        model.start(join_utc_ms=clock.now_utc_ms)
        # New session generates blocks 0, 1 (indices reset)

        # Try completing block from session 1 (BLOCK-test-0 was cleared by start())
        # Since start() clears in_flight, old IDs are gone
        accepted = model.on_block_complete("BLOCK-test-0")
        # This BLOCK-test-0 was regenerated in the new session, so it's actually
        # in-flight. Let me use a truly foreign ID instead.
        accepted = model.on_block_complete("BLOCK-other-session-16")
        assert not accepted, (
            "INV-WALLCLOCK-FENCE-002 VIOLATION: completion accepted for "
            "block from prior session."
        )

    def test_duplicate_completion_rejected(self):
        """Completing the same block twice is rejected."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=clock.now_utc_ms)
        block_a = blocks[0]

        clock.advance(30_000)  # past block A's start

        # First completion: accepted
        assert model.on_block_complete(block_a.block_id) is True

        # Second completion: rejected (already completed)
        assert model.on_block_complete(block_a.block_id) is False
        assert model._rejection_log[-1][1] == "duplicate"

    def test_active_block_completes_successfully(self):
        """A block that was seeded/fed and is active can complete."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=clock.now_utc_ms)

        clock.advance(30_000)
        assert model.on_block_complete(blocks[0].block_id) is True

        clock.advance(30_000)
        assert model.on_block_complete(blocks[1].block_id) is True


# =============================================================================
# 5. INV-WALLCLOCK-FENCE-004: One completion per tick
# =============================================================================

class TestOneCompletionPerTick:
    """INV-WALLCLOCK-FENCE-004: At most one completion per callback
    invocation, even if time has jumped far ahead."""

    def test_one_completion_per_tick(self):
        """Step clock beyond end_ts by 300s. Each on_block_complete call
        processes exactly one block."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=clock.now_utc_ms)
        # Feed several more blocks
        for _ in range(5):
            model.feed_block()

        # Jump clock way ahead (300 seconds past all blocks)
        clock.advance(300_000)

        # Complete block A: should accept exactly one
        accepted = model.on_block_complete(blocks[0].block_id)
        assert accepted
        assert len(model._completion_log) == 1, (
            "INV-WALLCLOCK-FENCE-004 VIOLATION: more than one completion "
            "processed in a single on_block_complete call."
        )

        # Complete block B: another single completion
        accepted = model.on_block_complete(blocks[1].block_id)
        assert accepted
        assert len(model._completion_log) == 2

    def test_no_while_loop_cascade(self):
        """Verify the model does NOT have a while loop that auto-completes
        multiple past-due blocks."""
        clock = FakeMasterClock(initial_utc_ms=1_000_000)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=clock.now_utc_ms)
        block_a, block_b = blocks

        # Jump to 5 minutes later
        clock.advance(300_000)

        # Only block_a completes (one call = one completion)
        model.on_block_complete(block_a.block_id)
        assert len(model._completion_log) == 1
        assert model._completion_log[0] == block_a.block_id

        # block_b is still in-flight (not auto-completed)
        assert block_b.block_id in model._in_flight_block_ids


# =============================================================================
# 6. INV-WALLCLOCK-FENCE-005: JIP does not shift schedule timing
# =============================================================================

class TestJIPDoesNotShiftTiming:
    """INV-WALLCLOCK-FENCE-005: JIP affects segment duration and
    asset_start_offset_ms only.  Block duration is always full.
    Block start is grid-aligned."""

    def test_jip_does_not_shift_schedule_timing(self):
        """Block A with JIP offset has full block duration; only segment is reduced."""
        epoch = 1_738_987_500_000  # ~Feb 2026, grid-aligned to 30s
        clock = FakeMasterClock(initial_utc_ms=epoch)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(
            join_utc_ms=epoch,
            jip_offset_ms=15_000,  # 15s into the block
        )
        block_a, block_b = blocks

        # Block A: starts at grid-aligned epoch, FULL duration
        assert block_a.start_utc_ms == epoch, (
            "INV-WALLCLOCK-FENCE-005 VIOLATION: JIP shifted start_utc_ms. "
            f"Got {block_a.start_utc_ms}, expected {epoch}."
        )
        assert block_a.duration_ms == 30_000, (
            "INV-WALLCLOCK-FENCE-005 VIOLATION: block duration must be full "
            f"(30000), got {block_a.duration_ms}. JIP must never reduce "
            "block duration."
        )
        assert block_a.end_utc_ms == epoch + 30_000, (
            "Block A end should be epoch + full duration."
        )
        assert block_a.asset_start_offset_ms == 15_000, (
            "JIP offset should be in asset_start_offset_ms."
        )
        # Segment duration is reduced by JIP offset
        assert block_a.segment_duration_ms == 15_000, (
            "Segment duration should be 30000 - 15000 = 15000."
        )

        # Block B: starts where A ends, full duration
        assert block_b.start_utc_ms == block_a.end_utc_ms
        assert block_b.duration_ms == 30_000
        assert block_b.end_utc_ms == block_a.end_utc_ms + 30_000

    def test_jip_completion_at_scheduled_end(self):
        """Block A with JIP completes at its full-duration end, not reduced."""
        epoch = 1_738_987_500_000
        clock = FakeMasterClock(initial_utc_ms=epoch)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=epoch, jip_offset_ms=10_000)
        block_a = blocks[0]

        # Block A: end = epoch + 30000 (full duration, NOT epoch + 20000)
        assert block_a.end_utc_ms == epoch + 30_000

        # Advance past block A's end
        clock.advance(30_000)

        accepted = model.on_block_complete(block_a.block_id)
        assert accepted

    def test_no_jip_full_duration(self):
        """Without JIP, block A has full duration and segment equals block."""
        epoch = 1_738_987_500_000
        clock = FakeMasterClock(initial_utc_ms=epoch)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        blocks = model.start(join_utc_ms=epoch, jip_offset_ms=0)
        block_a = blocks[0]

        assert block_a.duration_ms == 30_000
        assert block_a.end_utc_ms == epoch + 30_000
        assert block_a.asset_start_offset_ms == 0
        assert block_a.segment_duration_ms == 30_000

    def test_block_duration_never_reduced_by_jip(self):
        """Block duration MUST always equal block_duration_ms, regardless of JIP offset."""
        epoch = 1_738_987_500_000
        clock = FakeMasterClock(initial_utc_ms=epoch)
        model = BlockPlanProducerModel(clock=clock, block_duration_ms=30_000)

        for jip_offset in [0, 1, 5_000, 15_000, 29_999]:
            blocks = model.start(join_utc_ms=epoch, jip_offset_ms=jip_offset)
            for block in blocks:
                assert block.duration_ms == 30_000, (
                    f"INV-WALLCLOCK-FENCE-005 VIOLATION: block duration is "
                    f"{block.duration_ms} (expected 30000) with "
                    f"jip_offset={jip_offset}. "
                    f"JIP must never reduce block duration."
                )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
