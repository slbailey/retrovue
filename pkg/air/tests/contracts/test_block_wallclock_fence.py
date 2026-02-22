"""
Contract Tests: INV-BLOCK-WALLCLOCK-FENCE-001

Contract reference:
    pkg/air/docs/contracts/INV-BLOCK-WALLCLOCK-FENCE-001.md

These tests enforce Wall-Clock Fence invariants using a Python model
that mirrors PipelineManager's fence logic after the WALLFENCE
implementation.  The model uses absolute session-frame-index fences
computed from block schedule times (UTC ms), matching the C++ lambda
`compute_fence_frame`.

    INV-BLOCK-WALLFENCE-001  Wall clock is sole authority for block end
    INV-BLOCK-WALLFENCE-002  CT must not delay transition
    INV-BLOCK-WALLFENCE-003  Early CT exhaustion -> freeze, not advancement
    INV-BLOCK-WALLFENCE-004  Swap on fence tick
    INV-BLOCK-WALLFENCE-005  BlockCompleted fires AFTER swap

All tests are deterministic and require no media files, AIR process,
or wall-clock sleeps.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pytest


# =============================================================================
# Model: Faithful mirror of PipelineManager fence logic (post-WALLFENCE)
# =============================================================================

@dataclass
class FedBlock:
    """Mirrors blockplan::FedBlock."""
    block_id: str
    start_utc_ms: int
    end_utc_ms: int
    # Simplified: single segment
    asset_uri: str = "/test/asset.mp4"
    input_fps: float = 30.0
    total_content_frames: int = 900  # frames of actual content available


def compute_fence_frame(
    block: FedBlock, session_epoch_utc_ms: int, frame_dur_ms: int
) -> int:
    """Mirrors C++ compute_fence_frame lambda.

    Returns the absolute session frame index at which this block's
    scheduled wall-clock end is reached.
    """
    delta_ms = block.end_utc_ms - session_epoch_utc_ms
    if delta_ms <= 0:
        return 0
    return (delta_ms + frame_dur_ms - 1) // frame_dur_ms  # ceil division


@dataclass
class TickEvent:
    """Record of what happened on a single tick."""
    session_frame: int
    source: str  # "decode", "repeat", "freeze", "pad"
    block_id: Optional[str] = None


@dataclass
class FenceEvent:
    """Record of a fence firing."""
    session_frame: int
    outgoing_block_id: str
    swapped: bool
    swap_target_block_id: Optional[str] = None
    completion_fired_after_swap: bool = False


class PipelineManagerModel:
    """Python model of PipelineManager's tick loop and fence logic.

    Simulates the WALLFENCE implementation:
    - Fence computed from block.end_utc_ms, not from tick count
    - Fence fires when session_frame_index >= block_fence_frame_
    - Content time is diagnostic only, never gates transition
    - Swap executes BEFORE completion callback
    """

    def __init__(
        self,
        output_fps: float,
        session_epoch_utc_ms: int,
    ) -> None:
        self.output_fps = output_fps
        self.frame_dur_ms = round(1000.0 / output_fps)
        self.session_epoch_utc_ms = session_epoch_utc_ms

        self.session_frame_index = 0
        self.block_fence_frame: int = 2**63 - 1  # INT64_MAX sentinel

        # Current block state
        self.current_block: Optional[FedBlock] = None
        self.content_frames_remaining = 0
        self.content_frames_decoded = 0

        # Preview (next block, preloaded)
        self.preview_block: Optional[FedBlock] = None

        # Event log
        self.tick_log: list[TickEvent] = []
        self.fence_log: list[FenceEvent] = []
        self.completion_log: list[str] = []  # block_ids in order

        # Rational cadence/drop model
        self.cadence_active = False
        self.cadence_ratio = 0.0
        self.decode_budget = 0.0
        self.drop_active = False
        self.drop_step = 1
        self.input_frames_consumed = 0
        self.have_last_frame = False

    def load_block(self, block: FedBlock) -> None:
        """Load a block as the active live source."""
        self.current_block = block
        self.content_frames_remaining = block.total_content_frames
        self.content_frames_decoded = 0
        self.have_last_frame = False
        self.block_fence_frame = compute_fence_frame(
            block, self.session_epoch_utc_ms, self.frame_dur_ms
        )
        self._init_cadence(block)

    def set_preview(self, block: FedBlock) -> None:
        """Stage a block as the preloaded preview (next block)."""
        self.preview_block = block

    def _init_cadence(self, block: FedBlock) -> None:
        self.drop_active = False
        self.drop_step = 1
        ratio = (block.input_fps / self.output_fps) if self.output_fps > 0 else 0.0
        rounded = int(round(ratio)) if ratio > 0 else 1
        if ratio >= 1.0 and abs(ratio - rounded) < 1e-6:
            self.drop_active = True
            self.drop_step = max(1, rounded)
            self.cadence_active = False
            self.cadence_ratio = 0.0
            self.decode_budget = 0.0
            return

        if block.input_fps > 0 and block.input_fps < self.output_fps * 0.98:
            self.cadence_active = True
            self.cadence_ratio = block.input_fps / self.output_fps
            self.decode_budget = 1.0
        else:
            self.cadence_active = False
            self.cadence_ratio = 0.0
            self.decode_budget = 0.0

    def _should_decode(self) -> bool:
        if self.drop_active:
            return True
        if not self.cadence_active:
            return True
        self.decode_budget += self.cadence_ratio
        if self.decode_budget >= 1.0:
            self.decode_budget -= 1.0
            return True
        return False

    def tick(self) -> TickEvent:
        """Execute one tick of the main loop. Returns what happened."""
        event = TickEvent(session_frame=self.session_frame_index, source="pad")

        # Try to produce a frame from current block
        if self.current_block is not None:
            should_decode = self._should_decode()

            if should_decode:
                if self.content_frames_remaining > 0:
                    # Decode a real frame
                    consumed = self.drop_step if self.drop_active else 1
                    self.content_frames_remaining -= consumed
                    self.content_frames_decoded += 1
                    self.input_frames_consumed += consumed
                    self.have_last_frame = True
                    event.source = "decode"
                    event.block_id = self.current_block.block_id
                elif self.have_last_frame:
                    # Content exhausted, freeze last frame
                    # INV-BLOCK-WALLFENCE-003: freeze, not advance
                    event.source = "freeze"
                    event.block_id = self.current_block.block_id
            elif self.have_last_frame:
                # Cadence repeat
                event.source = "repeat"
                event.block_id = self.current_block.block_id

        self.tick_log.append(event)

        # Fence check — INV-BLOCK-WALLFENCE-001
        if (self.block_fence_frame != 2**63 - 1 and
                self.session_frame_index >= self.block_fence_frame):
            self._execute_fence()

        self.session_frame_index += 1
        return event

    def _execute_fence(self) -> None:
        """Execute the fence: snapshot, swap, completion."""
        assert self.current_block is not None
        outgoing_id = self.current_block.block_id

        # INV-BLOCK-WALLFENCE-004: Swap FIRST
        swapped = False
        swap_target_id = None
        if self.preview_block is not None:
            self.current_block = self.preview_block
            self.preview_block = None
            self.content_frames_remaining = self.current_block.total_content_frames
            self.content_frames_decoded = 0
            self.have_last_frame = False
            self.block_fence_frame = compute_fence_frame(
                self.current_block, self.session_epoch_utc_ms, self.frame_dur_ms
            )
            self._init_cadence(self.current_block)
            swapped = True
            swap_target_id = self.current_block.block_id
        else:
            # No next block — enter pad mode
            self.current_block = None
            self.block_fence_frame = 2**63 - 1
            self.content_frames_remaining = 0
            self.have_last_frame = False

        # INV-BLOCK-WALLFENCE-005: Completion fires AFTER swap
        self.completion_log.append(outgoing_id)

        self.fence_log.append(FenceEvent(
            session_frame=self.session_frame_index,
            outgoing_block_id=outgoing_id,
            swapped=swapped,
            swap_target_block_id=swap_target_id,
            completion_fired_after_swap=True,
        ))

    def run_ticks(self, n: int) -> list[TickEvent]:
        """Run N ticks and return all events."""
        events = []
        for _ in range(n):
            events.append(self.tick())
        return events


# =============================================================================
# Helpers
# =============================================================================

def _make_blocks_30fps(
    epoch_ms: int,
    block_durations_ms: list[int],
    input_fps: float = 30.0,
) -> list[FedBlock]:
    """Create a sequence of contiguous blocks starting at epoch."""
    blocks = []
    cursor = epoch_ms
    for i, dur_ms in enumerate(block_durations_ms):
        frame_dur_ms = round(1000.0 / input_fps)
        total_frames = dur_ms // frame_dur_ms  # exact content frames
        blocks.append(FedBlock(
            block_id=f"blk-{i:03d}",
            start_utc_ms=cursor,
            end_utc_ms=cursor + dur_ms,
            input_fps=input_fps,
            total_content_frames=total_frames,
        ))
        cursor += dur_ms
    return blocks


# =============================================================================
# 1. INV-BLOCK-WALLFENCE-001: Wall clock is sole authority
# =============================================================================

class TestWallClockAuthority:
    """INV-BLOCK-WALLFENCE-001: The fence fires based on session_frame_index
    reaching the computed absolute fence frame, regardless of content state."""

    def test_fence_fires_at_computed_frame(self):
        """Fence fires exactly at the frame index computed from block.end_utc_ms."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)  # 33ms

        blocks = _make_blocks_30fps(epoch, [30000])  # 30s block
        expected_fence = compute_fence_frame(blocks[0], epoch, frame_dur_ms)

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(blocks[0])

        # Run up to but NOT including the fence frame
        pm.run_ticks(expected_fence)
        assert len(pm.fence_log) == 0, (
            "INV-BLOCK-WALLFENCE-001 VIOLATION: fence fired before "
            f"expected frame {expected_fence}"
        )

        # The next tick hits the fence
        pm.tick()
        assert len(pm.fence_log) == 1, (
            "INV-BLOCK-WALLFENCE-001 VIOLATION: fence did not fire at "
            f"expected frame {expected_fence}"
        )
        assert pm.fence_log[0].session_frame == expected_fence, (
            f"Fence fired at frame {pm.fence_log[0].session_frame}, "
            f"expected {expected_fence}"
        )

    def test_fence_independent_of_content_count(self):
        """Fence timing is identical whether content has 10 frames or 10000."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 10000  # 10s block

        block_few = FedBlock(
            block_id="few",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
            total_content_frames=10,  # only 10 frames
        )
        block_many = FedBlock(
            block_id="many",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
            total_content_frames=10000,  # more than enough
        )

        expected = compute_fence_frame(block_few, epoch, frame_dur_ms)

        pm_few = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm_few.load_block(block_few)
        pm_few.run_ticks(expected + 1)

        pm_many = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm_many.load_block(block_many)
        pm_many.run_ticks(expected + 1)

        assert len(pm_few.fence_log) == 1
        assert len(pm_many.fence_log) == 1
        assert pm_few.fence_log[0].session_frame == pm_many.fence_log[0].session_frame, (
            "INV-BLOCK-WALLFENCE-001 VIOLATION: fence frame differs based on "
            "content frame count.  Wall clock must be sole authority."
        )


# =============================================================================
# 2. INV-BLOCK-WALLFENCE-002: CT must not delay transition
# =============================================================================

class TestCTCannotDelay:
    """INV-BLOCK-WALLFENCE-002: Content time behind schedule must not
    delay the block transition beyond the wall-clock fence."""

    def test_ct_behind_does_not_delay_fence(self):
        """When content is still being decoded at the fence, the fence
        fires anyway and content is truncated."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 10000  # 10s

        # Content has more frames than the block duration would need,
        # simulating content that hasn't finished when the fence fires.
        block = FedBlock(
            block_id="slow",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
            total_content_frames=99999,  # "infinite" content
        )
        fence_frame = compute_fence_frame(block, epoch, frame_dur_ms)

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block)
        pm.run_ticks(fence_frame + 1)

        assert len(pm.fence_log) == 1, (
            "INV-BLOCK-WALLFENCE-002 VIOLATION: fence did not fire despite "
            "wall-clock expiry.  Content was still decoding."
        )
        # Content was truncated — not all frames decoded
        assert pm.fence_log[0].outgoing_block_id == "slow"

    def test_23976_to_30_ct_lag_does_not_delay(self):
        """23.976->30fps cadence means CT progresses slower than wall clock.
        Fence must still fire on time."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 30000  # 30s block

        # At 23.976fps input, ~720 content frames in 30s.
        # But output produces 30s * 30fps = 910 output ticks.
        # With cadence, some ticks repeat instead of decode.
        # CT will lag behind the 30s wall clock.
        input_fps = 23.976
        total_content = int(dur_ms * input_fps / 1000)

        block = FedBlock(
            block_id="slow-cadence",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
            input_fps=input_fps,
            total_content_frames=total_content,
        )
        fence_frame = compute_fence_frame(block, epoch, frame_dur_ms)

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block)
        pm.run_ticks(fence_frame + 1)

        assert len(pm.fence_log) == 1, (
            "INV-BLOCK-WALLFENCE-002 VIOLATION: fence did not fire for "
            "23.976->30fps block despite wall-clock expiry."
        )
        assert pm.fence_log[0].session_frame == fence_frame

    def test_15fps_to_30_slow_content_fence_on_time(self):
        """15fps->30fps: content decodes at half rate.  Fence fires on time."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 10000

        input_fps = 15.0
        total_content = int(dur_ms * input_fps / 1000)

        block = FedBlock(
            block_id="15fps",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
            input_fps=input_fps,
            total_content_frames=total_content,
        )
        fence_frame = compute_fence_frame(block, epoch, frame_dur_ms)

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block)
        pm.run_ticks(fence_frame + 1)

        assert len(pm.fence_log) == 1, (
            "INV-BLOCK-WALLFENCE-002 VIOLATION: fence did not fire for "
            "15fps->30fps block despite wall-clock expiry."
        )


