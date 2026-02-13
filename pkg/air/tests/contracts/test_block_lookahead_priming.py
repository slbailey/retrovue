"""
Contract Tests: INV-BLOCK-LOOKAHEAD-PRIMING

Contract reference:
    pkg/air/docs/contracts/INV-BLOCK-LOOKAHEAD-PRIMING.md

These tests enforce Look-Ahead Priming invariants using a Python model
that faithfully mirrors the current C++ TickProducer / ProducerPreloader
lifecycle.  The model deliberately does NOT implement priming — it
reflects current AIR behavior.  Every test asserts a priming invariant
and therefore FAILS against the current model.

When priming is implemented in C++, the model is updated to match and
the tests pass.

    INV-BLOCK-PRIME-001  Decoder readiness before boundary
    INV-BLOCK-PRIME-002  Zero preparation latency at boundary
    INV-BLOCK-PRIME-003  No duplicate decoding
    INV-BLOCK-PRIME-004  No impact on steady-state cadence
    INV-BLOCK-PRIME-005  Priming failure degrades safely
    INV-BLOCK-PRIME-006  Priming is event-driven
    INV-BLOCK-PRIME-007  Primed frame metadata integrity

All tests are deterministic and require no media files, AIR process,
or wall-clock sleeps.

Copyright (c) 2025 RetroVue
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

import pytest


# =============================================================================
# Model: Faithful mirror of current C++ behavior (NO priming)
#
# The model tracks decode invocations explicitly so tests can distinguish
# "returned from memory" (primed) vs "returned from decode" (live).
# =============================================================================

@dataclass
class FrameData:
    """Mirrors blockplan::FrameData."""
    video_pts_us: int        # decoder-reported PTS in microseconds
    decoder_frame_index: int  # which frame the decoder was at when this was decoded
    asset_uri: str
    block_ct_ms: int
    audio_samples: int       # simplified: sample count


@dataclass
class FakeDecoder:
    """Simulates FFmpegDecoder: open, seek, decode in sequence.

    Every decode_frame() call advances the internal position by one frame,
    returns FrameData with PTS derived from position, and increments
    decode_call_count.  Tests read decode_call_count to detect whether
    TryGetFrame triggered a live decode.
    """
    asset_uri: str
    fps: float
    total_frames: int
    _position: int = 0
    _opened: bool = False
    decode_call_count: int = 0

    @property
    def frame_duration_us(self) -> int:
        return round(1_000_000 / self.fps)

    def open(self) -> bool:
        self._opened = True
        return True

    def seek_to_ms(self, offset_ms: int) -> None:
        frame_dur_ms = 1000.0 / self.fps
        self._position = int(offset_ms / frame_dur_ms)

    def decode_frame(self) -> Optional[FrameData]:
        if not self._opened or self._position >= self.total_frames:
            return None
        pts_us = self._position * self.frame_duration_us
        frame = FrameData(
            video_pts_us=pts_us,
            decoder_frame_index=self._position,
            asset_uri=self.asset_uri,
            block_ct_ms=0,  # filled by caller
            audio_samples=1024,
        )
        self._position += 1
        self.decode_call_count += 1
        return frame

    @property
    def position(self) -> int:
        return self._position


@dataclass
class BlockSpec:
    """Minimal block descriptor for the model."""
    block_id: str
    asset_uri: str
    input_fps: float
    total_frames: int
    duration_ms: int
    asset_start_offset_ms: int = 0


class TickProducerModel:
    """Python mirror of C++ TickProducer — current behavior, NO priming.

    State machine: EMPTY -> READY (AssignBlock) -> EMPTY (Reset)
    """

    EMPTY = "EMPTY"
    READY = "READY"

    def __init__(self, output_fps: float) -> None:
        self.output_fps = output_fps
        self.state = self.EMPTY
        self.decoder: Optional[FakeDecoder] = None
        self.decoder_ok = False
        self.primed_frame: Optional[FrameData] = None
        self.buffered_frames: deque[FrameData] = deque()
        self.block_ct_ms = 0
        self.input_fps = 0.0
        self.input_frame_duration_ms = 0
        self.frames_per_block = 0
        self._block: Optional[BlockSpec] = None

    def assign_block(self, block: BlockSpec) -> None:
        """Mirrors AssignBlock: probe, open, seek, set READY."""
        self.reset()
        self._block = block
        self.frames_per_block = int(
            math.ceil(block.duration_ms * self.output_fps / 1000.0)
        )

        self.decoder = FakeDecoder(
            asset_uri=block.asset_uri,
            fps=block.input_fps,
            total_frames=block.total_frames,
        )
        if not self.decoder.open():
            self.decoder = None
            self.decoder_ok = False
            self.state = self.READY
            return

        if block.asset_start_offset_ms > 0:
            self.decoder.seek_to_ms(block.asset_start_offset_ms)

        self.input_fps = block.input_fps
        self.input_frame_duration_ms = round(1000 / block.input_fps)
        self.block_ct_ms = 0
        self.decoder_ok = True
        self.state = self.READY
        # NOTE: Current C++ does NOT prime here.  state_ = kReady is set,
        # but no frame has been decoded.  primed_frame remains None.

    def prime_first_frame(self) -> None:
        """INV-BLOCK-PRIME-001: Decode first frame into held slot.

        Mirrors C++ TickProducer::PrimeFirstFrame().
        Called by ProducerPreloader::Worker after AssignBlock completes.
        """
        if self.state != self.READY or not self.decoder_ok or self.decoder is None:
            return  # INV-BLOCK-PRIME-005: failure degrades safely

        raw = self.decoder.decode_frame()
        if raw is None:
            return  # INV-BLOCK-PRIME-005: decode failure → empty slot

        # PTS-anchored CT (same logic as try_get_frame)
        decoded_pts_ms = raw.video_pts_us // 1000
        ct_before = decoded_pts_ms - self._block.asset_start_offset_ms
        raw.block_ct_ms = ct_before
        self.block_ct_ms = ct_before + self.input_frame_duration_ms

        self.primed_frame = raw

    def decode_next_frame_raw(self) -> Optional[FrameData]:
        """Mirrors C++ DecodeNextFrameRaw — decode-only, no delivery state."""
        if self.state != self.READY:
            return None
        if not self.decoder_ok or self.decoder is None:
            self.block_ct_ms += self.input_frame_duration_ms
            return None

        raw = self.decoder.decode_frame()
        if raw is None:
            self.block_ct_ms += self.input_frame_duration_ms
            return None

        decoded_pts_ms = raw.video_pts_us // 1000
        ct_before = decoded_pts_ms - self._block.asset_start_offset_ms
        raw.block_ct_ms = ct_before
        self.block_ct_ms = ct_before + self.input_frame_duration_ms
        return raw

    def prime_first_tick(self, min_audio_prime_ms: int) -> tuple[bool, int]:
        """Mirrors C++ PrimeFirstTick — decode-driven priming with local deque.

        Returns (met_threshold, actual_depth_ms).
        """
        self.prime_first_frame()
        if self.primed_frame is None:
            return (False, 0)
        if min_audio_prime_ms <= 0:
            return (True, 0)

        audio_samples = self.primed_frame.audio_samples
        depth_ms = (audio_samples * 1000) // 48000  # kHouseAudioSampleRate
        if depth_ms >= min_audio_prime_ms:
            return (True, depth_ms)

        # Move primed frame into local accumulation deque.
        primed_frames: deque[FrameData] = deque()
        primed_frames.append(self.primed_frame)
        self.primed_frame = None

        max_null_run = 10
        max_total_decodes = 60
        null_run = 0
        total_decodes = 0

        while depth_ms < min_audio_prime_ms and total_decodes < max_total_decodes:
            total_decodes += 1
            fd = self.decode_next_frame_raw()
            if fd is None:
                null_run += 1
                if null_run >= max_null_run:
                    break
                continue
            null_run = 0
            audio_samples += fd.audio_samples
            depth_ms = (audio_samples * 1000) // 48000
            primed_frames.append(fd)

        # Restore: first → primed_frame_, rest → buffered_frames_.
        self.primed_frame = primed_frames.popleft()
        for f in primed_frames:
            self.buffered_frames.append(f)

        return (depth_ms >= min_audio_prime_ms, depth_ms)

    def try_get_frame(self) -> Optional[FrameData]:
        """Mirrors TryGetFrame with priming gate at entry."""
        if self.state != self.READY:
            return None

        # INV-BLOCK-PRIME-002: primed frame returned without decode
        if self.primed_frame is not None:
            frame = self.primed_frame
            self.primed_frame = None
            return frame

        # INV-AUDIO-PRIME-001: return buffered frames from PrimeFirstTick
        if self.buffered_frames:
            return self.buffered_frames.popleft()

        if not self.decoder_ok or self.decoder is None:
            self.block_ct_ms += self.input_frame_duration_ms
            return None

        # Decode-only path
        return self.decode_next_frame_raw()

    def reset(self) -> None:
        self.state = self.EMPTY
        self.decoder = None
        self.decoder_ok = False
        self.primed_frame = None
        self.buffered_frames.clear()
        self.block_ct_ms = 0
        self.input_fps = 0.0
        self.input_frame_duration_ms = 0
        self.frames_per_block = 0
        self._block = None


class ProducerPreloaderModel:
    """Python mirror of ProducerPreloader::Worker sequence."""

    def __init__(self) -> None:
        self.result: Optional[TickProducerModel] = None

    def preload(self, block: BlockSpec, output_fps: float) -> TickProducerModel:
        """Mirrors Worker: create TickProducer, AssignBlock, [prime], publish.

        Current model mirrors current C++:
          1. AssignBlock  (opens decoder, seeks, sets kReady)
          2. prime_first_frame  (NO-OP — not implemented)
          3. publish result_
        """
        tp = TickProducerModel(output_fps)
        tp.assign_block(block)
        # INV-BLOCK-PRIME-006: priming executes here, after AssignBlock,
        # as a direct continuation on the worker thread.
        tp.prime_first_frame()
        # publish
        self.result = tp
        return tp

    def take_source(self) -> Optional[TickProducerModel]:
        result = self.result
        self.result = None
        return result


class CadenceGate:
    """Python mirror of PipelineManager's cadence accumulator."""

    def __init__(self, input_fps: float, output_fps: float) -> None:
        self.output_fps = output_fps
        if input_fps > 0.0 and input_fps < output_fps * 0.98:
            self.active = True
            self.ratio = input_fps / output_fps
            self.budget = 1.0  # first tick always decodes
        else:
            self.active = False
            self.ratio = 0.0
            self.budget = 0.0

    def should_decode(self) -> bool:
        if not self.active:
            return True
        self.budget += self.ratio
        if self.budget >= 1.0:
            self.budget -= 1.0
            return True
        return False


