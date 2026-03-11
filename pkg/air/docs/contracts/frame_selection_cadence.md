# Frame Selection Cadence Contract

**Status:** Active
**Scope:** Frame selection at the output tick loop (PipelineManager)
**Owner:** AIR (PipelineManager frame selection cascade)

## Purpose

This contract defines the observable correctness properties of frame cadence
conversion when the source frame rate differs from the output frame rate.

The canonical case is 3:2 pulldown: 24000/1001 fps source → 30000/1001 fps output.

## Invariants

### INV-CADENCE-POP-001: Repeat Ticks Must Not Consume Source Frames

When the cadence accumulator decides REPEAT for a given output tick, the pipeline
MUST NOT call `TryPopFrame()` on the video lookahead buffer. The pipeline MUST
re-encode the previously selected frame (`last_good_video_frame_`).

**Rationale:** Each `TryPopFrame()` call dequeues one decoded source frame. If
REPEAT ticks also pop, source frames are consumed at the output rate (30fps)
instead of the source rate (24fps). This produces 1.25× playback speed:
content that should take 1 second plays in 0.8 seconds.

### INV-CADENCE-POP-002: Source Consumption Equals Advance Count

Over any measurement window:

```
source_frames_consumed == cadence_advance_count
```

The number of frames popped from the video lookahead buffer MUST equal the number
of ADVANCE decisions made by the cadence accumulator.

**Rationale:** The cadence accumulator is the sole authority for frame consumption
rate. If any other code path pops frames, the consumption rate diverges from the
cadence decision rate.

### INV-CADENCE-POP-003: Consumption Ratio Matches FPS Ratio

Over N output ticks with cadence enabled:

```
source_frames_consumed / N ≈ input_fps / output_fps
```

For 24000/1001 → 30000/1001: ratio ≈ 0.8 (4 pops per 5 ticks).

Tolerance: ±0.001 over 1000+ ticks.

**Rationale:** This is the defining property of frame rate conversion. The source
is consumed at the source rate, output ticks occur at the output rate, and the
cadence accumulator bridges the two by inserting repeat frames.

### INV-RESAMPLE-DETERMINISM-001: Time-Based Frame Selection

Frame selection MUST use a deterministic time-domain mapping. For output tick N
with source FPS `in_num/in_den` and output FPS `out_num/out_den`:

```
source_frame_index(N) = floor(N × in_num × out_den / (out_num × in_den))
```

The advance-vs-repeat decision is:
- **ADVANCE** when `source_frame_index(N) > source_frame_index(N-1)`
- **REPEAT** when `source_frame_index(N) == source_frame_index(N-1)`

This mapping is:
1. **Pure** — depends only on N and the two FPS values; no accumulated state.
2. **Monotonically non-decreasing** — `source_frame_index(N) >= source_frame_index(N-1)`.
3. **Integer-arithmetic only** — 128-bit intermediates, no floating-point.

**Rationale:** A stateless time-mapping produces identical cadence patterns to the
former Bresenham accumulator but eliminates accumulated state that must be carefully
reset across segment and block boundaries. The advance/repeat ratio is mathematically
identical: for 24000/1001 → 30000/1001, `floor(N×4/5)` produces 4 advances per 5
ticks (ratio 0.8), matching the Bresenham accumulator exactly.

**Supersedes:** INV-CADENCE-POP-004 (Bresenham accumulator orientation).

## Observable Behavior

| Metric | Expected |
|--------|----------|
| Advance:Repeat ratio | 4:1 per 5 ticks (24→30) |
| Buffer pops per second | 24 (= source fps) |
| Content playback speed | 1.0× |
| Audio sync | Correct (audio is continuous per tick) |

## Test Strategy

Unit tests verify `SourceFrameForTick()` produces identical advance/repeat
decisions to the former Bresenham accumulator over 100,000+ ticks for all
standard FPS pairs.

See: `pkg/air/tests/contracts/BlockPlan/TimeBasedResamplingContractTests.cpp`
