# INV-PACING-SINGLE-AUTHORITY-001

## Behavioral Guarantee

Wall-clock pacing of playout emission (first paced byte onward) has **exactly one authority**: **`OutputClock`**. After bootstrap handoff succeeds, live A/V phase MUST remain a pure function of `OutputClock` progression and the tick schedule derived from it. No AIR component may mutate the video timeline or re-target video PTS toward audio PTS as a post-hoc correction path. **Mux, encoder, `MpegTSOutputSink`, and `ProgramOutput` MUST NOT** apply timing or A/V skew repair for conditions that **INV-BOOTSTRAP-AV-PHASE-001** requires to be resolved **before** pacing begins.

## Authority Model

- **`OutputClock`**: Sole owner of wall-time pacing and live A/V phase once started.
- **`PipelineManager`**: Owns **ordering only** — it MUST establish **phase-valid** upstream state per **INV-BOOTSTRAP-AV-PHASE-001**, then start **`OutputClock`**, then open the **emission gate** (TS bytes held until bootstrap complete — ordering implemented in `PipelineManager` and `SocketSink`). Canonical emission ordering is: **bootstrap phase valid → `OutputClock::Start` → gate open**. It MUST NOT perform live timeline mutation that makes video PTS a function of audio PTS.
- **`VideoLookaheadBuffer` fill thread**: Owns **fill-domain** A/V lead enforcement per **INV-FILL-AV-LEAD-CLAMP-001**; it does **not** replace `OutputClock` pacing or rewrite live PTS timelines.

## Boundary / Constraint

1. **`OutputClock` MUST NOT** be started until **INV-BOOTSTRAP-AV-PHASE-001** handoff conditions are satisfied **or** **INV-BOOTSTRAP-AV-PHASE-001** failure path has been taken (session teardown — see that invariant).
2. The **emission gate** (bytes reaching the transport consumer) MUST remain **closed** until after **`OutputClock::Start`** completes in the successful bootstrap path.
3. **Downstream** (mux, PCR interleaving, TS packetization) MUST **assume** upstream PTS/timebase is already consistent with editorial intent at gate open; they MUST NOT add **bootstrap-phase** A/V catch-up logic.
4. **Video timeline purity:** after `OutputClock::Start`, `video_pts` MUST remain the nominal tick-derived timeline. Any post-hoc video PTS convergence toward audio PTS is forbidden.
5. **Stall recovery path:** recovery from late ticks, startup phase error fallout, or transient queue imbalance MUST occur through authorized queue/consumption discipline (bootstrap gate, fill-domain clamp, decode gate/backpressure), not through timeline mutation.

## Violation

- `OutputClock` started while bootstrap **phase-invalid** per **INV-BOOTSTRAP-AV-PHASE-001**.
- Emission gate opened before `OutputClock` epoch is established.
- Any code path that adjusts live `video_pts` as a function of `audio_pts` (including bounded convergence, clamp-forward, or catch-up retargeting).
- Encoder, mux, or sink code path that **adjusts timing or sample cadence** specifically to fix **pre-existing** bootstrap A/V skew (as opposed to format-compliant encode/mux of already-valid timelines).

## Derives From

- `LAW-CLOCK`
- `LAW-RUNTIME-AUTHORITY`

## Relationship

- Supersedes the informal backlog label **INV-PACING-001** for the **single pacing authority** slice. Other pacing topics (decode rate, segment content) remain separate invariants if promoted from backlog.

## Required Tests

- `runtime/tests/contracts/BlockPlan/AudioClockAuthorityContractTests.cpp` (`CadenceConversionIsOutputClockAuthoritative`)
- `runtime/tests/contracts/BlockPlan/AudioClockAuthorityContractTests.cpp` (`StartupAnchorIgnoresPrerollBufferEpoch`)
- `runtime/tests/contracts/BlockPlan/AudioClockAuthorityContractTests.cpp` (`SeamTransitionPreservesCumulativeContinuity`)
- `runtime/tests/contracts/BlockPlan/AudioClockAuthorityContractTests.cpp` (`LateTickUsesObservedElapsedForAudioCatchup`)
- `runtime/tests/contracts/BlockPlan/AudioClockAuthorityContractTests.cpp` (`CumulativeDueIsMonotonicInTotalButNotDoubleCounted`)

## Enforcement Evidence

TODO
