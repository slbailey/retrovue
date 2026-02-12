# Phase Archive Index

Cross-repo index of markdown documentation under `docs/`, `pkg/air/docs/`, and `pkg/core/docs/`. Focus: contracts, laws, phases, and canonical documentation.

| repo | file path | phase | primary topic | still canonical? | likely contains rules to codify? | notes |
|------|-----------|-------|---------------|------------------|----------------------------------|-------|
| main | docs/ComponentMap.md | — | system overview | yes | high | Status=Canonical. Component inventory, Phase 0 invariant, ChannelManager lifecycle. |
| main | docs/contracts/PHASE_MODEL.md | 6A,7,8,9 | phase taxonomy | yes | med | Defines phase taxonomy; links to Air contracts. Cross-repo entry point. |
| main | docs/core/GLOSSARY.md | — | glossary | yes | low | Terms, spellings. Cross-refs architecture. |
| main | docs/core/README.md | — | docs index | yes | low | Entry point to core docs. |
| main | docs/legacy/air/contracts/MpegTSPlayoutSinkDomainContract.md | 7+ | TS, sink | no | high | Deferred Phase 7+; superseded by pkg/air contracts. Preserved TS mux/encoding rules. |
| main | docs/legacy/air/contracts/MpegTSPlayoutSinkTimingContract.md | 7+ | clock, TS | no | high | Deferred Phase 7+; MasterClock authority, PTS mapping. Preserved timing rules. |
| main | docs/legacy/air/contracts/OrchestrationLoopDomainContract.md | 7+ | orchestration, clock | no | high | Tick discipline, back-pressure, starvation. Superseded by Air coordination contracts. |
| main | docs/legacy/air/domain/MpegTSPlayoutSinkDomain.md | — | TS, sink | no | med | Domain model; references legacy contracts. |
| main | docs/legacy/air/domain/OrchestrationLoopDomain.md | — | orchestration | no | med | Loop interfaces; references MasterClock. |
| main | docs/legacy/air/runtime/phase6.md | 6 | runtime evolution | no | low | Draft overview; superseded by Phase6A. |
| main | docs/legacy/air/developer/Phase2_Goals.md | 2 | developer | no | low | Historical goals. |
| main | docs/legacy/air/milestones/Phase1_Complete.md | 1 | milestones | no | low | Historical. |
| main | docs/legacy/air/milestones/Phase1_Skeleton.md | 1 | milestones | no | low | Historical. |
| main | docs/legacy/air/air/contracts/MpegTSPlayoutSinkTimingContract.md | 7+ | TS, timing | no | high | Duplicate of parent; same content. |
| main | docs/futureideas/CreatorsAsContent.md | — | future | unknown | low | Future ideas. |
| main | docs/standards/contract-hygiene.md | — | contracts | yes | high | Contract authoring guidelines. |
| main | docs/standards/test-methodology.md | — | testing | yes | high | Test methodology. |
| main | docs/standards/milestone-template.md | — | milestones | yes | med | Milestone doc template. |
| main | docs/standards/documentation-standards.md | — | documentation | yes | med | Doc authoring standards. |
| main | docs/standards/ai-assistant-methodology.md | — | AI | yes | low | AI assistant guidance. |
| main | docs/standards/contributing.md | — | contributing | yes | low | Contribution guidelines. |
| main | docs/standards/README.md | — | standards | yes | low | Standards index. |
| air | pkg/air/docs/contracts/README.md | — | authority model | yes | high | Layer 0–5; laws supreme; contracts normative. Entry point. |
| air | pkg/air/docs/contracts/INVARIANTS-INDEX.md | 8,9,10 | invariants | yes | high | All invariant IDs; links to canonical sources. |
| air | pkg/air/docs/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md | — | clock, timeline, output, switching | yes | high | Layer 0. Constitutional laws; non-negotiable. |
| air | pkg/air/docs/contracts/semantics/PlayoutEngineContract.md | 6A,7+ | playout, gRPC | yes | high | gRPC control plane; THINK vs ACT; clock authority refs laws. |
| air | pkg/air/docs/contracts/semantics/MasterClockContract.md | — | clock | yes | high | MT_001–MT_006; refs laws for clock authority. |
| air | pkg/air/docs/contracts/semantics/FileProducerContract.md | 6A.2,7+ | producers | yes | high | Lifecycle, segment params; PROD-010, PROD-010b. |
| air | pkg/air/docs/contracts/semantics/RendererContract.md | — | renderer | yes | med | Output, telemetry. |
| air | pkg/air/docs/contracts/semantics/OutputTimingContract.md | — | output, timing | yes | high | Real-time delivery, pacing. |
| air | pkg/air/docs/contracts/semantics/OutputContinuityContract.md | — | output, PTS | yes | high | PTS monotonicity; refs laws. |
| air | pkg/air/docs/contracts/semantics/MetricsAndTimingContract.md | — | telemetry, timing | yes | med | Metrics guarantees. |
| air | pkg/air/docs/contracts/semantics/MetricsExportContract.md | — | telemetry | yes | med | MET_001–MET_003; non-blocking export. |
| air | pkg/air/docs/contracts/semantics/PlayoutInstanceAndProgramFormatContract.md | — | playout, format | yes | med | Session, ProgramFormat. |
| air | pkg/air/docs/contracts/semantics/Phase8-Invariants-Compiled.md | 8 | invariants | yes | high | Compiled Phase 8 invariants. |
| air | pkg/air/docs/contracts/semantics/PrimitiveInvariants.md | — | pacing, decode | yes | high | INV-PACING, INV-DECODE-RATE, INV-SEGMENT-CONTENT. |
| air | pkg/air/docs/contracts/semantics/RealTimeHoldPolicy.md | — | pacing, freeze | yes | high | Freeze-then-pad; no-drop policy. |
| air | pkg/air/docs/contracts/semantics/SinkLivenessPolicy.md | — | sink, output | yes | med | INV-P9-SINK-LIVENESS. |
| air | pkg/air/docs/contracts/semantics/AirArchitectureReference.md | — | architecture | yes | med | Component layout, signal flow. |
| air | pkg/air/docs/contracts/coordination/SwitchWatcherStopTargetContract.md | 8 | switching | yes | high | INV-P8-SWITCHWATCHER-*; successor protection. |
| air | pkg/air/docs/contracts/coordination/Phase8-Overview.md | 8 | TS, transport | yes | high | Phase 8.0–8.9; stream transport, TS pipeline. |
| air | pkg/air/docs/contracts/coordination/Phase8-0-Transport.md | 8.0 | transport | yes | med | AttachStream, DetachStream; UDS. |
| air | pkg/air/docs/contracts/coordination/Phase8-1-AirOwnsMpegTs.md | 8.1 | TS | yes | med | Air-owned ffmpeg TS output. |
| air | pkg/air/docs/contracts/coordination/Phase8-2-SegmentControl.md | 8.2 | segment | yes | high | start_offset_ms, hard_stop_time_ms. |
| air | pkg/air/docs/contracts/coordination/LegacyPreviewSwitchModel.md | 8.3 (Retired) | switching | yes | high | Legacy preview/switch; superseded by BlockPlan. Shadow decode, PTS continuity; INV-P8-SWITCH-*. |
| air | pkg/air/docs/contracts/coordination/Phase8-4-PersistentMpegTsMux.md | 8.4 | TS, mux | yes | med | One mux per channel; stable PIDs. |
| air | pkg/air/docs/contracts/coordination/Phase8-5-FanoutTeardown.md | 8.5 | teardown | yes | med | N viewers; last disconnect. |
| air | pkg/air/docs/contracts/coordination/Phase8-6-RealMpegTsE2E.md | 8.6 | TS, E2E | yes | med | Real TS only; VLC-playable. |
| air | pkg/air/docs/contracts/coordination/Phase8-7-ImmediateTeardown.md | 8.7 | teardown | yes | med | Viewer count 1→0 immediate. |
| air | pkg/air/docs/contracts/coordination/Phase8-8-FrameLifecycleAndPlayoutCompletion.md | 8.8 | frame lifecycle | yes | med | EOF ≠ completion. |
| air | pkg/air/docs/contracts/coordination/Phase8-9-AudioVideoUnifiedProducer.md | 8.9 | producers | yes | med | One FileProducer = AV source. |
| air | pkg/air/docs/contracts/coordination/Phase8-1-5-FileProducerInternalRefactor.md | 8.1.5 | producers | yes | med | Internal refactor. |
| air | pkg/air/docs/contracts/coordination/Phase9-OutputBootstrap.md | 9 | bootstrap, output | yes | high | Sink attachment, audio liveness. |
| air | pkg/air/docs/contracts/coordination/Phase6A-Contract.md | 6A | control | yes | high | Phase 6A coordination. |
| air | pkg/air/docs/contracts/coordination/OutputSwitchingContract.md | — | switching | yes | high | Output switching semantics. |
| air | pkg/air/docs/contracts/coordination/OutputBusAndOutputSinkContract.md | — | output, sink | yes | high | OutputBus, OutputSink. |
| air | pkg/air/docs/contracts/coordination/PlayoutControlContract.md | — | playout control | yes | med | State machine. |
| air | pkg/air/docs/contracts/coordination/ProducerBusContract.md | — | producers, bus | yes | high | ProducerBus, LIVE/PREVIEW. |
| air | pkg/air/docs/contracts/coordination/BlackFrameProducerContract.md | — | producers, pad | yes | med | Dead-man failsafe. |
| air | pkg/air/docs/contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md | 10 | flow control | yes | high | Backpressure, buffer equilibrium. |
| air | pkg/air/docs/contracts/coordination/build.md | — | build, codec | yes | high | Build invariants; static FFmpeg; no LD_LIBRARY_PATH. |
| air | pkg/air/docs/contracts/architecture/FileProducerContract.md | 6A.2 | producers | yes | high | Same content as semantics/FileProducerContract. |
| air | pkg/air/docs/contracts/architecture/MetricsExportContract.md | — | telemetry | yes | med | Same as semantics version. |
| air | pkg/air/docs/contracts/architecture/OutputTimingContract.md | — | output, timing | yes | high | Same as semantics version. |
| air | pkg/air/docs/contracts/architecture/PlayoutControlContract.md | — | playout control | yes | med | Same as coordination version. |
| air | pkg/air/docs/contracts/architecture/ProducerBusContract.md | — | producers, bus | yes | high | Same as coordination version. |
| air | pkg/air/docs/contracts/architecture/README.md | — | architecture | yes | low | Links to component contracts. |
| air | pkg/air/docs/contracts/phases/README.md | — | phases | yes | low | Links to Phase6A, Phase8. |
| air | pkg/air/docs/archive/phases/Phase6-ExecutionContract.md | 6 | control plane | no | high | gRPC mock-first; superseded by Phase6A. |
| air | pkg/air/docs/archive/phases/Phase6A-Overview.md | 6A | execution | no | high | Historical; superseded by contracts/architecture. |
| air | pkg/air/docs/archive/phases/Phase6A-0-ControlSurface.md | 6A.0 | gRPC | no | med | |
| air | pkg/air/docs/archive/phases/Phase6A-1-ExecutionProducer.md | 6A.1 | producers | no | high | |
| air | pkg/air/docs/archive/phases/Phase6A-2-FileBackedProducer.md | 6A.2 | producers | no | high | |
| air | pkg/air/docs/archive/phases/Phase6A-3-ProgrammaticProducer.md | 6A.3 | producers | no | med | |
| air | pkg/air/docs/archive/domain/*.md | — | domain | no | med | MasterClock, PlayoutEngine, FileProducer, etc. Superseded by semantics. |
| air | pkg/air/docs/archive/milestones/*.md | 2,3 | milestones | no | low | Phase2/3 Plan/Complete, Roadmap, Refactoring. |
| air | pkg/air/docs/DEBUG-VLC-NO-OUTPUT-RUNBOOK.md | — | ops | yes | low | Debug runbook for VLC issues. |
| air | pkg/air/docs/operations/telemetry-README.md | — | telemetry | yes | low | Grafana Timing.json. |
| air | pkg/air/docs/operations/Integration.md | — | integration | yes | med | Proto, versioning. |
| air | pkg/air/docs/runtime/PlayoutRuntime.md | — | runtime | yes | med | |
| air | pkg/air/docs/overview/*.md | — | overview | yes | low | Architecture, glossary, PROJECT_OVERVIEW. |
| air | pkg/air/docs/developer/*.md | — | developer | yes | low | BuildAndDebug, ContractTesting, TimingScenarios, etc. |
| core | pkg/core/docs/contracts/README.md | — | contracts index | yes | high | Authoritative index; normative contracts. |
| core | pkg/core/docs/contracts/resources/MasterClockContract.md | — | clock | yes | high | MC-001–MC-007; Core runtime clock. |
| core | pkg/core/docs/contracts/resources/ChannelManagerContract.md | — | channel, runtime | yes | high | ChannelManager behavior. |
| core | pkg/core/docs/contracts/runtime/ScheduleManagerContract.md | — | scheduling | yes | high | Consolidated ScheduleManager; grid, ScheduleDay, dynamic content, runtime, mid-segment seek. |
| core | pkg/core/docs/contracts/resources/*.md | — | CLI, resources | yes | med | 40+ resource contracts (Source, Asset, Channel, etc.). |
| core | pkg/core/docs/contracts/_ops/*.md | — | ops | yes | med | UnitOfWork, ProductionSafety, DestructiveOperation, SyncIdempotency. |
| core | pkg/core/docs/contracts/cli/*.md | — | CLI | yes | low | CLI command contracts. |
| core | pkg/core/docs/contracts/cross-domain/*.md | — | cross-domain | yes | med | Source_Importer, Source_Enricher, CLI_Data. |
| core | pkg/core/docs/archive/phases/README.md | — | phases | no | low | States: historical; normative under contracts/. |
| core | pkg/core/docs/archive/phases/Phase0-ClockContract.md | 0 | clock | no | high | MasterClock; superseded by MasterClockContract. |
| core | pkg/core/docs/archive/phases/Phase0-PlayoutRules.md | 0 | playout, grid | no | high | Grid, filler, playlog. |
| core | pkg/core/docs/archive/phases/Phase1-GridContract.md | 1 | grid | no | high | 30-min boundaries. |
| core | pkg/core/docs/archive/phases/Phase2-SchedulePlanContract.md | 2 | scheduling | no | high | Mock SchedulePlan. |
| core | pkg/core/docs/archive/phases/Phase2.5-AssetMetadataContract.md | 2.5 | asset | no | med | Metadata boundary. |
| core | pkg/core/docs/archive/phases/Phase3-ActiveItemResolverContract.md | 3 | scheduling | no | high | Active schedule item resolver. |
| core | pkg/core/docs/archive/phases/Phase4-PlayoutPipelineContract.md | 4 | playout pipeline | no | high | PlayoutSegment, gRPC mapping; hard_stop_time. |
| core | pkg/core/docs/archive/phases/Phase5-ChannelManagerContract.md | 5 | channel manager | no | high | Prefeed, legacy preload RPC/legacy switch RPC ordering. |
| core | pkg/core/docs/archive/phases/Phase7-E2EAcceptanceContract.md | 7 | E2E | no | high | E2E mock channel acceptance. |
| core | pkg/core/docs/archive/contracts/DestructiveOperationConfirmation.md | — | ops | no | med | Superseded by _ops/. |
| core | pkg/core/docs/archive/architecture/Directories.md | — | architecture | no | low | Historical. |
| core | pkg/core/docs/archive/developer/*.md | — | developer | no | low | Various historical. |
| core | pkg/core/docs/archive/data/broadcast-schema.md | — | schema | no | low | Historical. |
| core | pkg/core/docs/data/domain/*.md | — | domain | yes | med | Asset, Channel, MasterClock, PlayoutPipeline, etc. |
| core | pkg/core/docs/runtime/*.md | — | runtime | yes | med | ChannelManager, ProgramDirector, AsRun, etc. |
| core | pkg/core/docs/scheduling/*.md | — | scheduling | yes | high | EPG, broadcast_day_alignment, etc. |
| core | pkg/core/docs/architecture/*.md | — | architecture | yes | med | IngestArchitecture, SystemBoundaries, etc. |
| core | pkg/core/docs/overview/*.md | — | overview | yes | low | RepoReviewAndRoadmap, architecture. |
| core | pkg/core/docs/developer/*.md | — | developer | yes | low | PluginAuthoring, TestingStrategy, etc. |
| core | pkg/core/docs/operations/*.md | — | operations | yes | low | Configuration, OperatorWorkflows. |

---

## Quick reference: canonical vs archived

| Repo | Canonical (yes) | Archived / Superseded (no) |
|------|-----------------|----------------------------|
| main | ComponentMap, PHASE_MODEL, core/, standards/ | legacy/air/* (all) |
| air | contracts/, operations/, overview/, developer/, runtime/ | archive/* |
| core | contracts/, data/, runtime/, scheduling/, architecture/ | archive/* |

---

## Laws and rules priority (codify first)

1. **air/contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md** — supreme; all else defers.
2. **air/contracts/semantics/** — semantic contracts (correctness).
3. **air/contracts/coordination/** — coordination contracts (switching, flow control).
4. **core/contracts/resources/MasterClockContract.md** — Core clock; aligns with Air laws.
5. **core/contracts/runtime/ScheduleManager*.md** — scheduling invariants; cross-refs Air.
6. **main/docs/legacy/air/** — preserved rules in TS, timing, orchestration; migrate before codifying.
