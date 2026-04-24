# Bootstrap slice — pause status

**Paused:** 2026-04-24 during IR2 closure sprint.
**Work preserved at:** branch `wip/bootstrap-slice-2026-04-24` (14 runtime files modified, 9 new paths including the bootstrap module, 5 invariant docs, bootstrap contract tests).
**Main state:** unchanged by this pause — no partial slice committed.

## Test status at pause

### Bootstrap tests green

- `bootstrap_contract_tests`: **19/19 pass** on the WIP branch. The new module (`runtime/src/bootstrap/`) works in isolation.

### Regression introduced by this slice

`VideoLookaheadBuffer::FillLoop` in the WIP branch introduces a new `audio_burst_active_` atomic with hysteresis (enter burst when `audio_ms < LowWaterMs`, exit at `HighWaterMs`). While in burst, `should_park_for_lookahead()` returns `false` regardless of video depth (hard cap still enforced). Cited as `INV-AUDIO-LIVENESS-001 (Step 2 hysteresis)` in code at 6 sites, but that invariant has **no canonical contract document** — only a mention inside `docs/contracts/invariants/air/INV-FILL-AV-LEAD-CLAMP-001.md`.

Empirical evidence:
- Clean `main` (HEAD): `video_lookahead_tests` 30/30 pass across 5 consecutive runs.
- WIP branch: 30/30 on 3 runs, 29/30 on 2 runs, with different tests failing on different runs.
  - Observed fails: `FillAvLeadClampContract.FillLoop_HighWaterAdmission_MustNotOvershootInOneCycle`, `VideoLookaheadBufferTest.AVFillInterlockNoSuppression`, `VideoLookaheadBufferTest.HoldLastAudioContinuity_NeverUnderflows`.
  - The rest of `FillAvLeadClampContract` (13 tests) is latently at risk — same code path.

### Pre-existing failures (NOT caused by this slice)

Confirmed present on clean `main` as well:

- `blockplan_contract_tests`: 9 deterministic slow-fails in `ContinuousOutputContractTest.*` (30–35s per test): `BlockCompletedCallbackFires`, `StopDuringBlockExecution`, `PadFramesForEntireBlock`, `SourceSwapCountIncrements`, `StopDuringPreloadNoDeadlock`, `PadProof_SinglePadPostFence`, `PadProof_FivePadsPostFence`, `PadProof_PadOnlyMicroBlock`, `PadProof_SinglePadSeam`. 39 others pass.
- `contracts_playoutengine_tests`: deterministic `double free or corruption (out)` in `PlayoutControlContractTest.CTL_005_ProducerSwitchingSeamlessness`.
- `ctest -N` also flags a missing binary (`fatal_underflow_visibility_tests`) that the build config expects.

These are their own problem, separate from the bootstrap slice.

## Why no commit was made

Merging the WIP would ship a real, timing-sensitive regression into `main` under a "new module works" banner. The failing tests reference `INV-FILL-AV-LEAD-CLAMP-001`, which the new hysteresis reshapes. Whether the regression is a bug or a deliberate contract change depends on whether `INV-AUDIO-LIVENESS-001` is meant to subsume the clamp rule — a design question, not a triage question. Per the "no speculative fixes" constraint, holding the slice was the only correct call.

## Next design decision required

**Does `INV-AUDIO-LIVENESS-001` (audio-burst hysteresis) subsume or override `INV-FILL-AV-LEAD-CLAMP-001`'s "HighWater admission must not overshoot in one cycle" rule?**

1. **If yes (stacked policy):** `FillAvLeadClampContract` tests must be updated to reflect that liveness trumps clamp during burst. The new invariant also needs its own canonical doc at `docs/contracts/invariants/air/INV-AUDIO-LIVENESS-001.md` before any code citing it ships.
2. **If no (clamp is unconditional):** the new hysteresis in `VideoLookaheadBuffer::FillLoop` must be refined so the clamp guarantee holds even under audio burst.

Secondary: `INV-AUDIO-LIVENESS-001` is cited in code but has no contract document. That gap must be closed regardless of which branch above is chosen.

## Recommended owner / resume path

- **Owner:** author of the paused 2026-04-20 BootstrapContentGate slice (background in `/opt/retrovue/air/LIFECYCLE_DESIGN.md`).
- **Resume steps:**
  1. Check out `wip/bootstrap-slice-2026-04-24` into a working branch.
  2. Write `docs/contracts/invariants/air/INV-AUDIO-LIVENESS-001.md` answering the question above.
  3. Either update `FillAvLeadClampContract` tests (branch 1) or refine `VideoLookaheadBuffer::FillLoop` (branch 2) to match.
  4. Re-run `video_lookahead_tests` ×5; must be 30/30 on every run.
  5. Then the slice is safe to merge into `main`.
