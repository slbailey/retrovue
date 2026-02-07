# Invariants Index

**This index is navigational only. Canonical contract documents remain authoritative.**

**Purpose:** Single entry point to find every codified invariant by ID. Use this when coding or reviewing: look up the ID, read the one-line summary and type, then follow the link to the authoritative contract for full text and tests.

**Rule:** If code disagrees with an invariant, the code is wrong — fix the code or change the contract explicitly.

---

## How to use this index

| Goal | Go to |
|------|--------|
| **Constitutional laws** (Layer 0) | [PlayoutInvariants-BroadcastGradeGuarantees.md](laws/PlayoutInvariants-BroadcastGradeGuarantees.md) · [ObservabilityParityLaw.md](laws/ObservabilityParityLaw.md) |
| **Find an invariant by ID** | Tables below by layer; follow **Source** in each section |
| **Phase 8 timeline / segment / switch** | [Phase8-Invariants-Compiled.md](semantics/Phase8-Invariants-Compiled.md) |
| **Phase 9 bootstrap / audio liveness** | [Phase9-OutputBootstrap.md](coordination/Phase9-OutputBootstrap.md) |
| **Phase 10 pipeline flow control** | [INV-P10-PIPELINE-FLOW-CONTROL.md](coordination/INV-P10-PIPELINE-FLOW-CONTROL.md) |
| **Primitive invariants** (pacing, decode rate, content depth) | [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) |
| **Component-level contracts** | [README.md](semantics/README.md) |

**Invariant types:** **Law** (constitutional); **Semantic** (correctness and time); **Coordination** (barriers, switch, readiness, backpressure); **Diagnostic** (logging, stall/drop policies, violation logs). When an invariant could fit multiple categories, this index assigns the highest applicable layer (Law > Semantic > Coordination > Diagnostic).

---

## Layer 0 – Constitutional Laws

Top-level broadcast guarantees. **Authoritative definition lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](laws/PlayoutInvariants-BroadcastGradeGuarantees.md).** Phase invariants refine these; they do not replace them.

| Law | One-line | Type |
|-----|----------|------|
| **Clock** | MasterClock is the only source of "now"; CT never resets once established. | Law |
| **Timeline** | TimelineController owns CT mapping; producers are time-blind after lock. | Law |
| **Output Liveness** | ProgramOutput never blocks; if no content → deterministic pad (black + silence). | Law |
| **INV-TICK-GUARANTEED-OUTPUT** | Every output tick emits exactly one frame; fallback chain: real → freeze → black. No conditional can prevent emission. Contract: [INV-TICK-GUARANTEED-OUTPUT.md](INV-TICK-GUARANTEED-OUTPUT.md) | Law |
| **Audio Format** | Channel defines house format; all audio normalized before OutputBus; EncoderPipeline never negotiates. Contract test: **INV-AUDIO-HOUSE-FORMAT-001**. | Law |
| **Switching** | No gaps, no PTS regression, no silence during switches. | Law |
| **Observability Parity** | Intent, correlation, result, timing, and boundary evidence (LAW-OBS-001 through LAW-OBS-005). | Law |
| **LAW-RUNTIME-AUDIO-AUTHORITY** | When producer_audio_authoritative=true, producer MUST emit audio ≥90% of nominal rate, or mode auto-downgrades to silence-injection. | Law |

**Source:** [ObservabilityParityLaw.md](laws/ObservabilityParityLaw.md)

---

## Layer 1 – Semantic Invariants

Truths about correctness and time: CT monotonicity, provenance, determinism, time-blindness, wall-clock correspondence, output safety/liveness semantics, format correctness.

**Source:** [Phase8-Invariants-Compiled.md](semantics/Phase8-Invariants-Compiled.md) · [Phase8-3-PreviewSwitchToLive.md](coordination/Phase8-3-PreviewSwitchToLive.md) · [Phase9-OutputBootstrap.md](coordination/Phase9-OutputBootstrap.md) · [INV-P10-PIPELINE-FLOW-CONTROL.md](coordination/INV-P10-PIPELINE-FLOW-CONTROL.md) · [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) · [RealTimeHoldPolicy.md](semantics/RealTimeHoldPolicy.md) · Core `ScheduleManagerPhase8Contract.md`

