"""
Contract Tests: INV-BLOCK-FRAME-BUDGET-AUTHORITY

Contract reference:
    pkg/air/docs/contracts/INV-BLOCK-FRAME-BUDGET-AUTHORITY.md

These tests enforce block frame budget invariants using a Python model
that mirrors PipelineManager's tick loop with explicit remaining-frame
tracking.  The model supports multi-segment blocks (N >= 1) where
segments are internal composition — blocks are the timing authority.

    INV-FRAME-BUDGET-001  Frame budget is the single authoritative limit
    INV-FRAME-BUDGET-002  Explicit remaining frame tracking
    INV-FRAME-BUDGET-003  One frame, one decrement
    INV-FRAME-BUDGET-004  Zero budget triggers block completion
    INV-FRAME-BUDGET-005  Segments must consult remaining budget
    INV-FRAME-BUDGET-006  Segment exhaustion does not cause block completion
    INV-FRAME-BUDGET-007  No negative frame budget

All tests are deterministic and require no media files, AIR process,
wall-clock sleeps, or timestamps.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import pytest


# =============================================================================
# Model types
# =============================================================================

@dataclass
class Segment:
    """A content segment within a block.

    content_frames is the number of decodable frames this segment can
    produce before its content is exhausted (decoder EOF).
    """
    segment_id: str
    content_frames: int  # Decodable frames available in this segment


@dataclass
class Block:
    """A block with a fixed duration and N >= 1 segments."""
    block_id: str
    duration_seconds: float
    segments: list[Segment]

    def frame_budget(self, output_fps: float) -> int:
        """Exact frame budget: ceil(duration_seconds * output_fps).

        Matches C++ TickProducer::AssignBlock:
            ceil(duration_ms * output_fps_ / 1000.0)
        """
        return math.ceil(self.duration_seconds * output_fps)

    @property
    def total_content_frames(self) -> int:
        """Sum of all segment content frames."""
        return sum(s.content_frames for s in self.segments)


@dataclass
class TickRecord:
    """What happened on a single output tick."""
    tick_index: int           # Tick number within this block (0-based)
    frame_source: str         # "decode", "freeze", "pad"
    segment_id: Optional[str] # Which segment provided the frame (None for pad)
    remaining_before: int     # remaining_block_frames BEFORE emission
    remaining_after: int      # remaining_block_frames AFTER emission


@dataclass
class CompletionRecord:
    """Record of a BlockCompleted event."""
    block_id: str
    tick_index: int           # Block-local tick on which completion fired
    total_frames_emitted: int
    remaining_at_completion: int  # Must be 0


# =============================================================================
# Model: PipelineManager frame budget logic
# =============================================================================

class FrameBudgetModel:
    """Python model of PipelineManager's tick loop with explicit
    remaining_block_frames_ tracking.

    This model enforces all 7 INV-FRAME-BUDGET invariants.  It supports
    blocks with any number of segments (N >= 1).  PipelineManager does
    not know how many segments a block has — it calls TryGetFrame() and
    gets a frame or nullopt.  This model mirrors that opacity: the
    segment cursor is internal, and PipelineManager only sees
    "frame available" or "no frame available."
    """

    def __init__(self, output_fps: float = 30.0) -> None:
        self.output_fps = output_fps

        # Block state
        self.current_block: Optional[Block] = None
        self.remaining_block_frames: int = 0
        self.block_tick_index: int = 0
        self.block_completed: bool = False

        # Segment cursor (TickProducer-internal — opaque to PipelineManager)
        self._segment_index: int = 0
        self._segment_frames_remaining: int = 0

        # Fallback state
        self._have_last_frame: bool = False

        # Event logs
        self.tick_log: list[TickRecord] = []
        self.completion_log: list[CompletionRecord] = []
        self.frames_emitted_total: int = 0

        # Next block (for transition testing)
        self.next_block: Optional[Block] = None
        self.next_block_loaded: bool = False

    def load_block(self, block: Block) -> None:
        """Load a block as the active live source.

        INV-FRAME-BUDGET-001: Compute frame budget from duration * fps.
        INV-FRAME-BUDGET-002: Initialize remaining_block_frames.
        """
        self.current_block = block
        self.remaining_block_frames = block.frame_budget(self.output_fps)
        self.block_tick_index = 0
        self.block_completed = False
        self._have_last_frame = False
        self.tick_log.clear()
        self.frames_emitted_total = 0

        # Initialize segment cursor
        self._segment_index = 0
        if block.segments:
            self._segment_frames_remaining = block.segments[0].content_frames
        else:
            self._segment_frames_remaining = 0

    def set_next_block(self, block: Block) -> None:
        """Stage the next block for transition testing."""
        self.next_block = block
        self.next_block_loaded = False

    def _try_get_frame(self) -> tuple[Optional[str], str]:
        """Model of TickProducer::TryGetFrame().

        Returns (segment_id, source_type) where source_type is one of:
        - "decode": real frame from current segment
        - None: no frame available (triggers freeze/pad in caller)

        Handles segment transitions internally.  PipelineManager never
        sees segment boundaries — only "frame" or "no frame."
        """
        if self.current_block is None or not self.current_block.segments:
            return (None, "none")

        segments = self.current_block.segments

        # Current segment has frames?
        if self._segment_frames_remaining > 0:
            seg_id = segments[self._segment_index].segment_id
            self._segment_frames_remaining -= 1
            self._have_last_frame = True
            return (seg_id, "decode")

        # Current segment exhausted — try next segment
        # (INV-FRAME-BUDGET-006: segment exhaustion != block completion)
        while self._segment_index + 1 < len(segments):
            self._segment_index += 1
            self._segment_frames_remaining = \
                segments[self._segment_index].content_frames
            if self._segment_frames_remaining > 0:
                seg_id = segments[self._segment_index].segment_id
                self._segment_frames_remaining -= 1
                self._have_last_frame = True
                return (seg_id, "decode")

        # All segments exhausted — no frame
        return (None, "none")

    def tick(self) -> Optional[TickRecord]:
        """Execute one output tick.

        Returns the TickRecord, or None if the block is already complete.

        Enforces:
        - INV-FRAME-BUDGET-005: Check budget before emitting
        - INV-FRAME-BUDGET-003: Decrement by exactly 1
        - INV-FRAME-BUDGET-004: Complete at zero
        - INV-FRAME-BUDGET-007: Never negative
        """
        if self.current_block is None:
            return None

        # INV-FRAME-BUDGET-004: No frames after completion
        if self.block_completed:
            return None

        # INV-FRAME-BUDGET-005: Check budget BEFORE emitting
        if self.remaining_block_frames <= 0:
            # Budget exhausted — trigger completion, do NOT emit
            self._complete_block()
            return None

        remaining_before = self.remaining_block_frames

        # Try to get a real frame from TickProducer
        seg_id, source = self._try_get_frame()

        if source == "decode":
            frame_source = "decode"
            frame_seg_id = seg_id
        elif self._have_last_frame:
            # INV-TICK-GUARANTEED-OUTPUT: freeze last frame
            frame_source = "freeze"
            frame_seg_id = None
        else:
            # INV-TICK-GUARANTEED-OUTPUT: pad (black + silence)
            frame_source = "pad"
            frame_seg_id = None

        # INV-FRAME-BUDGET-003: Decrement by exactly 1
        self.remaining_block_frames -= 1
        self.frames_emitted_total += 1

        # INV-FRAME-BUDGET-007: Assert never negative
        assert self.remaining_block_frames >= 0, (
            f"INV-FRAME-BUDGET-007 VIOLATION: remaining_block_frames="
            f"{self.remaining_block_frames} after decrement"
        )

        remaining_after = self.remaining_block_frames

        record = TickRecord(
            tick_index=self.block_tick_index,
            frame_source=frame_source,
            segment_id=frame_seg_id,
            remaining_before=remaining_before,
            remaining_after=remaining_after,
        )
        self.tick_log.append(record)
        self.block_tick_index += 1

        # INV-FRAME-BUDGET-004: Zero budget triggers completion
        if self.remaining_block_frames == 0:
            self._complete_block()

        return record

    def _complete_block(self) -> None:
        """Execute block completion sequence.

        INV-FRAME-BUDGET-004:
        - Block ends
        - BlockCompleted fires exactly once
        - No further frames for this block
        """
        if self.block_completed:
            return  # Already fired — no double completion

        self.block_completed = True

        completion = CompletionRecord(
            block_id=self.current_block.block_id,
            tick_index=self.block_tick_index,
            total_frames_emitted=self.frames_emitted_total,
            remaining_at_completion=self.remaining_block_frames,
        )
        self.completion_log.append(completion)

        # A/B swap: load next block if available
        if self.next_block is not None:
            self.load_block(self.next_block)
            self.next_block_loaded = True
            self.next_block = None

    def run_block(self, block: Block) -> list[TickRecord]:
        """Convenience: load a block and run it to completion.

        Returns the tick log for the block.
        """
        self.load_block(block)
        records = []
        while not self.block_completed:
            record = self.tick()
            if record is not None:
                records.append(record)
        return records


# =============================================================================
# 1. INV-FRAME-BUDGET-001: Frame budget computation
# =============================================================================

class TestFrameBudgetComputation:
    """INV-FRAME-BUDGET-001: The block frame budget is
    block_duration_seconds * output_fps (ceiling)."""

    def test_30s_at_30fps(self):
        """30-second block at 30fps = exactly 900 frames."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=900),
        ])
        assert block.frame_budget(30.0) == 900

    def test_30s_at_29_97fps(self):
        """30-second block at 29.97fps = ceil(899.1) = 900 frames."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=900),
        ])
        budget = block.frame_budget(29.97)
        assert budget == 900, (
            f"INV-FRAME-BUDGET-001: expected 900, got {budget}"
        )

    def test_60s_at_30fps(self):
        """60-second block at 30fps = exactly 1800 frames."""
        block = Block("B-1", duration_seconds=60.0, segments=[
            Segment("S-1", content_frames=1800),
        ])
        assert block.frame_budget(30.0) == 1800

    def test_10s_at_24fps(self):
        """10-second block at 24fps = exactly 240 frames."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=240),
        ])
        assert block.frame_budget(24.0) == 240

    def test_fractional_duration_rounds_up(self):
        """15.5-second block at 30fps = ceil(465) = 465 frames."""
        block = Block("B-1", duration_seconds=15.5, segments=[
            Segment("S-1", content_frames=465),
        ])
        assert block.frame_budget(30.0) == 465

    def test_budget_immutable_during_execution(self):
        """INV-FRAME-BUDGET-001: Frame budget does not change during block."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=300),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        expected_budget = block.frame_budget(30.0)  # 300

        model.load_block(block)
        initial = model.remaining_block_frames

        # Run half the block
        for _ in range(150):
            model.tick()

        # The budget (total) hasn't changed — only remaining has
        assert block.frame_budget(30.0) == expected_budget
        assert initial == expected_budget
        assert model.remaining_block_frames == 150


# =============================================================================
# 2. INV-FRAME-BUDGET-002/003: Explicit tracking and 1:1 decrement
# =============================================================================

class TestRemainingFrameTracking:
    """INV-FRAME-BUDGET-002/003: remaining_block_frames decrements by
    exactly 1 per emitted frame."""

    def test_remaining_decrements_by_one(self):
        """Every tick decrements remaining by exactly 1."""
        block = Block("B-1", duration_seconds=1.0, segments=[
            Segment("S-1", content_frames=30),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.load_block(block)

        for i in range(30):
            record = model.tick()
            assert record is not None
            assert record.remaining_before == 30 - i, (
                f"Tick {i}: remaining_before should be {30 - i}, "
                f"got {record.remaining_before}"
            )
            assert record.remaining_after == 29 - i, (
                f"Tick {i}: remaining_after should be {29 - i}, "
                f"got {record.remaining_after}"
            )

    def test_freeze_frames_decrement_budget(self):
        """Freeze frames decrement the budget identically to real frames.

        Block: 10s at 30fps = 300 frames budget.
        Segment: only 200 frames of content.
        Remaining 100 frames must be freeze, each decrementing by 1.
        """
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=200),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 300
        decode_records = [r for r in records if r.frame_source == "decode"]
        freeze_records = [r for r in records if r.frame_source == "freeze"]

        assert len(decode_records) == 200
        assert len(freeze_records) == 100

        # Every record has remaining_before - remaining_after == 1
        for r in records:
            assert r.remaining_before - r.remaining_after == 1, (
                f"INV-FRAME-BUDGET-003 VIOLATION: tick {r.tick_index} "
                f"decrement was {r.remaining_before - r.remaining_after}, "
                "expected 1"
            )

    def test_pad_frames_decrement_budget(self):
        """Pad frames (no last frame to freeze) decrement the budget.

        Block: 1s at 30fps = 30 frames budget.
        Segment: 0 decodable frames (immediate failure).
        All 30 frames must be pad, each decrementing by 1.
        """
        block = Block("B-1", duration_seconds=1.0, segments=[
            Segment("S-1", content_frames=0),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 30
        for r in records:
            assert r.frame_source == "pad"
            assert r.remaining_before - r.remaining_after == 1


# =============================================================================
# 3. INV-FRAME-BUDGET-004: Block completion at zero budget
# =============================================================================

class TestBlockCompletionAtZero:
    """INV-FRAME-BUDGET-004: BlockCompleted fires exactly when
    remaining_block_frames reaches 0."""

    def test_completion_fires_at_exact_budget(self):
        """30s block at 30fps: BlockCompleted fires after frame 899
        (0-indexed), which is the 900th frame emitted."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=900),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.run_block(block)

        assert len(model.completion_log) == 1
        c = model.completion_log[0]
        assert c.block_id == "B-1"
        assert c.total_frames_emitted == 900, (
            f"INV-FRAME-BUDGET-004: expected 900 frames emitted, "
            f"got {c.total_frames_emitted}"
        )
        assert c.remaining_at_completion == 0, (
            "INV-FRAME-BUDGET-004: remaining must be 0 at completion"
        )

    def test_no_completion_before_budget_exhausted(self):
        """After 899 frames (of 900 budget), BlockCompleted must NOT
        have fired yet."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=900),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.load_block(block)

        for _ in range(899):
            model.tick()

        assert len(model.completion_log) == 0, (
            "INV-FRAME-BUDGET-004 VIOLATION: BlockCompleted fired before "
            "frame budget exhausted"
        )
        assert model.remaining_block_frames == 1

        # One more tick exhausts the budget
        model.tick()
        assert len(model.completion_log) == 1
        assert model.remaining_block_frames == 0

    def test_completion_fires_exactly_once(self):
        """BlockCompleted must fire exactly once per block, never twice."""
        block = Block("B-1", duration_seconds=5.0, segments=[
            Segment("S-1", content_frames=150),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.run_block(block)

        assert len(model.completion_log) == 1

        # Attempting more ticks after completion produces nothing
        for _ in range(100):
            result = model.tick()
            # tick() returns None when block is complete
            assert result is None or model.block_completed

        assert len(model.completion_log) == 1, (
            "INV-FRAME-BUDGET-004 VIOLATION: BlockCompleted fired more "
            "than once"
        )

    def test_no_frames_emitted_after_completion(self):
        """After BlockCompleted, no further frames may be emitted
        for that block."""
        block = Block("B-1", duration_seconds=2.0, segments=[
            Segment("S-1", content_frames=60),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.run_block(block)

        frames_at_completion = model.frames_emitted_total
        tick_count_at_completion = len(model.tick_log)

        # Try 50 more ticks
        for _ in range(50):
            model.tick()

        assert len(model.tick_log) == tick_count_at_completion, (
            "INV-FRAME-BUDGET-004 VIOLATION: frames emitted after "
            "BlockCompleted"
        )


# =============================================================================
# 4. INV-FRAME-BUDGET-005: Budget check before emission
# =============================================================================

class TestBudgetCheckBeforeEmission:
    """INV-FRAME-BUDGET-005: Segments must consult remaining_block_frames
    before emitting."""

    def test_segment_clamped_at_budget(self):
        """Segment has 1000 frames of content, but block budget is only
        300 frames (10s at 30fps).  Exactly 300 frames emitted."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=1000),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 300, (
            f"INV-FRAME-BUDGET-005 VIOLATION: emitted {len(records)} "
            "frames, expected 300 (budget should clamp segment)"
        )
        # All should be decode (content was not exhausted)
        assert all(r.frame_source == "decode" for r in records)

    def test_budget_one_frame(self):
        """Edge case: block budget of 1 frame. Exactly 1 frame emitted."""
        # 1/30 second ≈ 0.0334s → ceil(0.0334 * 30) = 1
        block = Block("B-1", duration_seconds=1.0/30.0, segments=[
            Segment("S-1", content_frames=100),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 1
        assert len(model.completion_log) == 1
        assert model.completion_log[0].total_frames_emitted == 1


# =============================================================================
# 5. INV-FRAME-BUDGET-006: Segment exhaustion != block completion
# =============================================================================

class TestSegmentExhaustionNotBlockCompletion:
    """INV-FRAME-BUDGET-006: Segment exhaustion MUST NOT cause block
    completion unless the frame budget is also exhausted."""

    def test_single_segment_shorter_than_block(self):
        """Segment has 100 frames, block budget is 300.
        Block continues with freeze for remaining 200 frames.
        BlockCompleted fires at frame 300, NOT at frame 100."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=100),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 300, (
            f"INV-FRAME-BUDGET-006 VIOLATION: block ended at "
            f"{len(records)} frames instead of 300 (segment exhaustion "
            "incorrectly triggered block completion)"
        )

        # BlockCompleted fires once, at frame 300
        assert len(model.completion_log) == 1
        assert model.completion_log[0].total_frames_emitted == 300

        # First 100 are decode, last 200 are freeze
        decode_count = sum(1 for r in records if r.frame_source == "decode")
        freeze_count = sum(1 for r in records if r.frame_source == "freeze")
        assert decode_count == 100
        assert freeze_count == 200

    def test_segment_exhaustion_mid_block_no_completion(self):
        """Explicit check: at the exact tick where the segment exhausts,
        BlockCompleted must NOT have fired."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=50),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.load_block(block)

        # Run 50 ticks (segment exhausts at tick 49, 0-indexed)
        for i in range(50):
            model.tick()

        # Segment is exhausted
        assert model._segment_frames_remaining == 0

        # But BlockCompleted must NOT have fired
        assert len(model.completion_log) == 0, (
            "INV-FRAME-BUDGET-006 VIOLATION: BlockCompleted fired at "
            "segment exhaustion, not at budget exhaustion"
        )
        assert model.remaining_block_frames == 250

    def test_all_segments_exhaust_before_budget(self):
        """Three segments, all exhaust before the block budget.
        Block fills remainder with freeze/pad.
        BlockCompleted fires at budget exhaustion."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=50),
            Segment("S-2", content_frames=80),
            Segment("S-3", content_frames=20),
        ])
        # Total content: 150 frames.  Budget: 300 frames.
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 300
        assert model.completion_log[0].total_frames_emitted == 300

        decode_count = sum(1 for r in records if r.frame_source == "decode")
        assert decode_count == 150  # 50 + 80 + 20


# =============================================================================
# 6. Single-segment block
# =============================================================================

class TestSingleSegmentBlock:
    """Block with exactly one segment — the simple case."""

    def test_content_exactly_fills_budget(self):
        """Segment content frames == block frame budget.
        All frames are decode.  BlockCompleted fires at the end."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=900),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 900
        assert all(r.frame_source == "decode" for r in records)
        assert len(model.completion_log) == 1
        assert model.completion_log[0].total_frames_emitted == 900

    def test_content_shorter_than_budget(self):
        """Segment: 600 frames.  Budget: 900 frames.
        600 decode + 300 freeze.  Completion at 900."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=600),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 900
        decode_count = sum(1 for r in records if r.frame_source == "decode")
        freeze_count = sum(1 for r in records if r.frame_source == "freeze")
        assert decode_count == 600
        assert freeze_count == 300
        assert model.completion_log[0].total_frames_emitted == 900

    def test_content_longer_than_budget(self):
        """Segment: 1200 frames.  Budget: 900 frames.
        Exactly 900 decode frames emitted.  300 frames truncated."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=1200),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 900, (
            f"INV-FRAME-BUDGET-005 VIOLATION: emitted {len(records)} frames "
            "instead of 900 (segment overran budget)"
        )
        assert all(r.frame_source == "decode" for r in records)
        assert model.completion_log[0].total_frames_emitted == 900


# =============================================================================
# 7. Multi-segment block
# =============================================================================

class TestMultiSegmentBlock:
    """Block with N > 1 segments.  The model must not assume any
    fixed segment count."""

    def test_two_segments_fill_budget_exactly(self):
        """Two segments whose content sums to exactly the budget.
        450 + 450 = 900 = budget.  All decode.  One completion."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=450),
            Segment("S-2", content_frames=450),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 900
        assert all(r.frame_source == "decode" for r in records)
        assert len(model.completion_log) == 1
        assert model.completion_log[0].total_frames_emitted == 900

        # Verify both segments contributed
        s1_frames = sum(1 for r in records if r.segment_id == "S-1")
        s2_frames = sum(1 for r in records if r.segment_id == "S-2")
        assert s1_frames == 450
        assert s2_frames == 450

    def test_four_segments_commercial_break(self):
        """Four 15-second spots in a 60-second block (commercial break).
        Each spot: 450 frames.  Budget: 1800 frames.
        4 * 450 = 1800 = budget.  All decode.  One completion."""
        block = Block("B-1", duration_seconds=60.0, segments=[
            Segment("SPOT-1", content_frames=450),
            Segment("SPOT-2", content_frames=450),
            Segment("SPOT-3", content_frames=450),
            Segment("SPOT-4", content_frames=450),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 1800
        assert len(model.completion_log) == 1

        # Each spot contributed 450 frames
        for spot_id in ["SPOT-1", "SPOT-2", "SPOT-3", "SPOT-4"]:
            count = sum(1 for r in records if r.segment_id == spot_id)
            assert count == 450, (
                f"Segment {spot_id} emitted {count} frames, expected 450"
            )

    def test_multi_segment_total_shorter_than_budget(self):
        """Three segments totaling 200 frames in a 300-frame block.
        200 decode + 100 freeze.  Completion at 300."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=80),
            Segment("S-2", content_frames=70),
            Segment("S-3", content_frames=50),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 300
        decode_count = sum(1 for r in records if r.frame_source == "decode")
        freeze_count = sum(1 for r in records if r.frame_source == "freeze")
        assert decode_count == 200
        assert freeze_count == 100

    def test_multi_segment_total_longer_than_budget(self):
        """Two segments totaling 1000 frames in a 300-frame block.
        Exactly 300 frames emitted.  First segment exhausts at 600,
        but budget clamps at 300 — second segment never touched."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=600),
            Segment("S-2", content_frames=400),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 300, (
            f"INV-FRAME-BUDGET-005 VIOLATION: emitted {len(records)} frames "
            "instead of 300"
        )
        # All 300 came from S-1 (it had 600, budget clamped at 300)
        assert all(r.frame_source == "decode" for r in records)
        s1_frames = sum(1 for r in records if r.segment_id == "S-1")
        assert s1_frames == 300

    def test_segment_transition_does_not_fire_completion(self):
        """At the exact tick where segment S-1 exhausts and S-2 begins,
        BlockCompleted must NOT fire."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=100),
            Segment("S-2", content_frames=200),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.load_block(block)

        # Run through S-1 exhaustion
        for _ in range(100):
            model.tick()

        assert len(model.completion_log) == 0, (
            "INV-FRAME-BUDGET-006 VIOLATION: BlockCompleted fired at "
            "segment transition"
        )

        # S-2 should now be active
        record = model.tick()
        assert record is not None
        assert record.frame_source == "decode"
        assert record.segment_id == "S-2"

    def test_seven_segments(self):
        """Arbitrary segment count (7).  Block budget is the authority,
        not segment count.  No hardcoded N."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=40),
            Segment("S-2", content_frames=50),
            Segment("S-3", content_frames=30),
            Segment("S-4", content_frames=45),
            Segment("S-5", content_frames=35),
            Segment("S-6", content_frames=60),
            Segment("S-7", content_frames=40),
        ])
        # Total content: 300 = budget.  Exact fit.
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        assert len(records) == 300
        assert all(r.frame_source == "decode" for r in records)
        assert len(model.completion_log) == 1


# =============================================================================
# 8. INV-FRAME-BUDGET-007: Budget never negative
# =============================================================================

class TestBudgetNeverNegative:
    """INV-FRAME-BUDGET-007: remaining_block_frames >= 0 at all times."""

    def test_remaining_never_negative_full_block(self):
        """Run a full block.  Assert remaining >= 0 after every tick."""
        block = Block("B-1", duration_seconds=30.0, segments=[
            Segment("S-1", content_frames=900),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        for r in records:
            assert r.remaining_after >= 0, (
                f"INV-FRAME-BUDGET-007 VIOLATION: remaining_after="
                f"{r.remaining_after} at tick {r.tick_index}"
            )

    def test_remaining_never_negative_overlong_content(self):
        """Content longer than budget.  Budget must not go negative
        even though content could keep producing."""
        block = Block("B-1", duration_seconds=5.0, segments=[
            Segment("S-1", content_frames=999),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        records = model.run_block(block)

        for r in records:
            assert r.remaining_after >= 0
        assert model.remaining_block_frames == 0
        assert len(records) == 150  # 5s * 30fps


# =============================================================================
# 9. Block transition: A completes, B starts
# =============================================================================

class TestBlockTransition:
    """Two consecutive blocks with independent frame budgets."""

    def test_independent_budgets(self):
        """Block A (10s) and Block B (20s) have independent budgets.
        A emits 300, B emits 600.  Each BlockCompleted fires at the
        correct count."""
        block_a = Block("A", duration_seconds=10.0, segments=[
            Segment("A-S1", content_frames=300),
        ])
        block_b = Block("B", duration_seconds=20.0, segments=[
            Segment("B-S1", content_frames=600),
        ])

        model = FrameBudgetModel(output_fps=30.0)
        model.load_block(block_a)
        model.set_next_block(block_b)

        # Run block A to completion
        while len(model.completion_log) < 1:
            model.tick()

        a_completion = model.completion_log[0]
        assert a_completion.block_id == "A"
        assert a_completion.total_frames_emitted == 300

        # Block B should now be loaded
        assert model.next_block_loaded
        assert model.current_block.block_id == "B"
        assert model.remaining_block_frames == 600

        # Run block B to completion
        while len(model.completion_log) < 2:
            model.tick()

        b_completion = model.completion_log[1]
        assert b_completion.block_id == "B"
        assert b_completion.total_frames_emitted == 600

    def test_no_frame_leak_across_boundary(self):
        """Block A's last frame is tick 299 (budget 300).
        Block B's first frame is tick 0 of B (budget 600).
        No frame belongs to both blocks.  No gap."""
        block_a = Block("A", duration_seconds=10.0, segments=[
            Segment("A-S1", content_frames=300),
        ])
        block_b = Block("B", duration_seconds=20.0, segments=[
            Segment("B-S1", content_frames=600),
        ])

        model = FrameBudgetModel(output_fps=30.0)
        model.load_block(block_a)
        model.set_next_block(block_b)

        # Run block A to completion
        a_records = []
        while len(model.completion_log) < 1:
            r = model.tick()
            if r is not None:
                a_records.append(r)

        # Block A emitted exactly 300
        assert len(a_records) == 300
        assert a_records[-1].remaining_after == 0

        # Block B starts fresh at remaining = 600
        assert model.remaining_block_frames == 600

        b_records = []
        while len(model.completion_log) < 2:
            r = model.tick()
            if r is not None:
                b_records.append(r)

        assert len(b_records) == 600
        assert b_records[0].remaining_before == 600
        assert b_records[-1].remaining_after == 0

    def test_transition_with_different_segment_counts(self):
        """Block A has 1 segment.  Block B has 4 segments.
        Frame budget is independent of segment count."""
        block_a = Block("A", duration_seconds=10.0, segments=[
            Segment("A-S1", content_frames=300),
        ])
        block_b = Block("B", duration_seconds=10.0, segments=[
            Segment("B-S1", content_frames=75),
            Segment("B-S2", content_frames=75),
            Segment("B-S3", content_frames=75),
            Segment("B-S4", content_frames=75),
        ])

        model = FrameBudgetModel(output_fps=30.0)
        model.set_next_block(block_b)
        model.run_block(block_a)

        # Both have 300-frame budget regardless of segment count
        assert model.completion_log[0].total_frames_emitted == 300

        while not model.block_completed:
            model.tick()

        assert model.completion_log[1].total_frames_emitted == 300


# =============================================================================
# 10. Completion timing (BlockCompleted on final frame, not before/after)
# =============================================================================

class TestCompletionTiming:
    """BlockCompleted must fire on the tick that exhausts the budget,
    not one tick early, not one tick late."""

    def test_completion_on_last_tick_not_after(self):
        """The tick that emits frame 299 (0-indexed, budget=300) is the
        tick that fires BlockCompleted.  The next tick must not emit."""
        block = Block("B-1", duration_seconds=10.0, segments=[
            Segment("S-1", content_frames=300),
        ])
        model = FrameBudgetModel(output_fps=30.0)
        model.load_block(block)

        for i in range(299):
            record = model.tick()
            assert record is not None
            assert not model.block_completed

        # Tick 299: last frame, completion fires
        record = model.tick()
        assert record is not None
        assert record.tick_index == 299
        assert record.remaining_after == 0
        assert model.block_completed
        assert len(model.completion_log) == 1

        # Tick 300: must NOT emit
        result = model.tick()
        assert result is None

    def test_completion_tick_matches_budget_exactly(self):
        """For various block durations, verify completion fires at
        exactly tick (budget - 1)."""
        for duration_s, fps in [(1.0, 30.0), (10.0, 24.0), (30.0, 30.0),
                                (60.0, 29.97), (0.5, 30.0)]:
            block = Block(
                f"B-{duration_s}s",
                duration_seconds=duration_s,
                segments=[Segment("S-1", content_frames=10000)],
            )
            budget = block.frame_budget(fps)
            model = FrameBudgetModel(output_fps=fps)
            records = model.run_block(block)

            assert len(records) == budget, (
                f"Block {duration_s}s@{fps}fps: emitted {len(records)}, "
                f"expected {budget}"
            )
            assert model.completion_log[0].total_frames_emitted == budget
            assert records[-1].remaining_after == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
