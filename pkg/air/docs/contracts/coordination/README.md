# Development phase contracts

**Purpose:** Contracts tied to **development phases** (milestones), not the standing architecture. They define what was built or validated in a given phase (e.g. Phase 6A control surface, Phase 8 transport and TS mux). Use them to understand scope and exit criteria for those phases; for current architecture and first-class components, see [Air Architecture Reference](../semantics/AirArchitectureReference.md) and [semantics contracts](../semantics/README.md).

**Use when:** Tracing why a feature exists, what was in scope for a release, or what “Phase 6A” / “Phase 8” mean. Do not use phase contracts as the sole authority for current behavior—the code and architecture contracts are.

**Find invariants by ID:** [INVARIANTS-INDEX.md](../INVARIANTS-INDEX.md) lists every INV-P8-*, INV-P9-*, INV-P10-*, and INV-AUDIO-HOUSE-FORMAT-001 with one-line summary and link to authoritative doc.

---

## Phase 6A — Control surface and producers (historical)

| Contract | Focus |
|----------|--------|
| [Phase6A-Contract](Phase6A-Contract.md) | Phase 6A contract (in this directory). |
| [Phase6A-Overview](../../archive/phases/Phase6A-Overview.md) | Scope and deferrals (archive). |
| [Phase6A-0-ControlSurface](../../archive/phases/Phase6A-0-ControlSurface.md) | gRPC control surface (archive). |
| [Phase6A-1-ExecutionProducer](../../archive/phases/Phase6A-1-ExecutionProducer.md) | Producer lifecycle, buses (archive). |
| [Phase6A-2-FileBackedProducer](../../archive/phases/Phase6A-2-FileBackedProducer.md) | File-backed producer (archive). |
| [Phase6A-3-ProgrammaticProducer](../../archive/phases/Phase6A-3-ProgrammaticProducer.md) | Programmatic producer (archive). |

## Phase 8 — Transport, TS mux, segment control

| Contract | Focus |
|----------|--------|
| [Phase8-Overview](Phase8-Overview.md) | Scope and dependencies. |
| [Phase8-Invariants-Compiled](../semantics/Phase8-Invariants-Compiled.md) | **All Phase 8 invariants in one place** (timeline, segment, switch). |
| [Phase8-0-Transport](Phase8-0-Transport.md) | Stream transport (UDS, FD). |
| [Phase8-1-AirOwnsMpegTs](Phase8-1-AirOwnsMpegTs.md) | Air owns MPEG-TS output. |
| [Phase8-1-5-FileProducerInternalRefactor](Phase8-1-5-FileProducerInternalRefactor.md) | FileProducer internal refactor. |
| [Phase8-2-SegmentControl](Phase8-2-SegmentControl.md) | Segment control (seek/stop). |
| [LegacyPreviewSwitchModel (Retired model)](LegacyPreviewSwitchModel.md) | Legacy preview/switch model; superseded by BlockPlan. |
| [Phase8-4-PersistentMpegTsMux](Phase8-4-PersistentMpegTsMux.md) | Persistent mux, PIDs. |
| [Phase8-5-FanoutTeardown](Phase8-5-FanoutTeardown.md) | Fan-out and teardown. |
| [Phase8-6-RealMpegTsE2E](Phase8-6-RealMpegTsE2E.md) | Real MPEG-TS E2E. |
| [Phase8-7-ImmediateTeardown](Phase8-7-ImmediateTeardown.md) | Immediate teardown. |
| [Phase8-8-FrameLifecycleAndPlayoutCompletion](Phase8-8-FrameLifecycleAndPlayoutCompletion.md) | Frame lifecycle. |
| [Phase8-9-AudioVideoUnifiedProducer](Phase8-9-AudioVideoUnifiedProducer.md) | Unified AV producer. |

## Phase 9 — Output bootstrap, audio liveness

| Contract | Focus |
|----------|--------|
| [Phase9-OutputBootstrap](Phase9-OutputBootstrap.md) | Bootstrap from segment commit to first output; INV-P9-* (flush, ready, deadlock, output safety/liveness, write barrier, audio liveness, PCR). Tests: `tests/contracts/Phase9OutputBootstrapTests.cpp`. |

## Phase 10 — Pipeline flow control

| Contract | Focus |
|----------|--------|
| [INV-P10-PIPELINE-FLOW-CONTROL](INV-P10-PIPELINE-FLOW-CONTROL.md) | Steady-state flow control; INV-P10-* (throughput, backpressure, throttle, frame-drop policy, buffer equilibrium, CT-authoritative, PCR-paced mux, no silence injection). |

---

## See also

- [INVARIANTS-INDEX.md](../INVARIANTS-INDEX.md) — Find any invariant by ID.
- [PlayoutInvariants-BroadcastGradeGuarantees.md](../laws/PlayoutInvariants-BroadcastGradeGuarantees.md) — Top-level laws.
- [Air Architecture Reference](../semantics/AirArchitectureReference.md) — First-class components (reference contract).
- [Semantics contracts](../semantics/README.md) — Standing component/domain contracts.
