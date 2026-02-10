"""
Contract Tests: INV-JOIN-IN-PROGRESS-BLOCKPLAN

Contract reference:
    docs/contracts/runtime/INV-JOIN-IN-PROGRESS-BLOCKPLAN.md

These tests enforce the Join-In-Progress invariants for the BlockPlan
bootstrap path:

    INV-JIP-BP-001  Single computation on first viewer (0->1 transition)
    INV-JIP-BP-002  block_offset_ms in [0, active_entry_duration_ms)
    INV-JIP-BP-003  Deterministic mapping for identical inputs
    INV-JIP-BP-004  Continuous sequence (no rewind, no skip)
    INV-JIP-BP-005  First seed carries offset, second seed starts clean
    INV-JIP-BP-006  Block duration always full; segment duration reduced by offset
    INV-JIP-BP-007  Cursor consistency after seeding
    INV-JIP-BP-008  Steady-state feeding unchanged after JIP seed

All tests are deterministic and require no media files or AIR process.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Guarded import: compute_jip_position is the pure function defined by
# the JIP design.  If it doesn't exist yet, tests that depend on it
# will fail with an explicit TODO message.
# ---------------------------------------------------------------------------
try:
    from retrovue.runtime.channel_manager import compute_jip_position
    _HAS_COMPUTE_JIP = True
except ImportError:
    _HAS_COMPUTE_JIP = False
    compute_jip_position = None  # type: ignore[assignment]

from retrovue.runtime.channel_manager import BlockPlanProducer


# =============================================================================
# Test Infrastructure
# =============================================================================

# A uniform plan: 3 entries, each 10 000 ms
UNIFORM_PLAN = [
    {"asset_path": "assets/A.mp4", "duration_ms": 10_000},
    {"asset_path": "assets/B.mp4", "duration_ms": 10_000},
    {"asset_path": "assets/C.mp4", "duration_ms": 10_000},
]
UNIFORM_CYCLE_MS = 30_000  # 10 + 10 + 10

# A heterogeneous plan: entries with different durations
VARIABLE_PLAN = [
    {"asset_path": "assets/Ep1.mp4", "duration_ms": 25_000},
    {"asset_path": "assets/Filler.mp4", "duration_ms": 5_000},
    {"asset_path": "assets/Ep2.mp4", "duration_ms": 20_000},
]
VARIABLE_CYCLE_MS = 50_000  # 25 + 5 + 20

# A plan where entries carry a non-zero base asset_start_offset_ms
OFFSET_PLAN = [
    {"asset_path": "assets/Movie.mp4", "asset_start_offset_ms": 60_000,
     "duration_ms": 15_000},
    {"asset_path": "assets/Bumper.mp4", "duration_ms": 5_000},
]
OFFSET_CYCLE_MS = 20_000  # 15 + 5

DEFAULT_BLOCK_DURATION_MS = 10_000
CYCLE_ORIGIN = 0  # Unix epoch anchor


def _require_compute_jip() -> None:
    """Fail fast if the JIP pure function is not yet implemented."""
    if not _HAS_COMPUTE_JIP:
        pytest.fail(
            "TODO: compute_jip_position() not yet implemented in "
            "retrovue.runtime.channel_manager.  "
            "Add: def compute_jip_position(playout_plan, block_duration_ms, "
            "cycle_origin_utc_ms, now_utc_ms) -> tuple[int, int]"
        )


def _make_producer(block_duration_ms: int = DEFAULT_BLOCK_DURATION_MS) -> BlockPlanProducer:
    """Create a bare BlockPlanProducer (no session, no AIR)."""
    return BlockPlanProducer(
        channel_id="jip-test",
        configuration={"block_duration_ms": block_duration_ms},
        channel_config=None,   # uses MOCK_CHANNEL_CONFIG
        schedule_service=None,
        clock=None,
    )


def _generate_with_jip(
    producer: BlockPlanProducer,
    plan: list[dict[str, Any]],
    jip_offset_ms: int,
) -> Any:
    """
    Call _generate_next_block with jip_offset_ms.

    Fails clearly if the parameter hasn't been added yet.
    """
    try:
        return producer._generate_next_block(plan, jip_offset_ms=jip_offset_ms)
    except TypeError:
        pytest.fail(
            "TODO: _generate_next_block() does not yet accept the "
            "jip_offset_ms keyword argument.  "
            "Add: def _generate_next_block(self, playout_plan, "
            "jip_offset_ms=0) -> BlockPlan"
        )


# =============================================================================
# 1. INV-JIP-BP-002: Offset within block range
# =============================================================================

class TestJipOffsetWithinBlockRange:
    """
    INV-JIP-BP-002: block_offset_ms in [0, active_entry_duration_ms).

    For several station_now values — including boundary hits, mid-block,
    and multi-cycle wraps — the computed offset must be non-negative and
    strictly less than the active entry's resolved duration.
    """

    def test_uniform_plan_various_times(self):
        """Offset is in bounds for a uniform-duration plan at many time points."""
        _require_compute_jip()

        # Times chosen to exercise: start, mid-block, boundary, wrap
        test_times_ms = [
            0,          # exactly at cycle start
            1,          # 1 ms in
            5_000,      # mid-first-entry
            9_999,      # 1 ms before first boundary
            10_000,     # exactly at second entry
            15_000,     # mid-second-entry
            20_000,     # exactly at third entry
            29_999,     # 1 ms before cycle wrap
            30_000,     # exactly at cycle wrap (back to entry 0)
            30_001,     # 1 ms after wrap
            75_000,     # 2.5 cycles in
            999_999,    # large elapsed time
        ]

        for now_ms in test_times_ms:
            index, offset = compute_jip_position(
                UNIFORM_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, now_ms,
            )
            entry_dur = UNIFORM_PLAN[index].get("duration_ms", DEFAULT_BLOCK_DURATION_MS)
            assert 0 <= offset < entry_dur, (
                f"INV-JIP-BP-002: offset={offset} not in [0, {entry_dur}) "
                f"for now_ms={now_ms}, index={index}"
            )

    def test_variable_plan_various_times(self):
        """Offset is in bounds when entries have heterogeneous durations."""
        _require_compute_jip()

        test_times_ms = [0, 12_000, 24_999, 25_000, 29_999, 30_000, 49_999, 50_000, 100_000]

        for now_ms in test_times_ms:
            index, offset = compute_jip_position(
                VARIABLE_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, now_ms,
            )
            entry_dur = VARIABLE_PLAN[index].get("duration_ms", DEFAULT_BLOCK_DURATION_MS)
            assert 0 <= offset < entry_dur, (
                f"INV-JIP-BP-002: offset={offset} not in [0, {entry_dur}) "
                f"for now_ms={now_ms}, index={index} (variable plan)"
            )

    def test_single_entry_plan(self):
        """Single-entry plan: index always 0, offset wraps within entry."""
        _require_compute_jip()

        plan = [{"asset_path": "assets/Solo.mp4", "duration_ms": 8_000}]

        for now_ms in [0, 3_000, 7_999, 8_000, 16_000, 100_000]:
            index, offset = compute_jip_position(plan, 8_000, CYCLE_ORIGIN, now_ms)
            assert index == 0, f"Single-entry plan must always select index 0, got {index}"
            assert 0 <= offset < 8_000, (
                f"INV-JIP-BP-002: offset={offset} not in [0, 8000) for now_ms={now_ms}"
            )


# =============================================================================
# 2. INV-JIP-BP-003: Deterministic mapping
# =============================================================================

class TestJipDeterministicMapping:
    """
    INV-JIP-BP-003: Identical inputs always produce identical outputs.

    Also verifies correct index selection for known positions in the cycle.
    """

    def test_same_inputs_same_outputs(self):
        """10 identical calls produce identical (index, offset) pairs."""
        _require_compute_jip()

        now_ms = 47_123  # arbitrary
        first_result = compute_jip_position(
            UNIFORM_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, now_ms,
        )

        for i in range(10):
            result = compute_jip_position(
                UNIFORM_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, now_ms,
            )
            assert result == first_result, (
                f"INV-JIP-BP-003: call {i} returned {result}, expected {first_result}"
            )

    def test_known_positions_uniform(self):
        """Verify exact index and offset for known cycle positions."""
        _require_compute_jip()

        # Plan: [A=10s, B=10s, C=10s], cycle=30s, origin=0
        cases = [
            # (now_ms, expected_index, expected_offset)
            (0,      0, 0),      # start of A
            (5_000,  0, 5_000),  # mid A
            (10_000, 1, 0),      # start of B
            (15_000, 1, 5_000),  # mid B
            (20_000, 2, 0),      # start of C
            (25_000, 2, 5_000),  # mid C
            (30_000, 0, 0),      # cycle wrap → start of A
            (35_000, 0, 5_000),  # second cycle, mid A
            (60_000, 0, 0),      # two full cycles
        ]

        for now_ms, exp_idx, exp_off in cases:
            index, offset = compute_jip_position(
                UNIFORM_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, now_ms,
            )
            assert (index, offset) == (exp_idx, exp_off), (
                f"INV-JIP-BP-003: now_ms={now_ms} → ({index}, {offset}), "
                f"expected ({exp_idx}, {exp_off})"
            )

    def test_known_positions_variable(self):
        """Correct index for heterogeneous durations (25s + 5s + 20s = 50s)."""
        _require_compute_jip()

        cases = [
            # (now_ms, expected_index, expected_offset)
            (0,      0, 0),       # start of Ep1 (25s)
            (12_000, 0, 12_000),  # mid Ep1
            (24_999, 0, 24_999),  # last ms of Ep1
            (25_000, 1, 0),       # start of Filler (5s)
            (27_000, 1, 2_000),   # mid Filler
            (30_000, 2, 0),       # start of Ep2 (20s)
            (45_000, 2, 15_000),  # mid Ep2
            (49_999, 2, 19_999),  # last ms of Ep2
            (50_000, 0, 0),       # cycle wrap
            (75_000, 0, 25_000),  # oops — 75000 % 50000 = 25000, which is start of Filler
        ]

        # Fix the last case: 75000 % 50000 = 25000 → Filler start
        cases[-1] = (75_000, 1, 0)

        for now_ms, exp_idx, exp_off in cases:
            index, offset = compute_jip_position(
                VARIABLE_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, now_ms,
            )
            assert (index, offset) == (exp_idx, exp_off), (
                f"INV-JIP-BP-003: now_ms={now_ms} → ({index}, {offset}), "
                f"expected ({exp_idx}, {exp_off}) [variable plan]"
            )

    def test_nonzero_cycle_origin(self):
        """Non-zero cycle_origin shifts the reference correctly."""
        _require_compute_jip()

        origin = 100_000  # cycle started at 100s
        # At now=105_000, elapsed = 5_000 → entry 0, offset 5_000
        index, offset = compute_jip_position(
            UNIFORM_PLAN, DEFAULT_BLOCK_DURATION_MS, origin, 105_000,
        )
        assert (index, offset) == (0, 5_000), (
            f"INV-JIP-BP-003: nonzero origin → ({index}, {offset}), "
            f"expected (0, 5000)"
        )


# =============================================================================
# 3. INV-JIP-BP-005 + 006: First block offset, second block clean
# =============================================================================

class TestJipAppliesOffsetOnlyToFirstSeededBlock:
    """
    INV-JIP-BP-005: First seeded block carries JIP offset; second starts clean.
    INV-JIP-BP-006 / INV-JIP-WALLCLOCK-001: Block duration is always full
    (wall-clock invariant); only segment_duration_ms is reduced by JIP offset.

    Tests operate on _generate_next_block directly, simulating the seeding
    sequence that start() performs.
    """

    def test_first_block_offset_second_block_clean(self):
        """block_a.offset == jip_offset, block_b.offset == 0."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN

        # Simulate JIP at entry 0, offset 3000
        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=3_000)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(plan)

        # block_a: plan entry 0 (A.mp4), entry offset 0 + jip 3000 = 3000
        assert block_a.segments[0]["asset_start_offset_ms"] == 3_000, (
            f"INV-JIP-BP-005: block_a offset should be 3000, "
            f"got {block_a.segments[0]['asset_start_offset_ms']}"
        )

        # block_b: plan entry 1 (B.mp4), entry offset 0, no JIP
        assert block_b.segments[0]["asset_start_offset_ms"] == 0, (
            f"INV-JIP-BP-005: block_b offset should be 0, "
            f"got {block_b.segments[0]['asset_start_offset_ms']}"
        )

    def test_first_block_duration_immutable(self):
        """INV-JIP-BP-006: block duration always full; segment reduced by JIP offset."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN

        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=3_000)

        # Block container is always full duration (wall-clock invariant).
        assert block_a.duration_ms == 10_000, (
            f"INV-JIP-WALLCLOCK-001: block_a duration should be 10000 (full), "
            f"got {block_a.duration_ms}"
        )
        assert block_a.end_utc_ms - block_a.start_utc_ms == 10_000

        # Segment duration is the remaining content after JIP seek.
        assert block_a.segments[0]["segment_duration_ms"] == 7_000, (
            f"INV-JIP-BP-006: segment_duration_ms should be 7000, "
            f"got {block_a.segments[0]['segment_duration_ms']}"
        )

    def test_second_block_full_duration(self):
        """block_b uses full entry duration (no reduction)."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN

        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=3_000)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(plan)

        assert block_b.duration_ms == 10_000, (
            f"INV-JIP-BP-005: block_b should have full duration 10000, "
            f"got {block_b.duration_ms}"
        )

    def test_entry_with_base_offset_adds_jip(self):
        """JIP offset adds to the entry's own asset_start_offset_ms."""
        producer = _make_producer(block_duration_ms=15_000)
        plan = OFFSET_PLAN  # entry 0: asset_start_offset_ms=60000, duration=15000

        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=5_000)

        # Expected: entry offset 60000 + JIP offset 5000 = 65000
        assert block_a.segments[0]["asset_start_offset_ms"] == 65_000, (
            f"INV-JIP-BP-005: entry offset 60000 + JIP 5000 = 65000, "
            f"got {block_a.segments[0]['asset_start_offset_ms']}"
        )
        # Block duration is always full (wall-clock invariant).
        assert block_a.duration_ms == 15_000, (
            f"INV-JIP-WALLCLOCK-001: block duration should be 15000 (full), "
            f"got {block_a.duration_ms}"
        )
        # Segment duration is reduced by JIP offset.
        assert block_a.segments[0]["segment_duration_ms"] == 10_000, (
            f"INV-JIP-BP-006: segment 15000 - 5000 = 10000, "
            f"got {block_a.segments[0]['segment_duration_ms']}"
        )

    def test_zero_offset_produces_full_block(self):
        """JIP offset 0 means no modification — full block, original offset."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN

        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=0)

        assert block_a.segments[0]["asset_start_offset_ms"] == 0
        assert block_a.duration_ms == 10_000
        assert block_a.segments[0]["segment_duration_ms"] == 10_000

    def test_presentation_time_contiguous(self):
        """block_b.start_utc_ms == block_a.end_utc_ms (no gap)."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN

        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=4_000)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(plan)

        # INV-JIP-WALLCLOCK-001: block_a is full duration, not shortened.
        assert block_a.start_utc_ms == 0
        assert block_a.end_utc_ms == 10_000, (
            f"INV-JIP-WALLCLOCK-001: block_a end should be 10000 (full), "
            f"got {block_a.end_utc_ms}"
        )
        assert block_b.start_utc_ms == 10_000, (
            f"Presentation gap: block_a ends at {block_a.end_utc_ms}, "
            f"block_b starts at {block_b.start_utc_ms}"
        )


