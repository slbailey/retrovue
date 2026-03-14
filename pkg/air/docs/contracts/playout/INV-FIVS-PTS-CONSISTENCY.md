# INV-FIVS-PTS-CONSISTENCY: PTS Slope Consistency for Frame-Indexed Video Store

## Classification
| Field | Value |
|-------|-------|
| ID | INV-FIVS-PTS-CONSISTENCY |
| Type | Diagnostic |
| Owner | `PipelineManager` (tick loop) |
| Enforcement | Runtime (C++ emission path — logging only, never blocks playback) |
| Parent | [Frame-Indexed Video Store](frame_indexed_video_store.md) |

---

## Contract — INV-FIVS-PTS-CONSISTENCY

### Purpose

Validate that the PTS (Presentation Time Stamp) delta between consecutive
decoded video frames remains consistent with the established PTS slope for
the current segment.

RetroVue's playout pipeline is driven by deterministic frame scheduling:
the tick loop computes a `source_frame_index` from the wall clock and retrieves
the corresponding frame from the Frame-Indexed Video Store (FIVS). The frame
index is the scheduler's sole truth. PTS is media truth — it originates in
the encoded container and passes through the decoder unmodified.

This invariant detects divergence between consecutive PTS values without
assuming any relationship between frame index and PTS. It works correctly
with cadence resampling, telecine, and variable-frame-rate (VFR) sources.

### Architectural Context

The playout signal path:

```
MasterClock
  → Tick loop (computes selected_src_this_tick)
    → FIVS[source_frame_index]
      → PTS slope check (diagnostic only, on real decodes)
        → Emit frame
```

**Frame index** is the scheduling coordinate. The tick loop requests
frames by index. FIVS stores and retrieves frames by index. No component
in the emission path uses PTS to select, order, or gate frames.

**PTS** is the media coordinate. It is stamped by the encoder, preserved
through demux and decode, and carried on the frame as metadata. PTS is
consumed downstream by the muxer for output stream timing. It is never
consumed by the scheduler.

**Why not `source_frame_index × frame_duration`?** When cadence resampling
is active (e.g. 24fps source → 29.97fps output), `source_frame_index` advances
at the output rate and includes cadence repeats. It is not a decode counter.
Additionally, telecine and VFR sources have actual PTS spacing that differs
from their declared frame rate. A slope-based check avoids both problems
by measuring what the stream actually does rather than what it declares.

### Definitions

| Term | Definition |
|------|------------|
| **source_frame_index** | Monotonic, segment-relative integer assigned to each decoded video frame. The canonical scheduling coordinate. Not suitable for PTS prediction when cadence resampling is active. |
| **PTS** | Presentation Time Stamp. The media-domain timestamp carried on the decoded frame, originating from the container. Units: microseconds. |
| **was_decoded** | Boolean flag on `VideoBufferFrame`. `true` for real decoder output, `false` for cadence repeats and hold-last frames. Only `was_decoded=true` frames participate in slope measurement. |
| **PTS delta** | `pts[n] − pts[n−1]` between consecutive `was_decoded=true` frames. |
| **established delta** | The average PTS delta computed from the first `kSlopeWindow` decoded frames in a segment. This is the expected inter-frame PTS spacing for that segment. |
| **slope window** | The number of initial decoded frames used to establish the PTS delta (currently 24, approximately 1 second of 24fps content). |
| **segment boundary** | A change in `segment_origin_id` on the emitted frame. Indicates a new media source — the established slope is no longer valid. |

### Invariant

For consecutive decoded frames (where `was_decoded=true`) within a segment,
after the slope window has been established:

```
established_delta = average(pts[i] − pts[i−1]) for i in 1..kSlopeWindow

For each subsequent decoded frame:
  actual_delta = pts[n] − pts[n−1]
  |actual_delta − established_delta| ≤ 0.5 × established_delta
```

If this condition holds, the PTS progression is consistent with the
established slope for this segment. No action is taken.

If this condition is violated, the frame is still emitted. The engine logs
a `PTS_DRIFT_DETECTED` diagnostic event. Playback is never interrupted.

### Slope Establishment

The first `kSlopeWindow` (24) PTS deltas in a segment are accumulated
without checking. Their average becomes the established delta. This
accommodates:

