# Development phase contracts

**Purpose:** Contracts tied to **development phases** (milestones), not the standing architecture. They define what was built or validated in a given phase (e.g. Phase 6A control surface, Phase 8 transport and TS mux). Use them to understand scope and exit criteria for those phases; for current architecture and first-class components, see [Air Architecture Reference](../../architecture/AirArchitectureReference.md) and [architecture contracts](../architecture/README.md).

**Use when:** Tracing why a feature exists, what was in scope for a release, or what “Phase 6A” / “Phase 8” mean. Do not use phase contracts as the sole authority for current behavior—the code and architecture contracts are.

## Phase 6A — Control surface and producers

| Contract | Focus |
|----------|--------|
| [Phase6A-Overview](Phase6A-Overview.md) | Scope and deferrals. |
| [Phase6A-0-ControlSurface](Phase6A-0-ControlSurface.md) | gRPC control surface. |
| [Phase6A-1-ExecutionProducer](Phase6A-1-ExecutionProducer.md) | Producer lifecycle, buses. |
| [Phase6A-2-FileBackedProducer](Phase6A-2-FileBackedProducer.md) | File-backed producer. |
| [Phase6A-3-ProgrammaticProducer](Phase6A-3-ProgrammaticProducer.md) | Programmatic (synthetic) producer. |

## Phase 8 — Transport, TS mux, segment control

| Contract | Focus |
|----------|--------|
| [Phase8-Overview](Phase8-Overview.md) | Scope and dependencies. |
| [Phase8-0-Transport](Phase8-0-Transport.md) | Stream transport (UDS, FD). |
| [Phase8-1-AirOwnsMpegTs](Phase8-1-AirOwnsMpegTs.md) | Air owns MPEG-TS output. |
| [Phase8-1-5-FileProducerInternalRefactor](Phase8-1-5-FileProducerInternalRefactor.md) | FileProducer internal refactor. |
| [Phase8-2-SegmentControl](Phase8-2-SegmentControl.md) | Segment control (seek/stop). |
| [Phase8-3-PreviewSwitchToLive](Phase8-3-PreviewSwitchToLive.md) | Preview / SwitchToLive. |
| [Phase8-4-PersistentMpegTsMux](Phase8-4-PersistentMpegTsMux.md) | Persistent mux, PIDs. |
| [Phase8-5-FanoutTeardown](Phase8-5-FanoutTeardown.md) | Fan-out and teardown. |
| [Phase8-6-RealMpegTsE2E](Phase8-6-RealMpegTsE2E.md) | Real MPEG-TS E2E. |
| [Phase8-7-ImmediateTeardown](Phase8-7-ImmediateTeardown.md) | Immediate teardown. |
| [Phase8-8-FrameLifecycleAndPlayoutCompletion](Phase8-8-FrameLifecycleAndPlayoutCompletion.md) | Frame lifecycle. |
| [Phase8-9-AudioVideoUnifiedProducer](Phase8-9-AudioVideoUnifiedProducer.md) | Unified AV producer. |

## See also

- [Air Architecture Reference](../../architecture/AirArchitectureReference.md) — First-class components (reference contract).
- [Architecture contracts](../architecture/README.md) — Standing component/domain contracts.
