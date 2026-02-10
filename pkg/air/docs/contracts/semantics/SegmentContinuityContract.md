# Segment Continuity Contract (AIR)

**Classification**: Semantic Contract (Layer 1)
**Owner**: `PipelineManager` / `VideoLookaheadBuffer` / `AudioLookaheadBuffer`
**Derives From**: INV-TICK-GUARANTEED-OUTPUT (Law, Layer 0), Switching Law (Layer 0)
**Formalized By**: [SeamContinuityEngine.md](SeamContinuityEngine.md) (INV-SEAM-001 through INV-SEAM-005)

## Purpose
Define broadcast-grade continuity outcomes for any **decoder transition** (segment seam),
including episode→filler, filler→pad, and block→block (because it is also a segment transition).

This contract is the source of truth for "the channel stays alive and seamless" requirements.

## Definitions
- **Segment seam / decoder transition**: A change where the active decode source changes.
- **Seam tick**: The output tick at which the system begins emitting from the new segment.
- **Audio headroom**: Buffered audio available to the tick loop, expressed in ms.
- **Continuity fallback**: Silence/pad injection used to prevent underflow or stream death.

## Scope

These outcomes apply to:

- **All decoder transitions** where the active decode source changes:
  segment→segment within a block, block→block, content→pad, pad→content.

These outcomes do NOT apply to:

- **Steady-state decoding** within a single segment (no source change).
- **Fence tick computation** (owned by Program Block Authority).
- **Tick cadence or clock behavior** (owned by Channel Clock).
- **Decoder implementation details** — no outcome references FFmpeg, codecs,
  container formats, or I/O APIs. Outcomes are defined at the buffer/swap
  abstraction level.

## Contract Outcomes

### OUT-SEG-001: Seam safety gate (readiness)
A segment may only become active at a seam tick if the system has established continuity readiness for the incoming segment.

**Continuity readiness** MUST include:
- Incoming decode source is open and able to produce frames, OR the system will emit continuity fallback frames at the seam tick.

### OUT-SEG-002: No stream death on segment seam
A segment seam MUST NOT cause session termination.
Decoder open/close latency, probe latency, or startup delay MUST NOT stop the channel.

### OUT-SEG-003: Continuous audio output across segment seam
At every output tick, audio MUST be produced:
- from buffered decoded audio, OR
- from continuity fallback (silence/tone) if decoded audio is temporarily unavailable.

A segment seam MUST NOT create a hard audio gap (i.e., "no audio produced this tick").

### OUT-SEG-004: Audio underflow is survivable and observable
If audio underflow would otherwise occur at or after a segment seam, the system MUST:
- continue output (no teardown),
- emit continuity fallback audio for that tick,
- increment a counter/metric, and
- emit a diagnostic log event.

### OUT-SEG-005: Segment seam is mechanically equivalent to a prepared source swap
A segment seam MUST be representable as a "prepared swap" from the perspective of the tick loop:
- The tick loop MUST NOT block on decoder open/close at seam time.
- Any expensive work required to begin the next segment MUST NOT be performed on the critical output path.

(Contract statement: it is acceptable to use fallback output if preparation cannot complete in time.)

### OUT-SEG-005b: Bounded fallback at segment seams (normal case)
For well-formed local assets, segment seams SHOULD NOT require continuity fallback for more
than N consecutive ticks (where N is a tunable threshold, default 5).

Fallback is an emergency bridge, not a routine operating mode. Healthy playout should resolve
decoder transitions within a bounded number of ticks via prepared-swap preloading.

The system MUST track `max_consecutive_audio_fallback_ticks` as an observable metric.

### OUT-SEG-006: Segment transition invariants are enforced at all decoder transitions
The outcomes in this contract MUST apply uniformly to:
- segment transitions inside a program block
- program block transitions (block→block)
- transitions into PAD mode
- transitions into emergency/override modes (if implemented)

## Required Tests (must exist in tests/contracts/)
- T-SEG-001: SegmentSeamDoesNotKillSession
- T-SEG-002: SegmentSeamAudioContinuity_NoSilentTicks
- T-SEG-003: SegmentSeamUnderflowInjectsSilenceAndContinues
- T-SEG-004: SegmentSeamDoesNotBlockTickLoop
- T-SEG-005: SegmentSeamMetricsIncrementOnFallback
- T-SEG-006: SegmentSeamAppliesToBlockToBlockTransition
- T-SEG-007: RealMediaSeamBoundedFallback

## Notes
This contract defines outcomes only. Implementation strategy is intentionally unspecified.
