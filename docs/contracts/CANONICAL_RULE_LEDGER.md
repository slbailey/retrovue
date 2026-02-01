# Canonical Rule Ledger

**Status:** Authoritative
**Purpose:** Single source of truth for all active rules governing RetroVue Core and AIR
**Last Updated:** 2026-02-01

This ledger enumerates every active rule in the RetroVue system. If a rule is not in this ledger, it is not enforced. If code disagrees with a rule in this ledger, the code is wrong.

---

## Classification Key

| Classification | Meaning |
|----------------|---------|
| **LAW** | Constitutional guarantee. Cannot be overridden by contracts. Defined in `laws/` directory. |
| **CONTRACT** | Behavioral specification. Refines laws. Defined in `coordination/` or `semantics/` directories. |

| Enforcement Phase | Meaning |
|-------------------|---------|
| **P8** | Phase 8 — Timeline, segment, switch semantics |
| **P9** | Phase 9 — Output bootstrap after segment commit |
| **P10** | Phase 10 — Pipeline flow control, steady-state playout |
| **INIT** | Initialization / construction time |
| **RUNTIME** | Continuous runtime enforcement |
| **TEARDOWN** | Shutdown / cleanup phase |
| **SCHEDULE-TIME** | Core plan generation time (before AIR receives plan) |
| **ARCHITECTURE** | Structural constraint enforced by code review |

---

## Derivation Notes

Some contracts are refinements or aliases of laws. This section documents these relationships to prevent confusion.

| Contract | Derives From | Relationship |
|----------|--------------|--------------|
| INV-P8-001 | LAW-TIMELINE §1 | **Alias** — "only TimelineController assigns CT" restates law |
| INV-P8-005 | LAW-CLOCK §2 | **Alias** — "epoch unchanged until session end" restates law |
| INV-P8-006 | LAW-TIMELINE §2 | **Alias** — "producers do not read/compute CT" restates "time-blind after lock" |
| INV-P8-OUTPUT-001 | LAW-OUTPUT-LIVENESS | **Refines** — adds "explicit flush, bounded delivery" to liveness guarantee |
| INV-AUDIO-HOUSE-FORMAT-001 | LAW-AUDIO-FORMAT | **Test obligation** — contract test verifying the law |
| INV-STARVATION-FAILSAFE-001 | LAW-OUTPUT-LIVENESS | **Operationalizes** — defines bounded time for pad emission |
| INV-P9-BOOTSTRAP-READY | INV-SWITCH-READINESS | **Bootstrap minimum** — P9 requires ≥1 frame; full readiness requires ≥2 |
| INV-P10-SINK-GATE | INV-P9-SINK-LIVENESS-001 | **Complementary** — SINK-GATE prevents consumption; SINK-LIVENESS describes routing after attachment |

---

## Layer 0 — Constitutional Laws

Laws are non-negotiable. All contracts must conform to these laws.

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **LAW-CLOCK** | LAW | AIR | RUNTIME | Yes | No | — |
| **LAW-TIMELINE** | LAW | AIR | P8 | Yes | No | — |
| **LAW-OUTPUT-LIVENESS** | LAW | AIR | RUNTIME | Yes | Yes | — |
| **LAW-AUDIO-FORMAT** | LAW | AIR | INIT | No | No | — |
| **LAW-SWITCHING** | LAW | AIR | P8 | Yes | Yes | — |
| **LAW-VIDEO-DECODABILITY** | LAW | AIR | RUNTIME | Yes | Yes | — |
| **LAW-FRAME-EXECUTION** | CONTRACT | AIR | P10 | No | No | — |
| **LAW-OBS-001** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-002** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-003** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-004** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-005** | LAW | AIR | RUNTIME | No | Yes | — |

### Law Definitions