### Primitive Invariants

These are foundational assumptions from which other invariants derive. Violation of a primitive causes cascade failures across multiple derived invariants. See [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) for full behavioral contracts including violation discrimination matrix.

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-PACING-001** | Frame emission rate = target_fps; render loop paced by wall clock, not CPU | `ProgramOutput` | Semantic (Primitive) |
| **INV-PACING-ENFORCEMENT-002** | No-drop, freeze-then-pad: max 1 frame/period; freeze last frame ≤250ms; then pad; no catch-up, no drops | `ProgramOutput` | Semantic (Enforcement) |
| **INV-DECODE-RATE-001** | Producer sustains decode rate ≥ target_fps (burst allowed); buffer never drains below low-watermark | `FileProducer` | Semantic (Primitive) |
| **INV-SEGMENT-CONTENT-001** | Aggregate frame_count of all segments in slot ≥ slot_duration × fps; Core provides content + filler plan | `Core` (external) | Semantic (Primitive) |

### Sink Liveness Invariants

Output sink attachment policy. See [SinkLivenessPolicy.md](semantics/SinkLivenessPolicy.md) for full behavioral contract.

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-P9-SINK-LIVENESS-001** | Pre-attach discard: frames routed to bus without sink are silently discarded (legal) | `OutputBus` | Semantic |
| **INV-P9-SINK-LIVENESS-002** | Post-attach delivery: after AttachSink succeeds, all frames MUST reach sink until DetachSink | `OutputBus` | Semantic |
| **INV-P9-SINK-LIVENESS-003** | Sink stability: sink pointer SHALL NOT become null between attach and explicit detach | `OutputBus` | Semantic |
| **INV-SINK-NO-IMPLICIT-EOF** | After AttachStream, sink MUST emit TS until explicit stop/detach/fatal error. Producer EOF, empty queues, segment boundaries MUST NOT terminate emission. Contract: [INV-SINK-NO-IMPLICIT-EOF.md](INV-SINK-NO-IMPLICIT-EOF.md) | `MpegTSOutputSink` | Semantic |

### Derived Semantic Invariants

| ID | One-line | Type |
|----|----------|------|
| INV-P8-001 | Single Timeline Writer — only TimelineController assigns CT | Semantic |
| INV-P8-002 | Monotonic Advancement — CT strictly increasing | Semantic |
| INV-P8-003 | Contiguous Coverage — no CT gaps. *Defines timeline continuity.* | Semantic |
| INV-P8-004 | Wall-Clock Correspondence — W = epoch + CT steady-state | Semantic |
| INV-P8-005 | Epoch Immutability — epoch unchanged until session end | Semantic |
| INV-P8-006 | Producer Time Blindness — producers do not read/compute CT | Semantic |
| INV-P8-008 | Frame Provenance — one producer, one MT, one CT per frame | Semantic |
| INV-P8-009 | Atomic Buffer Authority — one active buffer, instant switch | Semantic |
| INV-P8-010 | No Cross-Producer Dependency — new CT from TC state only | Semantic |
| INV-P8-011 | Backpressure Isolation — consumer slowness does not slow CT | Semantic |
| INV-P8-012 | Deterministic Replay — same inputs → same CT sequence | Semantic |
| INV-P8-OUTPUT-001 | Deterministic Output Liveness — explicit flush, bounded delivery. *Defines emission continuity.* | Semantic |
| INV-P8-TIME-BLINDNESS | Producer must not drop on MT vs target, delay for alignment, gate audio on video PTS; all admission via TimelineController | Semantic |
| INV-P8-SWITCH-002 | CT and MT describe same instant at segment start; first frame locks both | Semantic |
| INV-P8-AUDIO-CT-001 | Audio PTS derived from CT, init from first video frame | Semantic |
| INV-P9-A-OUTPUT-SAFETY | No frame emitted to sink before its CT | Semantic |
| INV-P9-B-OUTPUT-LIVENESS | Frame whose CT has arrived must eventually be emitted (or dropped); audio processed even if video empty | Semantic |
| INV-P10-REALTIME-THROUGHPUT | Output rate must match configured frame rate within tolerance during steady-state | Semantic |
| INV-P10-PRODUCER-CT-AUTHORITATIVE | Muxer must use producer-provided CT (no local CT counter) | Semantic |
| INV-P10-PCR-PACED-MUX | Mux loop must be time-driven, not availability-driven | Semantic |
| INV-AUDIO-HOUSE-FORMAT-001 | All audio reaching EncoderPipeline (including pad) must be house format; pipeline rejects or fails loudly on non-house input; pad uses same path, CT, cadence, format as program. Test: INV_AUDIO_HOUSE_FORMAT_001_HouseFormatOnly (stub) | Semantic |
| INV-AIR-IDR-BEFORE-OUTPUT | AIR must not emit any video packets for a segment until an IDR frame has been produced by the encoder for that segment. Gate resets on segment switch (ResetOutputTiming). | Semantic |
| **INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT** | After AttachStream, emit decodable TS within 500ms using fallback if needed. Output-first, content-second. Contract: [INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT.md](INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT.md) | Semantic |
| ~~INV-AIR-CONTENT-BEFORE-PAD~~ | **RETIRED** — Replaced by INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT. Old philosophy (gate output on content) was backwards. | — |