- **Telecine sources** (23.976fps declared but 29.97fps PTS spacing):
  The slope learns the actual PTS spacing, not the declared frame rate.
- **VFR sources** (variable frame rate): The average absorbs minor
  frame-to-frame variation during the establishment window.
- **Non-integer frame rates** (29.97fps, 23.976fps): No rounding error
  accumulates because the check is delta-based, not index-multiplicative.

### Tolerance Rule

The tolerance band is **± 0.5 × established_delta**.

This means a PTS delta can vary by up to 50% from the established slope
before triggering a diagnostic. This accommodates:

- **B-frame reordering jitter.** H.264/H.265 B-frame decode-order PTS
  may jitter by a fraction of a frame period relative to display order.
- **Container packetization variance.** MKV and TS containers may round
  or truncate PTS at packet boundaries.
- **Cadence pattern variation.** In 3:2 pulldown or similar cadence
  patterns, consecutive decoded frames may have slightly uneven PTS
  spacing even though the average is stable.

Drift beyond 50% of the established slope means consecutive PTS values
disagree by more than normal variation can explain. At that point,
something upstream is genuinely wrong: a timestamp discontinuity, a
corrupt packet, or a decoder state error.

### Segment Boundary Reset

When `segment_origin_id` changes on a decoded frame, all slope state
is reset:

- `pts_drift_prev_pts_us_` → -1
- `pts_drift_established_delta_us_` → -1
- `pts_drift_slope_sum_us_` → 0
- `pts_drift_slope_count_` → 0

Each segment establishes its own slope independently. This is necessary
because consecutive segments may come from different media files with
different frame rates, different PTS epochs, or different encoding
characteristics. Carrying slope state across a segment boundary would
produce false positives.

### Cadence Repeat Filtering

Only frames with `was_decoded=true` participate in slope measurement.
Cadence repeats (`was_decoded=false`) are emitted at the output frame
rate (e.g. 29.97fps) and carry the same PTS as the preceding decoded
frame. Including them in the slope calculation would corrupt the delta
measurement.

This means the PTS slope check operates at the source decode rate
(e.g. 24fps), not the output display rate (e.g. 29.97fps). The slope
reflects the actual media cadence, not the output cadence.

### Rate Limiting

`PTS_DRIFT_DETECTED` is logged at most once per 30 output ticks
(approximately 1 second at 29.97fps) to avoid log flooding on
persistently drifting streams.

### Scheduler Relationship

The scheduler is frame-index driven. This invariant does not change that.

- The tick loop computes `selected_src_this_tick` from the wall clock
  and schedule. This computation does not reference PTS.
- FIVS lookup is keyed by `source_frame_index`. PTS is not used for
  storage, retrieval, or eviction.
- The PTS slope check occurs **after** the frame has been selected
  for emission. It is a post-hoc validation, not a selection criterion.

If PTS drift is detected, the scheduler does not change its behavior.
It does not skip frames, seek, or re-select. The frame that the scheduler
chose is the frame that gets emitted. The diagnostic exists so that
operators and automated monitoring can detect upstream media problems.

### Violation Behavior

When a decoded frame's PTS delta falls outside the tolerance band:

1. The frame is emitted normally. Playback continues without interruption.
2. A `PTS_DRIFT_DETECTED` diagnostic event is logged (subject to rate limit).
3. No corrective action is taken by the engine.

This invariant is **diagnostic only**. It is a canary, not a gate. Its
purpose is to surface problems that would otherwise be invisible until
they manifest as visible playback artifacts (lip sync drift, frame jumps,
or stuttering).

### Non-Goals

This invariant explicitly does NOT:

- **Change scheduler behavior.** The scheduler remains frame-index driven.
  PTS is never used to select, reorder, or skip frames.
- **Change FIVS indexing.** The Frame-Indexed Video Store remains keyed
  by source_frame_index. PTS is not a storage or retrieval key.
- **Halt or pause playback.** A PTS drift detection never blocks frame
  emission. The frame is always emitted regardless of PTS consistency.
- **Correct PTS values.** The engine does not rewrite, adjust, or
  normalize PTS based on this check. PTS passes through unmodified.