| Rule ID | One-Line Definition | Source |
|---------|---------------------|--------|
| LAW-CLOCK | MasterClock is the only source of "now"; CT never resets once established | PlayoutInvariants §1 |
| LAW-TIMELINE | TimelineController owns CT mapping; producers are time-blind after lock | PlayoutInvariants §2 |
| LAW-OUTPUT-LIVENESS | ProgramOutput never blocks; if no content → deterministic pad (black + silence) | PlayoutInvariants §3 |
| LAW-AUDIO-FORMAT | Channel defines house format; all audio normalized before OutputBus; EncoderPipeline never negotiates | PlayoutInvariants §4 |
| LAW-SWITCHING | No gaps, no PTS regression, no silence during switches | PlayoutInvariants §5 |
| LAW-VIDEO-DECODABILITY | Every segment starts with IDR; real content gates pad; AIR owns keyframes | PlayoutInvariants §6 |
| LAW-FRAME-EXECUTION | Frame index is execution authority; CT derives from frame index | PlayoutInvariants §7 *(Reclassified to CONTRACT: architectural choice, not broadcast-grade guarantee)* |
| LAW-OBS-001 | Intent evidence — every significant action has intent log | ObservabilityParityLaw |
| LAW-OBS-002 | Correlation evidence — related events share correlation ID | ObservabilityParityLaw |
| LAW-OBS-003 | Result evidence — every action has outcome log | ObservabilityParityLaw |
| LAW-OBS-004 | Timing evidence — significant events have timestamps | ObservabilityParityLaw |
| LAW-OBS-005 | Boundary evidence — phase/state transitions are logged | ObservabilityParityLaw |

---

## Layer 1 — Semantic Invariants

Truths about correctness and time.

### Primitive Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-PACING-001** | CONTRACT | ProgramOutput | RUNTIME | Yes | Yes | — |
| **INV-PACING-ENFORCEMENT-002** | CONTRACT | ProgramOutput | RUNTIME | Yes | Yes | RULE_HARVEST #14 |
| **INV-DECODE-RATE-001** | CONTRACT | FileProducer | RUNTIME | Yes | Yes | — |
| **INV-SEGMENT-CONTENT-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-PACING-001 | Frame emission rate = target_fps; render loop paced by wall clock, not CPU |
| INV-PACING-ENFORCEMENT-002 | No-drop, freeze-then-pad: max 1 frame/period; freeze ≤250ms then pad; no catch-up |
| INV-DECODE-RATE-001 | Producer sustains decode rate ≥ target_fps; buffer never drains below low-watermark |
| INV-SEGMENT-CONTENT-001 | Aggregate frame_count ≥ slot_duration × fps; Core provides content + filler plan |

