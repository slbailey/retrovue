# Authority Sweep — Output Tick Cadence and PTS Step

**Goal:** Ensure no code uses input/source FPS for output timing (tick schedule, deadline, PTS step, output duration). Output timing must use session/house RationalFps only (INV-FPS-RESAMPLE, INV-FPS-TICK-PTS, TIMING-AUTHORITY-OVERVIEW).

**Date:** 2026-02-23

---

## 1. Patterns searched

| Pattern | Purpose |
|--------|---------|
| `GetInputFrameDurationUs` / `GetFrameDurationUs` | Producer/input frame duration; must not drive output PTS step |
| `FrameDurationMs()` | Legacy API; must not be used for segment frame counts, proof, or tick schedule |
| `round(1e6/fps)` or `1'000'000.0 / fps` | Forbidden for output tick cadence; use RationalFps.FrameDurationUs() |
| `target_fps.FrameDurationUs()` outside input paths | Input cadence only; output must use session RationalFps |
| `pts += frame_duration_us` / `target_pts = ... + frame_duration_us` | PTS step must be session one-tick duration |

---

## 2. Hit list and verdicts

### GetInputFrameDurationUs / GetFrameDurationUs

| Location | Verdict | Notes |
|---------|--------|--------|
| `FileProducer.h` / `FileProducer.cpp` | **OK** | Definition only; renamed to `GetInputFrameDurationUs()`; no use for output PTS. |
| `DRIFT-REGRESSION-AUDIT-FINDINGS.md` | **OK** | Documentation reference. |

### FrameDurationMs()

| Location | Verdict | Notes |
|----------|--------|--------|
| `PipelineManager.cpp` | **OK** | Uses `ctx_->fps.FramesFromDurationCeilMs()` for segment frame count; comment "no FrameDurationMs()". |
| `OutputClock.cpp` / `RationalFps.hpp` | **OK** | Definition; legacy API; not used for scheduling in hot path. |
| `IOutputClock.hpp` / `OutputClock.hpp` | **OK** | Interface/override. |
| `DeterministicOutputClock.cpp` (test) | **SUSPECT (test)** | Test harness; document that production uses rational. |
| `ContinuousOutputContractTests.cpp` | **OK** | Assert on clock value; test only. |
| Docs (DRIFT, INV-*, ACTION-PLAN) | **OK** | Documentation. |

### round(1e6/fps) / 1'000'000.0 / fps

| Location | Verdict | Notes |
|----------|--------|--------|
| `FrameProducer.cpp` | **OK** | Uses `DeriveRationalFPS(config_.target_fps).FrameDurationUs()`; no round(1e6/fps). |
| `MpegTSOutputSink.cpp` (line 426) | **FIXED** | Was `1'000'000.0 / config_.target_fps` for fallback PTS step and sleep. Now uses `DeriveRationalFPS` / `RationalFps(fps_num, fps_den)` → `FrameDurationUs()`. |
| `TimelineController.h` `FromFps()` | **FIXED** | Was `static_cast<int64_t>(1'000'000.0 / fps)` for `frame_period_us`. Now uses `DeriveRationalFPS(fps).FrameDurationUs()` (FPS_30 fallback). |
| `ProgramOutput.cpp` (556, 611, 882) | **OK (comparison)** | `target_fps = 1'000'000.0 / pad_frame_duration_us_` used for violation detection and sample math; pad_frame_duration_us_ is set from first frame or default. Not used as authority for output tick schedule. |
| `PacingInvariantContractTests.cpp` (82) | **OK (test)** | Test helper to build synthetic frames; not production output path. |
| `FpsResampleTests.cpp` (162, 240, etc.) | **SUSPECT (test)** | Test helpers; document intended rational behavior. |
| `test_inv_fps_resample_drift.cpp` | **OK** | Documents forbidden pattern. |
| Docs | **OK** | Reference only. |

### target_fps.FrameDurationUs() / config_.target_fps (producer/config)

| Location | Verdict | Notes |
|----------|--------|--------|
| `FileProducer.cpp` (121, 2584) | **OK** | Input/stub cadence and `GetInputFrameDurationUs()`; output PTS from TickTimeUs(output_fps_) when resampling. |
| `FileProducer.cpp` (2291, 2579) | **OK** | Stub path PTS and GetNextPTS; frame_interval_us_ is input cadence. |
| `ProgrammaticProducer.cpp` (30, 136) | **OK** | Programmatic producer runs at config FPS; session format typically matches. |
| `BlackFrameProducer.cpp` (51, 226) | **OK** | Fallback producer; format from Configure(ProgramFormat) → session FPS. |
| `FpsResampleTests.cpp` (89) | **OK** | Test; compares to expected input duration. |

### pts += frame_duration_us / target_pts = ... + frame_duration_us

| Location | Verdict | Notes |
|----------|--------|--------|
| `PlayoutControl.cpp` | **OK** | `frame_duration_us` from `session_output_fps_.FrameDurationUs()` (SetSessionOutputFps). |
| `PlayoutEngine.cpp` (1158, 1430) | **OK** | `fps_r` from `DeriveRationalFPS(state->program_format.GetFrameRateAsDouble())` → session. |
| `EncoderPipeline.cpp` (1648) | **OK** | `frame_duration_90k` from encoder time base (session). |
| `MpegTSOutputSink.cpp` (707, 746) | **FIXED** | Was derived from `1'000'000.0 / config_.target_fps`; now uses rational `frame_duration_us` (see above). |
| `ProgramOutput.cpp` (514, 943) | **OK** | Pacing uses `pad_frame_duration_us_` / `pacing_frame_period_us_` set from first frame metadata or default; downstream of pipeline. |
| `TimelineController.cpp` (311, 381, 396) | **OK** | Uses `config_.frame_period_us`; config from `FromFps(session fps)` now rational. |
| `PacingInvariantContractTests.cpp` | **OK (test)** | Synthetic frame PTS for test only. |

---

## 3. Summary

- **Authority:** All output tick cadence and PTS step now use session/house RationalFps (ctx_->fps, session_output_fps_, DeriveRationalFPS(program_format), or config populated from session). No producer FPS or asset metadata FPS used for output timing.
- **Formula:** Remaining fixes in this sweep: MpegTSOutputSink (fallback PTS step and black frame duration) and TimelineConfig::FromFps (CT frame period) now use RationalFps.FrameDurationUs() / FrameDurationSec() instead of 1e6/fps.
- **Tests:** PlayoutControlPtsStepUsesSessionFpsNotProducer locks PlayoutControl; no new contract test added for MpegTSOutputSink or TimelineController (behavior unchanged except exact µs for 29.97 etc.).

---

## 4. References

- [DRIFT-REGRESSION-AUDIT-FINDINGS.md](DRIFT-REGRESSION-AUDIT-FINDINGS.md) — findings table and remediation status
- [INV-FPS-RESAMPLE](semantics/INV-FPS-RESAMPLE.md) — tick grid from rational only
- [INV-FPS-TICK-PTS](semantics/INV-FPS-TICK-PTS.md) — PTS delta = one output tick
- [TIMING-AUTHORITY-OVERVIEW](semantics/TIMING-AUTHORITY-OVERVIEW.md) — output timing exclusive to session rational