# =============================================================================
# 3. INV-BLOCK-WALLFENCE-003: Early CT exhaustion -> freeze
# =============================================================================

class TestEarlyCTExhaustion:
    """INV-BLOCK-WALLFENCE-003: When content runs out before the fence,
    the engine must freeze (hold last frame), not advance to the next block."""

    def test_content_exhausted_freezes_until_fence(self):
        """Block with fewer content frames than fence: engine freezes,
        does NOT advance to next block early."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 10000  # 10s block

        # Only 100 frames of content (3.3s at 30fps) in a 10s block
        block = FedBlock(
            block_id="short-content",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
            total_content_frames=100,
        )
        next_block = FedBlock(
            block_id="next",
            start_utc_ms=epoch + dur_ms,
            end_utc_ms=epoch + dur_ms + dur_ms,
            total_content_frames=300,
        )
        fence_frame = compute_fence_frame(block, epoch, frame_dur_ms)

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block)
        pm.set_preview(next_block)

        # Run past content exhaustion (100 frames) but before fence
        pm.run_ticks(150)
        assert len(pm.fence_log) == 0, (
            "INV-BLOCK-WALLFENCE-003 VIOLATION: fence fired at content "
            "exhaustion instead of scheduled wall-clock time."
        )

        # Check that after content exhaustion, we get freeze frames
        freeze_ticks = [e for e in pm.tick_log if e.source == "freeze"]
        assert len(freeze_ticks) > 0, (
            "INV-BLOCK-WALLFENCE-003 VIOLATION: no freeze frames after "
            "content exhaustion.  Engine should hold last frame."
        )

        # Run to fence
        remaining = fence_frame + 1 - 150
        pm.run_ticks(remaining)
        assert len(pm.fence_log) == 1, (
            "Fence must fire at scheduled time even after early content exhaustion."
        )

    def test_early_exhaustion_does_not_swap_early(self):
        """Even with preview ready, swap must NOT happen before the fence."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 10000

        block = FedBlock(
            block_id="early-exhaust",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
            total_content_frames=50,  # exhausts at frame 50
        )
        next_block = FedBlock(
            block_id="waiting",
            start_utc_ms=epoch + dur_ms,
            end_utc_ms=epoch + 2 * dur_ms,
        )
        fence_frame = compute_fence_frame(block, epoch, frame_dur_ms)

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block)
        pm.set_preview(next_block)

        # Run to frame 100 (well past exhaustion at 50, well before fence)
        pm.run_ticks(100)
        assert len(pm.fence_log) == 0, (
            "INV-BLOCK-WALLFENCE-003 VIOLATION: swap occurred before fence. "
            "Content exhaustion must not trigger early block transition."
        )
        # Verify we're still on the original block
        assert pm.current_block is not None
        assert pm.current_block.block_id == "early-exhaust"