### Phase 8 Semantic Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes | Notes |
|---------|---------------|-------|-------------|------|-----|------------|-------|
| **INV-P8-001** | CONTRACT | TimelineController | P8 | Yes | No | — | *Alias of LAW-TIMELINE §1* |
| **INV-P8-002** | CONTRACT | TimelineController | P8 | Yes | No | — |
| **INV-P8-003** | CONTRACT | TimelineController | P8 | Yes | No | — |
| **INV-P8-004** | CONTRACT | TimelineController | P8 | Yes | No | — |
| **INV-P8-005** | CONTRACT | TimelineController | INIT | Yes | No | — | *Alias of LAW-CLOCK §2* |
| **INV-P8-006** | CONTRACT | FileProducer | P8 | Yes | No | — | *Alias of LAW-TIMELINE §2; absorbs INV-P8-TIME-BLINDNESS* |
| **INV-P8-008** | CONTRACT | TimelineController | P8 | Yes | No | — | |
| **INV-P8-009** | CONTRACT | PlayoutEngine | P8 | Yes | No | — | |
| **INV-P8-010** | CONTRACT | TimelineController | P8 | Yes | No | — | |
| **INV-P8-011** | CONTRACT | ProgramOutput | P8 | Yes | No | — | |
| **INV-P8-012** | CONTRACT | TimelineController | P8 | No | No | — | |
| **INV-P8-OUTPUT-001** | CONTRACT | ProgramOutput | RUNTIME | Yes | Yes | — | *Refines LAW-OUTPUT-LIVENESS* |
| **INV-P8-SWITCH-002** | CONTRACT | TimelineController | P8 | Yes | No | — | |
| **INV-P8-AUDIO-CT-001** | CONTRACT | TimelineController | P8 | Yes | No | — | |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-001 | Single Timeline Writer — only TimelineController assigns CT |
| INV-P8-002 | Monotonic Advancement — CT strictly increasing |
| INV-P8-003 | Contiguous Coverage — no CT gaps |
| INV-P8-004 | Wall-Clock Correspondence — W = epoch + CT steady-state |
| INV-P8-005 | Epoch Immutability — epoch unchanged until session end |
| INV-P8-006 | Producer Time Blindness — producers do not read/compute CT; must not drop/delay/gate based on MT vs target |
| INV-P8-008 | Frame Provenance — one producer, one MT, one CT per frame |
| INV-P8-009 | Atomic Buffer Authority — one active buffer, instant switch |
| INV-P8-010 | No Cross-Producer Dependency — new CT from TC state only |
| INV-P8-011 | Backpressure Isolation — consumer slowness does not slow CT |
| INV-P8-012 | Deterministic Replay — same inputs → same CT sequence |
| INV-P8-OUTPUT-001 | Deterministic Output Liveness — explicit flush, bounded delivery |
| INV-P8-SWITCH-002 | CT and MT describe same instant at segment start; first frame locks both |
| INV-P8-AUDIO-CT-001 | Audio PTS derived from CT, init from first video frame |

### Phase 9/10 Semantic Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-P9-A-OUTPUT-SAFETY** | CONTRACT | ProgramOutput | P9 | Yes | No | — |
| **INV-P9-EMISSION-OBLIGATION** | CONTRACT | ProgramOutput | P9 | Yes | No | — |
| **INV-P10-REALTIME-THROUGHPUT** | CONTRACT | ProgramOutput | P10 | No | Yes | — |
| **INV-P10-PRODUCER-CT-AUTHORITATIVE** | CONTRACT | MpegTSOutputSink | P10 | Yes | No | RULE_HARVEST #8 |
| **INV-P10-PCR-PACED-MUX** | CONTRACT | MpegTSOutputSink | P10 | Yes | No | — |
| **INV-P10-CONTENT-BLIND** | CONTRACT | ProgramOutput | P10 | No | No | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P9-A-OUTPUT-SAFETY | No frame emitted to sink before its CT |
| INV-P9-EMISSION-OBLIGATION | Frame whose CT has arrived must eventually be emitted *(renamed from INV-P9-B-OUTPUT-LIVENESS to avoid collision with LAW-OUTPUT-LIVENESS)* |
| INV-P10-REALTIME-THROUGHPUT | Output rate matches configured frame rate within tolerance |
| INV-P10-PRODUCER-CT-AUTHORITATIVE | Muxer must use producer-provided CT (no local CT counter) |
| INV-P10-PCR-PACED-MUX | Mux loop must be time-driven, not availability-driven |
| INV-P10-CONTENT-BLIND | Frame-based rendering presents authored sequence; no pixel heuristics |

### Sink Liveness Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-P9-SINK-LIVENESS-001** | CONTRACT | OutputBus | P9 | Yes | No | — |
| **INV-P9-SINK-LIVENESS-002** | CONTRACT | OutputBus | P9 | Yes | No | — |
| **INV-P9-SINK-LIVENESS-003** | CONTRACT | OutputBus | P9 | Yes | No | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P9-SINK-LIVENESS-001 | Pre-attach discard: frames without sink silently discarded (legal) |
| INV-P9-SINK-LIVENESS-002 | Post-attach delivery: after AttachSink, all frames reach sink until DetachSink |
| INV-P9-SINK-LIVENESS-003 | Sink stability: sink pointer stable between attach and explicit detach |