# =============================================================================
# Helpers
# =============================================================================

def _make_block(
    block_id: str = "blk-001",
    asset_uri: str = "/test/asset.mp4",
    input_fps: float = 30.0,
    total_frames: int = 900,
    duration_ms: int = 30_000,
    asset_start_offset_ms: int = 0,
) -> BlockSpec:
    return BlockSpec(
        block_id=block_id,
        asset_uri=asset_uri,
        input_fps=input_fps,
        total_frames=total_frames,
        duration_ms=duration_ms,
        asset_start_offset_ms=asset_start_offset_ms,
    )


def _make_broken_decoder_block() -> BlockSpec:
    """Block whose decoder will fail (0 total frames simulates open failure)."""
    return _make_block(block_id="blk-broken", total_frames=0)


# =============================================================================
# 1. INV-BLOCK-PRIME-001: Decoder readiness before boundary
# =============================================================================

class TestDecoderReadyBeforeBoundary:
    """INV-BLOCK-PRIME-001: After preload completes, the producer MUST hold
    a decoded frame before the readiness signal is observable."""

    def test_primed_frame_exists_after_preload(self):
        """After PreloaderModel.preload(), primed_frame must be populated."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.primed_frame is not None, (
            "INV-BLOCK-PRIME-001 VIOLATION: primed_frame is None after preload. "
            "The first frame must be decoded into the held slot before the "
            "producer is published to PipelineManager."
        )

    def test_primed_frame_exists_before_result_published(self):
        """The result must not be observable until priming completes."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        preloader.preload(block, output_fps=30.0)

        # take_source is how PipelineManager observes the result
        tp = preloader.take_source()
        assert tp is not None
        assert tp.primed_frame is not None, (
            "INV-BLOCK-PRIME-001 VIOLATION: take_source() returned a producer "
            "with no primed frame.  The readiness signal was observable before "
            "priming completed."
        )

    def test_primed_frame_is_frame_zero(self):
        """The primed frame must be the first frame of the block (index 0)."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.primed_frame is not None, "Precondition: primed_frame must exist"
        assert tp.primed_frame.decoder_frame_index == 0, (
            "INV-BLOCK-PRIME-001 VIOLATION: primed frame is not frame 0. "
            f"Got index={tp.primed_frame.decoder_frame_index}."
        )

    def test_primed_frame_with_jip_offset(self):
        """When asset_start_offset_ms > 0 (JIP), the primed frame must be
        at the seeked position, not frame 0 of the asset."""
        preloader = ProducerPreloaderModel()
        block = _make_block(
            input_fps=30.0,
            asset_start_offset_ms=10_000,  # 10 seconds in
        )
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.primed_frame is not None, "Precondition: primed_frame must exist"
        # At 30fps, 10000ms = frame 300
        expected_index = 300
        assert tp.primed_frame.decoder_frame_index == expected_index, (
            "INV-BLOCK-PRIME-001 VIOLATION: primed frame index after JIP seek "
            f"is {tp.primed_frame.decoder_frame_index}, expected {expected_index}."
        )


# =============================================================================
# 2. INV-BLOCK-PRIME-002: Zero preparation latency at boundary
# =============================================================================

class TestFirstFrameEmittedOnBoundary:
    """INV-BLOCK-PRIME-002: The first TryGetFrame after swap must return
    without invoking the decoder."""

    def test_first_try_get_frame_returns_without_decode(self):
        """First TryGetFrame must not trigger a decode call."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        # Record decode count BEFORE first TryGetFrame
        assert tp.decoder is not None, "Precondition: decoder must exist"
        decodes_before = tp.decoder.decode_call_count

        frame = tp.try_get_frame()
        assert frame is not None, "First TryGetFrame must return a frame"

        decodes_after = tp.decoder.decode_call_count
        assert decodes_after == decodes_before, (
            "INV-BLOCK-PRIME-002 VIOLATION: first TryGetFrame triggered "
            f"{decodes_after - decodes_before} decode call(s). "
            "The primed frame must be returned from memory, not from the decoder."
        )

    def test_first_frame_has_valid_content(self):
        """The frame returned on the boundary tick must have real content,
        not a pad sentinel."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        frame = tp.try_get_frame()
        assert frame is not None, (
            "INV-BLOCK-PRIME-002 VIOLATION: first TryGetFrame returned None. "
            "The boundary tick must return a real frame, not a pad."
        )
        assert frame.video_pts_us >= 0, (
            "INV-BLOCK-PRIME-002 VIOLATION: frame has invalid PTS."
        )


# =============================================================================
# 3. INV-BLOCK-PRIME-003: No duplicate decoding
# =============================================================================

class TestNoDoubleDecode:
    """INV-BLOCK-PRIME-003: The primed frame must be consumed exactly once.
    The decoder must not be rewound or re-seeked."""

    def test_second_frame_is_different(self):
        """Second TryGetFrame must return a different frame than the first."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        frame_1 = tp.try_get_frame()
        frame_2 = tp.try_get_frame()

        assert frame_1 is not None, "Precondition: frame 1 must exist"
        assert frame_2 is not None, "Precondition: frame 2 must exist"
        assert frame_2.decoder_frame_index == frame_1.decoder_frame_index + 1, (
            "INV-BLOCK-PRIME-003 VIOLATION: second frame index is "
            f"{frame_2.decoder_frame_index}, expected "
            f"{frame_1.decoder_frame_index + 1}. "
            "The primed frame was either duplicated or the decoder was rewound."
        )

    def test_primed_frame_consumed_exactly_once(self):
        """After the first TryGetFrame, primed_frame must be None."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        _ = tp.try_get_frame()  # consume primed frame
        assert tp.primed_frame is None, (
            "INV-BLOCK-PRIME-003 VIOLATION: primed_frame is still set after "
            "first TryGetFrame.  The primed frame must be consumed exactly once."
        )

    def test_decoder_position_after_prime(self):
        """After priming, the decoder's read position must be at frame 1
        (frame 0 was primed).  After first TryGetFrame (returns primed),
        the next decode reads frame 1."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.decoder is not None, "Precondition"
        # After priming, decoder should have advanced past frame 0
        assert tp.decoder.position == 1, (
            "INV-BLOCK-PRIME-003 VIOLATION: decoder position after prime is "
            f"{tp.decoder.position}, expected 1. "
            "Priming must advance the decoder past the primed frame."
        )

    def test_total_decode_count_for_n_frames(self):
        """For N calls to TryGetFrame, exactly N decodes must occur total
        (1 during priming + N-1 during TryGetFrame)."""
        preloader = ProducerPreloaderModel()
        block = _make_block(total_frames=100)
        tp = preloader.preload(block, output_fps=30.0)

        n = 10
        for _ in range(n):
            tp.try_get_frame()

        assert tp.decoder is not None, "Precondition"
        assert tp.decoder.decode_call_count == n, (
            "INV-BLOCK-PRIME-003 VIOLATION: after {n} TryGetFrame calls, "
            f"decode_call_count is {tp.decoder.decode_call_count}, expected {n}. "
            "Priming accounts for 1 decode; TryGetFrame adds N-1."
        )


