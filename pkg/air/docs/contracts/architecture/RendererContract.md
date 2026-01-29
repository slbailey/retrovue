# Renderer Contract

_Related: [Playout Engine Contract](PlayoutEngineContract.md) · [Phase 6A Overview](../phases/Phase6A-Overview.md) · [Metrics Contract](MetricsAndTimingContract.md)_

**Applies starting in:** Phase 7+ (Renderer placement and frame-to-TS path)  
**Status:** Deferred (Applies Phase 7+); Enforced when Renderer is in scope

**Principle:** Air must be correct before it is fast. Performance guarantees are explicitly deferred until correctness is contractually proven.

## Phase 6A Deferral

**This contract is not enforced during Phase 6A.** Phase 6A explicitly defers:

- **Renderer placement** — where decoded frames become output (inside Air vs separate Renderer)
- **Frame-to-TS path** — real MPEG-TS serving and tune-in

During 6A.0–6A.3, execution is validated without requiring a Renderer: control surface, producer lifecycle, minimal FileBackedProducer (e.g. null sink or test file), and ProgrammaticProducer. All guarantees below are **preserved** as institutional knowledge and **future intent**; they apply when the Renderer component is implemented and placed (e.g. Phase 7). Nothing in this document is deleted — only scoped to post-6A enforcement.

---

## Purpose

Define the observable guarantees for the **Renderer** subsystem — the component that consumes decoded frames and produces output. This contract specifies **what** the renderer guarantees, not how it is implemented. Output responsibility is an intentional design boundary: either Air outputs MPEG-TS directly, or Air outputs frames to a Renderer that muxes MPEG-TS; deployments fix one path.

---

## Renderer Modes

### Headless Mode

**Purpose:** Consume frames without visual output.

**Use cases:** Server deployments, automated testing, performance benchmarking.

**Observable behavior:**
- Frames consumed at configured rate
- No display dependencies required
- Telemetry metrics emitted

---

### Preview Mode

**Purpose:** Display frames in a debug window.

**Use cases:** Development, visual validation, real-time monitoring.

**Observable behavior:**
- Window displays decoded frames
- Statistics overlay (FPS, buffer depth, timing)
- Window can be resized/closed
- Falls back to headless if display unavailable

---

## Functional Guarantees

### REN-010: Frame Consumption Timing

**Guarantee:** Frames are consumed at their scheduled PTS time.

**Observable behavior:**
- Frames with `PTS ≤ current_time` are consumed immediately
- Frames with `PTS > current_time` wait until scheduled time
- Frame delivery timing matches PTS within ±2ms

**Verification:** Query metrics for timing deviation; verify within tolerance.

---

### REN-011: Frame Rate

**Guarantee:** Renderer maintains target frame rate.

**Observable behavior:**
- Headless mode: ≥ 30 fps sustained
- Metric `renderer_fps` reflects actual consumption rate
- No busy-waiting when waiting for next frame

---

### REN-020: Empty Buffer Handling

**Guarantee:** Empty buffer is handled gracefully.

**Observable behavior:**
- Frame request returns "no frame available" (not a crash)
- `renderer_underrun_total` metric increments
- Renderer continues polling until frames available
- CPU usage remains low during underrun

---

### REN-021: Buffer Underrun Recovery

**Guarantee:** Renderer recovers automatically when buffer refills.

**Observable behavior:**
- Normal consumption resumes when frames available
- No manual intervention required
- Recovery logged and reflected in metrics

---

### REN-030: Mode Transition

**Guarantee:** Switching between headless and preview modes is seamless.

**Observable behavior:**
- Switch to preview: window opens within 500ms
- Switch to headless: window closes within 200ms
- No frames dropped during transition
- Continuous frame consumption maintained

---

### REN-031: Preview Fallback

**Guarantee:** Preview mode fails gracefully if display unavailable.

**Observable behavior:**
- Falls back to headless mode
- Warning logged
- `renderer_preview_available` metric = 0
- Frame consumption continues normally

---

### REN-040: PTS Monotonicity

**Guarantee:** Non-monotonic PTS is detected and handled.

**Observable behavior:**
- PTS violation logged
- `renderer_pts_violation_total` metric increments
- Frame may be skipped
- Renderer does not crash
- Subsequent frames processed normally

---

### REN-041: Dimension Consistency

**Guarantee:** Frame dimension changes are detected.

**Observable behavior:**
- Dimension mismatch logged
- `renderer_dimension_mismatch_total` metric increments
- Mismatched frame may be skipped
- Renderer does not crash

---

### REN-050: Graceful Shutdown

**Guarantee:** Shutdown completes cleanly.

**Observable behavior:**
- Shutdown completes within 200ms
- All resources released (no leaks)
- Preview window closed (if active)
- Final metrics snapshot emitted

---