### Video Decodability Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-AIR-IDR-BEFORE-OUTPUT** | CONTRACT | EncoderPipeline | P9 | Yes | Yes | — |
| **INV-AIR-CONTENT-BEFORE-PAD** | CONTRACT | ProgramOutput | P9 | Yes | Yes | — |
| **INV-AUDIO-HOUSE-FORMAT-001** | CONTRACT | EncoderPipeline | INIT | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-AIR-IDR-BEFORE-OUTPUT | AIR must not emit video packets until IDR produced; gate resets on switch |
| INV-AIR-CONTENT-BEFORE-PAD | Pad frames only after first real decoded content frame routed to output |
| INV-AUDIO-HOUSE-FORMAT-001 | All audio reaching EncoderPipeline must be house format; reject non-house input |

### Frame Execution Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-FRAME-001** | CONTRACT | Core | SCHEDULE-TIME | No | No | — |
| **INV-FRAME-002** | CONTRACT | Core | SCHEDULE-TIME | No | No | — |
| **INV-FRAME-003** | CONTRACT | TimelineController | P10 | No | No | — |
| **INV-P10-FRAME-INDEXED-EXECUTION** | CONTRACT | FileProducer | P10 | No | No | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-FRAME-001 | Segment boundaries are frame-indexed, not time-based |
| INV-FRAME-002 | Padding is expressed in frames, never duration |
| INV-FRAME-003 | CT derives from frame index: ct = epoch + (frame_index × frame_duration) |
| INV-P10-FRAME-INDEXED-EXECUTION | Producers track progress by frame index, not elapsed time |

---

## Layer 2 — Coordination Invariants

Write barriers, switch orchestration, readiness, backpressure.