# =============================================================================
# 4. INV-JIP-BP-007: Cursor consistency after seeding
# =============================================================================

class TestJipCursorStateAfterSeed:
    """
    INV-JIP-BP-007: After seeding two blocks, cursor state allows correct
    next-block generation with no rewinds or skips.
    """

    def test_cursor_points_to_correct_next_entry(self):
        """
        JIP at entry 1 → seed B(partial), C(full) → cursor at entry 0.
        """
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN  # [A, B, C]

        # JIP says: entry 1 (B.mp4), offset 5000
        producer._block_index = 1
        producer._next_block_start_ms = 10_000
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=5_000)
        producer._advance_cursor(block_a)

        block_b = producer._generate_next_block(plan)
        producer._advance_cursor(block_b)

        # After seeding entries 1 and 2, next should be entry 0 (wrap).
        # _block_index is an ID counter; entry selection derives from
        # _next_block_start_ms via wall-clock position.

        # Verify the next generated block IS entry 0 (A.mp4)
        block_c = producer._generate_next_block(plan)
        assert block_c.segments[0]["asset_uri"] == "assets/A.mp4", (
            f"Next block should be A.mp4, got {block_c.segments[0]['asset_uri']}"
        )

    def test_next_block_start_ms_contiguous(self):
        """_next_block_start_ms == block_b.end_utc_ms."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN

        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=3_000)
        producer._advance_cursor(block_a)

        block_b = producer._generate_next_block(plan)
        producer._advance_cursor(block_b)

        assert producer._next_block_start_ms == block_b.end_utc_ms, (
            f"INV-JIP-BP-007: _next_block_start_ms={producer._next_block_start_ms} "
            f"!= block_b.end_utc_ms={block_b.end_utc_ms}"
        )

        # The next generated block starts where block_b ended
        block_c = producer._generate_next_block(plan)
        assert block_c.start_utc_ms == block_b.end_utc_ms

    def test_full_sequence_no_gaps(self):
        """
        Generate 5 blocks from JIP point — verify contiguous timeline
        and correct round-robin cycling.
        """
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN  # [A, B, C]

        # JIP at entry 2 (C.mp4), offset 7000
        producer._block_index = 2
        producer._next_block_start_ms = 20_000
        blocks = []

        block = _generate_with_jip(producer, plan, jip_offset_ms=7_000)
        blocks.append(block)
        producer._advance_cursor(block)

        for _ in range(4):
            block = producer._generate_next_block(plan)
            blocks.append(block)
            producer._advance_cursor(block)

        # Verify contiguous timeline (no gaps)
        for i in range(1, len(blocks)):
            assert blocks[i].start_utc_ms == blocks[i - 1].end_utc_ms, (
                f"Gap between block {i-1} and {i}: "
                f"end={blocks[i-1].end_utc_ms}, start={blocks[i].start_utc_ms}"
            )

        # Verify asset sequence: C(partial) → A → B → C → A
        expected_assets = ["assets/C.mp4", "assets/A.mp4", "assets/B.mp4",
                           "assets/C.mp4", "assets/A.mp4"]
        actual_assets = [b.segments[0]["asset_uri"] for b in blocks]
        assert actual_assets == expected_assets, (
            f"INV-JIP-BP-004/007: Expected sequence {expected_assets}, "
            f"got {actual_assets}"
        )

        # INV-JIP-WALLCLOCK-001: ALL blocks are full duration.
        # JIP only reduces segment_duration_ms within block_a.
        for b in blocks:
            assert b.duration_ms == 10_000, (
                f"INV-JIP-WALLCLOCK-001: block {b.block_id} duration should be "
                f"10000 (full), got {b.duration_ms}"
            )
        # First block's segment is partial (3000ms remaining after JIP seek)
        assert blocks[0].segments[0]["segment_duration_ms"] == 3_000

    def test_variable_duration_cursor(self):
        """Cursor is correct with heterogeneous entry durations."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = VARIABLE_PLAN  # [Ep1=25s, Filler=5s, Ep2=20s]

        # JIP at entry 0 (Ep1), offset 10_000
        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=10_000)
        producer._advance_cursor(block_a)

        # INV-JIP-WALLCLOCK-001: block_a is full entry duration.
        # Segment duration is the remaining content after JIP seek.
        assert block_a.duration_ms == 25_000, (
            f"INV-JIP-WALLCLOCK-001: block_a duration should be 25000 (full), "
            f"got {block_a.duration_ms}"
        )
        assert block_a.segments[0]["segment_duration_ms"] == 15_000
        assert block_a.segments[0]["asset_uri"] == "assets/Ep1.mp4"

        block_b = producer._generate_next_block(plan)
        producer._advance_cursor(block_b)

        # block_b: Filler, full 5000
        assert block_b.duration_ms == 5_000
        assert block_b.segments[0]["asset_uri"] == "assets/Filler.mp4"

        # Next should be Ep2
        block_c = producer._generate_next_block(plan)
        assert block_c.segments[0]["asset_uri"] == "assets/Ep2.mp4"
        assert block_c.duration_ms == 20_000


