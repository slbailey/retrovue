# Drift Regression Audit — Forbidden Time Math

**Goal:** Ensure no code path computes tick timing, PTS, duration, fences, seams, or deadlines using integer ms, rounded µs, float fps, or 1/fps approximations.

**Scope:** Output scheduling and presentation timing paths only. Decode PTS from FFmpeg is ignored unless used to compute output PTS or tick deadlines.

**Date:** 2026-02-23

---

## 1. Files that compute time deltas (by category)

### Tick schedule / deadlines

| File | What it computes | Uses rational fps_num/fps_den? |
|------|-------------------|--------------------------------|
| `PipelineManager.cpp` | Block fence tick: `compute_fence_frame` | **Yes** — `(delta_ms * fps_num + fps_den*1000 - 1) / (fps_den*1000)` |
| `PipelineManager.cpp` | Segment seam frames: `ComputeSegmentSeamFrames` | **Yes** — `block_activation_frame_ + (ct_ms * fps_num + denom - 1) / denom` |
| `OutputClock.cpp` | Deadline offset for tick N | **Yes** — `fps_.DurationFromFramesNs(session_frame_index)` |
| `TickProducer.cpp` | Block CT: `CtMs(k)`, `CtUs(k)` | **Yes** — `(k * 1000 * fps_den) / fps_num` |
| `FileProducer.cpp` | Tick time: `TickTimeUs(n)` | **Yes** — RationalFps-based (DurationFromFramesUs) |
| `PlayoutEngine.cpp` | Legacy AlignPTS: `target_next_pts = last_emitted_pts + frame_period_us` | **Yes** — `fps_r.FrameDurationUs()` from `DeriveRationalFPS(GetFrameRateAsDouble())` (double source, then rational) |
| `PlayoutControl.cpp` | Seamless switch: `target_pts = last_live_pts + frame_duration_us` | **Yes** — `session_output_fps_.FrameDurationUs()` (SetSessionOutputFps at StartChannel); fallback FPS_30 |

### PTS and duration

| File | What it computes | Uses rational fps_num/fps_den? |
|------|-------------------|--------------------------------|
| `TickProducer.cpp` | Output PTS for returned frame (DROP path) | **Yes** — `tick_pts_us` from tick grid |
| `FileProducer.cpp` | Output PTS in resample path | **Yes** — `next_output_tick_us_ = TickTimeUs(tick_index_)` |
| `OutputClock.cpp` | `FrameIndexToPts90k` | **Yes** — `session_frame_index * frame_duration_90k_` (90k from rational with round in ctor) |
| `PipelineManager.cpp` | Video PTS to encoder | **Yes** — `clock->FrameIndexToPts90k(session_frame_index)` |
| `PlaybackTraceTypes.hpp` | `BuildIntent` expected_frames | **No** — see violations |

### Fences / seams

| File | What it computes | Uses rational fps_num/fps_den? |
|------|-------------------|--------------------------------|
| `PipelineManager.cpp` | Block fence tick | **Yes** — rational formula (see above) |
| `PipelineManager.cpp` | Segment seam frames | **Yes** — rational from boundaries |
| `PipelineManager.cpp` | Segment **frame count** for `block_acc.BeginSegment` (proof) | **No** — uses `ceil(seg_duration_ms / FrameDurationMs())` |

---

## 2. Invariant mapping (INV-*)

| INV | Scope |
|-----|--------|
| **INV-FPS-RESAMPLE** | Output tick grid and block CT from rational only; no round(1e6/fps) or int(1000/fps) accumulation. |
| **INV-FPS-TICK-PTS** | Output video PTS advances by exactly one output tick per frame; PTS owned by tick grid. |
| **INV-TICK-DEADLINE-DISCIPLINE-001** | Tick deadlines from epoch + rational FPS; no slip; late tick still emits fallback. |
| **INV-BLOCK-WALLCLOCK-FENCE-001** | Fence tick = ceil(delta_ms * fps_num / (fps_den * 1000)); forbidden: ceil(delta_ms / round(1000/fps)). |