### Phase 8 Coordination

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-P8-007** | CONTRACT | TimelineController | P8 | Yes | No | — |
| **INV-P8-SWITCH-001** | CONTRACT | PlayoutEngine | P8 | Yes | No | — |
| **INV-P8-SHADOW-PACE** | CONTRACT | FileProducer | P8 | Yes | No | — |
| **INV-P8-AUDIO-GATE** | CONTRACT | FileProducer | P8 | Yes | No | — |
| **INV-P8-SEGMENT-COMMIT** | CONTRACT | TimelineController | P8 | Yes | No | — |
| **INV-P8-SEGMENT-COMMIT-EDGE** | CONTRACT | TimelineController | P8 | Yes | No | — |
| **INV-P8-SWITCH-ARMED** | CONTRACT | PlayoutEngine | P8 | Yes | No | — |
| **INV-P8-WRITE-BARRIER-DEFERRED** | CONTRACT | PlayoutEngine | P8 | Yes | No | — |
| **INV-P8-EOF-SWITCH** | CONTRACT | PlayoutEngine | P8 | Yes | No | — |
| **INV-P8-PREVIEW-EOF** | CONTRACT | PlayoutEngine | P8 | Yes | No | — |
| **INV-P8-SWITCHWATCHER-STOP-TARGET-001** | CONTRACT | PlayoutEngine | P8 | Yes | Yes | — |
| **INV-P8-SWITCHWATCHER-COMMITGEN-EDGE-SAFETY-002** | CONTRACT | PlayoutEngine | P8 | Yes | No | — |
| **INV-P8-COMMITGEN-RETIREMENT-SEMANTICS-003** | CONTRACT | PlayoutEngine | P8 | Yes | No | — |
| **INV-P8-SHADOW-FLUSH** | CONTRACT | FileProducer | P8 | Yes | No | — |
| **INV-P8-ZERO-FRAME-READY** | CONTRACT | FileProducer | P8 | Yes | No | — |
| **INV-P8-ZERO-FRAME-BOOTSTRAP** | CONTRACT | ProgramOutput | P8 | Yes | No | — |
| **INV-P8-AV-SYNC** | CONTRACT | FileProducer | P8 | Yes | No | — |
| **INV-P8-AUDIO-PRIME-001** | CONTRACT | MpegTSOutputSink | P8 | Yes | No | — |
| **INV-P8-IO-UDS-001** | CONTRACT | MpegTSOutputSink | P8 | No | No | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-007 | Write Barrier Finality — post-barrier writes = 0 |
| INV-P8-SWITCH-001 | Mapping pending BEFORE preview fills; write barrier on live before new segment |
| INV-P8-SHADOW-PACE | Shadow caches first frame, waits in place; no run-ahead decode |
| INV-P8-AUDIO-GATE | Audio gated only while shadow (and while mapping pending) |
| INV-P8-SEGMENT-COMMIT | First frame admitted → segment commits, owns CT; old segment RequestStop |
| INV-P8-SEGMENT-COMMIT-EDGE | Generation counter per commit for multi-switch edge detection |
| INV-P8-SWITCH-ARMED | No LoadPreview while switch armed; FATAL if reset reached while armed |
| INV-P8-WRITE-BARRIER-DEFERRED | Write barrier on live waits until preview shadow ready |
| INV-P8-EOF-SWITCH | Live EOF → switch completes immediately (no buffer depth wait) |
| INV-P8-PREVIEW-EOF | Preview EOF with frames → complete with lower thresholds |
| INV-P8-SWITCHWATCHER-STOP-TARGET-001 | Switch machinery must not stop/disable successor as result of bookkeeping |
| INV-P8-SWITCHWATCHER-COMMITGEN-EDGE-SAFETY-002 | Post-swap commit-gen transitions must not retire successor |
| INV-P8-COMMITGEN-RETIREMENT-SEMANTICS-003 | Retirement ignores successor activation or same-segment bookkeeping |
| INV-P8-SHADOW-FLUSH | On leaving shadow: flush cached first frame to buffer immediately |
| INV-P8-ZERO-FRAME-READY | When frame_count=0, signal shadow_decode_ready immediately |
| INV-P8-ZERO-FRAME-BOOTSTRAP | When no_content_segment=true, bypass CONTENT-BEFORE-PAD gate |
| INV-P8-AV-SYNC | Audio gated until video locks mapping (no audio ahead of video at switch) |
| INV-P8-AUDIO-PRIME-001 | No header until first audio; no video encode before header written |
| INV-P8-IO-UDS-001 | UDS/output must not block on prebuffer; prebuffering disabled for UDS |

### Phase 9 Coordination

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-P9-FLUSH** | CONTRACT | FileProducer | P9 | Yes | No | — |
| **INV-P9-BOOTSTRAP-READY** | CONTRACT | PlayoutEngine | P9 | Yes | Yes | — |
| **INV-P9-NO-DEADLOCK** | CONTRACT | ProgramOutput | P9 | Yes | No | — |
| **INV-P9-WRITE-BARRIER-SYMMETRIC** | CONTRACT | PlayoutEngine | P9 | Yes | No | — |
| **INV-P9-BOOT-LIVENESS** | CONTRACT | MpegTSOutputSink | P9 | Yes | No | — |
| **INV-P9-AUDIO-LIVENESS** | CONTRACT | MpegTSOutputSink | P9 | Yes | No | — |
| **INV-P9-PCR-AUDIO-MASTER** | CONTRACT | MpegTSOutputSink | P9 | Yes | No | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P9-FLUSH | Cached shadow frame pushed to buffer synchronously when shadow disabled |
| INV-P9-BOOTSTRAP-READY | Readiness = commit detected AND ≥1 video frame, not deep buffering |
| INV-P9-NO-DEADLOCK | Output routing must not wait on conditions requiring output routing |
| INV-P9-WRITE-BARRIER-SYMMETRIC | When write barrier set, audio and video suppressed symmetrically |
| INV-P9-BOOT-LIVENESS | Newly attached sink emits decodable TS within bounded time |
| INV-P9-AUDIO-LIVENESS | From header written, output contains continuous monotonic audio PTS |
| INV-P9-PCR-AUDIO-MASTER | Audio owns PCR at startup |