# =============================================================================
# 5. INV-JIP-BP-001: No polling / timer / sleep in JIP path
# =============================================================================

class TestJipNoPollingOrTimerRetry:
    """
    INV-JIP-BP-001: JIP is computed once, synchronously, during the 0->1
    join path.  No timers, sleeps, or polling loops.
    """

    def test_compute_jip_does_not_sleep(self, monkeypatch):
        """time.sleep is never called by compute_jip_position."""
        _require_compute_jip()

        sleep_calls = []
        monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

        compute_jip_position(UNIFORM_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, 15_000)

        assert len(sleep_calls) == 0, (
            f"INV-JIP-BP-001: compute_jip_position called time.sleep "
            f"{len(sleep_calls)} time(s)"
        )

    def test_compute_jip_does_not_create_threads(self, monkeypatch):
        """No Thread or Timer is created during JIP computation."""
        _require_compute_jip()

        threads_created = []
        original_init = threading.Thread.__init__

        def spy_thread_init(self_thread, *args, **kwargs):
            threads_created.append(self_thread)
            original_init(self_thread, *args, **kwargs)

        monkeypatch.setattr(threading.Thread, "__init__", spy_thread_init)

        compute_jip_position(VARIABLE_PLAN, DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, 37_000)

        assert len(threads_created) == 0, (
            f"INV-JIP-BP-001: compute_jip_position spawned "
            f"{len(threads_created)} thread(s)"
        )

    def test_generate_with_jip_does_not_sleep(self, monkeypatch):
        """Block generation with JIP offset does not sleep."""
        sleep_calls = []
        monkeypatch.setattr(time, "sleep", lambda s: sleep_calls.append(s))

        producer = _make_producer(block_duration_ms=10_000)
        producer._block_index = 0
        _generate_with_jip(producer, UNIFORM_PLAN, jip_offset_ms=5_000)

        assert len(sleep_calls) == 0, (
            "INV-JIP-BP-001: _generate_next_block(jip_offset_ms=...) "
            "must not call time.sleep"
        )


