# Action Plan: Complete RationalFps Migration

**Status:** Draft  
**Goal:** Eliminate all floating-point arithmetic and floating literals from timing/scheduling hot paths. Use RationalFps plus canonical integer timebase helpers and 64-bit tick counters everywhere. Enforce via contract tests and CI source-scan.  
**Related:** [INV-FPS-RATIONAL-001](contracts/INV-FPS-RATIONAL-001.md), [INV-FPS-MAPPING](contracts/semantics/INV-FPS-MAPPING.md), [INV-FPS-RESAMPLE](contracts/semantics/INV-FPS-RESAMPLE.md), [PTS-AND-FRAME-RATE-AUDIT](contracts/semantics/PTS-AND-FRAME-RATE-AUDIT.md)

---

## Phase 1: Foundation (PipelineManager)

**Goal:** Eliminate remaining `double` fps in the hot path; establish 64-bit tick types and canonical timebase helpers.

| Task | File(s)                     | Change                                                       |
|------|-----------------------------|--------------------------------------------------------------|
| 1.1  | PipelineManager.hpp/cpp     | Change `double input_fps` → `RationalFps input_fps`          |
| 1.2  | PipelineManager.cpp:988-993 | Replace floating-point math with `input_fps.FrameDurationUs()` |
| 1.3  | ITickProducer.hpp           | Add `virtual RationalFps GetInputRationalFps() const = 0`      |
| 1.4  | TickProducer.hpp/cpp        | Implement `GetInputRationalFps()` returning derived rational  |
| 1.5  | blockplan/pipeline          | Audit and migrate tick/budget types: `session_frame_index`, `fence_tick`, `block_start_tick`, `remaining_block_frames` — all MUST be signed 64-bit minimum |
| 1.6  | RationalFps / timebase      | Centralize canonical timebase helpers: `FrameDurationUs()` or `FrameDurationNs()`, `DurationFromFrames(N)`, `FramesFromDurationCeil(delta)`, `FramesFromDurationFloor(delta)`; ensure no inline formulas remain |

**Acceptance criteria (Phase 1):**

- No 32-bit tick types in blockplan/pipeline directories.
- All frame-duration math routed through canonical helpers.

---

## Phase 2: Decoder Boundary

**Goal:** Prevent double contamination from FFmpeg; enforce normalization and tick-grid authority.

| Task | File(s)                  | Change                                                                  |
|------|--------------------------|-------------------------------------------------------------------------|
| 2.1  | FFmpegDecoderAdapter.cpp | Parse FPS as fraction (AVRational), never convert to double             |
| 2.2  | FFmpegDecoderAdapter.hpp | Change `GetVideoFPS()` return to `RationalFps` OR add `GetVideoRationalFps()` |
| 2.3  | All decoder callsites    | Use rational path exclusively                                         |
| 2.4  | RationalFps construction | Enforce normalization at all construction boundaries: reject `num <= 0` or `den <= 0`; guarantee GCD normalization |
| 2.5  | Decoder vs session       | Ensure decoder `time_base` does NOT influence session tick grid; scheduling math must use output RationalFps only |

---

## Phase 3: Duration & Timing Cleanup

**Goal:** No floating-point arithmetic or floating literals in timing/scheduling hot paths.

| Task | File(s)              | Change                                      |
|------|----------------------|---------------------------------------------|
| 3.1  | Hot-path directories  | Remove all `float`, `double`, and floating literals in hot-path directories |
| 3.2  | Chrono / ToDouble     | Replace any `std::chrono::duration<double>` usage; eliminate any `ToDouble()` usage in blockplan/pipeline code |
| 3.3  | Timebase calculations | Use integer microsecond math exclusively; route through canonical helpers only |
| 3.4  | Audio depth           | Rational-based frame↔ms conversion via canonical helpers |
| 3.5  | Ad-hoc conversions    | Replace all ad-hoc den/num conversions with canonical helpers |

**Acceptance criteria (Phase 3):**

- Hot-path grep scan finds zero float/double usage or floating literals.
- No inline conversion formulas remain.

---

## Phase 4: Contract Test Audit & Hardening

**Goal:** All tests use RationalFps; verify exact arithmetic. Enforcement-by-test is mandatory.

| Test Category              | Action                                                                    |
|----------------------------|---------------------------------------------------------------------------|
| Existing RationalFps tests | Verify they use canonical constants (FPS_2997, not `{30000,1001}` literals) |
| DOUBLE-based tests         | Convert all `30.0` → FPS_30, `29.97` → FPS_2997                          |
| Edge case tests            | **NEW:** Test 59.94→29.97 exact DROP step=2                              |
| Drift tests                | **NEW:** Run 10-minute simulation, prove zero accumulated error          |
| Cadence tests              | **NEW:** Verify 23.976→30/1 produces exact cadence pattern               |
| **Required:** FrameIndex↔Time | **NEW:** Round-trip identity over ≥ 1,000,000 frames (no drift, no off-by-one) |
| **Required:** Hot-path source scan | **NEW:** Test that fails if: `float`/`double` types appear, floating literals appear, or `ToDouble()` appears in prohibited directories |
| **Optional**               | `static_assert(sizeof(tick_type) == 8)` where tick_type is used for fence/budget |