### Phase 10 Coordination

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-P10-BACKPRESSURE-SYMMETRIC** | CONTRACT | FileProducer, FrameRingBuffer | P10 | No | Yes | — |
| **INV-P10-PRODUCER-THROTTLE** | CONTRACT | FileProducer | P10 | No | Yes | — |
| **INV-P10-BUFFER-EQUILIBRIUM** | CONTRACT | FrameRingBuffer | P10 | No | Yes | — |
| **INV-P10-NO-SILENCE-INJECTION** | CONTRACT | MpegTSOutputSink | P10 | No | No | — |
| **INV-P10-SINK-GATE** | CONTRACT | ProgramOutput | P10 | No | No | — |
| **INV-OUTPUT-READY-BEFORE-LIVE** | CONTRACT | PlayoutEngine | P10 | No | Yes | — |
| **INV-SWITCH-READINESS** | CONTRACT | PlayoutEngine | P10 | No | Yes | — |
| **INV-SWITCH-SUCCESSOR-EMISSION** | CONTRACT | TimelineController | P10 | Yes | Yes | — |
| **RULE-P10-DECODE-GATE** | CONTRACT | FileProducer | P10 | No | Yes | RULE_HARVEST #39 |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P10-BACKPRESSURE-SYMMETRIC | When buffer full, both audio and video throttled symmetrically |
| INV-P10-PRODUCER-THROTTLE | Producer decode rate governed by consumer capacity, not decoder speed |
| INV-P10-BUFFER-EQUILIBRIUM | Buffer depth oscillates around target, not unbounded or zero |
| INV-P10-NO-SILENCE-INJECTION | Audio liveness disabled when PCR-paced mux active |
| INV-P10-SINK-GATE | ProgramOutput must not consume frames before sink attached *(complementary to INV-P9-SINK-LIVENESS-001: SINK-GATE prevents consumption; SINK-LIVENESS describes routing)* |
| INV-OUTPUT-READY-BEFORE-LIVE | Channel must not enter LIVE until output pipeline observable |
| INV-SWITCH-READINESS | SwitchToLive completes when video ≥2, sink attached, format locked *(full readiness; INV-P9-BOOTSTRAP-READY defines bootstrap minimum of ≥1 frame)* |
| INV-SWITCH-SUCCESSOR-EMISSION | Switch not complete until real successor video frame emitted |
| RULE-P10-DECODE-GATE | Slot-based gating at decode level; block at capacity, unblock when one slot frees |

---

## Layer 3 — Diagnostic Invariants

Logging requirements, drop policies, enforcement rails.

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-P8-WRITE-BARRIER-DIAG** | CONTRACT | FileProducer | P8 | No | Yes | — |
| **INV-P8-AUDIO-PRIME-STALL** | CONTRACT | MpegTSOutputSink | P8 | No | Yes | — |
| **INV-P10-FRAME-DROP-POLICY** | CONTRACT | ProgramOutput | P10 | No | Yes | RULE_HARVEST #3,#14 |
| **INV-P10-PAD-REASON** | CONTRACT | ProgramOutput | P10 | No | Yes | — |
| **INV-NO-PAD-WHILE-DEPTH-HIGH** | CONTRACT | ProgramOutput | P10 | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-WRITE-BARRIER-DIAG | On writes_disabled_: drop frame, log INV-P8-WRITE-BARRIER |
| INV-P8-AUDIO-PRIME-STALL | Log if video dropped too long waiting for audio prime |
| INV-P10-FRAME-DROP-POLICY | Frame drops forbidden except explicit conditions; must log with reason |
| INV-P10-PAD-REASON | Every pad frame classified by root cause (BUFFER_TRULY_EMPTY, etc.) |
| INV-NO-PAD-WHILE-DEPTH-HIGH | Pad emission with depth ≥10 is a violation; must log |

---

## Proposed Invariants (Pending Promotion)