# =============================================================================
# 6. Burn-in tripwire: _playlist must not be set
# =============================================================================

class TestBurnInTripwirePlaylistNotSet:
    """
    Contract constraint C2: JIP operates on playout_plan (list[dict]).
    BlockPlanProducer must never read or require manager._playlist.

    The burn-in path enforces that _playlist is None on the manager.
    """

    def test_producer_has_no_playlist_attribute(self):
        """BlockPlanProducer must not own a _playlist field."""
        producer = _make_producer()
        assert not hasattr(producer, "_playlist"), (
            "BlockPlanProducer must not have a _playlist attribute. "
            "JIP operates on playout_plan (list[dict]) only."
        )

    def test_jip_works_without_playlist(self):
        """
        JIP block generation succeeds with only a playout_plan list.
        No Playlist object, no manager._playlist, no schedule-manager
        dependency.
        """
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN  # plain list[dict], no Playlist wrapper

        producer._block_index = 1
        producer._next_block_start_ms = 10_000
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=2_000)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(plan)

        # Succeeds without any Playlist or _playlist
        assert block_a.segments[0]["asset_uri"] == "assets/B.mp4"
        assert block_b.segments[0]["asset_uri"] == "assets/C.mp4"


# =============================================================================
# 7. INV-JIP-BP-008: Steady-state feeding unchanged
# =============================================================================