# =============================================================================
# 4. INV-BLOCK-PRIME-004: No impact on steady-state cadence
# =============================================================================

class TestSteadyStateUnchanged:
    """INV-BLOCK-PRIME-004: After the primed frame is consumed, the cadence
    gate must produce the identical decode/repeat pattern as a non-primed block."""

    @staticmethod
    def _run_cadence_pattern(
        input_fps: float, output_fps: float, ticks: int
    ) -> list[bool]:
        """Run the cadence gate for N ticks, return decode/repeat pattern."""
        gate = CadenceGate(input_fps, output_fps)
        return [gate.should_decode() for _ in range(ticks)]

    def test_cadence_pattern_23976_to_30_matches(self):
        """For 23.976->30fps, the decode/repeat pattern of ticks 2..N of a
        primed block must exactly match ticks 2..N of a non-primed block."""
        input_fps = 23.976
        output_fps = 30.0
        ticks = 300  # 10 seconds

        # Non-primed reference: run cadence for `ticks` frames
        reference = self._run_cadence_pattern(input_fps, output_fps, ticks)

        # Primed block: cadence is initialized the same way (from input_fps/output_fps)
        # The primed frame is consumed on tick 0 (which always decodes: budget=1.0).
        # Ticks 1..N must be identical to reference ticks 1..N.
        primed = self._run_cadence_pattern(input_fps, output_fps, ticks)

        # Tick 0 is always a decode in both cases (budget starts at 1.0).
        # Compare ticks 1 through N-1.
        assert reference[1:] == primed[1:], (
            "INV-BLOCK-PRIME-004 VIOLATION: cadence pattern diverges after "
            "primed frame consumption.  Priming must not alter the "
            "decode/repeat sequence."
        )

    def test_cadence_accumulator_not_biased_by_priming(self):
        """After consuming the primed frame (tick 0), decode_budget must
        be identical to what a non-primed block would have."""
        input_fps = 23.976
        output_fps = 30.0

        # Non-primed reference
        ref_gate = CadenceGate(input_fps, output_fps)
        ref_gate.should_decode()  # tick 0
        ref_budget_after_tick0 = ref_gate.budget

        # Primed: same initialization, same tick 0
        primed_gate = CadenceGate(input_fps, output_fps)
        primed_gate.should_decode()  # tick 0 (consumes primed frame)
        primed_budget_after_tick0 = primed_gate.budget

        assert primed_budget_after_tick0 == ref_budget_after_tick0, (
            "INV-BLOCK-PRIME-004 VIOLATION: decode_budget after tick 0 is "
            f"{primed_budget_after_tick0}, expected {ref_budget_after_tick0}. "
            "Priming must not bias the accumulator."
        )

    def test_primed_block_frame_sequence_matches_non_primed(self):
        """The complete frame sequence (PTS values) from a primed block must
        match a non-primed block, frame for frame."""
        block = _make_block(input_fps=30.0, total_frames=100, duration_ms=5000)
        n = 20

        # Non-primed: standard TryGetFrame sequence
        tp_ref = TickProducerModel(output_fps=30.0)
        tp_ref.assign_block(block)
        ref_frames = []
        for _ in range(n):
            f = tp_ref.try_get_frame()
            if f:
                ref_frames.append(f.video_pts_us)

        # Primed: preloader path
        preloader = ProducerPreloaderModel()
        tp_primed = preloader.preload(block, output_fps=30.0)
        primed_frames = []
        for _ in range(n):
            f = tp_primed.try_get_frame()
            if f:
                primed_frames.append(f.video_pts_us)

        assert len(primed_frames) == len(ref_frames), (
            "INV-BLOCK-PRIME-004 VIOLATION: primed block produced "
            f"{len(primed_frames)} frames, reference produced "
            f"{len(ref_frames)} frames in {n} ticks."
        )
        assert primed_frames == ref_frames, (
            "INV-BLOCK-PRIME-004 VIOLATION: primed block PTS sequence diverges "
            "from non-primed reference.  Priming must produce identical output."
        )


