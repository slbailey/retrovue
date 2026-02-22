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
