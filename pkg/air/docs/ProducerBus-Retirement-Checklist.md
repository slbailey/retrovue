# ProducerBus Retirement Checklist

**Status:** Pre-retirement (ProducerBus path deprecated for BlockPlan; still active for legacy sessions)
**Blocking invariant:** INV-BLOCKPLAN-QUARANTINE (runtime guard prevents dual-path execution)
**Replacement:** PipelineManager TAKE-based source selection (INV-PAD-PRODUCER)
**Created:** 2026-02-09

---

## 1. Contracts That Must Be Retired

These contracts govern behavior that exists only on the ProducerBus execution path.
When ProducerBus is deleted, these documents have no implementation to govern.

| Contract | Path | Governs |
|----------|------|---------|
| ProducerBusContract (architecture) | `docs/contracts/architecture/ProducerBusContract.md` | Bus semantics, LIVE/PREVIEW switching, always-valid-output via bus model |
| ProducerBusContract (coordination) | `docs/contracts/coordination/ProducerBusContract.md` | Same (duplicate) |
| BlackFrameProducerContract | `docs/contracts/coordination/BlackFrameProducerContract.md` | Dead-man failsafe, INV-PAD-EXACT-COUNT structural padding |
| PlayoutControlContract (architecture) | `docs/contracts/architecture/PlayoutControlContract.md` | CTL-001 through CTL-004: state machine for bus switching |
| PlayoutControlContract (coordination) | `docs/contracts/coordination/PlayoutControlContract.md` | Same (duplicate) |
| Phase8-3-PreviewSwitchToLive | `docs/contracts/coordination/Phase8-3-PreviewSwitchToLive.md` | INV-P8-SWITCH-001/002, write barriers, shadow decode, audio gate |
| OutputSwitchingContract | `docs/contracts/coordination/OutputSwitchingContract.md` | Output bus switching during producer transitions |
| Phase8-2-SegmentControl | `docs/contracts/coordination/Phase8-2-SegmentControl.md` | Segment commit, timeline ownership, EOF handling |
| Phase8-8-FrameLifecycleAndPlayoutCompletion | `docs/contracts/coordination/Phase8-8-FrameLifecycleAndPlayoutCompletion.md` | Frame lifecycle through ProducerBus path |
| Phase8-5-FanoutTeardown | `docs/contracts/coordination/Phase8-5-FanoutTeardown.md` | Teardown sequence for bus-based sessions |
| Phase8-7-ImmediateTeardown | `docs/contracts/coordination/Phase8-7-ImmediateTeardown.md` | Immediate teardown for bus-based sessions |
| SwitchWatcherStopTargetContract | `docs/contracts/coordination/SwitchWatcherStopTargetContract.md` | INV-P8-SWITCHWATCHER-STOP-TARGET-001 |
| Phase9-OutputBootstrap | `docs/contracts/coordination/Phase9-OutputBootstrap.md` | INV-P9-SINK-LIVENESS, boot sequence via ProducerBus |
| INV-P10-PIPELINE-FLOW-CONTROL | `docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md` | Flow control between ProducerBus and encoder |

**Contracts that survive (shared or BlockPlan-only):**
- INV-PAD-PRODUCER — replaces BlackFrameProducerContract for BlockPlan
- INV-TICK-GUARANTEED-OUTPUT — satisfied by PadProducer in BlockPlan
- INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT — enforced by PipelineManager
- PlayoutInvariants-BroadcastGradeGuarantees (law) — implementation-agnostic
- INV-BLOCK-WALLCLOCK-FENCE-001, INV-BLOCK-FRAME-BUDGET-AUTHORITY, INV-BLOCK-LOOKAHEAD-PRIMING — BlockPlan-only

---

## 2. Test Suites That Must Be Replaced or Absorbed

### 2.1 `contracts_playoutengine_tests` (DISABLED — deadlocks in CI)

**Target:** `contracts_playoutengine_tests` in CMakeLists.txt (line 229)
**Status:** Builds but is not registered with CTest (lines 281-286 commented out)

