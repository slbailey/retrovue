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

### INV-CADENCE-POP-004: Accumulator Orientation

The Bresenham accumulator MUST use:

```
increment = input_fps.num × output_fps.den
threshold = output_fps.num × input_fps.den
```

With `increment < threshold`, the accumulator crosses the threshold on 4 out of
5 ticks (for 24→30), producing the correct ADVANCE:REPEAT ratio.

**Rationale:** Inverting increment and threshold would produce the wrong ratio.
The current orientation is verified correct by the CADENCE_DIAG counters.

## Observable Behavior

| Metric | Correct | Incorrect (current bug) |
|--------|---------|------------------------|
| Advance:Repeat ratio | 4:1 per 5 ticks | 4:1 per 5 ticks (correct) |
| Buffer pops per second | 24 (= source fps) | 30 (= output fps) |
| Content playback speed | 1.0× | 1.25× |
| Audio sync | Correct | Correct (audio is authoritative) |

The accumulator decision ratio is correct. The violation is in enforcement:
the pipeline pops frames on ticks where the accumulator said REPEAT.

## Test Strategy

Tests operate on a deterministic simulation of the cadence accumulator and a
mock video buffer. No FFmpeg, no real-time pacing.

See: `pkg/air/tests/contracts/frame_selection_cadence_contract_tests.cpp`
See: `tests/contracts/test_frame_selection_cadence_contract.py`