class TestJipSteadyStateFeedingUnchanged:
    """
    INV-JIP-BP-008: After JIP seeding, the feeding discipline is governed
    entirely by INV-FEED-QUEUE-*.  JIP introduces no extra state or
    control paths into the steady-state loop.
    """

    def test_on_block_complete_after_jip_is_normal(self):
        """
        _on_block_complete after JIP seed generates the correct next block
        using the standard path (no JIP offset leaking into steady-state).
        """
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN  # [A, B, C]
        producer._playout_plan = plan
        producer._started = True

        # Simulate JIP seed: entry 1, offset 5000
        producer._block_index = 1
        producer._next_block_start_ms = 10_000
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=5_000)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(plan)
        producer._advance_cursor(block_b)

        # At this point: _block_index should be 3
        # Simulate what _on_block_complete does: generate next block
        next_block = producer._generate_next_block(producer._playout_plan)

        # Should be entry 3 % 3 = 0 → A.mp4, full duration, no JIP offset
        assert next_block.segments[0]["asset_uri"] == "assets/A.mp4"
        assert next_block.segments[0]["asset_start_offset_ms"] == 0
        assert next_block.duration_ms == 10_000, (
            "INV-JIP-BP-008: Steady-state block must use full duration, "
            f"got {next_block.duration_ms}"
        )

    def test_pending_block_slot_not_affected_by_jip(self):
        """JIP seed does not leave anything in _pending_block."""
        producer = _make_producer(block_duration_ms=10_000)
        plan = UNIFORM_PLAN

        # Simulate JIP seeding
        producer._block_index = 0
        block_a = _generate_with_jip(producer, plan, jip_offset_ms=2_000)
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(plan)
        producer._advance_cursor(block_b)

        assert producer._pending_block is None, (
            "INV-JIP-BP-008: _pending_block must be None after JIP seeding"
        )