| Test file | Coverage area | BlockPlan equivalent |
|-----------|---------------|---------------------|
| `PlayoutEngine/PlayoutEngineContractTests.cpp` | StartChannel/LoadPreview/SwitchToLive lifecycle, Phase 6A.0/6A.1/6A.2/6A.3, BC-001 through BC-007 | `BlockPlan/ContinuousOutputContractTests.cpp` covers session lifecycle; gRPC entry-point coverage via INV-BLOCKPLAN-QUARANTINE guards |
| `OutputSwitching/OutputSwitchingContractTests.cpp` | Preview-to-live atomic switching, OS-001 through OS-006 | `BlockPlan/TakeAtCommitContractTests.cpp` covers TAKE-based A/B switching |
| `Phase815FileProducerTests.cpp` | FileProducer hard stop, EOF behavior on ProducerBus | `BlockPlan/PlaybackTraceContractTests.cpp` covers TickProducer EOF and real-media playback |
| `Phase84PersistentMpegTsMuxTests.cpp` | Persistent mux across bus switches | Session-scoped encoder in PipelineManager (tested in ContinuousOutputContractTests) |
| `file_producer/FileProducerContractTests.cpp` | FileProducer decode rate, wall-clock pacing, audio buffer limits | TickProducer + VideoLookaheadBuffer + AudioLookaheadBuffer tests |
| `TimelineController/TimelineControllerContractTests.cpp` | Timeline controller state machine | No BlockPlan equivalent (timeline controller not used) |
| `TimelineController/Phase8IntegrationTests.cpp` | Phase 8 timeline integration | No BlockPlan equivalent |
| `Phase9OutputBootstrapTests.cpp` | Output bootstrap liveness (INV-P9-BOOT-LIVENESS) | Covered by INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT in ContinuousOutputContractTests |
| `Phase9SteadyStateSilenceTests.cpp` | Silence injection in steady state | PadProducer silence via INV-PAD-PRODUCER-002 |
| `Phase9SymmetricBackpressureTests.cpp` | Backpressure between producer and encoder | VideoLookaheadBuffer/AudioLookaheadBuffer bounded depth |
| `Phase9NoPadWhileDepthHighTests.cpp` | No pad when buffer depth is sufficient | INV-PAD-PRODUCER-006 TAKE priority (content before pad) |
| `Phase9BufferEquilibriumTests.cpp` | Buffer equilibrium in steady state | Lookahead buffer contract tests |
| `Phase10PipelineFlowControlTests.cpp` | Credit-based flow control | Not ported (PipelineManager uses different flow model) |
| `Phase10FrameIndexedExecutionTests.cpp` | Frame-indexed execution (INV-FRAME-001/002/003) | BlockPlan uses wall-clock fence (INV-BLOCK-WALLCLOCK-FENCE-001) |
| `Phase11AudioContinuityTests.cpp` | Audio continuity across switches | AudioLookaheadBuffer + rational accumulator in PipelineManager |
| `BoundaryDeclarationTests.cpp` | Boundary declaration protocol | SeamProofContractTests + PlaybackTraceContractTests |
| `PrefeedProtocolTests.cpp` | Prefeed protocol for pre-loading | ProducerPreloader in BlockPlan |
| `DeadlineSwitchTests.cpp` | Deadline-based switching | TAKE-at-commit at fence tick |
| `PrimitiveInvariants/PacingInvariantContractTests.cpp` | INV-PACING-001 | OutputClock + INV-TICK-DEADLINE-DISCIPLINE-001 |
| `PrimitiveInvariants/SinkLivenessContractTests.cpp` | INV-P9-SINK-LIVENESS | SocketSink liveness in ContinuousOutputContractTests |
| `ProducerContinuity/ProducerContinuityContractTests.cpp` | Producer handoff continuity | TAKE-at-commit PTS continuity (PTSContinuityContractTests) |

### 2.2 `deterministic_harness_tests` (ACTIVE)

**Target:** `deterministic_harness_tests` in CMakeLists.txt (line 291)
**Status:** Registered with CTest, runs in CI

| Test file | Coverage area | BlockPlan equivalent |
|-----------|---------------|---------------------|
| `DeterministicHarness/DeterministicHarnessContractTests.cpp` | Control-plane invariants with FakeProducers and RecordingSink | No direct equivalent — harness tests PlayoutControl state machine, not PipelineManager |