- **Assume frame_index × frame_duration.** The check does NOT multiply
  a frame index by a declared frame duration. This was an earlier
  formulation that produced false positives on telecine and VFR sources.
- **Replace existing PTS diagnostics.** INV-FPS-TICK-PTS and other
  existing PTS-related diagnostics remain authoritative for their
  respective concerns.

### Diagnostics

**Event:** `PTS_DRIFT_DETECTED`

**Emitted when:** A decoded frame's PTS delta deviates from the
established slope by more than ±50%.

**Log fields:**

| Field | Description |
|-------|-------------|
| `actual_delta_us` | `pts[n] − pts[n−1]` (microseconds) |
| `established_delta_us` | Average PTS delta from the slope window (microseconds) |
| `deviation_us` | `actual_delta_us − established_delta_us` (signed, microseconds) |
| `prev_pts_us` | PTS of the previous decoded frame (microseconds) |
| `actual_pts_us` | PTS of the current frame (microseconds) |
| `asset_uri` | The source asset, for correlation with media files |

**Rate limiting:** At most once per 30 output ticks (~1 second at 29.97fps).

### Operational Value

This invariant detects three categories of upstream problems:

1. **Broken timestamps.** Files with incorrect or discontinuous PTS
   values — caused by bad encoders, truncated remux operations, or
   container corruption. These files play "fine" in most players (which
   use their own PTS reconstruction) but produce drift in a system that
   trusts source PTS for muxing.

2. **Timestamp discontinuities.** Sudden PTS jumps within a segment —
   caused by edit points in the source container, advertisement splicing
   artifacts, or decoder seek recovery errors. The slope check detects
   these as large deviations from the established cadence.

3. **Decoder state errors.** Situations where the decoder accumulates
   PTS error over long decodes — rounding in rational-to-integer
   conversions, timestamp wrap-around handling, or packet loss recovery
   that shifts PTS relative to the established slope.

In all three cases, the diagnostic gives operators a specific, actionable
signal: which asset, which frames, how much deviation, and the established
baseline. This converts "something looks off" into "asset X has PTS jump
of +83ms at frame N, established cadence was 33ms."

### Explicitly Supported Source Types

| Source type | Why it works |
|-------------|-------------|
| **Constant frame rate (CFR)** | Established delta ≈ `1/fps`. Consistent deltas, no false positives. |
| **Telecine (3:2 pulldown)** | Declared fps may be 23.976 but actual PTS spacing is 29.97fps. Slope learns actual spacing. |
| **Variable frame rate (VFR)** | Slope window averages over initial variation. Only extreme jumps (>50%) trigger diagnostics. |
| **Cadence resampled (24→29.97)** | Only `was_decoded=true` frames are checked. Cadence repeats are invisible to the slope. |

---

## Implementation

**Enforcement:** `PipelineManager.cpp`, FIVS hit path (after `GetByIndex`,
before emission).

**State members** (`PipelineManager.hpp`):
- `pts_drift_last_log_tick_` — session tick of last log (rate limiting)
- `pts_drift_prev_pts_us_` — PTS of previous decoded frame
- `pts_drift_established_delta_us_` — average delta from slope window
- `pts_drift_slope_sum_us_` — running sum during accumulation phase
- `pts_drift_slope_count_` — number of deltas accumulated
- `pts_drift_last_segment_origin_` — last `segment_origin_id` (boundary reset)

---

## Test

- `test_slope_consistent_no_diagnostic`: Sequence of frames with constant
  PTS delta. Verify no PTS_DRIFT_DETECTED after slope establishment.
- `test_slope_deviation_triggers_diagnostic`: Frame with PTS delta >150%
  of established slope. Verify PTS_DRIFT_DETECTED is emitted.
- `test_segment_boundary_resets_slope`: Changing segment_origin_id resets
  slope state. Verify new segment re-establishes its own slope.
- `test_cadence_repeats_excluded`: Only `was_decoded=true` frames contribute
  to slope measurement. Cadence repeats do not corrupt the delta.
- `test_telecine_no_false_positive`: Source with declared 23.976fps but
  actual PTS spacing at 29.97fps. Verify no false drift after slope
  establishment.
- `test_frame_always_emitted_on_drift`: Frame with drifted PTS is still
  returned to the tick loop for emission. Playback is not blocked.