# =============================================================================
# 8. Edge case: empty plan
# =============================================================================

class TestJipEdgeCases:
    """Additional edge-case tests derived from the contract."""

    def test_empty_plan_returns_zero_zero(self):
        """Empty playout_plan produces (0, 0) — no-JIP fallback."""
        _require_compute_jip()

        index, offset = compute_jip_position([], DEFAULT_BLOCK_DURATION_MS, CYCLE_ORIGIN, 50_000)
        assert (index, offset) == (0, 0), (
            f"Empty plan should produce (0, 0), got ({index}, {offset})"
        )

    def test_now_before_origin(self):
        """
        If now_utc_ms < cycle_origin_utc_ms, the elapsed time is negative.
        The function should handle this gracefully (e.g., mod wraps).
        """
        _require_compute_jip()

        origin = 100_000
        now = 50_000  # 50s before origin

        index, offset = compute_jip_position(
            UNIFORM_PLAN, DEFAULT_BLOCK_DURATION_MS, origin, now,
        )
        entry_dur = UNIFORM_PLAN[index].get("duration_ms", DEFAULT_BLOCK_DURATION_MS)
        assert 0 <= offset < entry_dur, (
            f"INV-JIP-BP-002: offset={offset} not in [0, {entry_dur}) "
            f"for now < origin"
        )