---

## 3. Findings table (OK vs suspect vs violation)

| # | File | Line(s) | Context | Verdict | INV / notes |
|---|------|--------|---------|---------|-------------|
| 1 | `PipelineManager.cpp` | 943–945, 1873–1876, 2122–2124, 2633–2636 | `seg_frames = (seg0.segment_duration_ms + frame_ms - 1) / frame_ms` with `frame_ms = clock->FrameDurationMs()` for `block_acc.BeginSegment` | **VIOLATION** | INV-BLOCK-WALLCLOCK-FENCE-001 (forbidden shape ceil(delta_ms / frame_duration_ms)); segment proof uses ms-quantized frame count |
| 2 | `PipelineManager.cpp` | 1184–1186, 1479–1481 | `headroom_ms = (block_fence_frame_ - session_frame_index) * clock->FrameDurationMs()` | **SUSPECT** | Informational / preload; value is (ticks × truncated ms). No direct scheduling, but time-remaining is ms-derived |
| 3 | `PipelineManager.cpp` | 1493–1496 | `degraded_elapsed_ms = (session_frame_index - degraded_entered_frame_index_) * clock->FrameDurationMs()`; compared to `kDegradedHoldMaxMs` for escalation | **SUSPECT** | Decision (when to escalate to standby) uses truncated frame_duration_ms; at 60fps, 60×16ms = 960ms vs 1000ms |
| 4 | `PipelineManager.cpp` | 1691–1693 | `BuildPlaybackProof(outgoing_block, summary, clock->FrameDurationMs(), ...)` | **VIOLATION** | Proof/intent built with frame_duration_ms → BuildIntent uses RationalFps(1000, frame_duration_ms) → wrong rational for 29.97 (33ms → 1000/33 ≠ 30000/1001) |
| 5 | `PlaybackTraceTypes.hpp` | 353–361 | `BuildIntent(block, frame_duration_ms)`: `RationalFps(1000, frame_duration_ms)`, `expected_frames = block_fps.FramesFromDurationCeilMs(...)` | **VIOLATION** | INV-FPS-RESAMPLE / fence discipline; expected_frames derived from ms-quantized rational |
| 6 | `PlayoutControl.cpp` | (remediated) | PTS step: `frame_duration_us = session_output_fps_.IsValid() ? session_output_fps_.FrameDurationUs() : FPS_30.FrameDurationUs()` | **OK** | INV-FPS-TICK-PTS, INV-FPS-RESAMPLE; authority is session/house RationalFps via SetSessionOutputFps (PlayoutEngine at StartChannel); never producer FPS |
| 7 | `OutputClock.hpp` / `RationalFps.hpp` | 43, 59–61 | `frame_duration_ms_` = `fps_.FrameDurationMs()` = `(1000*den)/num` (truncation) | **SUSPECT** | Stored for legacy APIs; any use for scheduling is suspect. RationalFps uses integer division (truncation), not round |
| 8 | `OutputClock.cpp` | 17–18 | `frame_duration_90k_ = ((90000*den) + (num/2)) / num` (rounded) | **OK** | Used for PTS90k; rounding one value is acceptable if deadlines use DurationFromFramesNs; see DeterministicOutputClock for test drift risk |
| 9 | `playout_service.cpp` | 975–976 | `asset_start_frame = round(seg.asset_start_offset_ms * fps.ToDouble() / 1000.0)` | **SUSPECT** | Evidence field; double fps and round; could affect analytics, not tick scheduling |
| 10 | `ProgramOutput.cpp` | 611–614 | Pad audio: `fps = 1e6 / pad_frame_duration_us_`, `exact_samples = sample_rate/fps + remainder`, `samples = floor(exact_samples)` | **SUSPECT** | Double fps and float remainder for sample count; long-run float accumulation possible |
| 11 | `FrameProducer.cpp` | 68–76 | (remediated) | **OK** | `frame_interval_us_` from `DeriveRationalFPS(config_.target_fps).FrameDurationUs()`; no round(1e6/fps). |
| 11b | `MpegTSOutputSink.cpp` | (remediated) | Fallback PTS step and sleep: was `1'000'000.0 / config_.target_fps` | **OK** | Now `RationalFps` (fps_num/fps_den or DeriveRationalFPS(target_fps)).FrameDurationUs(); black frame duration = FrameDurationSec(). |
| 11c | `TimelineController.h` | FromFps() | `frame_period_us = static_cast<int64_t>(1'000'000.0 / fps)` | **OK** | Now `DeriveRationalFPS(fps).FrameDurationUs()` (FPS_30 fallback). |
| 12 | `PlayoutEngine.cpp` | 1153–1155 | `DeriveRationalFPS(state->program_format.GetFrameRateAsDouble())`, then `frame_period_us = fps_r.FrameDurationUs()` | **SUSPECT** | Double as source; if format is stored rational-only per INV-FPS-RATIONAL-001, this is a conversion boundary |
| 13 | `TickProducer.cpp` | 80–82, 610–621 | `duration_ms = block.end_utc_ms - block.start_utc_ms`; `frames_per_block_` = rational formula. Fade uses `seg.transition_in_duration_ms` for alpha only | **OK** | frames_per_block is rational; fade duration is Core-supplied ms for effect, not tick grid |
| 14 | `VideoLookaheadBuffer.cpp` | 132 | Log: `tick_duration_ms = (1000 * output_fps_.den / output_fps_.num)` | **OK** | Logging only; integer division |
| 15 | `FileProducer.cpp` | 2291, 2579 | Stub: `base_pts = pts_counter * frame_interval_us_`; GetNextPTS: `next_pts + frame_interval_us_` | **OK** (production path) | FileProducer sets frame_interval_us_ from config.target_fps.FrameDurationUs() (rational). Stub path in FileProducer uses same; FrameProducer (separate stub) is violation #11 |
| 16 | `BlockPlanSessionTypes.hpp` | 100–119 | `DeriveRationalFPS(double fps)` | **OK** | Conversion double→rational for legacy/config; not used for accumulation |
| 17 | `DeterministicOutputClock.cpp` (test) | 20–26 | `frame_duration_ms_ = round(1000*fps_den/fps_num)`, `frame_duration_90k_ = round(90000*...)` | **SUSPECT (test)** | Test harness; if tests assert on expected_frames or segment counts using this clock, they reinforce ms-derived formulas |
| 18 | `FpsResampleTests.cpp` | 162, 240, 247, 290 | `tick_us = round(1e6/30)`, etc. | **SUSPECT (test)** | Test helpers; document intended rational behavior |
| 19 | `MediaTimeContractTests.cpp` | 150, 179, 196–206, etc. | `input_frame_duration_ms = llround(1000/input_fps)`, OldFramesPerBlock with ceil(duration_ms/frame_duration_ms) | **OK** | Tests explicitly compare OLD (forbidden) vs exact formula; enforce correct behavior |