### 2.3 `PlayoutControl/PlayoutControlContractTests.cpp` (in `contracts_playoutengine_tests`)

| Test case | Coverage area | BlockPlan equivalent |
|-----------|---------------|---------------------|
| CTL-001 DeterministicStateTransitions | State machine correctness | PipelineManager has no external state machine (start/stop only) |
| CTL-002 ControlActionLatency | Latency guarantees for bus operations | Not applicable (TAKE is single-tick) |
| CTL-003 CommandIdempotency | Idempotent bus operations | PipelineManager Stop() idempotency tested in ContinuousOutputContractTests |
| CTL-004 FailureTelemetry | Telemetry on bus failures | PipelineMetrics in PipelineManager |

---

## 3. Components Covered Only by ProducerBus Tests

These components have **no test coverage from BlockPlan tests**.  Before deletion, each must either:
(a) have its behavior absorbed by a BlockPlan test, or
(b) be confirmed as dead code with no BlockPlan consumers.

### Source files

| Component | File | BlockPlan uses it? | Action required |
|-----------|------|--------------------|-----------------|
| ProducerBus | `src/runtime/ProducerBus.cpp` | No | Delete with ProducerBus |
| PlayoutControl | `src/runtime/PlayoutControl.cpp` | No | Delete with ProducerBus |
| PlayoutEngine | `src/runtime/PlayoutEngine.cpp` | No | Delete with ProducerBus |
| PlayoutInterface | `src/runtime/PlayoutInterface.cpp` | No | Delete with ProducerBus |
| BlackFrameProducer | `src/producers/black/BlackFrameProducer.cpp` | No | Delete with ProducerBus |
| TimingLoop | `src/runtime/TimingLoop.cpp` | No | Verify no BlockPlan dependency, then delete |
| ProgrammaticProducer | `src/producers/programmatic/ProgrammaticProducer.cpp` | No | Delete with ProducerBus |
| ProgramOutput (renderer) | `src/renderer/ProgramOutput.cpp` | No | Verify no BlockPlan dependency, then delete |
| PTSController | `src/playout_sinks/mpegts/PTSController.cpp` | No | Verify no BlockPlan dependency, then delete |
| OutputBus | `src/output/OutputBus.cpp` | No | Verify no BlockPlan dependency, then delete |
| TimelineController | `src/timing/TimelineController.cpp` | No | Delete with ProducerBus |

### Headers

| Header | BlockPlan includes it? | Action required |
|--------|----------------------|-----------------|
| `include/retrovue/runtime/ProducerBus.h` | No | Delete |
| `include/retrovue/runtime/PlayoutControl.h` | No | Delete |
| `include/retrovue/runtime/PlayoutEngine.h` | No | Delete |
| `include/retrovue/runtime/PlayoutInterface.h` | No | Delete |
| `include/retrovue/runtime/PlayoutController.h` | No | Delete |
| `include/retrovue/runtime/TimingLoop.h` | No | Delete |
| `include/retrovue/producers/black/BlackFrameProducer.h` | No | Delete |
| `include/retrovue/runtime/ProgramFormat.h` | **Yes** (BlockPlanSessionTypes uses ProgramFormat indirectly) | **Retain** — shared component |
| `include/retrovue/runtime/AspectPolicy.h` | Verify | Verify before deleting |

### gRPC handlers (in `playout_service.cpp`)

| Handler | Status | Action required |
|---------|--------|-----------------|
| `StartChannel` | Guarded by INV-BLOCKPLAN-QUARANTINE | Delete handler; remove from proto |
| `LoadPreview` | Guarded by INV-BLOCKPLAN-QUARANTINE | Delete handler; remove from proto |
| `SwitchToLive` | Guarded by INV-BLOCKPLAN-QUARANTINE | Delete handler; remove from proto |
| `UpdatePlan` | Legacy only | Delete handler; remove from proto |
| `StopChannel` | Legacy only | Delete handler; remove from proto |
| `AttachStream` / `DetachStream` | Legacy only | Delete handler; remove from proto |