These invariants are drafted from RULE_HARVEST analysis and await promotion to canonical status.

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes | Notes |
|---------|---------------|-------|-------------|------|-----|------------|-------|
| **INV-SINK-TIMING-OWNERSHIP-001** | CONTRACT | MpegTSOutputSink | RUNTIME | No | No | RULE_HARVEST #2 | |
| **INV-SINK-PIXEL-FORMAT-FAULT-001** | CONTRACT | EncoderPipeline | RUNTIME | No | Yes | RULE_HARVEST #6 | |
| **INV-ENCODER-NO-B-FRAMES-001** | CONTRACT | EncoderPipeline | INIT | No | Yes | RULE_HARVEST #7 | |
| **INV-ENCODER-GOP-FIXED-001** | CONTRACT | EncoderPipeline | INIT | No | Yes | RULE_HARVEST #9 | |
| **INV-ENCODER-BITRATE-BOUNDED-001** | CONTRACT | EncoderPipeline | RUNTIME | No | Yes | RULE_HARVEST #11 | |
| **INV-SINK-FAULT-LATCH-001** | CONTRACT | MpegTSOutputSink | RUNTIME | No | Yes | RULE_HARVEST #29 | |
| **INV-SINK-PRODUCER-THREAD-ISOLATION-001** | CONTRACT | MpegTSOutputSink | RUNTIME | No | Yes | RULE_HARVEST #12,#13 | |
| **INV-LIFECYCLE-IDEMPOTENT-001** | CONTRACT | PlayoutEngine, MpegTSOutputSink, FileProducer, ProgramOutput | INIT/TEARDOWN | No | Yes | RULE_HARVEST #18,#19 | |
| **INV-TEARDOWN-BOUNDED-001** | CONTRACT | MpegTSOutputSink | TEARDOWN | No | Yes | RULE_HARVEST #20-23 | |
| **INV-CONFIG-IMMUTABLE-001** | CONTRACT | MpegTSOutputSink, EncoderPipeline, FileProducer, TimelineController | INIT | No | Yes | RULE_HARVEST #35 | |
| **INV-SINK-ROLE-BOUNDARY-001** | CONTRACT | MpegTSOutputSink | ARCHITECTURE | No | No | RULE_HARVEST #36 | |
| **INV-STARVATION-FAILSAFE-001** | CONTRACT | ProgramOutput | RUNTIME | No | Yes | RULE_HARVEST #40 | *Operationalizes LAW-OUTPUT-LIVENESS* |
| **INV-TIMING-DESYNC-LOG-001** | CONTRACT | MpegTSOutputSink | RUNTIME | No | Yes | RULE_HARVEST #15 | |
| **INV-NETWORK-BACKPRESSURE-DROP-001** | CONTRACT | MpegTSOutputSink | RUNTIME | No | Yes | RULE_HARVEST #3-5 | |

---

## Cross-Domain Rules (Core/AIR Boundary)

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **RULE-CANONICAL-GATING** | CONTRACT | Core + AIR | SCHEDULE-TIME, P8 | Yes | Yes | RULE_HARVEST #52,#53,#58-60; absorbs INV-CANONICAL-CONTENT-ONLY-001 |
| **RULE-CORE-RUNTIME-READONLY** | CONTRACT | Core | RUNTIME | No | No | RULE_HARVEST #49,#56,#57 |
| **RULE-CORE-PLAYLOG-AUTHORITY** | CONTRACT | Core | RUNTIME | No | No | RULE_HARVEST #55 |
| **INV-P8-SWITCH-TIMING** | CONTRACT | Core | RUNTIME | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| RULE-CANONICAL-GATING | Only assets with canonical=true may be scheduled (Core) and played (AIR); dual enforcement |
| RULE-CORE-RUNTIME-READONLY | Runtime services treat config tables as immutable |
| RULE-CORE-PLAYLOG-AUTHORITY | Only ScheduleService writes playlog_event; ChannelManager reads only |
| INV-P8-SWITCH-TIMING | Core: switch at boundary; log if pending after boundary *(moved from Layer 3 Diagnostic)* |

