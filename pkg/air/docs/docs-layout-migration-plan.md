# Proposed Directory Layout — pkg/air/docs

**Goal:** Map existing documents into a layer-based layout so Cursor (and humans) can distinguish laws, semantics, coordination, overview, developer notes, and archive. **This is a plan only.** No files are moved or modified.

**Target top-level structure:**

- `contracts/laws/` — Layer 0: constitutional laws (non-negotiable guarantees)
- `contracts/semantics/` — Layer 1: correctness rules (time, provenance, output semantics)
- `contracts/coordination/` — Layer 2: concurrency, switching, backpressure, phase contracts
- `overview/` — Narrative / entry point (unchanged)
- `developer/` — Developer notes / investigations (unchanged)
- `archive/` — Historical material (unchanged)

---

## 1. contracts/laws/

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `contracts/PlayoutInvariants-BroadcastGradeGuarantees.md` | `contracts/laws/PlayoutInvariants-BroadcastGradeGuarantees.md` | Single canonical Layer 0 document: clock, timeline, output liveness, audio format, switching. Non-negotiable; no other doc overrides it. |

---

## 2. contracts/semantics/

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `contracts/architecture/MasterClockContract.md` | `contracts/semantics/MasterClockContract.md` | Timing authority, monotonic now, PTS–UTC mapping; defines *what* is correct for time. |
| `contracts/architecture/OutputContinuityContract.md` | `contracts/semantics/OutputContinuityContract.md` | Monotonic PTS/DTS, no regression; correctness of timestamp progression. |
| `contracts/architecture/OutputTimingContract.md` | `contracts/semantics/OutputTimingContract.md` | Real-time delivery discipline; *what* “on time” means. |
| `contracts/architecture/FileProducerContract.md` | `contracts/semantics/FileProducerContract.md` | Segment params, decode contract, frame contract; correctness of producer behavior. |
| `contracts/architecture/RendererContract.md` | `contracts/semantics/RendererContract.md` | ProgramOutput, frame consumption; correctness of render path. |
| `contracts/architecture/PlayoutInstanceAndProgramFormatContract.md` | `contracts/semantics/PlayoutInstanceAndProgramFormatContract.md` | One instance per channel, ProgramFormat lifecycle; structural correctness. |
| `contracts/architecture/PlayoutEngineContract.md` | `contracts/semantics/PlayoutEngineContract.md` | gRPC control plane, rule IDs, metrics guarantees; correctness of control surface. |
| `contracts/architecture/MetricsAndTimingContract.md` | `contracts/semantics/MetricsAndTimingContract.md` | Metrics schema, timing enforcement; correctness of observable timing. |
| `contracts/architecture/MetricsExportContract.md` | `contracts/semantics/MetricsExportContract.md` | Telemetry export contract; correctness of export behavior. |
| `contracts/phases/Phase8-Invariants-Compiled.md` | `contracts/semantics/Phase8-Invariants-Compiled.md` | Compiled reference of Phase 8 invariants (timeline, CT, output liveness); mostly semantic; used as lookup. |
| `contracts/AirArchitectureReference.md` | `contracts/semantics/AirArchitectureReference.md` | Canonical list of first-class components and boundaries; defines *what* the system is (structural semantics). |
| `contracts/architecture/README.md` | `contracts/semantics/README.md` | Index of semantics contracts; move with architecture → semantics. |

---