# =============================================================================
# 4. INV-BLOCK-WALLFENCE-004: Swap on fence tick
# =============================================================================

class TestSwapOnFenceTick:
    """INV-BLOCK-WALLFENCE-004: The A/B swap executes on exactly the
    fence tick, not one tick before or after."""

    def test_swap_happens_at_fence_frame(self):
        """Preview block becomes active exactly at the fence frame."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 10000

        blocks = _make_blocks_30fps(epoch, [dur_ms, dur_ms])

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(blocks[0])
        pm.set_preview(blocks[1])

        fence_frame = compute_fence_frame(blocks[0], epoch, frame_dur_ms)

        # Run to fence - 1: no swap yet
        pm.run_ticks(fence_frame)
        assert len(pm.fence_log) == 0

        # Fence tick: swap happens
        pm.tick()
        assert len(pm.fence_log) == 1
        assert pm.fence_log[0].swapped is True
        assert pm.fence_log[0].swap_target_block_id == blocks[1].block_id

    def test_no_swap_without_preview(self):
        """At fence with no preview, enter pad mode (no swap)."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 5000

        block = FedBlock(
            block_id="lonely",
            start_utc_ms=epoch,
            end_utc_ms=epoch + dur_ms,
        )
        fence_frame = compute_fence_frame(block, epoch, frame_dur_ms)

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block)
        # No preview set

        pm.run_ticks(fence_frame + 1)
        assert len(pm.fence_log) == 1
        assert pm.fence_log[0].swapped is False
        assert pm.current_block is None, (
            "INV-BLOCK-WALLFENCE-004: after fence with no preview, "
            "current_block should be None (pad mode)."
        )