---

## Superseded Rules (Historical Reference)

These rules from RULE_HARVEST are explicitly superseded and should not be enforced.

| Original Rule | Superseded By | Reason |
|---------------|---------------|--------|
| RULE_HARVEST #3 (network drop, not block) | INV-NETWORK-BACKPRESSURE-DROP-001 | Refined to distinguish network layer from timing layer |
| RULE_HARVEST #8 (PTS from MasterClock) | INV-P10-PRODUCER-CT-AUTHORITATIVE | Clarified: producer provides CT; muxer uses it |
| RULE_HARVEST #14 (drop if >2 frames behind) | INV-PACING-ENFORCEMENT-002 | Replaced by freeze-then-pad; no drops |
| RULE_HARVEST #37 (≤33ms latency p95) | — | OBSOLETE: Phase 10 uses different metrics |
| RULE_HARVEST #39 (3-tick backpressure) | RULE-P10-DECODE-GATE | Replaced by slot-based flow control |
| RULE_HARVEST #45 (2-3 frame lead) | INV-P10-BUFFER-EQUILIBRIUM | Replaced by configurable buffer depth |

---

## Test Coverage Summary

| Layer | Total Rules | With Tests | Coverage |
|-------|-------------|------------|----------|
| Layer 0 (Laws) | 11 | 6 | 55% |
| Layer 1 (Semantic) | 32 | 25 | 78% |
| Layer 2 (Coordination) | 32 | 26 | 81% |
| Layer 3 (Diagnostic) | 5 | 0 | 0% |
| Cross-Domain | 4 | 1 | 25% |
| Proposed | 14 | 0 | 0% |
| **Total** | **98** | **58** | **59%** |

---

## Log Coverage Summary

| Layer | Total Rules | With Logs | Coverage |
|-------|-------------|-----------|----------|
| Layer 0 (Laws) | 11 | 7 | 64% |
| Layer 1 (Semantic) | 32 | 9 | 28% |
| Layer 2 (Coordination) | 32 | 8 | 25% |
| Layer 3 (Diagnostic) | 5 | 5 | 100% |
| Cross-Domain | 4 | 2 | 50% |
| Proposed | 14 | 12 | 86% |
| **Total** | **98** | **43** | **44%** |

---

## Document References

| Document | Location | Content |
|----------|----------|---------|
| PlayoutInvariants-BroadcastGradeGuarantees | `pkg/air/docs/contracts/laws/` | Layer 0 Laws |
| ObservabilityParityLaw | `pkg/air/docs/contracts/laws/` | Observability Laws |
| INVARIANTS-INDEX | `pkg/air/docs/contracts/` | Navigational index |
| Phase8-Invariants-Compiled | `pkg/air/docs/contracts/semantics/` | Phase 8 detail |
| Phase9-OutputBootstrap | `pkg/air/docs/contracts/coordination/` | Phase 9 detail |
| INV-P10-PIPELINE-FLOW-CONTROL | `pkg/air/docs/contracts/coordination/` | Phase 10 detail |
| PrimitiveInvariants | `pkg/air/docs/contracts/semantics/` | Primitive assumptions |
| PROPOSED-INVARIANTS-FROM-HARVEST | `pkg/air/docs/contracts/` | Pending promotion |

---

## Maintenance

This ledger is the single source of truth. When adding new rules:

1. Assign a unique Rule ID following the naming convention
2. Classify as LAW or CONTRACT
3. Identify the Owner component
4. Specify Enforcement Phase
5. Document Test Coverage (yes/no)
6. Document Log Coverage (yes/no)
7. List any Superseded Rules
8. Update coverage summaries

**Rule:** If code enforces a rule not in this ledger, the code is wrong. If this ledger lists a rule that code does not enforce, the code is wrong.
