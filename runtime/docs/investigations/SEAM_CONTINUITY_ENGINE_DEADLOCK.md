# Investigation: SeamContinuityEngineContractTest Deadlock

## Status: Open — Pre-existing, out of scope for current FIVS/PTS work

## Test Name
`SeamContinuityEngineContractTest` (all subtests: T_SEAM_001a through T_SEAM_004a)

## Reproduction
```bash
timeout 30 runtime/build/blockplan_contract_tests --gtest_filter="SeamContinuityEngineContractTest.*"
```
Exits with SEGFAULT (actually a timeout-killed hang, not a true segfault).

Individual subtests pass in isolation:
```bash
timeout 20 runtime/build/blockplan_contract_tests --gtest_filter="SeamContinuityEngineContractTest.T_SEAM_001a*"
# PASSED (3597 ms)
```

The hang occurs when running the full test suite sequentially — likely a resource leak or thread not joining from an earlier test that cascades.

## Pre-existing Confirmation

Verified on 2026-03-22 by stashing all current AIR changes (PTS correction in TickProducer, timestamp addition in PipelineManager, FIVS test fixes), rebuilding from clean HEAD, and running the same test:

```bash
git stash -- runtime/src/blockplan/TickProducer.cpp \
             runtime/include/retrovue/blockplan/TickProducer.hpp \
             runtime/src/blockplan/PipelineManager.cpp
cmake --build runtime/build -j$(nproc)
timeout 15 runtime/build/blockplan_contract_tests --gtest_filter="SeamContinuityEngineContractTest.*"
# Result: timeout, dumped core — identical to current branch
git stash pop
```

## Observed Behavior

The test hangs after:
```
[PipelineManager] PAD_B_PRIME reason=session_start depth_ms=500
[PipelineManager] PRIME_CHECK: state_ready=1 has_decoder=1
```

The pipeline manager's execution thread appears to be waiting on a condvar or lock that is never signaled. This happens only when run after other tests in the same binary — individual subtests pass.

## Why Out of Scope

This is a pipeline thread lifecycle issue in the test harness, not related to:
- PTS discontinuity absorption (TickProducer change)
- PTS_DRIFT_DETECTED timestamps (PipelineManager change)
- FIVS consumer position contract (test-only changes)

The deadlock involves SeamPreparer/PipelineManager thread coordination, which is a separate subsystem.

## Likely Investigation Path

1. Check if `SeamContinuityEngineContractTest` fixture teardown properly joins all threads
2. Check if a prior test in the binary leaves a thread or lock in a bad state
3. Run with `--gtest_shuffle` to see if test ordering matters
4. Run with ThreadSanitizer (`-fsanitize=thread`) to identify the deadlocked mutex