### REN-051: Shutdown During Underrun

**Guarantee:** Shutdown works even when waiting for frames.

**Observable behavior:**
- Shutdown interrupts wait immediately
- Completes within 100ms
- No hang or deadlock

---

## Telemetry

### Required Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `retrovue_renderer_frames_rendered_total{channel}` | Counter | Total frames consumed |
| `retrovue_renderer_fps{channel}` | Gauge | Current frame rate |
| `retrovue_renderer_frame_delay_ms{channel}` | Gauge | Timing deviation |
| `retrovue_renderer_underrun_total{channel}` | Counter | Buffer underrun events |
| `retrovue_renderer_invalid_frame_total{channel}` | Counter | Invalid frames skipped |
| `retrovue_renderer_pts_violation_total{channel}` | Counter | PTS violations |
| `retrovue_renderer_dimension_mismatch_total{channel}` | Counter | Dimension mismatches |
| `retrovue_renderer_preview_active{channel}` | Gauge | Preview mode enabled (0/1) |
| `retrovue_renderer_preview_available` | Gauge | Display available (0/1) |

---

### Metric Guarantees

- **REN-TEL-001:** All metrics include `channel` label
- **REN-TEL-002:** Counters never decrease
- **REN-TEL-003:** Metrics updated in real-time (not batched)

---

## Performance Targets

### Throughput

| Metric | Target |
|--------|--------|
| Frame rate (headless) | ≥ 30 fps sustained |
| Frame rate (preview) | ≥ 30 fps sustained |

### Latency

| Metric | Target |
|--------|--------|
| Frame consumption (p95) | ≤ 16ms |
| Mode switch (to preview) | ≤ 500ms |
| Mode switch (to headless) | ≤ 200ms |
| Shutdown | ≤ 200ms |

### Jitter

| Metric | Target |
|--------|--------|
| Frame interval std dev | ≤ 2 frames over 60s |

### Overhead

| Metric | Target |
|--------|--------|
| Preview vs headless CPU | ≤ 20% increase |

---

## Error Handling

### REN-ERR-001: Invalid Frame Data

**Trigger:** Frame data is null or corrupted.

**Observable behavior:**
- Frame skipped
- `renderer_invalid_frame_total` increments
- Error logged
- Renderer continues normally

---

### REN-ERR-002: Display Initialization Failure

**Trigger:** SDL2/display subsystem fails to initialize.

**Observable behavior:**
- Falls back to headless mode
- Warning logged
- `renderer_preview_available` = 0
- Frame consumption continues

---

### REN-ERR-003: Window Close Event

**Trigger:** User closes preview window via OS controls.

**Observable behavior:**
- Transitions to headless mode
- `renderer_window_closed_by_user_total` increments
- Frame consumption continues
- Info logged

---

### REN-ERR-004: Clock Error

**Trigger:** MasterClock returns invalid time.

**Observable behavior:**
- `renderer_clock_error_total` increments
- Falls back to system time for that frame
- Renderer continues
- Error logged

---

## Seamless Switching Behavior

### REN-SWITCH-001: Continuity During Producer Switch

**Guarantee:** Renderer continues consuming frames seamlessly during content switches.

**Observable behavior:**
- No gap in frame consumption
- No visual discontinuity
- PTS remains continuous
- No frames dropped
- Buffer is not cleared during switch

---

## Behavioral Rules Summary

| Rule | Guarantee |
|------|-----------|
| REN-010 | Frames consumed at PTS time |
| REN-011 | Target frame rate maintained |
| REN-020 | Empty buffer handled gracefully |
| REN-021 | Automatic recovery from underrun |
| REN-030 | Seamless mode transitions |
| REN-031 | Preview fallback to headless |
| REN-040 | PTS violations detected and logged |
| REN-041 | Dimension mismatches detected |
| REN-050 | Shutdown within 200ms |
| REN-051 | Shutdown works during underrun |
| REN-SWITCH-001 | Continuity during producer switch |

---

## Test Coverage

| Rule | Test |
|------|------|
| REN-010, REN-011 | `test_renderer_timing` |
| REN-020, REN-021 | `test_renderer_underrun` |
| REN-030, REN-031 | `test_renderer_mode_switch` |
| REN-040, REN-041 | `test_renderer_validation` |
| REN-050, REN-051 | `test_renderer_shutdown` |
| REN-SWITCH-001 | `test_renderer_seamless_switch` |
| REN-ERR-* | `test_renderer_error_handling` |
| REN-TEL-* | `test_renderer_metrics` |

---

## See Also

- [Playout Engine Contract](PlayoutEngineContract.md) — control plane
- [Phase 6A Overview](../phases/Phase6A-Overview.md) — deferral of Renderer placement
- [Metrics Contract](MetricsAndTimingContract.md) — telemetry details