### Test infrastructure

| Component | File | Action required |
|-----------|------|-----------------|
| FakeProducers | `tests/harness/deterministic/FakeProducers.cpp` | Delete with harness |
| RecordingSink | `tests/harness/deterministic/RecordingSink.cpp` | Delete with harness |
| DeterministicTestHarness | `tests/harness/deterministic/DeterministicTestHarness.cpp` | Delete with harness |
| ContractRegistry | `tests/ContractRegistry.cpp` | Delete with legacy tests |
| TestMasterClock | `src/timing/TestMasterClock.cpp` | Verify no BlockPlan consumer, then delete |

---

## 4. Deletion Criteria

ProducerBus and all legacy components listed above can be safely deleted when **all** of the following are true:

### 4.1 No remaining callers

- [ ] Core's `PLAYOUT_AUTHORITY` is permanently `"blockplan"` (no fallback to legacy path)
- [ ] No gRPC client (Core, manual, or test) calls `StartChannel`, `LoadPreview`, or `SwitchToLive`
- [ ] `playout.proto` RPCs for the legacy path are removed or marked `reserved`
- [ ] INV-BLOCKPLAN-QUARANTINE guards have never fired in production (confirm via logs/metrics)

### 4.2 Behavioral parity verified

- [ ] Every invariant enforced by `contracts_playoutengine_tests` is either:
  - (a) covered by an equivalent BlockPlan contract test, or
  - (b) documented as intentionally not applicable to BlockPlan (with rationale)
- [ ] `deterministic_harness_tests` behaviors are absorbed or documented as N/A
- [ ] FileProducer decode-rate and EOF tests have BlockPlan equivalents via TickProducer + VideoLookaheadBuffer tests
- [ ] Output bootstrap (INV-P9-BOOT-LIVENESS) is covered by INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT tests
- [ ] Audio continuity across block transitions is covered by AudioLookaheadBuffer + rational accumulator tests
- [ ] Pad frame emission is covered by INV-PAD-PRODUCER contract tests (PadProducerContractTests, ContinuousOutputContractTests PAD-PROOF-001 through PAD-PROOF-005)

### 4.3 Shared components audited

- [ ] `ProgramFormat.h` / `ProgramFormat.cpp` — confirmed still needed by BlockPlan; retained
- [ ] `AspectPolicy.h` — confirmed not needed by BlockPlan, or retained if shared
- [ ] `FrameRingBuffer.h` / `FrameRingBuffer.cpp` — confirmed needed by BlockPlan (used by TickProducer fill thread); retained
- [ ] `MasterClock.h` — confirmed needed only by legacy path; delete or retain based on BlockPlan usage
- [ ] `EncoderPipeline` — shared between both paths; retained
- [ ] `SocketSink` / `MpegTSOutputSink` — shared; retained

### 4.4 Build system cleaned

- [ ] Legacy source files removed from `AIR_CORE_SOURCES` in CMakeLists.txt
- [ ] `contracts_playoutengine_tests` target removed from CMakeLists.txt
- [ ] `deterministic_harness_tests` target removed from CMakeLists.txt
- [ ] Clean build succeeds with zero legacy references
- [ ] `blockplan_contract_tests` continues to pass (94+ tests)

### 4.5 Documentation retired

- [ ] All contracts listed in Section 1 moved to `docs/contracts/retired/` (not deleted — audit trail)
- [ ] INVARIANTS-INDEX.md updated to mark retired invariants
- [ ] CANONICAL_RULE_LEDGER.md updated (if applicable)
- [ ] ProducerBus deprecation comments removed from surviving files
- [ ] This checklist marked as completed

---

## Retirement Sequence (recommended order)

1. Verify behavioral parity (Section 4.2) — write missing BlockPlan tests
2. Remove Core's ability to call legacy RPCs (Section 4.1)
3. Remove gRPC handlers and proto definitions
4. Remove source files and headers (Section 3)
5. Remove test targets and test files (Section 2)
6. Clean CMakeLists.txt (Section 4.4)
7. Retire contract documents (Section 4.5)
8. Final clean build + full test pass