### Media Time Authority Invariants

Decoded media time governs block execution and segment transitions. See [INV-AIR-MEDIA-TIME.md](semantics/INV-AIR-MEDIA-TIME.md) for full behavioral contract.

| ID | One-line | Owner | Type |
|----|----------|-------|------|
| **INV-AIR-MEDIA-TIME-001** | Block execution governed by decoded media time, not rounded FPS math | `TickProducer` | Semantic |
| **INV-AIR-MEDIA-TIME-002** | No cumulative drift — PTS-anchored tracking bounds error to one frame period | `TickProducer` | Semantic |
| **INV-AIR-MEDIA-TIME-003** | Fence alignment — decoded media time converges to block end within one frame | `TickProducer` | Semantic |
| **INV-AIR-MEDIA-TIME-004** | Cadence independence — output FPS does not affect media time tracking | `TickProducer` | Semantic |
| **INV-AIR-MEDIA-TIME-005** | Pad is never primary — padding only when decoded media time exceeds block end | `TickProducer` | Semantic |

**Overlap note:** INV-P8-003 defines **timeline continuity** (no gaps in CT). INV-P8-OUTPUT-001 defines **emission continuity** (output explicitly flushed and delivered in bounded time). Both are required; they address different continuities.

---

## Layer 2 – Coordination / Concurrency Invariants

Write barriers, shadow decode, switch arming, backpressure symmetry, readiness, no-deadlock rules, ordering and sequencing that coordinate components.

**Source:** [Phase8-Invariants-Compiled.md](semantics/Phase8-Invariants-Compiled.md) · [Phase8-3-PreviewSwitchToLive.md](coordination/Phase8-3-PreviewSwitchToLive.md) · [Phase9-OutputBootstrap.md](coordination/Phase9-OutputBootstrap.md) · [INV-P10-PIPELINE-FLOW-CONTROL.md](coordination/INV-P10-PIPELINE-FLOW-CONTROL.md) · [SwitchWatcherStopTargetContract.md](coordination/SwitchWatcherStopTargetContract.md)