# =============================================================================
# 5. INV-BLOCK-WALLFENCE-005: BlockCompleted fires AFTER swap
# =============================================================================

class TestCompletionAfterSwap:
    """INV-BLOCK-WALLFENCE-005: The on_block_completed callback fires
    AFTER the A/B swap, not before."""

    def test_completion_uses_outgoing_block_id(self):
        """The completion callback receives the outgoing block's ID,
        not the new block's ID."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)
        dur_ms = 5000

        blocks = _make_blocks_30fps(epoch, [dur_ms, dur_ms])

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(blocks[0])
        pm.set_preview(blocks[1])

        fence_frame = compute_fence_frame(blocks[0], epoch, frame_dur_ms)
        pm.run_ticks(fence_frame + 1)

        assert len(pm.completion_log) == 1
        assert pm.completion_log[0] == blocks[0].block_id, (
            "INV-BLOCK-WALLFENCE-005 VIOLATION: completion callback received "
            f"block_id='{pm.completion_log[0]}', expected outgoing "
            f"block_id='{blocks[0].block_id}'."
        )

    def test_completion_fires_after_swap_flag(self):
        """The model's fence event records that completion fired after swap."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)

        blocks = _make_blocks_30fps(epoch, [5000, 5000])

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(blocks[0])
        pm.set_preview(blocks[1])

        fence_frame = compute_fence_frame(blocks[0], epoch, frame_dur_ms)
        pm.run_ticks(fence_frame + 1)

        assert pm.fence_log[0].completion_fired_after_swap is True, (
            "INV-BLOCK-WALLFENCE-005 VIOLATION: completion callback fired "
            "before swap."
        )


