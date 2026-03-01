# Test Matrix: AIR Media Time & FPS Resample Invariants

**Scope:** Deterministic validation of FPS detection, resample mode selection, PTS drift prevention, and VFR file handling in the AIR playout engine.

**Authoritative inputs:**
- `docs/contracts/laws/LAW-LIVENESS.md`
- `docs/contracts/invariants/air/INV-VFR-DROP-GUARD-001.md`

**Test framework:** Google Test (GTest). All contract tests are C++.

**Test executable:** `mediatime_contract_tests` (defined in `pkg/air/CMakeLists.txt`)

**Run command:** `ctest --test-dir pkg/air/build -R MediaTimeContracts --output-on-failure`

---

## 1. INV-VFR-DROP-GUARD-001

**Test file:** `pkg/air/tests/contracts/BlockPlan/MediaTimeContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| VfrFile_MustNotEnterDropMode | FakeVfrDecoder reports 30000/1001 (avg_frame_rate after VFR guard snaps 28.6fps); output at 30000/1001 | ResampleMode MUST NOT be DROP; drop_step MUST be 1; 100 frames decode without premature EOF |

**Bug scenario (before fix):**
1. VFR HEVC file: `r_frame_rate` = 60000/1001, actual 1863 frames in 65 seconds (avg ~28.6fps).
2. `GetVideoRationalFps()` returns 60000/1001 from `r_frame_rate`.
3. `UpdateResampleMode()` sees 60/30 = 2 → DROP mode, `drop_step_ = 2`.
4. DROP mode consumes 2 input frames per output frame → all 1863 frames exhausted in ~931 output frames (~31s).
5. Audio from those decodes covers full 65 seconds → 34 seconds excess in `AudioLookaheadBuffer`.
6. Video decoder hits EOF at ~31s → `content_gap` (hold-last/black) while real audio continues.

**Fix:**
`FFmpegDecoder::GetVideoRationalFps()` compares `r_frame_rate` and `avg_frame_rate`. When divergence exceeds 10%, uses `avg_frame_rate` (snapped to standard broadcast rate). For the Popeye file: avg 28.6fps → snapped to 30000/1001 → matches output fps → OFF mode (no frame dropping).

---

## 2. INV-FPS-RESAMPLE (Drift Prevention)

**Test file:** `pkg/air/tests/contracts/test_inv_fps_resample_drift.cpp`

| Test | Scenario | Expected |
|---|---|---|
| LongRun100kTicksNoDrift | 100,000 ticks at 30000/1001 | Zero cumulative drift; PTS delta exactly one output tick per frame |
| ProofFramesUseRationalNotMs | 1000ms at 29.97fps | Rational formula (30 frames) differs from ms-based (31 frames) |
| ProofFramesRationalFormulaMatchesFence | 1000ms at 30fps | Rational frame count matches fence formula |

## 3. INV-FPS-MAPPING / INV-FPS-TICK-PTS (DROP Mode Correctness)

**Test file:** `pkg/air/tests/contracts/BlockPlan/MediaTimeContractTests.cpp`

| Test | Scenario | Expected |
|---|---|---|
| ResampleMode_60to30_DROP_step2 | Input 60fps, output 30fps | DROP mode, drop_step=2 |
| ResampleMode_30to30_OFF | Input 30fps, output 30fps | OFF mode |
| ResampleMode_23976to30_CADENCE | Input 23.976fps, output 30fps | CADENCE mode |
| TickProducer_DROP_SetsOutputDuration_ToOutputTick | Fake 60fps decoder, output 30fps | Frame duration = 1/30s (not 1/60s) |
| TickProducer_DROP_OutputPTS_AdvancesByTickDuration | Fake 60fps decoder, 10 ticks | PTS delta = one output tick (not 1/60s) |