## 3. contracts/coordination/

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `contracts/architecture/ProducerBusContract.md` | `contracts/coordination/ProducerBusContract.md` | Live/Preview buses, input path; coordination of producer slots. |
| `contracts/architecture/PlayoutControlContract.md` | `contracts/coordination/PlayoutControlContract.md` | RuntimePhase, bus switching, valid sequencing; coordination of control state. |
| `contracts/architecture/OutputSwitchingContract.md` | `contracts/coordination/OutputSwitchingContract.md` | Switching invariants, gapless transitions; coordination at switch. |
| `contracts/architecture/BlackFrameProducerContract.md` | `contracts/coordination/BlackFrameProducerContract.md` | Fallback producer, dead-man failsafe; coordinates output when live underruns. |
| `contracts/architecture/OutputBusAndOutputSinkContract.md` | `contracts/coordination/OutputBusAndOutputSinkContract.md` | Output signal path, attach/detach, sink lifecycle; coordination of output path. |
| `contracts/build.md` | `contracts/coordination/build.md` | Non-negotiable build/codec rules; coordinates with build system and toolchain (not playout laws). |
| `contracts/phases/Phase6A-Contract.md` | `contracts/coordination/Phase6A-Contract.md` | Phase 6A contract; coordination contract per Document Role. |
| `contracts/phases/Phase8-Overview.md` | `contracts/coordination/Phase8-Overview.md` | Phase 8 scope and narrative; Document Role = Coordination Contract. |
| `contracts/phases/Phase8-0-Transport.md` | `contracts/coordination/Phase8-0-Transport.md` | Transport contract; Coordination Contract. |
| `contracts/phases/Phase8-1-AirOwnsMpegTs.md` | `contracts/coordination/Phase8-1-AirOwnsMpegTs.md` | Air owns MPEG-TS; Coordination Contract. |
| `contracts/phases/Phase8-1-5-FileProducerInternalRefactor.md` | `contracts/coordination/Phase8-1-5-FileProducerInternalRefactor.md` | FileProducer refactor; Coordination Contract. |
| `contracts/phases/Phase8-2-SegmentControl.md` | `contracts/coordination/Phase8-2-SegmentControl.md` | Segment control; Coordination Contract. |
| `contracts/phases/Phase8-3-PreviewSwitchToLive.md` | `contracts/coordination/Phase8-3-PreviewSwitchToLive.md` | Preview/SwitchToLive; Coordination Contract. |
| `contracts/phases/Phase8-4-PersistentMpegTsMux.md` | `contracts/coordination/Phase8-4-PersistentMpegTsMux.md` | Persistent mux; Coordination Contract. |
| `contracts/phases/Phase8-5-FanoutTeardown.md` | `contracts/coordination/Phase8-5-FanoutTeardown.md` | Fan-out and teardown; Coordination Contract. |
| `contracts/phases/Phase8-6-RealMpegTsE2E.md` | `contracts/coordination/Phase8-6-RealMpegTsE2E.md` | Real MPEG-TS E2E; Coordination Contract. |
| `contracts/phases/Phase8-7-ImmediateTeardown.md` | `contracts/coordination/Phase8-7-ImmediateTeardown.md` | Immediate teardown; Coordination Contract. |
| `contracts/phases/Phase8-8-FrameLifecycleAndPlayoutCompletion.md` | `contracts/coordination/Phase8-8-FrameLifecycleAndPlayoutCompletion.md` | Frame lifecycle; Coordination Contract. |
| `contracts/phases/Phase8-9-AudioVideoUnifiedProducer.md` | `contracts/coordination/Phase8-9-AudioVideoUnifiedProducer.md` | Unified AV producer; Coordination Contract. |
| `contracts/phases/Phase9-OutputBootstrap.md` | `contracts/coordination/Phase9-OutputBootstrap.md` | Output bootstrap; Coordination Contract. |
| `contracts/phase10/INV-P10-PIPELINE-FLOW-CONTROL.md` | `contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md` | Phase 10 flow control; Coordination Contract (backpressure, throttle, buffer equilibrium). |
| `contracts/phases/README.md` | `contracts/coordination/README.md` | Phase index; move with phases → coordination. |

---

## 4. contracts/ (root — keep as entry point)

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `contracts/README.md` | `contracts/README.md` | Authority model; defines layers and rules. Stays at root as entry point. |
| `contracts/INVARIANTS-INDEX.md` | `contracts/INVARIANTS-INDEX.md` | Navigational index across laws/semantics/coordination; keep at root so “find invariant by ID” has one place. |

---

## 5. overview/

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `overview/README.md` | `overview/README.md` | Entry point; unchanged. |
| `overview/ArchitectureOverview.md` | `overview/ArchitectureOverview.md` | Narrative; unchanged. |
| `overview/GLOSSARY.md` | `overview/GLOSSARY.md` | Narrative; unchanged. |
| `overview/PROJECT_OVERVIEW.md` | `overview/PROJECT_OVERVIEW.md` | Narrative; unchanged. |

---

## 6. developer/

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `developer/BuildAndDebug.md` | `developer/BuildAndDebug.md` | Developer notes; unchanged. |
| `developer/ContractTesting.md` | `developer/ContractTesting.md` | Developer notes; unchanged. |
| `developer/DevelopmentStandards.md` | `developer/DevelopmentStandards.md` | Developer notes; unchanged. |
| `developer/LastMilePrePublishAudit.md` | `developer/LastMilePrePublishAudit.md` | Developer notes; unchanged. |
| `developer/QuickStart.md` | `developer/QuickStart.md` | Developer notes; unchanged. |
| `developer/TimingScenarios.md` | `developer/TimingScenarios.md` | Developer notes; unchanged. |

---