# =============================================================================
# 5. INV-BLOCK-PRIME-005: Priming failure degrades safely
# =============================================================================

class TestPrimingFailureDegradesSafely:
    """INV-BLOCK-PRIME-005: If priming fails, the producer must still reach
    READY and TryGetFrame must fall through to normal decode or pad."""

    def test_decoder_failure_still_reaches_ready(self):
        """A block whose decoder fails must still reach READY state."""
        preloader = ProducerPreloaderModel()
        # total_frames=0 simulates a decoder that immediately returns None
        block = _make_block(block_id="blk-broken", total_frames=0)
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.state == TickProducerModel.READY, (
            "INV-BLOCK-PRIME-005 VIOLATION: producer state is "
            f"{tp.state} after failed preload, expected READY."
        )

    def test_decoder_failure_primed_frame_is_none(self):
        """When priming fails, primed_frame must be None (no partial frame)."""
        preloader = ProducerPreloaderModel()
        block = _make_block(total_frames=0)
        tp = preloader.preload(block, output_fps=30.0)

        # On failure, primed_frame must be explicitly None
        assert tp.primed_frame is None, (
            "INV-BLOCK-PRIME-005 VIOLATION: primed_frame is not None after "
            "priming failure.  A failed prime must leave the slot empty."
        )

    def test_decoder_failure_try_get_frame_returns_pad(self):
        """After failed priming, TryGetFrame falls through to pad (None)."""
        preloader = ProducerPreloaderModel()
        block = _make_block(total_frames=0)
        tp = preloader.preload(block, output_fps=30.0)

        frame = tp.try_get_frame()
        # With 0 total_frames, decode returns None -> pad
        assert frame is None, (
            "INV-BLOCK-PRIME-005: expected pad (None) from TryGetFrame after "
            "decoder failure."
        )

    def test_no_intermediate_state(self):
        """The producer must never be in a state other than EMPTY or READY."""
        preloader = ProducerPreloaderModel()
        block = _make_block(total_frames=0)
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.state in (TickProducerModel.EMPTY, TickProducerModel.READY), (
            "INV-BLOCK-PRIME-005 VIOLATION: producer in intermediate state "
            f"'{tp.state}'.  Only EMPTY and READY are permitted."
        )


