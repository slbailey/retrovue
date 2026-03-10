# Cadence Source Sync Contract (AIR)

**Classification**: Semantic Contract (Layer 1)
**Owner**: `PipelineManager`
**Derives From**: INV-PACING-001 (Primitive, Layer 0)

## Purpose

Define the required relationship between the frame selection cadence and
the active live source's frame rate.  The cadence controls whether each
output tick advances (pops a new decoded frame) or repeats (re-emits the
previous frame).  When the cadence does not reflect the current source
FPS, content plays at the wrong speed.

## Definitions

- **Frame selection cadence**: A Bresenham accumulator that decides, per
  output tick, whether to advance to the next decoded frame or repeat the
  last.  Parameterized by `increment` (derived from source FPS) and
  `threshold` (derived from output FPS).
- **Producer transition**: Any event where the identity of the live
  TickProducer changes — session start, block fence rotation, or
  padded-gap-exit.
- **Segment swap**: A decoder source change within a block (content→pad,
  pad→content, content→content).
- **Source FPS**: The frame rate reported by the active decoder
  (`GetInputRationalFps()`), snapped to a standard rational value.
- **Output FPS**: The session-fixed house format frame rate (e.g.
  30000/1001).

## Scope

These outcomes apply to:

- **All producer transitions** where the identity of the live
  TickProducer changes.
- **All segment swaps** where the decoder source within a block changes.

These outcomes do NOT apply to:

- Output tick pacing (owned by INV-PACING-001).
- PTS/DTS assignment (owned by OutputContinuity).
- Decoder implementation details.

## Contract Outcomes

### INV-CADENCE-SOURCE-SYNC-001: Cadence reflects live source at all times

At every output tick where the cadence is consulted, the cadence
parameters (`increment`, `threshold`, `enabled`) MUST correspond to the
current live source's FPS and the session output FPS.

A cadence derived from a prior source MUST NOT be active when a
different source is live.

### INV-CADENCE-SOURCE-SYNC-002: Producer transition resets cadence

After any producer transition (session start, block fence rotation via
any path, padded-gap-exit), the cadence MUST be reinitialized from the
new live source's FPS before the next output tick consults the cadence.

This rule applies uniformly to all fence rotation paths:
- Seamless B→A rotation (preview ready).
- Fallback synchronous queue drain (preview not ready).
- Padded-gap-exit (loaded from queue after empty state).

No path is exempt.

### INV-CADENCE-SOURCE-SYNC-003: Segment swap refreshes cadence

After any intra-block segment swap, the cadence MUST be refreshed from
the new segment's source FPS before the next output tick consults the
cadence.

### INV-CADENCE-SOURCE-SYNC-004: Stale cadence causes observable speed error

When the cadence does not match the live source FPS, content plays at
`source_fps / output_fps` relative speed instead of 1x.  Specifically:

- A 60→30 cadence applied to 24fps content produces 1.25x playback.
- A 24→30 cadence applied to 60fps content produces 0.8x playback.

This is always a defect.  There is no valid operating mode where the
cadence source FPS differs from the live source FPS.

## Failure Observability

### Detection via logs

A conforming implementation MUST emit a `FRAME_SELECTION_CADENCE_INIT`
or `FRAME_SELECTION_CADENCE_DISABLED` log line at every producer
transition, and a `FRAME_SELECTION_CADENCE_REFRESH` log line at every
segment swap.

**Violation signature:** A `FENCE_TRANSITION` or `BLOCK_START` log line
that is NOT followed (before the next `TAKE_COMMIT`) by a
`CADENCE_INIT` or `CADENCE_DISABLED` line indicates Rule 002 is
violated.

### Detection via frame consumption rate

When INV-PACING-001 holds (output ticks at real-time rate), the decoded
frame consumption rate over any 1-second window MUST equal the source
content's native FPS (±1 frame for cadence rounding).

If the consumption rate equals `output_fps` instead of `source_fps` for
a source where `source_fps ≠ output_fps`, the cadence is not active
(stale DISABLED from a prior 1:1 segment).

If the consumption rate equals a prior source's FPS instead of the
current source's FPS, the cadence is stale from a prior producer.

### INV-CADENCE-SINGLE-AUTHORITY: Cadence authority belongs to the output clock domain

Frame cadence decisions (advance vs repeat) MUST occur only at the clock
domain where frames are emitted to the output stream.  In this
architecture, that authority is the **TickLoop** (`PipelineManager`).

Decoder and buffer layers (e.g. `VideoLookaheadBuffer` FillLoop) MUST
NOT apply independent cadence logic.  The FillLoop is condvar-driven: it
wakes when the consumer pops a frame, so its natural iteration rate
already matches the source FPS.

**Violation mode:** When both TickLoop and FillLoop apply cadence, the
rate reduction is **multiplicative**.  For 24fps source / 29.97fps
output:

- TickLoop cadence: advance ratio = 24/29.97 ≈ 0.8008
- FillLoop cadence: decode ratio = 24/29.97 ≈ 0.8008
- Net unique frame rate = 29.97 × 0.8008 × 0.8008 = 19.2fps
- Content plays at 19.2/24 = **0.8× speed** (equivalently, movie takes
  1.25× longer)

This is always a defect.  Cadence is a clock-domain concern, not a
buffer-fill concern.

## Cross-Reference

| Related Contract | Relationship |
|-----------------|--------------|
| INV-PACING-001 (PrimitiveInvariants) | Parent: cadence correctness is meaningless without correct tick pacing |
| SegmentContinuityContract (OUT-SEG-006) | Sibling: segment transitions must also preserve cadence correctness |
| OutputTimingContract §5.4 | Downstream: correct PTS pacing depends on correct frame selection |