## 7. archive/

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `archive/AIR_COMPONENT_AUDIT.md` | `archive/AIR_COMPONENT_AUDIT.md` | Historical; unchanged. |
| `archive/domain/FileProducerDomain.md` | `archive/domain/FileProducerDomain.md` | Historical; unchanged. |
| `archive/domain/MasterClockDomain.md` | `archive/domain/MasterClockDomain.md` | Historical; unchanged. |
| `archive/domain/MetricsAndTimingDomain.md` | `archive/domain/MetricsAndTimingDomain.md` | Historical; unchanged. |
| `archive/domain/MetricsExportDomain.md` | `archive/domain/MetricsExportDomain.md` | Historical; unchanged. |
| `archive/domain/PlayoutControlDomain.md` | `archive/domain/PlayoutControlDomain.md` | Historical; unchanged. |
| `archive/domain/PlayoutEngineDomain.md` | `archive/domain/PlayoutEngineDomain.md` | Historical; unchanged. |
| `archive/domain/RendererDomain.md` | `archive/domain/RendererDomain.md` | Historical; unchanged. |
| `archive/milestones/Phase2_Complete.md` | `archive/milestones/Phase2_Complete.md` | Historical; unchanged. |
| `archive/milestones/Phase2_Plan.md` | `archive/milestones/Phase2_Plan.md` | Historical; unchanged. |
| `archive/milestones/Phase3_Complete.md` | `archive/milestones/Phase3_Complete.md` | Historical; unchanged. |
| `archive/milestones/Phase3_Plan.md` | `archive/milestones/Phase3_Plan.md` | Historical; unchanged. |
| `archive/milestones/Refactoring_Complete.md` | `archive/milestones/Refactoring_Complete.md` | Historical; unchanged. |
| `archive/milestones/Roadmap.md` | `archive/milestones/Roadmap.md` | Historical; unchanged. |
| `archive/phases/Phase6-ExecutionContract.md` | `archive/phases/Phase6-ExecutionContract.md` | Historical; unchanged. |
| `archive/phases/Phase6A-0-ControlSurface.md` | `archive/phases/Phase6A-0-ControlSurface.md` | Historical; unchanged. |
| `archive/phases/Phase6A-1-ExecutionProducer.md` | `archive/phases/Phase6A-1-ExecutionProducer.md` | Historical; unchanged. |
| `archive/phases/Phase6A-2-FileBackedProducer.md` | `archive/phases/Phase6A-2-FileBackedProducer.md` | Historical; unchanged. |
| `archive/phases/Phase6A-3-ProgrammaticProducer.md` | `archive/phases/Phase6A-3-ProgrammaticProducer.md` | Historical; unchanged. |
| `archive/phases/Phase6A-Overview.md` | `archive/phases/Phase6A-Overview.md` | Historical; unchanged. |

---

## 8. Other directories (not in target layers)

| Current path | Proposed path | Reason |
|--------------|---------------|--------|
| `README.md` | `README.md` | Docs root entry point; unchanged. |
| `operations/Integration.md` | (unchanged) or `developer/operations-Integration.md` | Operations/integration; not in target list. Left under `operations/` unless folded into developer. |
| `operations/telemetry-README.md` | (unchanged) | Same. |
| `operations/grafana/Timing.json` | (unchanged) | Config/asset; not a doc to re-layer. |
| `runtime/PlayoutRuntime.md` | (unchanged) or `overview/PlayoutRuntime.md` | Runtime narrative; could move to overview or stay. Left under `runtime/` unless folded. |

---

## 9. Summary

| Layer / bucket | New dir | # files moved |
|----------------|---------|----------------|
| Laws | `contracts/laws/` | 1 |
| Semantics | `contracts/semantics/` | 12 (10 from architecture + Phase8-Invariants-Compiled + AirArchitectureReference + architecture README) |
| Coordination | `contracts/coordination/` | 23 (5 from architecture + build + Phase6A + Phase8-* + Phase9 + phase10 + phases README) |
| Contracts root | `contracts/` | 2 (README, INVARIANTS-INDEX) |
| Overview | `overview/` | 4 (no moves) |
| Developer | `developer/` | 6 (no moves) |
| Archive | `archive/` | 20 (no moves) |
| Other | `operations/`, `runtime/`, root README | No re-layer in this plan |

**After migration:**

- `contracts/architecture/` is removed; its contents split between `contracts/semantics/` and `contracts/coordination/`.
- `contracts/phases/` and `contracts/phase10/` are removed; contents live under `contracts/coordination/` (with phase10 single file at `contracts/coordination/INV-P10-PIPELINE-FLOW-CONTROL.md`).
- All cross-references (e.g. in README, INVARIANTS-INDEX, and within contracts) would need to be updated in a separate step after you approve or adjust this plan.

---

**Link updates (if you automate moves):**

- `contracts/README.md` — update any paths to laws/semantics/coordination.
- `contracts/INVARIANTS-INDEX.md` — update link to `PlayoutInvariants-BroadcastGradeGuarantees.md` (e.g. `laws/PlayoutInvariants-BroadcastGradeGuarantees.md`); update Source links to phase docs under `coordination/`.
- `contracts/PlayoutInvariants-BroadcastGradeGuarantees.md` (after move to `laws/`) — update "Relationship to Other Contracts" links (e.g. Phase8 → `coordination/Phase8-Invariants-Compiled.md`, architecture contracts → `semantics/` or `coordination/`).
- Every moved contract — fix relative links to other contracts (e.g. `../PlayoutInvariants-BroadcastGradeGuarantees.md` → `../laws/PlayoutInvariants-BroadcastGradeGuarantees.md` from semantics/ or coordination/).
- `build.md` — fix Related link to Phase8-4 (path will change to coordination/).

**Next steps for you:** Review, adjust placements if needed, then decide what to automate (moves, link updates, or both).