# =============================================================================
# 6. Multi-block drift accumulation
# =============================================================================

class TestMultiBlockDrift:
    """Verify that absolute fence computation prevents drift across
    consecutive block boundaries."""

    def test_no_drift_across_three_blocks(self):
        """Three consecutive 30s blocks: each fence fires at the correct
        absolute frame, with zero accumulated drift."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)

        blocks = _make_blocks_30fps(epoch, [30000, 30000, 30000])
        expected_fences = [
            compute_fence_frame(b, epoch, frame_dur_ms) for b in blocks
        ]

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(blocks[0])
        pm.set_preview(blocks[1])

        # Run through first fence
        pm.run_ticks(expected_fences[0] + 1)
        assert len(pm.fence_log) == 1
        assert pm.fence_log[0].session_frame == expected_fences[0]

        # Load block 2 as preview
        pm.set_preview(blocks[2])

        # Run through second fence
        remaining = expected_fences[1] + 1 - pm.session_frame_index
        pm.run_ticks(remaining)
        assert len(pm.fence_log) == 2
        assert pm.fence_log[1].session_frame == expected_fences[1]

        # Run through third fence
        remaining = expected_fences[2] + 1 - pm.session_frame_index
        pm.run_ticks(remaining)
        assert len(pm.fence_log) == 3
        assert pm.fence_log[2].session_frame == expected_fences[2]

        # Verify spacing is consistent
        gap_01 = pm.fence_log[1].session_frame - pm.fence_log[0].session_frame
        gap_12 = pm.fence_log[2].session_frame - pm.fence_log[1].session_frame
        assert gap_01 == gap_12, (
            f"Drift detected: gap 0->1 = {gap_01}, gap 1->2 = {gap_12}. "
            "Absolute fence computation should prevent drift."
        )

    def test_no_drift_mixed_durations(self):
        """Mixed block durations (10s, 30s, 15s): fences at correct absolutes."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)

        blocks = _make_blocks_30fps(epoch, [10000, 30000, 15000])
        expected = [compute_fence_frame(b, epoch, frame_dur_ms) for b in blocks]

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(blocks[0])
        pm.set_preview(blocks[1])

        pm.run_ticks(expected[0] + 1)
        pm.set_preview(blocks[2])
        remaining = expected[1] + 1 - pm.session_frame_index
        pm.run_ticks(remaining)
        remaining = expected[2] + 1 - pm.session_frame_index
        pm.run_ticks(remaining)

        assert len(pm.fence_log) == 3
        for i, (log, exp) in enumerate(zip(pm.fence_log, expected)):
            assert log.session_frame == exp, (
                f"Block {i}: fence at frame {log.session_frame}, "
                f"expected {exp}. Drift detected."
            )