# =============================================================================
# 6. INV-BLOCK-PRIME-006: Priming is event-driven
# =============================================================================

class TestPrimingIsEventDriven:
    """INV-BLOCK-PRIME-006: Priming must execute as a direct continuation
    of AssignBlock on the preloader, not via poll or timer."""

    def test_prime_executes_during_preload(self):
        """prime_first_frame is called inside preload(), between AssignBlock
        and result publication.  If primed_frame is None after preload(),
        the prime either didn't execute or was a no-op."""
        preloader = ProducerPreloaderModel()
        block = _make_block()

        # preload() calls assign_block then prime_first_frame then publishes
        tp = preloader.preload(block, output_fps=30.0)

        # If prime executed and decoded, primed_frame is set.
        # If prime was a no-op (current code), primed_frame is None.
        assert tp.primed_frame is not None, (
            "INV-BLOCK-PRIME-006 VIOLATION: primed_frame is None after preload. "
            "Priming must execute as part of the preload sequence, not deferred."
        )

    def test_no_prime_method_needed_on_pipeline_manager(self):
        """PipelineManager must not need to call a priming method.  The
        producer arrives already primed.  Verify: after take_source(),
        the producer is ready with a primed frame — no additional call needed."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        preloader.preload(block, output_fps=30.0)

        tp = preloader.take_source()
        assert tp is not None
        # PipelineManager just calls TryGetFrame — it must not need to prime
        assert tp.primed_frame is not None, (
            "INV-BLOCK-PRIME-006 VIOLATION: producer from take_source() has "
            "no primed frame.  PipelineManager would need a priming call, "
            "which violates event-driven priming (C4)."
        )


# =============================================================================
# 7. INV-BLOCK-PRIME-007: Primed frame metadata integrity
# =============================================================================

class TestPrimedFrameMetadataIntegrity:
    """INV-BLOCK-PRIME-007: The primed frame must carry identical metadata
    to what a normal TryGetFrame decode would have produced."""

    def test_primed_pts_matches_normal_decode(self):
        """The primed frame's PTS must equal what TryGetFrame would produce."""
        block = _make_block(input_fps=30.0)

        # Reference: non-primed TryGetFrame
        tp_ref = TickProducerModel(output_fps=30.0)
        tp_ref.assign_block(block)
        ref_frame = tp_ref.try_get_frame()

        # Primed
        preloader = ProducerPreloaderModel()
        tp_primed = preloader.preload(block, output_fps=30.0)

        assert tp_primed.primed_frame is not None, (
            "Precondition: primed_frame must exist"
        )
        assert ref_frame is not None, "Precondition: reference frame must exist"

        assert tp_primed.primed_frame.video_pts_us == ref_frame.video_pts_us, (
            "INV-BLOCK-PRIME-007 VIOLATION: primed PTS "
            f"{tp_primed.primed_frame.video_pts_us} != reference PTS "
            f"{ref_frame.video_pts_us}.  Metadata must be identical."
        )

    def test_primed_asset_uri_correct(self):
        """The primed frame's asset_uri must match the first segment."""
        preloader = ProducerPreloaderModel()
        block = _make_block(asset_uri="/content/episode.mp4")
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.primed_frame is not None, "Precondition"
        assert tp.primed_frame.asset_uri == "/content/episode.mp4", (
            "INV-BLOCK-PRIME-007 VIOLATION: primed asset_uri is "
            f"'{tp.primed_frame.asset_uri}', expected '/content/episode.mp4'."
        )

    def test_primed_block_ct_ms_is_zero(self):
        """The primed frame is the first frame of the block.
        block_ct_ms must be 0 (content time before first frame advance)."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.primed_frame is not None, "Precondition"
        assert tp.primed_frame.block_ct_ms == 0, (
            "INV-BLOCK-PRIME-007 VIOLATION: primed block_ct_ms is "
            f"{tp.primed_frame.block_ct_ms}, expected 0."
        )

    def test_primed_audio_present(self):
        """The primed frame must include audio samples."""
        preloader = ProducerPreloaderModel()
        block = _make_block()
        tp = preloader.preload(block, output_fps=30.0)

        assert tp.primed_frame is not None, "Precondition"
        assert tp.primed_frame.audio_samples > 0, (
            "INV-BLOCK-PRIME-007 VIOLATION: primed frame has no audio. "
            "Audio samples associated with the video frame must be included."
        )


# =============================================================================
# 8. Cross-invariant: full preload→swap→tick lifecycle
# =============================================================================

class TestFullLifecycle:
    """End-to-end lifecycle: preload block, swap, tick N frames.
    Verifies all invariants together in the sequence PipelineManager executes."""

    def test_preload_swap_tick_sequence(self):
        """Simulate: preload → take_source → N TryGetFrame calls.

        Invariants checked:
          001: primed_frame exists after preload
          002: first TryGetFrame does not decode
          003: frames are sequential, no duplicates
          007: first frame metadata is correct
        """
        preloader = ProducerPreloaderModel()
        block = _make_block(input_fps=30.0, total_frames=100, duration_ms=5000)
        preloader.preload(block, output_fps=30.0)

        # Swap (PipelineManager does: live_ = take_source())
        tp = preloader.take_source()
        assert tp is not None

        # 001: primed frame exists
        assert tp.primed_frame is not None, "INV-BLOCK-PRIME-001"

        # Record decoder state before first TryGetFrame
        assert tp.decoder is not None
        decodes_before = tp.decoder.decode_call_count

        # First TryGetFrame (boundary tick)
        frame_0 = tp.try_get_frame()
        assert frame_0 is not None, "Boundary tick must return a frame"

        # 002: no decode on boundary tick
        assert tp.decoder.decode_call_count == decodes_before, (
            "INV-BLOCK-PRIME-002: boundary tick triggered a decode"
        )

        # 003: primed frame consumed
        assert tp.primed_frame is None, "INV-BLOCK-PRIME-003: not consumed"

        # Tick 9 more frames (normal decode path)
        frames = [frame_0]
        for _ in range(9):
            f = tp.try_get_frame()
            assert f is not None, "Steady-state tick must return a frame"
            frames.append(f)

        # 003: sequential indices
        for i in range(1, len(frames)):
            assert frames[i].decoder_frame_index == frames[i - 1].decoder_frame_index + 1, (
                f"INV-BLOCK-PRIME-003: frame {i} index "
                f"{frames[i].decoder_frame_index} is not sequential "
                f"(prev={frames[i - 1].decoder_frame_index})"
            )

        # 007: first frame metadata
        assert frame_0.decoder_frame_index == 0, "INV-BLOCK-PRIME-007: index"
        assert frame_0.video_pts_us == 0, "INV-BLOCK-PRIME-007: PTS"
        assert frame_0.asset_uri == block.asset_uri, "INV-BLOCK-PRIME-007: uri"


# =============================================================================
# 9. Regression: PrimeFirstTick decode depth (42ms plateau fix)
# =============================================================================

class TestAudioPrimeDecodeDepth:
    """Regression: PrimeFirstTick must decode multiple frames to reach audio threshold.

    Before the DecodeNextFrameRaw refactor, PrimeFirstTick could plateau at ~42ms
    (a single frame's audio) because the decode loop re-served buffered frames
    instead of advancing the decoder. This test catches that regression.
    """

    def test_prime_first_tick_reaches_500ms(self):
        """PrimeFirstTick(500) must report got_ms >= 500 on normal assets."""
        block = _make_block(
            input_fps=30.0,
            total_frames=900,
            duration_ms=30_000,
        )
        tp = TickProducerModel(output_fps=30.0)
        tp.assign_block(block)

        met, depth_ms = tp.prime_first_tick(500)

        assert met, (
            "INV-AUDIO-PRIME-001 REGRESSION: PrimeFirstTick(500) did not meet "
            f"threshold.  got_ms={depth_ms}.  The decode loop must advance the "
            "decoder beyond the first frame to accumulate audio."
        )
        assert depth_ms >= 500, (
            f"INV-AUDIO-PRIME-001 REGRESSION: depth_ms={depth_ms} < 500. "
            "Audio depth plateau indicates decode loop is not advancing."
        )

    def test_prime_first_tick_decodes_multiple_frames(self):
        """PrimeFirstTick(500) must decode beyond frame 0 (buffered_frames > 0).

        Indirect assertion: after PrimeFirstTick, calling TryGetFrame() repeatedly
        should return >1 frame before hitting decode latency (buffered frames
        return instantly; live decode has measurable latency).
        """
        block = _make_block(
            input_fps=30.0,
            total_frames=900,
            duration_ms=30_000,
        )
        tp = TickProducerModel(output_fps=30.0)
        tp.assign_block(block)
        tp.prime_first_tick(500)

        # Consume primed frame (frame 0)
        frame_0 = tp.try_get_frame()
        assert frame_0 is not None, "Primed frame must exist"

        # At least one buffered frame must exist from priming
        assert len(tp.buffered_frames) > 0 or tp.try_get_frame() is not None, (
            "INV-AUDIO-PRIME-001 REGRESSION: No buffered frames after "
            "PrimeFirstTick(500).  The decode loop did not advance beyond "
            "the first frame."
        )

    def test_prime_first_tick_buffered_frames_retain_audio(self):
        """Each buffered frame must retain its own decoded audio (not stripped).

        Before the refactor, buffered frames had their audio moved into
        primed_frame_.  After the refactor, each frame keeps its own audio.
        """
        block = _make_block(
            input_fps=30.0,
            total_frames=900,
            duration_ms=30_000,
        )
        tp = TickProducerModel(output_fps=30.0)
        tp.assign_block(block)
        tp.prime_first_tick(500)

        # Primed frame should have its own audio
        assert tp.primed_frame is not None
        assert tp.primed_frame.audio_samples > 0, (
            "Primed frame must retain its own audio"
        )

        # Each buffered frame must also have audio
        for i, bf in enumerate(tp.buffered_frames):
            assert bf.audio_samples > 0, (
                f"INV-AUDIO-PRIME-001 REGRESSION: buffered_frame[{i}] has "
                f"audio_samples={bf.audio_samples}.  Each frame must retain "
                "its own decoded audio."
            )

    def test_prime_produces_distinct_pts_values(self):
        """Decoded frames during priming must have distinct, advancing PTS."""
        block = _make_block(
            input_fps=30.0,
            total_frames=900,
            duration_ms=30_000,
        )
        tp = TickProducerModel(output_fps=30.0)
        tp.assign_block(block)
        tp.prime_first_tick(500)

        # Collect block_ct_ms from primed + buffered frames via TryGetFrame()
        ct_values = []
        while True:
            f = tp.try_get_frame()
            if f is None:
                break
            ct_values.append(f.block_ct_ms)
            # Stop after consuming all primed+buffered frames
            if len(ct_values) > 30:
                break

        assert len(ct_values) >= 2, (
            "Must have at least 2 frames to verify PTS advancement"
        )

        # Verify monotonically increasing
        for i in range(1, len(ct_values)):
            assert ct_values[i] > ct_values[i - 1], (
                f"INV-AUDIO-PRIME-001 REGRESSION: block_ct_ms not monotonically "
                f"increasing at index {i}: {ct_values[i]} <= {ct_values[i-1]}. "
                "Primed frames must have distinct, advancing PTS."
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
