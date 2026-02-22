# Action Plan: Complete RationalFps Migration

**Status:** Draft  
**Goal:** Eliminate `double` FPS from the hot path; use `RationalFps` and integer microsecond math everywhere so frame-rate and duration calculations are exact and reproducible.  
**Related:** [INV-FPS-MAPPING](contracts/semantics/INV-FPS-MAPPING.md), [INV-FPS-RESAMPLE](contracts/semantics/INV-FPS-RESAMPLE.md), [PTS-AND-FRAME-RATE-AUDIT](contracts/semantics/PTS-AND-FRAME-RATE-AUDIT.md)

---

## Phase 1: Foundation (PipelineManager)

**Goal:** Eliminate remaining `double` fps in the hot path.

| Task | File(s)                     | Change                                                       |
|------|-----------------------------|--------------------------------------------------------------|
| 1.1  | PipelineManager.hpp/cpp     | Change `double input_fps` → `RationalFps input_fps`          |
| 1.2  | PipelineManager.cpp:988-993 | Replace floating-point math with `input_fps.FrameDurationUs()` |
| 1.3  | ITickProducer.hpp           | Add `virtual RationalFps GetInputRationalFps() const = 0`      |
| 1.4  | TickProducer.hpp/cpp        | Implement `GetInputRationalFps()` returning derived rational  |

---

## Phase 2: Decoder Boundary

**Goal:** Prevent double contamination from FFmpeg.

| Task | File(s)                  | Change                                                                  |
|------|--------------------------|-------------------------------------------------------------------------|
| 2.1  | FFmpegDecoderAdapter.cpp | Parse FPS as fraction (AVRational), never convert to double             |
| 2.2  | FFmpegDecoderAdapter.hpp | Change `GetVideoFPS()` return to `RationalFps` OR add `GetVideoRationalFps()` |
| 2.3  | All decoder callsites    | Use rational path exclusively                                         |

---

## Phase 3: Duration & Timing Cleanup

**Goal:** No `1.0 / fps` anywhere in codebase.

| Task | File(s)              | Change                                      |
|------|----------------------|---------------------------------------------|
| 3.1  | Global search        | Replace `1.0/fps`, `1000.0/fps` with `RationalFps::FrameDurationUs()` (or equivalent) |
| 3.2  | Timebase calculations| Use integer microsecond math exclusively    |
| 3.3  | Audio depth calculations | Rational-based frame↔ms conversion       |

---

## Phase 4: Contract Test Audit & Hardening

**Goal:** All tests use RationalFps; verify exact arithmetic.

| Test Category              | Action                                                                    |
|----------------------------|---------------------------------------------------------------------------|
| Existing RationalFps tests | Verify they use canonical constants (FPS_2997, not `{30000,1001}` literals) |
| DOUBLE-based tests         | Convert all `30.0` → FPS_30, `29.97` → FPS_2997                          |
| Edge case tests            | **NEW:** Test 59.94→29.97 exact DROP step=2                              |
| Drift tests                | **NEW:** Run 10-minute simulation, prove zero accumulated error          |
| Cadence tests              | **NEW:** Verify 23.976→30/1 produces exact cadence pattern               |

---

## Phase 5: Invariant Enforcement

**Goal:** Prevent regression.

| Task | Implementation                                                           |
|------|--------------------------------------------------------------------------|
| 5.1  | Code review check: no `double` fps parameters in new code                |
| 5.2  | Static analysis: flag `1.0 / variable` in pipeline directories           |
| 5.3  | RationalFps constructor from double marked `explicit` with Doxygen warning |

---

## Phase 6: Validation Suite

**Command to verify after each phase:**

```bash
cd /opt/retrovue/pkg/air/build
./blockplan_contract_tests --gtest_filter=*Rational*:*Cadence*:*Resample*:*FPS*
```

**Success criteria:**

- All tests pass.
- No `grep -r "double.*fps\|1\.0 /" pkg/air/src/blockplan/` hits (except legacy wrappers).
- Drop step for 60000/1001 → 30000/1001 computed as exactly **2** after 10,000 frames.

---

## Execution Order

- **Phase 1** hits the current pain point (PipelineManager still on doubles); recommended to start here.
- Phases can be delegated as independent sub-tasks; Phase 2 depends on 1, Phase 3 can run in parallel with 2, Phase 4–6 follow after 1–3.