| ID | One-line | Type |
|----|----------|------|
| INV-P8-007 | Write Barrier Finality — post-barrier writes = 0 | Coordination |
| INV-P8-SWITCH-001 | Mapping must be pending BEFORE preview fills; write barrier on live before new segment | Coordination |
| INV-P8-SHADOW-PACE | Shadow caches first frame, waits in place; no run-ahead decode | Coordination |
| INV-P8-AUDIO-GATE | Audio gated only while shadow (and while mapping pending) | Coordination |
| INV-P8-SEGMENT-COMMIT | First frame admitted → segment commits, owns CT; old segment RequestStop | Coordination |
| INV-P8-SEGMENT-COMMIT-EDGE | Generation counter per commit for multi-switch edge detection | Coordination |
| INV-P8-SWITCH-ARMED | No LoadPreview while switch armed; FATAL if reset code reached while armed | Coordination |
| INV-P8-WRITE-BARRIER-DEFERRED | Write barrier on live MUST wait until preview shadow decode ready | Coordination |
| INV-P8-EOF-SWITCH | Live producer EOF → switch completes immediately (do not block on buffer depth) | Coordination |
| INV-P8-PREVIEW-EOF | Preview EOF with frames → complete with lower thresholds (e.g. ≥1 video, ≥1 audio) | Coordination |
| **INV-P8-SWITCHWATCHER-STOP-TARGET-001** | Switch machinery must not stop/disable/write-barrier successor as result of switch-completion or commit bookkeeping | Coordination |
| **INV-P8-SWITCHWATCHER-COMMITGEN-EDGE-SAFETY-002** | Post-swap commit-gen transitions must not trigger retirement actions against successor | Coordination |
| **INV-P8-COMMITGEN-RETIREMENT-SEMANTICS-003** | Retirement decisions must ignore commit-gen transitions representing successor activation or same-segment bookkeeping | Coordination |
| INV-P8-SHADOW-FLUSH | On leaving shadow: flush cached first frame to buffer immediately | Coordination |
| INV-P8-ZERO-FRAME-READY | When frame_count=0, signal shadow_decode_ready=true immediately; vacuous flush returns true | Coordination |
| INV-P8-ZERO-FRAME-BOOTSTRAP | When no_content_segment=true, bypass CONTENT-BEFORE-PAD gate; first pad frame bootstraps encoder | Coordination |
| INV-P8-AUDIO-GATE Fix #2 | mapping_locked_this_iteration_ so audio same iteration ungate after video locks | Coordination |
| INV-P8-AV-SYNC | Audio gated until video locks mapping (no audio ahead of video at switch) | Coordination |
| INV-P8-AUDIO-PRIME-001 | No header until first audio; no video encode before header written | Coordination |
| INV-P8-IO-UDS-001 | UDS/output must not block on prebuffer; prebuffering disabled for UDS path | Coordination |
| INV-P9-FLUSH | Cached shadow frame pushed to buffer synchronously when shadow disabled. Test: INV_P9_FLUSH_Synchronous | Coordination |
| INV-P9-BOOTSTRAP-READY | Readiness = commit detected AND ≥1 video frame, not deep buffering. Test: G9_002, AudioZeroFrameAcceptable | Coordination |
| INV-P9-NO-DEADLOCK | Output routing must not wait on conditions that require output routing. Test: G9_003_NoDeadlockOnSwitch | Coordination |
| INV-P9-WRITE-BARRIER-SYMMETRIC | When write barrier set, audio and video suppressed symmetrically; audio push checks writes_disabled_. Test: Audio liveness tests | Coordination |
| INV-P9-BOOT-LIVENESS | Newly attached sink must emit decodable TS within bounded time, even if audio not yet available. Test: G9_001, G9_004 | Coordination |
| INV-P9-AUDIO-LIVENESS | From header written, output must contain continuous, monotonic audio PTS with correct pacing (silence if no decoded audio yet). Test: AUDIO_LIVENESS_001/002/003 | Coordination |
| INV-P9-PCR-AUDIO-MASTER | Audio owns PCR at startup. Test: PCR_AUDIO_MASTER_001/002, VLC_STARTUP_SMOKE | Coordination |
| **INV-P9-TS-EMISSION-LIVENESS** | First decodable TS packet MUST be emitted within 500ms of PCR-PACE timing initialization. Refines INV-P9-BOOT-LIVENESS. | Coordination |
| INV-P10-BACKPRESSURE-SYMMETRIC | When buffer full, both audio and video throttled symmetrically | Coordination |
| INV-P10-PRODUCER-THROTTLE | Producer decode rate governed by consumer capacity, not decoder speed | Coordination |
| INV-P10-BUFFER-EQUILIBRIUM | Buffer depth must oscillate around target, not grow unbounded or drain to zero | Coordination |
| INV-P10-NO-SILENCE-INJECTION | Audio liveness must be disabled when PCR-paced mux is active | Coordination |
| **INV-P10-AUDIO-VIDEO-GATE** | When segment video epoch is established, first audio frame MUST be queued within 100ms. Complements INV-P8-AV-SYNC. | Coordination |

