# Fast deterministic contract mode (AIR)

Contract tests under `pkg/air/tests/contracts/` can run in **fast deterministic mode** so CI and local runs finish in minutes instead of 15–30+ minutes.

## Build options

| Option | Default | Effect |
|--------|---------|--------|
| **RETROVUE_FAST_TEST** | ON | Short block durations (500 ms), short boot guard (2.5 s), `DeterministicTimeSource`. Tests use `AdvanceUntilFence` / `FenceTickAt30fps` instead of fixed `SleepMs` where possible. |
| **RETROVUE_SOAK_TESTS** | OFF | When ON, adds CTest target `BlockPlanSlowContracts` (label `soak`) for long-running `*SLOW_*` tests. **Nightly only; excluded from CI.** |

Recommended for CI and local dev:

```bash
cmake -S pkg/air -B pkg/air/build \
  -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DRETROVUE_FAST_TEST=1
# Do not set RETROVUE_SOAK_TESTS=1 in CI.
```

## Test clock / tick harness

- **Fence-based advancement:** Tests that have a `PipelineManager*` use `test_utils::AdvanceUntilFence(engine, fence_tick)` so the test advances by **frame count** (simulate N ticks) instead of wall-clock sleep. Fence tick from duration: `test_infra::FenceTickAt30fps(duration_ms)`.
- **DeterministicTimeSource + DeterministicWaitStrategy:** In fast mode, `test_infra::MakeTestTimeSource()` returns a `DeterministicTimeSource` (nanosecond-precision virtual clock, starts at epoch 1e9 ms). `MakeTestOutputClock()` wires a `DeterministicWaitStrategy` that advances the time source by exactly one frame duration per tick (delta-based, no wall-clock sleep, no cumulative drift). `NowUtcMs()` returns advancing virtual time, truncated from internal nanosecond storage.
- **WaitForBounded:** Uses a short sleep + wall-clock timeout for polling. The DeterministicWaitStrategy advances virtual time in the tick loop, but the engine still needs real wall time for file I/O and thread startup.

## Tests that still use real time or long timeouts

- **LookaheadBufferContractTests, VideoLookaheadBufferTests:** Use `sleep_for` in mock producers and `WaitFor` with timeouts (1000–2000 ms). Not yet converted to fence-based advancement (no single PipelineManager in process).
- **FileProducerContractTests, PlayoutControlContractTests, PacingInvariantContractTests:** Use `sleep_for` for coordination or real-time pacing checks. Some are inherent (e.g. proving real-time pacing).
- **BlockPlanSlowContracts (SOAK):** Long runs; gated behind `RETROVUE_SOAK_TESTS` and label `SOAK`; excluded from default ctest and CI.

## CTest labels: contract (CI) vs soak (nightly)

- **contract** — Default for CI. All non-soak tests have this label. Run: `ctest --test-dir pkg/air/build -L contract`
- **soak** — Long-running tests (only when `RETROVUE_SOAK_TESTS=1`). Excluded from CI; run nightly with `ctest -L soak`.

Soak tests have label `soak` only (no `contract`), so `ctest -L contract` does not run them.

### Soak tests and fast deterministic counterparts

| Soak test (DISABLED_SLOW_*) | Fast counterpart (same invariants, simulated time) |
|-----------------------------|----------------------------------------------------|
| `PlaybackTraceContractTests::DISABLED_SLOW_PaddedTransitionStatus` | BlockPlanContracts (padded transition tests with AdvanceUntilFence / short blocks) |
| `SeamProofContractTests::DISABLED_SLOW_RealMediaBoundarySeamless` | SeamProofContractTests (non-SLOW seam tests with synthetic/fast blocks) |
| `ContinuousOutputContractTests::DISABLED_SLOW_PTSMonotonicAcrossSwaps` | ContinuousOutputContractTests PTS / pad-fill tests with FenceTickAt30fps |
| `ContinuousOutputContractTests::DISABLED_SLOW_PrerollArmingNextNextBlock` | ContinuousOutputContractTests preroll tests with bounded WaitForBounded / short durations |

All fast counterparts run in **BlockPlanContracts** with `RETROVUE_FAST_TEST=1` (AdvanceUntilFence, FenceTickAt30fps, no long sleep).