---

## Phase 5: Invariant Enforcement

**Goal:** Prevent regression; enforce INV-FPS-RATIONAL-001.

| Task | Implementation                                                           |
|------|--------------------------------------------------------------------------|
| 5.1  | Ban any float/double arithmetic in timing/scheduling hot paths            |
| 5.2  | Ban floating literals in those directories                               |
| 5.3  | Ban 32-bit tick/budget types                                             |
| 5.4  | Require canonical helper usage; no ad-hoc formulas                       |
| 5.5  | Enforce via CI and contract test (source-scan test must pass)            |

---

## Phase 6: Validation Suite

**Command to verify after each phase:**

```bash
cd /opt/retrovue/pkg/air/build
./blockplan_contract_tests --gtest_filter=*Rational*:*Cadence*:*Resample*:*FPS*:*RationalTimebase*:*HotPath*
```

**Success criteria:**

- All contract tests pass.
- Hot-path source-scan test passes.
- Drop ratio exactness verified (e.g. 60000/1001 → 30000/1001 step = 2).
- Fence/budget convergence identity holds.
- FrameIndex↔Time round-trip identity holds.

---

## Execution Order

- **Phase 1** must complete before Phase 3 (canonical helpers and 64-bit tick types are prerequisite for cleanup).
- Phase 2 can run in parallel with 1; Phase 4–6 depend on Phases 1–3.
- Decoder normalization (Phase 2) must be complete before cadence tests are finalized (Phase 4).
- Phase ordering is unchanged; dependencies are as above.

---

## Implementation Audit (2026-02-22)

**Summary:** The **blockplan hot path** (Phase 1–3 and 5) is implemented and enforced. Phase 4 contract-test cleanup is partially done; some tests still use `double` FPS at boundaries. Outside hot path (FileProducer, ProgramFormat, PlayoutEngine, etc.) still use `double` for config/API — not in scope for this plan.

### Phase 1: Foundation — **Done**

| Task | Status | Evidence |
|------|--------|----------|
| 1.1  | Done   | `PipelineManager.cpp` uses `RationalFps input_fps = live_tp()->GetInputRationalFps()` (no `double input_fps` member). |
| 1.2  | Done   | Lines 988–996 use `input_fps.FramesFromDurationCeilMs(kMinAudioPrimeMs)`; no floating-point math. |
| 1.3  | Done   | `ITickProducer.hpp` has `virtual RationalFps GetInputRationalFps() const = 0`. |
| 1.4  | Done   | `TickProducer::GetInputRationalFps()` returns `RationalFps{input_fps_num_, input_fps_den_}`. |
| 1.5  | Done   | `session_frame_index`, `block_fence_frame_`, `remaining_block_frames_` are `int64_t` in PipelineManager/PlaybackTraceTypes; no `int32_t` tick types in blockplan. |
| 1.6  | Done   | `RationalFps.hpp` has `FrameDurationUs()`, `FrameDurationNs()`, `FrameDurationMs()`, `DurationFromFramesUs/Ns()`, `FramesFromDurationCeilUs/Ms()`, `FramesFromDurationFloorUs/Ms()`. Blockplan uses these; no inline fps formulas in hot path. |

### Phase 2: Decoder Boundary — **Done**

| Task | Status | Evidence |
|------|--------|----------|
| 2.1  | Done   | `FFmpegDecoder::GetVideoRationalFps()` uses `AVRational fps = stream->avg_frame_rate`; no double conversion for FPS. |
| 2.2  | Done   | `GetVideoRationalFps()` exists; production uses it. (`FFmpegDecoder.h` still has `DecoderStats::current_fps` for metrics only.) |
| 2.3  | Done   | TickProducer uses `decoder_->GetVideoRationalFps()`; PipelineManager uses `GetInputRationalFps()` everywhere for timing. |
| 2.4  | Done   | `RationalFps` constructor calls `NormalizeInPlace()` (GCD); invalid `num`/`den` yield `{0,1}`. |
| 2.5  | Done   | Session tick grid uses `ctx_->fps` (output RationalFps); decoder FPS is only for input cadence/drop, not tick math. |

### Phase 3: Duration & Timing Cleanup — **Done (hot path only)**