---

## 4. Summary by invariant

- **INV-FPS-RESAMPLE:** Violations: PipelineManager segment frame count (proof), BuildIntent/BuildPlaybackProof (frame_duration_ms → rational), FrameProducer round(1e6/fps). Remediated: PlayoutControl uses session_output_fps_.FrameDurationUs() (SetSessionOutputFps). Suspects: OutputClock/RationalFps truncated ms when used for segment_frames or proof; test DeterministicOutputClock.
- **INV-FPS-TICK-PTS:** Remediated: PlayoutControl PTS step uses session/house RationalFps only (SetSessionOutputFps at StartChannel).
- **INV-TICK-DEADLINE-DISCIPLINE-001:** Fence computation itself is rational (OK). Segment proof and degraded escalation use ms-derived values (suspect/violation as above).
- **INV-BLOCK-WALLCLOCK-FENCE-001:** Violation: same as INV-FPS-RESAMPLE for segment frame count formula `ceil(seg_duration_ms / FrameDurationMs())` (forbidden shape).

---

## 5. Silent drift risks (accumulation over hours)

| Location | Risk |
|---------|------|
| Segment proof frame count (PipelineManager) | `seg_frames = ceil(seg_duration_ms / 33)` for 30fps over many segments can overcount frames vs rational ceiling; proof verdict and segment boundaries may diverge slightly over many blocks. |
| BuildIntent expected_frames | For 29.97fps, 1000/33 ≠ 30000/1001; expected_frames for a block can be off by one or more over long duration; proof false negatives/positives. |
| degraded_elapsed_ms | Truncated frame_duration_ms (e.g. 16ms at 60fps) means escalation to standby can trigger up to ~40ms early per second at 60fps; bounded, not unbounded drift. |
| FrameProducer stub | PTS = index × round(1e6/fps) accumulates ~0.5µs per frame at 30fps; over 24h (≈2.6M frames) ≈ 1.3s drift. |
| ProgramOutput pad audio remainder | Float remainder accumulation for samples per frame could cause slow phase drift vs rational; magnitude depends on pad duration. |
| DeterministicOutputClock (tests) | Tests using FrameDurationMs() for expected counts can hide production drift if production fixes rational path but tests still use rounded ms. |