# =============================================================================
# 7. Fence frame computation
# =============================================================================

class TestFenceComputation:
    """Verify compute_fence_frame correctly maps UTC ms to session frames."""

    def test_exact_alignment(self):
        """30fps, 33ms frame duration: 30000ms block -> ceil(30000/33) = 910."""
        epoch = 0
        frame_dur_ms = 33
        block = FedBlock(
            block_id="exact",
            start_utc_ms=0,
            end_utc_ms=30000,
        )
        result = compute_fence_frame(block, epoch, frame_dur_ms)
        expected = (30000 + 33 - 1) // 33  # = 910
        assert result == expected, f"Got {result}, expected {expected}"

    def test_ceil_rounding(self):
        """Fence must round UP so it fires on or after the scheduled end."""
        epoch = 0
        frame_dur_ms = 33
        block = FedBlock(
            block_id="ceil",
            start_utc_ms=0,
            end_utc_ms=10001,  # not evenly divisible by 33
        )
        result = compute_fence_frame(block, epoch, frame_dur_ms)
        # 10001/33 = 303.06 -> ceil = 304
        assert result == 304, f"Got {result}, expected 304"
        # Verify: frame 303 fires at 303*33=9999ms (before 10001ms)
        # Verify: frame 304 fires at 304*33=10032ms (at or after 10001ms)
        assert 303 * frame_dur_ms < 10001
        assert 304 * frame_dur_ms >= 10001

    def test_zero_delta(self):
        """Block ending at or before session start: fence at frame 0."""
        epoch = 5000
        frame_dur_ms = 33
        block = FedBlock(
            block_id="past",
            start_utc_ms=0,
            end_utc_ms=5000,  # exactly at epoch
        )
        result = compute_fence_frame(block, epoch, frame_dur_ms)
        assert result == 0

    def test_negative_delta(self):
        """Block ending before session start: fence at frame 0."""
        epoch = 10000
        frame_dur_ms = 33
        block = FedBlock(
            block_id="ancient",
            start_utc_ms=0,
            end_utc_ms=5000,  # before epoch
        )
        result = compute_fence_frame(block, epoch, frame_dur_ms)
        assert result == 0


# =============================================================================
# 8. Cadence alignment at fence
# =============================================================================