---

## Layer 3 – Diagnostic / Enforcement Invariants

Logging requirements, stall diagnostics, drop policies, safety rails, test-only guards. These make violations visible and enforce explicit handling.

**Source:** [Phase8-Invariants-Compiled.md](semantics/Phase8-Invariants-Compiled.md) · [INV-P10-PIPELINE-FLOW-CONTROL.md](coordination/INV-P10-PIPELINE-FLOW-CONTROL.md)

| ID | One-line | Type |
|----|----------|------|
| INV-P8-WRITE-BARRIER-DIAG | On writes_disabled_: drop frame, log INV-P8-WRITE-BARRIER | Diagnostic |
| INV-P8-AUDIO-PRIME-STALL | Diagnostic: log if video dropped too long waiting for audio prime | Diagnostic |
| INV-P8-SWITCH-TIMING | Core: switch at boundary; log if pending after boundary; violation log if complete after boundary | Diagnostic |
| INV-P10-FRAME-DROP-POLICY | Frame drops forbidden except under explicit conditions; must log INV-P10-FRAME-DROP | Diagnostic |

---

## Where to find what (for coding)

| You need… | Document / location |
|-----------|----------------------|
| **Laws** (Layer 0) | [PlayoutInvariants-BroadcastGradeGuarantees.md](laws/PlayoutInvariants-BroadcastGradeGuarantees.md) |
| **Invariants by layer** (this index) | Layer 1–3 tables above |
| **Phase 8** (timeline, segment, switch) | [Phase8-Invariants-Compiled.md](semantics/Phase8-Invariants-Compiled.md) + [Phase8-3-PreviewSwitchToLive.md](coordination/Phase8-3-PreviewSwitchToLive.md) |
| **Phase 9** (bootstrap, audio liveness) | [Phase9-OutputBootstrap.md](coordination/Phase9-OutputBootstrap.md) |
| **Phase 10** (flow control, backpressure, mux) | [INV-P10-PIPELINE-FLOW-CONTROL.md](coordination/INV-P10-PIPELINE-FLOW-CONTROL.md) |
| **Primitive invariants** (pacing, decode rate, content) | [PrimitiveInvariants.md](semantics/PrimitiveInvariants.md) |
| **RealTimeHold** (freeze-then-pad, no-drop policy) | [RealTimeHoldPolicy.md](semantics/RealTimeHoldPolicy.md) |
| **Component contracts** | [README.md](semantics/README.md) |
| **Broadcast-grade output** (unconditional emission) | [INV-TICK-GUARANTEED-OUTPUT.md](INV-TICK-GUARANTEED-OUTPUT.md) · [INV-SINK-NO-IMPLICIT-EOF.md](INV-SINK-NO-IMPLICIT-EOF.md) · [INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT.md](INV-BOOT-IMMEDIATE-DECODABLE-OUTPUT.md) |
| **Phase narrative** (what was built in Phase 8.0–8.9) | [Phase8-Overview.md](coordination/Phase8-Overview.md) · [README.md](coordination/README.md) |
| **Build / codec rules** | [build.md](coordination/build.md) |
| **Architecture reference** | [AirArchitectureReference.md](semantics/AirArchitectureReference.md) |

Canonical contract documents take precedence over this index. When in doubt, the contract wins.