# =============================================================================
# 9. INV-BLOCK-ALIGNMENT-001: Block boundaries aligned under JIP
# =============================================================================

class TestBlockAlignmentUnderJip:
    """
    INV-BLOCK-ALIGNMENT-001: block.start_utc_ms must be aligned to grid
    boundaries, regardless of JIP offset.

    Regression: burn_in.py shortened block_dur_ms by jip_offset_ms,
    making end_utc_ms misaligned.  The misaligned end cascaded to the
    next block's start_utc_ms, triggering:
        "BURN_IN: start not aligned to 30-min boundary (offset=1702903)"
    on block B even though block A's start was correctly aligned.

    Fix: block duration is NEVER reduced (INV-JIP-WALLCLOCK-001); pad
    absorbs the JIP gap.  Alignment is checked on start_utc_ms for ALL
    blocks, before segment composition.
    """

    def test_jip_block_start_and_end_aligned(self):
        """Block A (JIP): both start and end sit on grid boundaries."""
        block_dur = 10_000
        producer = _make_producer(block_duration_ms=block_dur)
        producer._block_index = 0
        producer._next_block_start_ms = block_dur  # = 10_000, aligned

        block_a = _generate_with_jip(producer, UNIFORM_PLAN, jip_offset_ms=3_000)

        assert block_a.start_utc_ms % block_dur == 0, (
            f"INV-BLOCK-ALIGNMENT-001: block_a.start_utc_ms="
            f"{block_a.start_utc_ms} not aligned to {block_dur}ms"
        )
        assert block_a.end_utc_ms % block_dur == 0, (
            f"INV-BLOCK-ALIGNMENT-001: block_a.end_utc_ms="
            f"{block_a.end_utc_ms} not aligned to {block_dur}ms"
        )
        assert block_a.duration_ms == block_dur

    def test_block_b_aligned_after_jip_block_a(self):
        """Block B inherits block A's end; both must be aligned."""
        block_dur = 10_000
        producer = _make_producer(block_duration_ms=block_dur)
        producer._block_index = 0
        producer._next_block_start_ms = block_dur

        block_a = _generate_with_jip(producer, UNIFORM_PLAN, jip_offset_ms=3_000)
        producer._advance_cursor(block_a)

        block_b = producer._generate_next_block(UNIFORM_PLAN)

        assert block_b.start_utc_ms == block_a.end_utc_ms, (
            f"Contiguity: block_b.start={block_b.start_utc_ms} "
            f"!= block_a.end={block_a.end_utc_ms}"
        )
        assert block_b.start_utc_ms % block_dur == 0, (
            f"INV-BLOCK-ALIGNMENT-001: block_b.start_utc_ms="
            f"{block_b.start_utc_ms} not aligned to {block_dur}ms"
        )

    def test_30min_jip_at_19_01_into_19_00_block(self):
        """
        Regression scenario: join at 19:01 into a 19:00 block.

        block.start_utc_ms is boundary-aligned; jip_offset_ms is non-zero;
        block generation succeeds and all subsequent blocks are aligned.
        """
        block_dur = 1_800_000  # 30 minutes
        producer = _make_producer(block_duration_ms=block_dur)

        # Plan entries must carry duration_ms matching the block size
        # (canonical _generate_next_block uses entry duration_ms).
        plan_30m = [
            {"asset_path": "assets/A.mp4", "duration_ms": block_dur},
            {"asset_path": "assets/B.mp4", "duration_ms": block_dur},
        ]

        # Simulate: cycle origin at 00:00 UTC, block starts at 19:00
        # _next_block_start_ms = 19 * 2 = 38 half-hours from midnight
        aligned_start = 38 * block_dur  # 19:00:00 UTC in ms from midnight
        producer._block_index = 0
        producer._next_block_start_ms = aligned_start

        # JIP 60 seconds into the block (viewer joins at 19:01)
        jip_ms = 60_000
        block_a = _generate_with_jip(producer, plan_30m, jip_offset_ms=jip_ms)

        # Block A: aligned start, full duration, aligned end
        assert block_a.start_utc_ms == aligned_start
        assert block_a.start_utc_ms % block_dur == 0
        assert block_a.duration_ms == block_dur, (
            f"INV-JIP-WALLCLOCK-001: duration should be {block_dur}, "
            f"got {block_a.duration_ms}"
        )
        assert block_a.end_utc_ms % block_dur == 0

        # Segment duration is reduced by JIP (content starts later),
        # but block container is full.
        seg_dur = block_a.segments[0]["segment_duration_ms"]
        assert seg_dur == block_dur - jip_ms, (
            f"Segment should be {block_dur - jip_ms}, got {seg_dur}"
        )

        # Block B: contiguous and aligned
        producer._advance_cursor(block_a)
        block_b = producer._generate_next_block(plan_30m)

        assert block_b.start_utc_ms == block_a.end_utc_ms
        assert block_b.start_utc_ms % block_dur == 0, (
            f"INV-BLOCK-ALIGNMENT-001: block_b.start={block_b.start_utc_ms} "
            f"not aligned after JIP block"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