---

## 6. Remediation status (post-drift fix)

| Step | Status | Implementation |
|------|--------|----------------|
| 1. Segment proof frame count | **Done** | PipelineManager uses `ctx_->fps.FramesFromDurationCeilMs(seg.segment_duration_ms)` for all `BeginSegment` and proof paths. |
| 2. BuildIntent/BuildPlaybackProof | **Done** | Signatures take `RationalFps session_fps`; `expected_frames = session_fps.FramesFromDurationCeilMs(expected_duration_ms)`. No frame_duration_ms. |
| 3. PlayoutControl | **Done** | PTS step from session/house FPS only: `SetSessionOutputFps()` set by PlayoutEngine at StartChannel; `frame_duration_us = session_output_fps_.FrameDurationUs()` or `FPS_30.FrameDurationUs()` fallback. `FileProducer::GetFrameDurationUs()` removed from this path; renamed to `GetInputFrameDurationUs()` (input cadence only; never output tick cadence). |
| 4. FrameProducer | **Done** | `frame_interval_us_` from `DeriveRationalFPS(config_.target_fps).FrameDurationUs()`; no `round(1e6/fps)`. |
| 5. headroom_ms / degraded_elapsed_ms | **Done** | PipelineManager uses `(delta_frames * 1000 * ctx_->fps.den) / ctx_->fps.num` for headroom and degraded_elapsed_ms. |
| 6. Tests | **Done** | Contract tests use rational (e.g. `test_inv_fps_resample_drift.cpp`, PlaybackTrace/segment proof tests pass `RationalFps`). |
| 7. MpegTSOutputSink | **Done** | Fallback PTS step and black frame duration: one-tick from `RationalFps` (fps_num/fps_den when set, else `DeriveRationalFPS(config_.target_fps)`); no `1'000'000.0 / config_.target_fps`. See [AUTHORITY-SWEEP-FPS-AUDIT.md](AUTHORITY-SWEEP-FPS-AUDIT.md). |
| 8. TimelineConfig::FromFps | **Done** | `frame_period_us` from `DeriveRationalFPS(fps).FrameDurationUs()` (FPS_30 fallback); no `1'000'000.0 / fps`. CT cadence is rational-exact. |

Legacy `FrameDurationMs()` remains on IOutputClock for compatibility; it must not be used for segment frame counts, proof intent, or tick scheduling.