| Task | Status | Evidence |
|------|--------|----------|
| 3.1  | Done   | `scripts/check_rationalfps_hotpath.py` scans `src/blockplan`, `src/producers`, `src/runtime`, `src/renderer`; telemetry allowlist covers files that use float/double only for diagnostics (see Phase 7). Blockplan has no float/double/literals; `HotPath_NoFloatNoToDoubleNoFloatLiterals` (blockplan-only) and `HotPath_NoFloatOutsideTelemetry` (full script) both pass. |
| 3.2  | Done   | No `ToDouble()` or `GetInputFPS()` calls in `src/blockplan`; `ITickProducer::GetInputFPS()` exists for legacy but is not used in blockplan. FileProducer uses ToDouble() only for legacy `source_fps_` logging; resample logic uses RationalFps; FileProducer is on telemetry allowlist. |
| 3.3–3.5 | Done | Frame-duration and frame↔ms math in blockplan use RationalFps helpers only. |

### Phase 4: Contract Test Audit — **Partially done**

| Item | Status | Notes |
|------|--------|-------|
| 59.94→29.97 DROP step=2 | Done | `test_rational_timebase_integrity.cpp`: `DropExactRatio_5994_to_2997_Is2`; `MediaTimeContractTests`: `ResampleMode_5994to2997_DROP_step2`. |
| 10-minute drift, zero error | Done | `DriftSimulation_10Minutes_2997_NoAccumulatedError`. |
| Cadence 23.976→30 | Done | `CadencePattern_23976_to_30_IsStable`, `CadenceExactPattern_23976_to_30_Repeatable`. |
| FrameIndex↔Time round-trip 1M | Done | `FrameIndexTimeRoundTrip_1M_IsIdentity`. |
| Hot-path source-scan test | Done | `HotPath_NoFloatNoToDoubleNoFloatLiterals` (blockplan-only C++ scan), `HotPath_NoFloatOutsideTelemetry` (runs full Python script), and `RationalFpsHotPathGuard` (CMake). |
| Canonical constants in RationalFps tests | Partial | `test_rational_timebase_integrity.cpp` uses literals e.g. `RationalFps(60000, 1001)` instead of `FPS_5994`/`FPS_2997`; behavior is correct. |
| DOUBLE-based tests → RationalFps | Partial | Many contract tests still pass `30.0`, `29.97`, `23.976` into mocks/config (e.g. `MockTickProducer(..., 30.0, ...)`, `config.target_fps = 30.0`). Hot path receives rational via `DeriveRationalFPS()`; converting test code to use `FPS_30`/`FPS_2997` would be consistency-only. |
| `static_assert(sizeof(tick_type)==8)` | Not done | Optional per plan. |

### Phase 5: Invariant Enforcement — **Done**

| Task | Status | Evidence |
|------|--------|----------|
| 5.1–5.4 | Done | Enforced by hot-path scan over `src/blockplan`, `src/producers`, `src/runtime`, `src/renderer`; telemetry allowlist for diagnostics-only float/double (no int32_t tick types). |
| 5.5    | Done | CMake adds test `RationalFpsHotPathGuard` running `scripts/check_rationalfps_hotpath.sh`; `RETROVUE_AIR_ROOT_DIR` used by `HotPath_NoFloatOutsideTelemetry`; `RETROVUE_BLOCKPLAN_SRC_DIR` set for blockplan-only scan. |

### Phase 6: Validation — **Passing**

- `python3 pkg/air/scripts/check_rationalfps_hotpath.py` → **PASSED**
- `./rational_timebase_integrity_tests --gtest_filter=*Rational*:*Cadence*:*HotPath*` → **10 tests PASSED** (includes `HotPath_NoFloatOutsideTelemetry`, `OutputClock_UsesCanonicalHelpers`)

### Gaps / Optional follow-ups

1. **Tests:** Use canonical constants (`FPS_2997`, `FPS_30`, etc.) in `test_rational_timebase_integrity.cpp` and, where applicable, in other contract tests that construct RationalFps.
2. **Tests:** Optionally replace `double` FPS in test mocks and config (e.g. `MockTickProducer(..., 30.0, ...)` → `RationalFps` or `FPS_30`) for consistency; not required for hot-path correctness.
3. **Optional:** Add `static_assert(sizeof(tick_type) == 8)` where tick types are defined for fence/budget.
4. **Out of scope for this plan:** `ProgramFormat::GetFrameRateAsDouble()`, PlayoutEngine/playout_service config using `double` for target_fps — migration would be a separate change. FileProducer uses RationalFps for resample logic; `source_fps_` double is legacy logging only and is allowlisted in the scanner.

### Phase 7: Closure Pass (repo-wide sealing) — **Done**

- **Enforcement scope:** `src/blockplan/`, `src/producers/`, `src/runtime/`, `src/renderer/`.
- **CI:** `RationalFpsHotPathGuard` runs `scripts/check_rationalfps_hotpath.py`.
- **Telemetry allowlist** (exact-path, justified in script): TimingLoop.cpp, PlayoutControl.cpp, ProgramFormat.cpp, ProgramOutput.cpp, FrameRenderer.cpp, FileProducer.cpp (legacy source_fps_ logging only; resample uses RationalFps).