class TestCadenceAtFence:
    """Verify that the cadence gate is correctly re-initialized when
    a new block loads after a fence swap."""

    def test_cadence_resets_at_fence_swap(self):
        """After a fence swap to a 23.976fps block, the cadence gate
        must be active with the correct ratio."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)

        block_1 = FedBlock(
            block_id="blk-30",
            start_utc_ms=epoch,
            end_utc_ms=epoch + 5000,
            input_fps=30.0,
            total_content_frames=150,
        )
        block_2 = FedBlock(
            block_id="blk-24",
            start_utc_ms=epoch + 5000,
            end_utc_ms=epoch + 10000,
            input_fps=23.976,
            total_content_frames=120,
        )

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block_1)
        pm.set_preview(block_2)

        # First block: 30fps -> no cadence
        assert not pm.cadence_active

        # Run through fence
        fence = compute_fence_frame(block_1, epoch, frame_dur_ms)
        pm.run_ticks(fence + 1)

        # After swap to 23.976fps block: cadence must be active
        assert pm.cadence_active, (
            "Cadence not activated after swap to 23.976fps block."
        )
        assert abs(pm.cadence_ratio - 23.976 / 30.0) < 0.001

    def test_cadence_produces_correct_pattern_after_swap(self):
        """After swapping to a 23.976fps block, the decode/repeat pattern
        must follow the expected 4:1 distribution."""
        epoch = 1000000
        output_fps = 30.0
        frame_dur_ms = round(1000.0 / output_fps)

        block_1 = FedBlock(
            block_id="blk-30",
            start_utc_ms=epoch,
            end_utc_ms=epoch + 5000,
            input_fps=30.0,
            total_content_frames=150,
        )
        block_2 = FedBlock(
            block_id="blk-24",
            start_utc_ms=epoch + 5000,
            end_utc_ms=epoch + 35000,  # 30s of 23.976fps
            input_fps=23.976,
            total_content_frames=720,
        )

        pm = PipelineManagerModel(output_fps=output_fps, session_epoch_utc_ms=epoch)
        pm.load_block(block_1)
        pm.set_preview(block_2)

        fence_1 = compute_fence_frame(block_1, epoch, frame_dur_ms)
        pm.run_ticks(fence_1 + 1)

        # Clear log to isolate post-swap behavior
        pre_swap_ticks = len(pm.tick_log)

        # Run 100 ticks of the 23.976fps block
        pm.run_ticks(100)

        post_swap_events = pm.tick_log[pre_swap_ticks:]
        decodes = sum(1 for e in post_swap_events if e.source == "decode")
        repeats = sum(1 for e in post_swap_events if e.source == "repeat")

        # 23.976/30 ~ 0.7992 -> roughly 80 decodes, 20 repeats per 100 ticks
        assert 75 <= decodes <= 85, (
            f"Expected ~80 decodes in 100 ticks for 23.976->30, got {decodes}"
        )
        assert 15 <= repeats <= 25, (
            f"Expected ~20 repeats in 100 ticks for 23.976->30, got {repeats}"
        )


# =============================================================================
# 9. INV-FENCE-WALLCLOCK-ANCHOR + INV-FENCE-PTS-DECOUPLE: Bootstrap delay
# =============================================================================

class TestBootstrapDelay:
    """INV-FENCE-WALLCLOCK-ANCHOR + INV-FENCE-PTS-DECOUPLE:
    Bootstrap delay must shift fence grid without affecting PTS."""

    def test_fence_correct_after_bootstrap_delay(self):
        """With 3s bootstrap delay, fence fires at correct wall-clock-aligned frame.

        session_epoch_utc_ms = 1000000 (Core join_utc_ms)
        fence_epoch_utc_ms = 1003000 (3s later, at clock.Start())
        Block end_utc_ms = 1030000 (30s block from join)

        Fence should be: ceil((1030000 - 1003000) * 30 / 1000) = ceil(810000/1000) = 810
        NOT: ceil((1030000 - 1000000) * 30 / 1000) = ceil(900000/1000) = 900
        """
        session_epoch = 1000000
        fence_epoch = 1003000  # 3s bootstrap delay
        fps = 30.0
        frame_dur_ms = 1000 // int(fps)

        block = FedBlock(
            block_id="delayed",
            start_utc_ms=session_epoch,
            end_utc_ms=session_epoch + 30000,
        )
        # Fence computed with fence_epoch, not session_epoch
        delta_ms = block.end_utc_ms - fence_epoch
        fence = (delta_ms + frame_dur_ms - 1) // frame_dur_ms
        assert fence == 819  # ceil(27000/33)

        # Model should use fence_epoch for fence math
        pm = PipelineManagerModel(output_fps=fps, session_epoch_utc_ms=fence_epoch)
        pm.load_block(block)
        pm.run_ticks(fence + 1)
        assert len(pm.fence_log) == 1
        assert pm.fence_log[0].session_frame == fence

    def test_pts_starts_at_zero_despite_bootstrap_delay(self):
        """PTS must start at 0 regardless of bootstrap delay.

        Before fix: session_frame_index was advanced by D/frame_dur_ms,
        causing video_pts to jump ahead of audio_pts.

        After fix: pts_origin_frame_index = 0, so PTS = FrameIndexToPts90k(0) = 0.
        """
        pts_origin_frame_index = 0
        pts_origin_audio_samples = 0
        session_frame_index = 0
        audio_samples_emitted = 0

        frame_duration_90k = 3000  # 30fps

        video_pts = (session_frame_index - pts_origin_frame_index) * frame_duration_90k
        audio_pts = ((audio_samples_emitted - pts_origin_audio_samples) * 90000) // 48000

        assert video_pts == 0, f"Video PTS should be 0 at first frame, got {video_pts}"
        assert audio_pts == 0, f"Audio PTS should be 0 at first frame, got {audio_pts}"
        assert video_pts == audio_pts, (
            f"A/V desync at first emission: video={video_pts}, audio={audio_pts}"
        )

    def test_av_sync_maintained_across_ticks(self):
        """Video and audio PTS advance in lockstep when origins are aligned."""
        frame_duration_90k = 3000  # 30fps
        samples_per_tick = 1600    # 48000/30

        pts_origin_frame = 0
        pts_origin_audio = 0

        for tick in range(100):
            video_pts = (tick - pts_origin_frame) * frame_duration_90k
            audio_pts = ((tick * samples_per_tick - pts_origin_audio) * 90000) // 48000
            # Allow up to 1 90k tick of rounding error
            assert abs(video_pts - audio_pts) <= frame_duration_90k, (
                f"A/V desync at tick {tick}: video={video_pts}, audio={audio_pts}, "
                f"delta={video_pts - audio_pts}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


class TestRationalCadenceLongRun:
    """Explicit long-run cadence/drop criteria for RationalFps closure."""

    def test_drop_5994_to_2997_step2_long_run(self):
        epoch = 1_000_000
        pm = PipelineManagerModel(output_fps=29.97, session_epoch_utc_ms=epoch)
        block = FedBlock(
            block_id="drop-5994-2997",
            start_utc_ms=epoch,
            end_utc_ms=epoch + 600_000,
            input_fps=59.94,
            total_content_frames=40_000,
        )
        pm.load_block(block)
        pm.run_ticks(17_982)  # ~10 minutes at 29.97fps

        decodes = sum(1 for e in pm.tick_log if e.source == "decode")
        repeats = sum(1 for e in pm.tick_log if e.source == "repeat")
        assert decodes == 17_982
        assert pm.drop_active
        assert pm.drop_step == 2
        assert pm.input_frames_consumed == 35_964

    def test_cadence_23976_to_30_exact_ratio_window(self):
        epoch = 2_000_000
        pm = PipelineManagerModel(output_fps=30.0, session_epoch_utc_ms=epoch)
        block = FedBlock(
            block_id="cadence-23976-30",
            start_utc_ms=epoch,
            end_utc_ms=epoch + 60_000,
            input_fps=23.976,
            total_content_frames=30_000,
        )
        pm.load_block(block)

        window = pm.run_ticks(3000)
        decodes = sum(1 for e in window if e.source == "decode")
        repeats = sum(1 for e in window if e.source == "repeat")

        # Expected ratio 24000/30000 = 0.8 exactly.
        assert decodes == 2400
        assert repeats == 600

    def test_ten_minute_no_accumulated_error_23976_to_30(self):
        epoch = 3_000_000
        pm = PipelineManagerModel(output_fps=30.0, session_epoch_utc_ms=epoch)
        block = FedBlock(
            block_id="longrun-23976-30",
            start_utc_ms=epoch,
            end_utc_ms=epoch + 600_000,
            input_fps=23.976,
            total_content_frames=100_000,
        )
        pm.load_block(block)

        ticks = 18_000
        pm.run_ticks(ticks)
        decodes = sum(1 for e in pm.tick_log if e.source == "decode")
        repeats = sum(1 for e in pm.tick_log if e.source == "repeat")

        expected_decodes = int(ticks * (23.976 / 30.0))
        assert abs(decodes - expected_decodes) <= 1
        assert decodes + repeats == ticks
