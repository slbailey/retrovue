# Canonical Rule Ledger

**Status:** Authoritative
**Purpose:** Single source of truth for all active rules governing RetroVue Core and AIR
**Last Updated:** 2026-02-02
**Last Audit:** 2026-02-02 (Live Session Authority); Phase 11F completed 2026-02-02; Phase 12 created 2026-02-02

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
| INV-P9-BOOTSTRAP-READY | INV-SWITCH-READINESS | **Bootstrap minimum** — P9 requires ≥1 frame; full readiness goal is ≥2. *(Note: INV-SWITCH-READINESS demoted to diagnostic goal per audit 2026-02-01)* |
| INV-P10-SINK-GATE | INV-P9-SINK-LIVENESS-001 | **Complementary** — SINK-GATE prevents consumption; SINK-LIVENESS describes routing after attachment |
| INV-P9-TS-EMISSION-LIVENESS | INV-P9-BOOT-LIVENESS | **Refines** — adds specific 500ms deadline to "bounded time" |
| INV-P10-AUDIO-VIDEO-GATE | LAW-OUTPUT-LIVENESS | **Prevents violation** — ensures audio availability so mux can emit TS |
| LAW-RUNTIME-AUDIO-AUTHORITY | LAW-AUDIO-FORMAT | **Operationalizes** — defines producer-authoritative mode enforcement |
| INV-BOUNDARY-TOLERANCE-001 | LAW-SWITCHING | **Operationalizes** — adds frame-level timing tolerance to switching law |
| INV-BOUNDARY-DECLARED-001 | LAW-SWITCHING | **Operationalizes** — requires declarative boundary time in protocol |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | LAW-AUDIO-FORMAT, INV-P10-BACKPRESSURE-SYMMETRIC | **Refines** — explicitly forbids audio sample drops under backpressure |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | LAW-AUTHORITY-HIERARCHY | **Derives** — scheduling feasibility determined before execution; runtime MUST NOT discover or repair infeasible boundaries |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | INV-SCHED-PLAN-BEFORE-EXEC-001, INV-CONTROL-NO-POLL-001, LAW-AUTHORITY-HIERARCHY | **Derives** — startup latency is a schedule content constraint; first boundary must account for launch overhead without offsetting planning_time |
| INV-SWITCH-ISSUANCE-DEADLINE-001 | LAW-AUTHORITY-HIERARCHY, INV-SWITCH-DEADLINE-AUTHORITATIVE-001, INV-CONTROL-NO-POLL-001 | **Derives** — if switch execution is deadline-authoritative, switch issuance must also be deadline-scheduled; cadence-based detection is forbidden |
| INV-LEADTIME-MEASUREMENT-001 | LAW-AUTHORITY-HIERARCHY, INV-CONTROL-NO-POLL-001, INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | **Derives** — lead-time feasibility uses issuance timestamp, not receipt time; transport jitter must not affect feasibility |
| INV-CONTROL-NO-POLL-001 | AIR-010 (Prefeed Ordering), INV-SCHED-PLAN-BEFORE-EXEC-001 | **Operationalizes** — forbids poll/retry semantics for switch readiness; presupposes planning-time feasibility |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | INV-BOUNDARY-DECLARED-001, LAW-CLOCK, LAW-AUTHORITY-HIERARCHY | **Refines** — AIR executes at declared time regardless of readiness; clock supersedes frame completion |
| LAW-FRAME-EXECUTION | LAW-AUTHORITY-HIERARCHY | **Subordinate** — governs execution precision (HOW), not transition timing (WHEN); clock authority takes precedence |
| INV-FRAME-001 | LAW-AUTHORITY-HIERARCHY | **Subordinate** — frame-indexed boundaries for execution, not for delaying clock-scheduled transitions |
| INV-FRAME-003 | LAW-AUTHORITY-HIERARCHY | **Subordinate** — CT derivation within segment; frame completion does not gate switch execution |
| INV-SWITCH-ISSUANCE-TERMINAL-001 | INV-SWITCH-ISSUANCE-DEADLINE-001, LAW-AUTHORITY-HIERARCHY | **Enforces** — exception during switch issuance is terminal; boundary transitions to FAILED_TERMINAL |
| INV-SWITCH-ISSUANCE-ONESHOT-001 | INV-SWITCH-ISSUANCE-DEADLINE-001, INV-CONTROL-NO-POLL-001 | **Enforces** — SwitchToLive is issued exactly once per boundary; duplicates are suppressed or fatal |
| INV-BOUNDARY-LIFECYCLE-001 | LAW-AUTHORITY-HIERARCHY, INV-SCHED-PLAN-BEFORE-EXEC-001 | **Enforces** — boundary state transitions are unidirectional; illegal transitions force FAILED_TERMINAL |
| INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 | INV-BOUNDARY-DECLARED-001, INV-SCHED-PLAN-BEFORE-EXEC-001 | **Enforces** — target_boundary_ms must equal plan-derived boundary, not `now + X` |
| INV-TEARDOWN-STABLE-STATE-001 | LAW-AUTHORITY-HIERARCHY, INV-BOUNDARY-LIFECYCLE-001 | **Enforces** — teardown deferred until boundary state is stable; transient states block immediate teardown |
| INV-TEARDOWN-GRACE-TIMEOUT-001 | INV-TEARDOWN-STABLE-STATE-001 | **Bounds** — deferred teardown cannot wait indefinitely; grace timeout forces FAILED_TERMINAL |
| INV-TEARDOWN-NO-NEW-WORK-001 | INV-TEARDOWN-STABLE-STATE-001 | **Enforces** — no new boundary work scheduled when teardown is pending |
| INV-VIEWER-COUNT-ADVISORY-001 | LAW-AUTHORITY-HIERARCHY, INV-TEARDOWN-STABLE-STATE-001 | **Clarifies** — viewer count triggers but does not force teardown during transient states |
| INV-LIVE-SESSION-AUTHORITY-001 | INV-BOUNDARY-LIFECYCLE-001 | **Defines** — channel is durably live only when `_boundary_state == LIVE` |
| INV-TERMINAL-SCHEDULER-HALT-001 | INV-BOUNDARY-LIFECYCLE-001, Phase 12 §7 | **Extends** — FAILED_TERMINAL is intent-absorbing, not just transition-absorbing; no scheduling intent after terminal failure |
| INV-TERMINAL-TIMER-CLEARED-001 | INV-TERMINAL-SCHEDULER-HALT-001 | **Enforces** — prevents ghost timer execution after terminal failure; timers cancelled on FAILED_TERMINAL entry |
| INV-SESSION-CREATION-UNGATED-001 | LAW-AUTHORITY-HIERARCHY, Phase 12 §8 | **Defines** — session creation not gated on boundary feasibility; viewer tune-in always creates session if resources available |
| INV-STARTUP-CONVERGENCE-001 | INV-SESSION-CREATION-UNGATED-001, Phase 12 §8 | **Defines** — infeasible boundaries skipped during startup convergence; session must converge within bounded window |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | INV-SCHED-PLAN-BEFORE-EXEC-001, INV-STARTUP-CONVERGENCE-001 | **Amended** — applies to boundary commitment, not session creation; pre-convergence infeasibility causes skip, post-convergence infeasibility is FATAL |
| INV-P8-SEGMENT-EOF-DISTINCT-001 | LAW-AUTHORITY-HIERARCHY, LAW-TIMELINE | **Enforces** — schedule-driven timeline; EOF is event, not authority; CT continues after EOF |
| INV-P8-CONTENT-DEFICIT-FILL-001 | LAW-OUTPUT-LIVENESS, INV-P8-SEGMENT-EOF-DISTINCT-001 | **Operationalizes** — fills gap between EOF and boundary with pad; preserves TS cadence |
| INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | LAW-AUTHORITY-HIERARCHY, INV-SCHED-PLAN-BEFORE-EXEC-001 | **Enforces** — frame_count is planning authority; short content triggers fill, long content truncated |
| LAW-TS-DISCOVERABILITY | LAW-OUTPUT-LIVENESS, LAW-VIDEO-DECODABILITY | **Derived consequence** — if output must be live (LAW-OUTPUT-LIVENESS) and decodable (LAW-VIDEO-DECODABILITY), then program structure must be discoverable at any join time. PAT/PMT emission is coupled to media frame writes in FFmpeg; discoverability is satisfied as a downstream consequence of liveness, not independently enforced. |
| INV-TS-CONTROL-PLANE-CADENCE | LAW-TS-DISCOVERABILITY, LAW-OUTPUT-LIVENESS | **Detects** — monitors for 500ms wall-time gaps in TS emission; logs LAW-OUTPUT-LIVENESS violation when detected. No independent enforcement — PAT/PMT emission is coupled to media frame writes in FFmpeg. |

---

## Authority Model (Canonical)

This section defines the authoritative model for resolving apparent conflicts between time-based and frame-based rules.

```
┌─────────────────────────────────────────────────────────────────┐
│                    LAW-AUTHORITY-HIERARCHY                       │
│         "Clock authority supersedes frame completion"            │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   LAW-CLOCK   │    │ LAW-SWITCHING │    │LAW-FRAME-EXEC │
│               │    │               │    │               │
│ WHEN things   │    │ WHEN switch   │    │ HOW precisely │
│ happen        │    │ executes      │    │ cuts happen   │
│               │    │ (± 1 frame)   │    │               │
│ [AUTHORITY]   │    │ [AUTHORITY]   │    │ [EXECUTION]   │
└───────────────┘    └───────────────┘    └───────────────┘
                              │
                              ▼
                    ┌───────────────┐
                    │INV-SEGMENT-   │
                    │CONTENT-001    │
                    │               │
                    │ WHETHER       │
                    │ content is    │
                    │ sufficient    │
                    │               │
                    │ [VALIDATION]  │
                    │ (clock does   │
                    │  not wait)    │
                    └───────────────┘
```

**Key Principle:** If frame completion and clock deadline conflict, clock wins. Frame-based rules describe *how to execute* within a segment, not *whether to execute* a scheduled transition.

**Anti-Pattern (BUG):** Code that waits for frame completion before executing a clock-scheduled switch. This inverts the hierarchy and causes boundary timing violations.

**Correct Pattern:** Schedule switch at clock time. If content isn't ready, use safety rails (pad/silence). Never delay the clock.

---

## Layer 0 — Constitutional Laws

Laws are non-negotiable. All contracts must conform to these laws.

### Authority Hierarchy (Supreme)

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **LAW-AUTHORITY-HIERARCHY** | LAW | System | ARCHITECTURE | No | No | — |

| Rule ID | One-Line Definition | Source |
|---------|---------------------|--------|
| LAW-AUTHORITY-HIERARCHY | **Clock authority supersedes frame completion for switch execution.** Clock (LAW-CLOCK) decides WHEN transitions occur. Frame boundary (LAW-FRAME-EXECUTION) decides HOW precisely cuts happen. Frame count (INV-SEGMENT-CONTENT-001) decides WHETHER content is sufficient, but clock does not wait for frame completion. | Audit 2026-02-01 |

**Rationale:** This hierarchy resolves the apparent contradiction between clock-based and frame-based rules. Without this hierarchy, code may incorrectly wait for frame completion before executing a clock-scheduled transition, causing the exact boundary timing violations observed in production.

### Core Laws

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **LAW-CLOCK** | LAW | AIR | RUNTIME | Yes | No | — |
| **LAW-TIMELINE** | LAW | AIR | P8 | Yes | No | — |
| **LAW-OUTPUT-LIVENESS** | LAW | AIR | RUNTIME | Yes | Yes | — |
| **LAW-AUDIO-FORMAT** | LAW | AIR | INIT | No | No | — |
| **LAW-SWITCHING** | LAW | AIR | P8 | Yes | Yes | — |
| **LAW-VIDEO-DECODABILITY** | LAW | AIR | RUNTIME | Yes | Yes | — |
| **LAW-TS-DISCOVERABILITY** | LAW | MpegTSOutputSink | RUNTIME | No | Yes | — |
| **LAW-FRAME-EXECUTION** | CONTRACT | AIR | P10 | No | No | — |
| **LAW-OBS-001** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-002** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-003** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-004** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-OBS-005** | LAW | AIR | RUNTIME | No | Yes | — |
| **LAW-RUNTIME-AUDIO-AUTHORITY** | LAW | PlayoutEngine | RUNTIME | No | Yes | — |

### Law Definitions

| Rule ID | One-Line Definition | Source |
|---------|---------------------|--------|
| LAW-CLOCK | MasterClock is the only source of "now"; CT never resets once established | PlayoutInvariants §1 |
| LAW-TIMELINE | TimelineController owns CT mapping; producers are time-blind after lock | PlayoutInvariants §2 |
| LAW-OUTPUT-LIVENESS | ProgramOutput never blocks; if no content → deterministic pad (black + silence) | PlayoutInvariants §3 |
| LAW-AUDIO-FORMAT | Channel defines house format; all audio normalized before OutputBus; EncoderPipeline never negotiates | PlayoutInvariants §4 |
| LAW-SWITCHING | No gaps, no PTS regression, no silence during switches. **Transitions MUST complete within one video frame duration of scheduled absolute boundary time.** | PlayoutInvariants §5 |
| LAW-VIDEO-DECODABILITY | Every segment starts with IDR; real content gates pad; AIR owns keyframes | PlayoutInvariants §6 |
| LAW-TS-DISCOVERABILITY | Transport stream MUST be self-describing to any late-joining observer; PAT/PMT are control-plane (not media) and MUST NOT be gated by CT pacing, buffer depth, or media availability; MpegTSOutputSink owns runtime enforcement | Late-joiner incident 2026-02-04 |
| LAW-FRAME-EXECUTION | Frame index governs execution precision (HOW cuts happen), not transition timing (WHEN cuts happen). CT derives from frame index within a segment. **Does not override LAW-CLOCK for switch timing.** | PlayoutInvariants §7 *(Reclassified to CONTRACT; subordinate to LAW-AUTHORITY-HIERARCHY)* |
| LAW-OBS-001 | Intent evidence — every significant action has intent log | ObservabilityParityLaw |
| LAW-OBS-002 | Correlation evidence — related events share correlation ID | ObservabilityParityLaw |
| LAW-OBS-003 | Result evidence — every action has outcome log | ObservabilityParityLaw |
| LAW-OBS-004 | Timing evidence — significant events have timestamps | ObservabilityParityLaw |
| LAW-OBS-005 | Boundary evidence — phase/state transitions are logged | ObservabilityParityLaw |
| LAW-RUNTIME-AUDIO-AUTHORITY | When producer_audio_authoritative=true, producer MUST emit audio ≥90% of nominal rate, or mode auto-downgrades to silence-injection | Incident 2026-02-01 |

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

### Phase 8 Content Deficit Invariants (Amendment 2026-02-02)

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes | Notes |
|---------|---------------|-------|-------------|------|-----|------------|-------|
| **INV-P8-SEGMENT-EOF-DISTINCT-001** | CONTRACT | PlayoutEngine | P8 | Pending | Yes | — | EOF ≠ boundary |
| **INV-P8-CONTENT-DEFICIT-FILL-001** | CONTRACT | ProgramOutput | P8 | Pending | Yes | — | Pad fills EOF-to-boundary gap |
| **INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001** | CONTRACT | FileProducer | P8 | Pending | Yes | — | frame_count is planning authority |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P8-SEGMENT-EOF-DISTINCT-001 | Segment EOF (decoder exhaustion) is distinct from segment end (scheduled boundary). EOF is an event within the segment; boundary is the scheduled instant at which the switch occurs. Timeline advancement driven by scheduled segment end time, not by EOF. |
| INV-P8-CONTENT-DEFICIT-FILL-001 | If live decoder reaches EOF before the scheduled segment end time, the gap (content deficit) MUST be filled using a deterministic fill strategy at real-time cadence until the boundary; pad (black/silence) is the guaranteed fallback. Output liveness and TS cadence preserved; mux never stalls. |
| INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | frame_count in the playout plan is planning authority from Core. AIR receives this authority and enforces runtime adaptation against it. If actual content is shorter than planned, INV-P8-CONTENT-DEFICIT-FILL-001 applies; if longer, segment end time still governs (schedule authoritative). |

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

### Transport Stream Discoverability Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-TS-CONTROL-PLANE-CADENCE** | CONTRACT | MpegTSOutputSink | RUNTIME | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-TS-CONTROL-PLANE-CADENCE | **DETECTOR:** If no TS bytes emitted for ≥500ms wall time while MuxLoop is running, log LAW-OUTPUT-LIVENESS violation. No independent enforcement — PAT/PMT emission is coupled to video frame writes in FFmpeg. |

**INV-TS-CONTROL-PLANE-CADENCE Details:**

- **Nature:** This is a **DETECTOR**, not an enforcer. There is no independent mechanism to emit PAT/PMT without emitting media frames — FFmpeg's `av_write_frame(nullptr)` does NOT trigger PAT/PMT resend; `resend_headers` and `pat_pmt_at_frames` flags only fire on actual packet writes.

- **Definition (Sliding Window):** At any wall-time T, there SHOULD exist TS bytes **emitted** in the interval (T−500ms, T]. If this condition fails, it indicates a LAW-OUTPUT-LIVENESS violation (not a separate discoverability enforcement gap).

- **"Emitted" means:** Any TS bytes observed leaving the sink (after `WriteToFdCallback` → `SocketSink`). Since PAT/PMT piggyback on video frame writes, no TS bytes = no PAT/PMT.

- **Detection Point:** `MpegTSOutputSink::MuxLoop` — track wall time since last muxer output; if threshold exceeded, log violation.

- **Log Requirement:** Yes — log when TS emission stalls:
  ```
  [MpegTSOutputSink] LAW-OUTPUT-LIVENESS VIOLATION: no TS emitted for Nms (control-plane cannot be discoverable)
  [MpegTSOutputSink] INV-TS-CONTROL-PLANE-CADENCE: idle_ms=N vq=V aq=A pcr_paced_active=B silence_injection_disabled=C
  ```
  This logs the root cause (liveness violation) and includes queue state for diagnosis.

- **Derives From:** LAW-TS-DISCOVERABILITY (which itself derives from LAW-OUTPUT-LIVENESS)

- **Why Not Enforcement:** FFmpeg's mpegts muxer does not provide an API to emit PAT/PMT independently of media. The `av_write_frame(NULL)` call only flushes buffered PES payloads; `MPEGTS_FLAG_REEMIT_PAT_PMT` is a one-shot flag cleared after first use; `MPEGTS_FLAG_PAT_PMT_AT_FRAMES` only triggers on actual video frame writes. The only way to guarantee PAT/PMT cadence is to guarantee media (or pad) frame cadence — i.e., enforce LAW-OUTPUT-LIVENESS.

- **Phase 10 Compliance:** Does NOT violate Phase 10:
  - No new thread (MuxLoop already runs)
  - No new queue (detection only, no emission path)
  - No new timing authority (wall time tracking already exists for CT pacing)
  - No blocking (detection is read-only)
  - No backpressure (logging does not affect data path)

### Frame Execution Invariants

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-FRAME-001** | CONTRACT | Core | SCHEDULE-TIME | No | No | — |
| **INV-FRAME-002** | CONTRACT | Core | SCHEDULE-TIME | No | No | — |
| **INV-FRAME-003** | CONTRACT | TimelineController | P10 | No | No | — |
| **INV-P10-FRAME-INDEXED-EXECUTION** | CONTRACT | FileProducer | P10 | No | No | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-FRAME-001 | Segment boundaries are frame-indexed for execution precision. **Does not delay clock-scheduled transitions.** *(Execution-level, not authority-level per LAW-AUTHORITY-HIERARCHY)* |
| INV-FRAME-002 | Padding is expressed in frames, never duration |
| INV-FRAME-003 | CT derives from frame index within a segment: ct = epoch + (frame_index × frame_duration). **Frame completion does not gate switch execution.** *(Execution-level, not authority-level per LAW-AUTHORITY-HIERARCHY)* |
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
| INV-P8-SWITCH-TIMING | Core: switch at boundary; **MUST complete within one frame of boundary**; violation log if >1 frame late |

### Broadcast-Grade Timing Invariants (Audit 2026-02-01)

These invariants were added to address observed violations of broadcast-grade timing requirements.

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-BOUNDARY-TOLERANCE-001** | CONTRACT | PlayoutEngine | P8 | No | Yes | — |
| **INV-BOUNDARY-DECLARED-001** | CONTRACT | Core + AIR | P8 | No | Yes | — |
| **INV-AUDIO-SAMPLE-CONTINUITY-001** | CONTRACT | FileProducer, FrameRingBuffer | RUNTIME | No | Yes | — |
| **INV-SCHED-PLAN-BEFORE-EXEC-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes | — |
| **INV-STARTUP-BOUNDARY-FEASIBILITY-001** | CONTRACT | Core | SCHEDULE-TIME | No | Yes | — |
| **INV-SWITCH-ISSUANCE-DEADLINE-001** | CONTRACT | Core | RUNTIME | No | Yes | — |
| **INV-LEADTIME-MEASUREMENT-001** | CONTRACT | Core + AIR | P8 | No | Yes | — |
| **INV-CONTROL-NO-POLL-001** | CONTRACT | Core | RUNTIME | No | Yes | — |
| **INV-SWITCH-DEADLINE-AUTHORITATIVE-001** | CONTRACT | PlayoutEngine | P8 | No | Yes | — |
| **INV-SWITCH-ISSUANCE-TERMINAL-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes | — |
| **INV-SWITCH-ISSUANCE-ONESHOT-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes | — |
| **INV-BOUNDARY-LIFECYCLE-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes | — |
| **INV-BOUNDARY-DECLARED-MATCHES-PLAN-001** | CONTRACT | ChannelManager | RUNTIME | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-BOUNDARY-TOLERANCE-001 | Grid boundary transitions MUST complete within one video frame duration (33.33ms at 30fps) of the absolute scheduled boundary time |
| INV-BOUNDARY-DECLARED-001 | SwitchToLive MUST include `target_boundary_time_ms` parameter; Core declares intent, AIR executes at that time |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | Audio sample continuity MUST be preserved; audio samples MUST NOT be dropped due to queue backpressure; overflow triggers producer throttling |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Scheduling feasibility MUST be determined once, at planning time. Only boundaries that are already feasible by construction may enter execution. Runtime MUST NOT discover, repair, delay, or re-evaluate boundary feasibility. |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | The first scheduled boundary MUST satisfy `boundary_time >= station_utc + startup_latency + MIN_PREFEED_LEAD_TIME`. This is a constraint on schedule content, not on planning_time. |
| INV-SWITCH-ISSUANCE-DEADLINE-001 | SwitchToLive issuance MUST be deadline-scheduled and issued no later than `boundary_time - MIN_PREFEED_LEAD_TIME`. Cadence-based detection, tick loops, and jitter padding are forbidden. |
| INV-LEADTIME-MEASUREMENT-001 | Prefeed lead time MUST be evaluated using the issuance timestamp supplied by Core (`issued_at_time_ms`), not AIR receipt time. Transport jitter MUST NOT affect feasibility determination. |
| INV-CONTROL-NO-POLL-001 | Core MUST NOT poll AIR for switch readiness; NOT_READY indicates protocol error (prefeed too late), not a condition to retry. Tick-based reissuance is forbidden. |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | When `target_boundary_time_ms` is provided, AIR MUST execute the switch at that wall-clock time ± 1 frame; internal readiness is AIR's responsibility |
| INV-SWITCH-ISSUANCE-TERMINAL-001 | Exception during SwitchToLive issuance MUST transition boundary to FAILED_TERMINAL state. No retry, no re-arm. |
| INV-SWITCH-ISSUANCE-ONESHOT-001 | SwitchToLive MUST be issued exactly once per boundary. Duplicate attempts are suppressed; duplicate into FAILED_TERMINAL is fatal. |
| INV-BOUNDARY-LIFECYCLE-001 | Boundary state transitions MUST be unidirectional (NONE→PLANNED→...→LIVE or →FAILED_TERMINAL). Illegal transitions force FAILED_TERMINAL. |
| INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 | target_boundary_ms sent to AIR MUST equal the boundary computed from the active playout plan, NOT a derived `now + X` value. |

#### INV-STARTUP-BOUNDARY-FEASIBILITY-001 (Full Definition)

At channel startup, a non-zero interval elapses between schedule planning (station_utc) and the moment Core can issue execution-time commands (LoadPreview, SwitchToLive). This interval includes AIR process spawn, ChannelManager initialization, gRPC channel establishment, and protocol handshake.

The schedule or playout plan MUST supply a first boundary whose scheduled time satisfies:

```
boundary_time >= station_utc + startup_latency + MIN_PREFEED_LEAD_TIME
```

Where:
- `station_utc` is the planning time (unmodified)
- `startup_latency` is a bounded, declared upper limit on channel launch overhead
- `MIN_PREFEED_LEAD_TIME` is the minimum lead time required by INV-CONTROL-NO-POLL-001

If no such boundary exists in the schedule, planning MUST fail immediately with a FATAL error, because runtime execution has no legal mechanism to recover from startup infeasibility.

**Derivation:**

| Parent Rule | Relationship |
|-------------|--------------|
| LAW-AUTHORITY-HIERARCHY | Clock authority is absolute; startup overhead does not suspend the clock |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Feasibility is determined at planning time; schedule content must be feasible by construction |
| INV-CONTROL-NO-POLL-001 | No retry or poll semantics; if first boundary cannot be honored, there is no recovery |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch executes at declared time; startup delay does not shift the boundary |

**Rationale:**

When INV-SCHED-PLAN-BEFORE-EXEC-001 is correctly enforced, runtime cannot compensate for infeasible boundaries. If the first boundary is infeasible due to startup latency, the channel will FATAL at runtime—correctly, per contract. This invariant makes the constraint explicit at the schedule/plan level, allowing planning to fail early rather than at runtime.

**Non-Goals (Explicitly Forbidden):**

This invariant does NOT permit:
- Offsetting `planning_time` to absorb startup latency
- Adding margin to `planning_time` calculations
- Delaying, padding, or adjusting the first boundary at runtime
- Retry or re-planning after startup begins
- Tick-based discovery of startup infeasibility
- "Soft" failures that allow degraded startup

**Operational Implication:**

Schedules must be constructed such that the first boundary of any startable segment is far enough in the future to accommodate startup overhead. This is a constraint on schedule generation and content selection, not on runtime behavior. Mock and test schedules are subject to the same startup feasibility constraint as production schedules.

#### INV-SWITCH-ISSUANCE-DEADLINE-001 (Full Definition)

If switch execution is deadline-authoritative (INV-SWITCH-DEADLINE-AUTHORITATIVE-001), then switch issuance must also be deadline-scheduled. The timing of SwitchToLive issuance MUST NOT depend on runtime loop frequency, tick cadence, or scheduling jitter.

**Definition of "deadline-scheduled":** The issuance is registered once with the event loop as a timed callback or task at plan time; it is not discovered later by periodic checks.

Core MUST compute a single, deterministic issuance time for each boundary:

```
issue_at = boundary_time - MIN_PREFEED_LEAD_TIME
```

SwitchToLive MUST be issued no later than `issue_at`; issuing earlier is permitted. Late issuance (after `issue_at`) is a violation and MUST be treated as fatal. The issuance MUST NOT be triggered by cadence-based polling that detects `now >= issue_at`.

**Derivation:**

| Parent Rule | Relationship |
|-------------|--------------|
| LAW-AUTHORITY-HIERARCHY | Clock authority is absolute; issuance timing derives from clock, not loop frequency |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Execution is deadline-bound; issuance must be equally precise |
| INV-CONTROL-NO-POLL-001 | No poll/retry semantics; extends to issuance timing |

**Rationale:**

Deadline-authoritative execution is undermined if issuance timing depends on runtime cadence. A tick loop running at 1-second intervals introduces up to 1 second of jitter. Padding lead times to absorb jitter reintroduces the timing luck that deadline-authoritative semantics were designed to eliminate. The only correct solution is deadline-scheduled issuance.

**Non-Goals (Explicitly Forbidden):**

This invariant does NOT permit:
- Cadence-based detection (`if now >= switch_at` in a tick loop)
- Tick-jitter padding or lead-time inflation to absorb loop frequency
- Loop-frequency-dependent correctness
- Runtime "catch-up" issuance after missed cadence
- Health-check-triggered switch issuance
- Polling-based approximation of deadline timing
- Using `asyncio.sleep(delay)` without an underlying deadline primitive

**Anti-Patterns (FORBIDDEN):**

```python
# WRONG: Cadence-based detection in tick loop
async def tick(self):
    now = datetime.now(timezone.utc)
    if now >= self._switch_at:  # VIOLATION: cadence-based detection
        await self._issue_switch_to_live()
```

```python
# WRONG: Inflating lead time to absorb tick jitter
_switch_lead_seconds = MIN_PREFEED_LEAD_TIME + 1  # VIOLATION: jitter padding
```

```python
# WRONG: Loop frequency determines correctness
async def run(self):
    while True:
        await asyncio.sleep(0.5)  # VIOLATION: correctness depends on sleep interval
        self._check_pending_switches()
```

```python
# WRONG: Catch-up issuance after missed cadence
if now > switch_at and not switch_issued:
    logger.warning("late issuance")  # VIOLATION: runtime catch-up
    await self._issue_switch_to_live()
```

**Correct Pattern:**

```python
# RIGHT: Deadline-scheduled issuance via event loop primitive
def _schedule_switch_issuance(self, boundary_time: datetime) -> None:
    issue_at = boundary_time - MIN_PREFEED_LEAD_TIME
    delay = (issue_at - datetime.now(timezone.utc)).total_seconds()

    # Register timed callback at plan time; event loop fires at deadline
    self._loop.call_later(delay, self._issue_switch_to_live_callback, boundary_time)
```

**Operational Implication:**

Switch issuance is a scheduled event, not a detected condition. Core computes `issue_at` once when the boundary is planned, registers a timed callback with the event loop to fire at that time, and issues SwitchToLive when the callback executes. No tick loop, health check, or cadence-based mechanism participates in issuance timing.

#### INV-LEADTIME-MEASUREMENT-001 (Full Definition)

Prefeed lead time MUST be evaluated using the issuance timestamp supplied by Core, not AIR's receipt time. Transport jitter (RPC latency, scheduling delays) MUST NOT affect feasibility determination.

**Protocol Requirement:**

SwitchToLiveRequest MUST include `issued_at_time_ms` (epoch milliseconds, station/master clock basis). Core populates this field with the wall-clock time at the moment SwitchToLive is issued. If `issued_at_time_ms` is absent or zero, receipt-time evaluation applies for backward compatibility only; this mode is deprecated and MUST NOT be relied upon by Core.

**Feasibility Evaluation:**

AIR MUST compute lead time as:

```
lead_time_ms = target_boundary_time_ms - issued_at_time_ms
```

AIR MUST enforce:

```
lead_time_ms >= kMinPrefeedLeadTimeMs
```

AIR MUST NOT use receipt time for feasibility. Receipt time MAY be logged for diagnostics.

**Clock Skew Detection:**

AIR MUST compute and log transport skew:

```
skew_ms = receipt_time_ms - issued_at_time_ms
```

If `skew_ms > 250`, AIR MUST log `PROTOCOL_CLOCK_SKEW` warning. This indicates clock divergence or excessive transport delay, but does NOT affect feasibility determination.

**Derivation:**

| Parent Rule | Relationship |
|-------------|--------------|
| LAW-AUTHORITY-HIERARCHY | Clock authority is absolute; measurement basis must be unambiguous |
| INV-CONTROL-NO-POLL-001 | No retry; feasibility must be deterministic at issuance |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Execution is deadline-bound; feasibility check must not introduce jitter |

**Rationale:**

If Core issues SwitchToLive at exactly `boundary_time - MIN_PREFEED_LEAD_TIME`, and AIR evaluates using receipt time, any non-zero RPC latency causes `lead_time_AIR < MIN_PREFEED`, guaranteeing rejection. The only stable measurement basis is the issuance timestamp, which Core controls and includes in the request.

**Non-Goals (Explicitly Forbidden):**

- Using AIR receipt time for feasibility determination
- Adding jitter padding to MIN_PREFEED_LEAD_TIME
- Silently compensating for clock skew
- Retrying on PROTOCOL_VIOLATION

**Log Format:**

```
[AIR] INV-LEADTIME-MEASUREMENT-001: issued_at_ms=%ld receipt_ms=%ld target_ms=%ld lead_time_ms=%ld min_required_ms=%ld skew_ms=%ld result=%s
```

#### INV-SWITCH-ISSUANCE-TERMINAL-001 (Full Definition)

Exception during SwitchToLive issuance MUST transition the boundary to FAILED_TERMINAL state. No retry, no re-arm, no tick-based reissuance.

**Trigger:**
Any exception in `_on_switch_issue_deadline()` or `_issue_switch_to_live()`.

**Behavior:**
1. Log FATAL with `INV-SWITCH-ISSUANCE-TERMINAL-001`
2. Transition boundary state to `FAILED_TERMINAL`
3. Set `_pending_fatal = SchedulingError(...)`
4. Do NOT re-register timer
5. Do NOT allow tick to retry

**Rationale:**
Per INV-SCHED-PLAN-BEFORE-EXEC-001, boundaries are feasible by construction. An exception during issuance indicates a system error (bug, network failure, invalid state), not a recoverable condition. Retry would violate INV-CONTROL-NO-POLL-001 and INV-SWITCH-ISSUANCE-ONESHOT-001.

**Log Format:**
```
INV-SWITCH-ISSUANCE-TERMINAL-001 FATAL: Switch issuance failed for boundary %s: %s
```

#### INV-SWITCH-ISSUANCE-ONESHOT-001 (Full Definition)

SwitchToLive MUST be issued exactly once per boundary. Duplicate issuance attempts are suppressed. Duplicate into FAILED_TERMINAL is treated as a control-flow bug (FATAL).

**Trigger:**
Any attempt to issue SwitchToLive when boundary state ≥ SWITCH_ISSUED.

**Behavior:**
- If state is `SWITCH_ISSUED` or `LIVE`: suppress, log warning
- If state is `FAILED_TERMINAL`: log FATAL, set `_pending_fatal`

**Guard Implementation:**
```python
def _guard_switch_issuance(self, boundary_time: datetime) -> bool:
    if self._boundary_state in (BoundaryState.SWITCH_ISSUED, BoundaryState.LIVE):
        self._logger.warning("INV-SWITCH-ISSUANCE-ONESHOT-001: Suppressed duplicate")
        return False
    if self._boundary_state == BoundaryState.FAILED_TERMINAL:
        self._logger.error("INV-SWITCH-ISSUANCE-ONESHOT-001 FATAL: Duplicate into terminal")
        self._pending_fatal = SchedulingError(...)
        return False
    return True
```

**Rationale:**
One-shot issuance is a corollary of deadline-scheduled semantics. If issuance is timer-scheduled at plan time, there is exactly one timer firing. Duplicate attempts indicate broken control flow (tick-based detection, exception swallowing, or state machine violation).

#### INV-BOUNDARY-LIFECYCLE-001 (Full Definition)

Boundary state transitions MUST be unidirectional and follow the defined state machine. Illegal transitions force immediate transition to FAILED_TERMINAL.

**State Machine:**
```
NONE → PLANNED → PRELOAD_ISSUED → SWITCH_SCHEDULED → SWITCH_ISSUED → LIVE
                                                                      ↑
Any state ──────────────────────────────────────────────────→ FAILED_TERMINAL
```

**Allowed Transitions:**
| From | To |
|------|----|
| NONE | PLANNED |
| PLANNED | PRELOAD_ISSUED, FAILED_TERMINAL |
| PRELOAD_ISSUED | SWITCH_SCHEDULED, FAILED_TERMINAL |
| SWITCH_SCHEDULED | SWITCH_ISSUED, FAILED_TERMINAL |
| SWITCH_ISSUED | LIVE, FAILED_TERMINAL |
| LIVE | NONE, PLANNED (next boundary) |
| FAILED_TERMINAL | (absorbing) |

**Terminal States:**
- `LIVE`: Success terminal for this boundary; next boundary can be planned
- `FAILED_TERMINAL`: Failure terminal; absorbing, no exit

**Behavior on Violation:**
1. Log `INV-BOUNDARY-LIFECYCLE-001 VIOLATION: Illegal transition %s -> %s`
2. Force transition to `FAILED_TERMINAL`
3. Set `_pending_fatal`

#### INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 (Full Definition)

The `target_boundary_ms` sent to AIR MUST equal the boundary computed from the active playout plan (segment boundary, block boundary), NOT a derived `now + X` value.

**Trigger:**
When constructing SwitchToLiveRequest.

**Enforcement:**
```python
plan_boundary_ms = self._get_plan_boundary_ms()  # From segment_end
target_boundary_ms = int(boundary_time.timestamp() * 1000)

if plan_boundary_ms is not None and target_boundary_ms != plan_boundary_ms:
    self._logger.error(
        "INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 FATAL: target=%d plan=%d",
        target_boundary_ms, plan_boundary_ms
    )
    self._transition_boundary_state(BoundaryState.FAILED_TERMINAL)
    return
```

**Rationale:**
Boundaries derived from `now + lead_time` drift with execution timing and retry attempts. Plan-derived boundaries are deterministic and auditable. This invariant prevents a class of "looks fine but drifts" bugs where switch timing gradually diverges from schedule intent.

**Log Format:**
```
INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 FATAL: target_boundary_ms=%d does not match plan boundary=%d
```

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
| **INV-P9-TS-EMISSION-LIVENESS** | CONTRACT | MpegTSOutputSink | P9 | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P9-FLUSH | Cached shadow frame pushed to buffer synchronously when shadow disabled |
| INV-P9-BOOTSTRAP-READY | Readiness = commit detected AND ≥1 video frame, not deep buffering |
| INV-P9-NO-DEADLOCK | Output routing must not wait on conditions requiring output routing |
| INV-P9-WRITE-BARRIER-SYMMETRIC | When write barrier set, audio and video suppressed symmetrically |
| INV-P9-BOOT-LIVENESS | Newly attached sink emits decodable TS within bounded time |
| INV-P9-AUDIO-LIVENESS | From header written, output contains continuous monotonic audio PTS |
| INV-P9-PCR-AUDIO-MASTER | Audio owns PCR at startup |
| INV-P9-TS-EMISSION-LIVENESS | First decodable TS packet MUST be emitted within 500ms of PCR-PACE timing initialization |

### Phase 10 Coordination

| Rule ID | Classification | Owner | Enforcement | Test | Log | Supersedes |
|---------|---------------|-------|-------------|------|-----|------------|
| **INV-P10-BACKPRESSURE-SYMMETRIC** | CONTRACT | FileProducer, FrameRingBuffer | P10 | No | Yes | — |
| **INV-P10-PRODUCER-THROTTLE** | CONTRACT | FileProducer | P10 | No | Yes | — |
| **INV-P10-BUFFER-EQUILIBRIUM** | CONTRACT | FrameRingBuffer | P10 | No | Yes | — |
| **INV-P10-NO-SILENCE-INJECTION** | CONTRACT | MpegTSOutputSink | P10 | No | No | — |
| **INV-P10-SINK-GATE** | CONTRACT | ProgramOutput | P10 | No | No | — |
| **INV-OUTPUT-READY-BEFORE-LIVE** | CONTRACT | PlayoutEngine | P10 | No | Yes | — |
| **INV-SWITCH-READINESS** | CONTRACT | PlayoutEngine | P10 | No | Yes | — | *DEMOTED to diagnostic goal; see Superseded Rules* |
| **INV-SWITCH-SUCCESSOR-EMISSION** | CONTRACT | TimelineController | P10 | Yes | Yes | — | *DEMOTED to diagnostic goal; see Superseded Rules* |
| **RULE-P10-DECODE-GATE** | CONTRACT | FileProducer | P10 | No | Yes | RULE_HARVEST #39 |
| **INV-P10-AUDIO-VIDEO-GATE** | CONTRACT | FileProducer | P10 | No | Yes | — |

| Rule ID | One-Line Definition |
|---------|---------------------|
| INV-P10-BACKPRESSURE-SYMMETRIC | When buffer full, both audio and video throttled symmetrically. **Audio samples MUST NOT be dropped due to queue backpressure; overflow MUST cause producer throttling.** |
| INV-P10-PRODUCER-THROTTLE | Producer decode rate governed by consumer capacity, not decoder speed |
| INV-P10-BUFFER-EQUILIBRIUM | Buffer depth oscillates around target, not unbounded or zero |
| INV-P10-NO-SILENCE-INJECTION | Audio liveness disabled when PCR-paced mux active |
| INV-P10-SINK-GATE | ProgramOutput must not consume frames before sink attached *(complementary to INV-P9-SINK-LIVENESS-001: SINK-GATE prevents consumption; SINK-LIVENESS describes routing)* |
| INV-OUTPUT-READY-BEFORE-LIVE | Channel must not enter LIVE until output pipeline observable *(includes safety rail output; does not require real content)* |
| INV-SWITCH-READINESS | **DIAGNOSTIC GOAL:** Switch SHOULD have video ≥2, sink attached, format locked. *(No longer a completion gate; superseded by INV-SWITCH-DEADLINE-AUTHORITATIVE-001 for completion semantics)* |
| INV-SWITCH-SUCCESSOR-EMISSION | **DIAGNOSTIC GOAL:** Real successor video frame SHOULD be emitted at switch. *(No longer a completion gate; switch completes at declared boundary time per INV-SWITCH-DEADLINE-AUTHORITATIVE-001)* |
| RULE-P10-DECODE-GATE | Slot-based gating at decode level; block at capacity, unblock when one slot frees |
| INV-P10-AUDIO-VIDEO-GATE | When segment video epoch is established, first audio frame MUST be queued within 100ms |

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

| Rule ID | One-Line Definition |
|---------|---------------------|
| RULE-CANONICAL-GATING | Only assets with canonical=true may be scheduled (Core) and played (AIR); dual enforcement |
| RULE-CORE-RUNTIME-READONLY | Runtime services treat config tables as immutable |
| RULE-CORE-PLAYLOG-AUTHORITY | Only ScheduleService writes playlog_event; ChannelManager reads only |

*Note: INV-P8-SWITCH-TIMING promoted to Layer 2 Coordination as of 2026-02-01 audit.*

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
| INV-SWITCH-READINESS (as completion gate) | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch completes at declared boundary time, not when readiness conditions met. Retained as diagnostic goal. |
| INV-SWITCH-SUCCESSOR-EMISSION (as completion gate) | INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Switch completes at declared boundary time, not when successor frame emitted. Retained as diagnostic goal. |
| INV-FRAME-001 (as authority) | LAW-AUTHORITY-HIERARCHY | Frame-indexed boundaries describe execution precision, not decision authority. Clock decides WHEN; frames decide HOW. |
| INV-FRAME-003 (as authority) | LAW-AUTHORITY-HIERARCHY | CT derivation within segment does not gate switch execution. Frame completion does not delay clock-scheduled transitions. |
| LAW-FRAME-EXECUTION (as decision authority) | LAW-AUTHORITY-HIERARCHY | Frame index governs execution precision within a segment. Subordinate to clock authority for transition timing. |

---

## Test Coverage Summary

| Layer | Total Rules | With Tests | Coverage |
|-------|-------------|------------|----------|
| Layer 0 (Laws) | 14 | 6 | 43% |
| Layer 1 (Semantic) | 32 | 25 | 78% |
| Layer 2 (Coordination) | 44 | 26 | 59% |
| Layer 3 (Diagnostic) | 5 | 0 | 0% |
| Cross-Domain | 3 | 1 | 33% |
| Proposed | 14 | 0 | 0% |
| **Total** | **111** | **58** | **52%** |

---

## Log Coverage Summary

| Layer | Total Rules | With Logs | Coverage |
|-------|-------------|-----------|----------|
| Layer 0 (Laws) | 14 | 9 | 64% |
| Layer 1 (Semantic) | 32 | 9 | 28% |
| Layer 2 (Coordination) | 44 | 20 | 45% |
| Layer 3 (Diagnostic) | 5 | 5 | 100% |
| Cross-Domain | 3 | 1 | 33% |
| Proposed | 14 | 12 | 86% |
| **Total** | **111** | **56** | **50%** |

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

---

## Phased Implementation Plan (Audit 2026-02-01)

This section documents the phased implementation of invariants added by the 2026-02-01 Broadcast-Grade Timing Compliance Audit.

### Phase 11A: Audio Sample Continuity (Foundation)

**Goal:** Eliminate audio discontinuities caused by queue backpressure.

**Invariants:**
- INV-AUDIO-SAMPLE-CONTINUITY-001

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By |
|---------|-------------|-------|------------|
| P11A-001 | Audit current audio queue behavior under backpressure | AIR | — |
| P11A-002 | Add audio sample drop detection and logging | AIR | P11A-001 |
| P11A-003 | Implement audio queue overflow → producer throttle (no drops) | AIR | P11A-002 |
| P11A-004 | Contract test: audio samples never dropped under backpressure | AIR | P11A-003 |
| P11A-005 | Update INV-P10-BACKPRESSURE-SYMMETRIC enforcement to include audio | AIR | P11A-003 |

**Exit Criteria:**
- No audio sample drops observed under 10-minute stress test
- Contract test passes: audio continuity preserved during queue full conditions
- Metric: `audio_samples_dropped_total = 0` during normal operation

**Risk:** Low — Localized to AIR audio queue management

---

### Phase 11B: Boundary Timing Observability (Instrumentation)

**Goal:** Make boundary timing violations observable before enforcing them.

**Invariants:**
- INV-P8-SWITCH-TIMING (strengthened)
- INV-BOUNDARY-TOLERANCE-001 (observability only)

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By |
|---------|-------------|-------|------------|
| P11B-001 | Add `switch_completion_time_ms` to SwitchToLive response | AIR | — |
| P11B-002 | Log `INV-BOUNDARY-TOLERANCE-001 VIOLATION` when switch >1 frame late | AIR | P11B-001 |
| P11B-003 | Add metric: `switch_boundary_delta_ms` histogram | AIR | P11B-001 |
| P11B-004 | Add metric: `switch_boundary_violations_total` counter | AIR | P11B-002 |
| P11B-005 | Baseline current boundary timing across test channels | Ops | P11B-003 |
| P11B-006 | Analyze baseline: what % of switches are >1 frame late? | Ops | P11B-005 |

**Exit Criteria:**
- Boundary timing is observable in logs and metrics
- Baseline established for current timing accuracy
- No enforcement changes; observability only

**Risk:** Very Low — Logging and metrics only; no behavioral change

---

### Phase 11C: Declarative Boundary Protocol (Proto Change)

**Goal:** Enable Core to declare switch boundary time to AIR.

**Invariants:**
- INV-BOUNDARY-DECLARED-001
- INV-CONTROL-NO-POLL-001 (partial — protocol support)

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By |
|---------|-------------|-------|------------|
| P11C-001 | Add `target_boundary_time_ms` field to SwitchToLiveRequest proto | Proto | — |
| P11C-002 | Regenerate proto stubs (Python + C++) | Build | P11C-001 |
| P11C-003 | AIR: Parse and log `target_boundary_time_ms` (no enforcement yet) | AIR | P11C-002 |
| P11C-004 | Core: Populate `target_boundary_time_ms` from schedule | Core | P11C-002 |
| P11C-005 | Add integration test: target_boundary_time_ms flows Core→AIR | Test | P11C-003, P11C-004 |

**Exit Criteria:**
- Proto includes `target_boundary_time_ms`
- Core sends boundary time in every SwitchToLive
- AIR logs receipt of boundary time
- No enforcement changes; protocol readiness only

**Risk:** Medium — Proto change affects Core/AIR interface; requires coordinated deployment

---

### Phase 11D: Deadline-Authoritative Switching (Enforcement) — **Closed 2026-02-02**

**Goal:** AIR executes switch at declared boundary time regardless of readiness.

**Invariants:**
- INV-SWITCH-DEADLINE-AUTHORITATIVE-001
- INV-BOUNDARY-TOLERANCE-001 (enforcement)
- INV-CONTROL-NO-POLL-001 (enforcement)
- INV-SCHED-PLAN-BEFORE-EXEC-001 (planning-time feasibility)
- INV-STARTUP-BOUNDARY-FEASIBILITY-001
- INV-SWITCH-ISSUANCE-DEADLINE-001
- INV-LEADTIME-MEASUREMENT-001 (observability: Core/AIR delta logging)

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By |
|---------|-------------|-------|------------|
| P11D-001 | AIR: Schedule switch for `target_boundary_time_ms` via MasterClock | AIR | P11C-003 |
| P11D-002 | AIR: Execute switch at deadline even if readiness not achieved | AIR | P11D-001 |
| P11D-003 | AIR: If not ready at deadline, use safety rails (pad/silence) and log violation | AIR | P11D-002 |
| P11D-004 | AIR: Deprecate NOT_READY response; replace with PROTOCOL_VIOLATION if prefeed late | AIR | P11D-002 |
| P11D-005 | Core: Remove SwitchToLive retry loop; treat NOT_READY as fatal | Core | P11D-004 |
| P11D-009 | Core: Enforce planning-time feasibility (INV-SCHED-PLAN-BEFORE-EXEC-001) | Core | P11D-005 |
| P11D-010 | Core: Enforce startup boundary feasibility (INV-STARTUP-BOUNDARY-FEASIBILITY-001) | Core | P11D-009 |
| P11D-011 | Core: Deadline-scheduled switch issuance (INV-SWITCH-ISSUANCE-DEADLINE-001) | Core | P11D-010 |
| P11D-006 | Core: Ensure LoadPreview issued with sufficient lead time | Core | P11D-005, P11D-009, P11D-010, P11D-011 |
| P11D-007 | Contract test: switch executes within 1 frame of declared boundary | Test | P11D-002 |
| P11D-008 | Contract test: late prefeed results in PROTOCOL_VIOLATION, not retry | Test | P11D-004 |
| P11D-012 | Core + AIR: Delta logging for lead-time / clock skew (INV-LEADTIME-MEASUREMENT-001 observability) | Core + AIR | P11D-011 |

**Exit Criteria:**
- All switches execute within 1 frame of declared boundary time
- No poll/retry pattern in Core for SwitchToLive
- Prefeed timing violations are logged as protocol errors
- 10-minute multi-switch test passes with 0 boundary violations

**Risk:** High — Fundamental change to switch semantics; requires extensive testing

**Rollback Plan:** Feature flag `use_deadline_authoritative_switch` defaults to false; can be enabled per-channel

---

### Phase 11E: Prefeed Timing Contract (Core Obligation) — **Closed 2026-02-02**

**Goal:** Core guarantees prefeed arrives with sufficient lead time.

**Invariants:**
- INV-CONTROL-NO-POLL-001 (Core enforcement)
- AIR-010 (Prefeed Ordering) — amended

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By |
|---------|-------------|-------|------------|
| P11E-001 | Define `MIN_PREFEED_LEAD_TIME_MS` constant (e.g., 5000ms) | Core | — |
| P11E-002 | Core: Issue LoadPreview at `boundary_time - MIN_PREFEED_LEAD_TIME_MS` | Core | P11E-001 |
| P11E-003 | Core: Log violation if LoadPreview issued with <MIN_PREFEED_LEAD_TIME_MS | Core | P11E-002 |
| P11E-004 | Core: Add metric `prefeed_lead_time_ms` histogram | Core | P11E-002 |
| P11E-005 | Contract test: all LoadPreview calls have ≥MIN_PREFEED_LEAD_TIME_MS | Test | P11E-003 |

**Exit Criteria:**
- All LoadPreview calls issued with ≥5 seconds lead time
- Late prefeed is logged as Core scheduling error
- No scheduling scenarios where prefeed cannot meet lead time

**Risk:** Medium — Requires Core scheduler changes; affects schedule lookahead

---

### Phase 11F: Boundary Lifecycle State Machine (Core Hardening)

**Goal:** Enforce terminal failure semantics and one-shot issuance for boundaries.

**Invariants:**
- INV-SWITCH-ISSUANCE-TERMINAL-001 (exception → FAILED_TERMINAL)
- INV-SWITCH-ISSUANCE-ONESHOT-001 (exactly once per boundary)
- INV-BOUNDARY-LIFECYCLE-001 (unidirectional state machine)
- INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 (target must match plan)
- INV-SWITCH-ISSUANCE-DEADLINE-001 (tightened: loop.call_later, not threading.Timer)
- INV-CONTROL-NO-POLL-001 (tightened: tick-based reissuance forbidden)

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By | Status |
|---------|-------------|-------|------------|--------|
| P11F-001 | Fix `_MIN_PREFEED_LEAD_TIME_MS` typo in channel_manager_launch.py | Core | — | **Done** 2026-02-02 |
| P11F-002 | Add BoundaryState enum and transition enforcement | Core | P11F-001 | **Done** 2026-02-02 |
| P11F-003 | Implement terminal exception handling in switch issuance | Core | P11F-002 | **Done** 2026-02-02 |
| P11F-004 | Add one-shot guard to prevent duplicate issuance | Core | P11F-002 | **Done** 2026-02-02 |
| P11F-005 | Replace threading.Timer with loop.call_later() | Core | P11F-002 | **Done** 2026-02-02 |
| P11F-006 | Add plan-boundary match validation | Core | P11F-002 | **Done** 2026-02-02 |
| P11F-007 | Contract test: boundary lifecycle transitions | Test | P11F-003, P11F-004 | **Done** 2026-02-02 |
| P11F-008 | Contract test: duplicate issuance suppression | Test | P11F-004 | **Done** 2026-02-02 |
| P11F-009 | Contract test: terminal exception handling | Test | P11F-003 | **Done** 2026-02-02 |

**Exit Criteria:**
- Boundary state machine enforced with unidirectional transitions
- Exception during issuance transitions to FAILED_TERMINAL (no retry)
- Duplicate issuance attempts suppressed; duplicate into terminal is fatal
- Switch issuance uses loop.call_later(), not threading.Timer
- target_boundary_ms validated against plan-derived boundary
- No tick-based switch detection patterns in codebase

**Risk:** Medium — Changes Core control flow; requires careful exception handling

---

### Phase 12: Live Session Authority & Teardown Semantics

**Goal:** Define when teardown is permitted and enforce deferred teardown during transient boundary states.

**Governing Document:** [PHASE12.md](./PHASE12.md)

**Invariants:**
- INV-TEARDOWN-STABLE-STATE-001 (teardown deferred in transient states)
- INV-TEARDOWN-GRACE-TIMEOUT-001 (bounded deferral; timeout forces FAILED_TERMINAL)
- INV-TEARDOWN-NO-NEW-WORK-001 (no new boundary work when teardown pending)
- INV-VIEWER-COUNT-ADVISORY-001 (viewer count advisory during transitions)
- INV-LIVE-SESSION-AUTHORITY-001 (liveness only in LIVE state)
- INV-TERMINAL-SCHEDULER-HALT-001 (no scheduling intent after FAILED_TERMINAL)
- INV-TERMINAL-TIMER-CLEARED-001 (timers cancelled on FAILED_TERMINAL entry)
- INV-SESSION-CREATION-UNGATED-001 (session creation not gated on boundary feasibility)
- INV-STARTUP-CONVERGENCE-001 (infeasible boundaries skipped during startup convergence)
- INV-STARTUP-BOUNDARY-FEASIBILITY-001 **amended** (applies to boundary commitment, not session creation)

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By | Status |
|---------|-------------|-------|------------|--------|
| P12-CORE-001 | Add teardown state fields to ChannelManager | Core | — | **Done** |
| P12-CORE-002 | Implement `_request_teardown()` guard | Core | P12-CORE-001 | **Done** |
| P12-CORE-003 | Integrate deferred teardown into state transitions | Core | P12-CORE-002 | **Done** |
| P12-CORE-004 | Add grace timeout enforcement to `tick()` | Core | P12-CORE-002 | **Done** |
| P12-CORE-005 | Block new work when teardown pending | Core | P12-CORE-002 | **Done** |
| P12-CORE-006 | Update ProgramDirector viewer disconnect handler | Core | P12-CORE-002 | **Done** |
| P12-CORE-007 | Add `is_live` property | Core | P12-CORE-001 | **Done** |
| P12-CORE-008 | Implement terminal scheduler halt | Core | P12-CORE-005 | — |
| P12-CORE-009 | Clear timers on FAILED_TERMINAL entry | Core | P12-CORE-008 | — |
| P12-TEST-001 | Contract test: teardown blocked in transient states | Test | P12-CORE-003 | **Done** |
| P12-TEST-002 | Contract test: deferred teardown executes on LIVE | Test | P12-CORE-003 | **Done** |
| P12-TEST-003 | Contract test: grace timeout forces FAILED_TERMINAL | Test | P12-CORE-004 | **Done** |
| P12-TEST-004 | Contract test: no new work when teardown pending | Test | P12-CORE-005 | **Done** |
| P12-TEST-005 | Contract test: viewer disconnect defers during transition | Test | P12-CORE-006 | **Done** |
| P12-TEST-006 | Contract test: liveness only in LIVE state | Test | P12-CORE-007 | **Done** |
| P12-TEST-007 | Contract test: scheduler halts in FAILED_TERMINAL | Test | P12-CORE-008 | — |
| P12-TEST-008 | Contract test: timers cleared on FAILED_TERMINAL | Test | P12-CORE-009 | — |
| **Startup Convergence Amendment** |||||
| P12-CORE-010 | Ungate session creation from boundary feasibility | Core | P12-CORE-001 | — |
| P12-CORE-011 | Implement startup convergence tracking (`_converged` flag) | Core | P12-CORE-010 | — |
| P12-CORE-012 | Implement boundary skip logic during convergence | Core | P12-CORE-011 | — |
| P12-CORE-013 | Add convergence timeout enforcement | Core | P12-CORE-011 | — |
| P12-TEST-009 | Contract test: session creation ungated | Test | P12-CORE-010 | — |
| P12-TEST-010 | Contract test: boundary skip during convergence | Test | P12-CORE-012 | — |
| P12-TEST-011 | Contract test: convergence timeout forces FAILED_TERMINAL | Test | P12-CORE-013 | — |
| P12-TEST-012 | Contract test: post-convergence feasibility enforced | Test | P12-CORE-011 | — |

**Exit Criteria:**
- Teardown blocked during transient states (PLANNED, PRELOAD_ISSUED, SWITCH_SCHEDULED, SWITCH_ISSUED)
- Teardown permitted in stable states (NONE, LIVE, FAILED_TERMINAL)
- Grace timeout forces FAILED_TERMINAL after 10s deferral
- No new boundary work scheduled when teardown pending
- Viewer disconnect routes through `_request_teardown()`
- `is_live` property returns True only in LIVE state
- No scheduling intent generated after FAILED_TERMINAL (fully absorbing)
- Transient timers cancelled on FAILED_TERMINAL entry
- Session creation never returns 503 due to boundary timing
- Infeasible boundaries skipped during startup convergence (logged, not fatal)
- Session converges within MAX_STARTUP_CONVERGENCE_WINDOW or enters FAILED_TERMINAL
- Post-convergence boundary infeasibility is FATAL

**Risk:** Low — Additive changes; does not modify Phase 8 or Phase 11 semantics

---

### Phase 8 Content Deficit Amendment

**Goal:** Distinguish decoder EOF from segment boundary; fill content deficit with pad to preserve output liveness.

**Governing Document:** [PHASE8_EXECUTION_PLAN.md](./PHASE8_EXECUTION_PLAN.md)
**Incident Reference:** 2026-02-02 Black Screen Incident (Decoder EOF → False Viewer Disconnect)

**Invariants:**
- INV-P8-SEGMENT-EOF-DISTINCT-001 (decoder EOF ≠ segment end)
- INV-P8-CONTENT-DEFICIT-FILL-001 (pad fills EOF-to-boundary gap)
- INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 (frame_count is planning authority)

**Implementation Tasks:**

| Task ID | Description | Owner | Blocked By | Status |
|---------|-------------|-------|------------|--------|
| P8-PLAN-001 | Store frame_count as planning authority in FileProducer | AIR | — | — |
| P8-PLAN-002 | Detect early EOF (frames_delivered < planned_frame_count) | AIR | P8-PLAN-001 | — |
| P8-PLAN-003 | Handle long content (truncate at boundary) | AIR | P8-PLAN-001 | — |
| P8-EOF-001 | Add EOF signaling from FileProducer to PlayoutEngine | AIR | P8-PLAN-002 | — |
| P8-EOF-002 | Decouple EOF from boundary evaluation in PlayoutEngine | AIR | P8-EOF-001 | — |
| P8-EOF-003 | Preserve CT advancement after live EOF | AIR | P8-EOF-002 | — |
| P8-FILL-001 | Implement content deficit detection in PlayoutEngine | AIR | P8-EOF-002 | — |
| P8-FILL-002 | Emit pad frames during content deficit | AIR | P8-FILL-001 | — |
| P8-FILL-003 | End content deficit on boundary switch | AIR | P8-FILL-002 | — |
| P8-TEST-EOF-001 | Contract test: EOF signaled before boundary, CT continues | Test | P8-EOF-003 | — |
| P8-TEST-EOF-002 | Contract test: EOF does not trigger switch | Test | P8-EOF-002 | — |
| P8-TEST-FILL-001 | Contract test: Pad emitted during content deficit | Test | P8-FILL-002 | — |
| P8-TEST-FILL-002 | Contract test: TS emission continues during deficit | Test | P8-FILL-002 | — |
| P8-TEST-FILL-003 | Contract test: Switch terminates deficit fill | Test | P8-FILL-003 | — |
| P8-TEST-PLAN-001 | Contract test: Short content triggers early EOF | Test | P8-PLAN-002 | — |
| P8-TEST-PLAN-002 | Contract test: Long content truncated at boundary | Test | P8-PLAN-003 | — |
| P8-INT-001 | Integration: short content → pad → switch | Test | P8-TEST-FILL-003 | — |
| P8-INT-002 | Integration: HTTP connection survives content deficit | Test | P8-INT-001 | — |

**Exit Criteria:**
- Decoder EOF logged distinctly from boundary
- CT continues advancing after EOF
- Content deficit filled with pad at real-time cadence
- TS emission continues during deficit (no HTTP timeout)
- Switch executes at boundary time, not EOF time
- No false viewer disconnects due to content deficit
- No black screen incidents from short content

**Risk:** Low — Additive semantics; closes gap in existing pad mechanism

---

### Phase Dependency Graph

```
Phase 11A (Audio Continuity)      ─────────────────────────────────┐
                                                                    │
Phase 11B (Observability)         ──────────────────────────────┐  │
                                                                 │  │
Phase 11C (Proto Change)          ─────────────────────────┐    │  │
                                                            │    │  │
                                                            v    v  v
Phase 11D (Deadline Enforcement)  ◄─────────────────────────────────┤
                                                                    │
Phase 11E (Prefeed Contract)      ◄─────────────────────────────────┤
                                                                    │
Phase 11F (Lifecycle Hardening)   ◄─────────────────────────────────┤
                                                                    │
Phase 12 (Teardown Semantics)     ◄─────────────────────────────────┘
```

- **11A** can proceed immediately (no dependencies)
- **11B** can proceed immediately (no dependencies)
- **11C** can proceed immediately (proto change)
- **11D** requires 11C complete (needs proto field)
- **11E** requires 11D complete (enforcement semantics must be clear)
- **11F** requires 11E complete (builds on prefeed contract)
- **12** requires 11F complete (builds on BoundaryState enum)

### Recommended Execution Order

1. **Parallel:** 11A + 11B + 11C (no dependencies between them)
2. **Sequential:** 11D (after 11C)
3. **Sequential:** 11E (after 11D)
4. **Sequential:** 11F (after 11E)
5. **Sequential:** 12 (after 11F)

### Summary Timeline

| Phase | Description | Dependencies | Risk | Est. Effort |
|-------|-------------|--------------|------|-------------|
| 11A | Audio Sample Continuity | None | Low | 2-3 days |
| 11B | Boundary Timing Observability | None | Very Low | 1-2 days |
| 11C | Declarative Boundary Protocol | None | Medium | 2-3 days |
| 11D | Deadline-Authoritative Switching | 11C | High | 5-7 days |
| 11E | Prefeed Timing Contract | 11D | Medium | 3-4 days |
| 11F | Boundary Lifecycle Hardening | 11E | Medium | 2-3 days |
| 12 | Live Session Authority & Teardown | 11F | Low | 2-3 days |
| **Total** | | | | **17-25 days** |

---

## Audit History

```
Phase 11A (Audio Continuity)      ─────────────────────────────────┐
                                                                    │
Phase 11B (Observability)         ──────────────────────────────┐  │
                                                                 │  │
Phase 11C (Proto Change)          ─────────────────────────┐    │  │
                                                            │    │  │
                                                            v    v  v
Phase 11D (Deadline Enforcement)  ◄─────────────────────────────────┤
                                                                    │
Phase 11E (Prefeed Contract)      ◄─────────────────────────────────┘
```

- **11A** can proceed immediately (no dependencies)
- **11B** can proceed immediately (no dependencies)
- **11C** can proceed immediately (proto change)
- **11D** requires 11C complete (needs proto field)
- **11E** requires 11D complete (enforcement semantics must be clear)

### Recommended Execution Order

1. **Parallel:** 11A + 11B + 11C (no dependencies between them)
2. **Sequential:** 11D (after 11C)
3. **Sequential:** 11E (after 11D)

### Summary Timeline

| Phase | Description | Dependencies | Risk | Est. Effort |
|-------|-------------|--------------|------|-------------|
| 11A | Audio Sample Continuity | None | Low | 2-3 days |
| 11B | Boundary Timing Observability | None | Very Low | 1-2 days |
| 11C | Declarative Boundary Protocol | None | Medium | 2-3 days |
| 11D | Deadline-Authoritative Switching | 11C | High | 5-7 days |
| 11E | Prefeed Timing Contract | 11D | Medium | 3-4 days |
| **Total** | | | | **13-19 days** |

---

## Audit History

| Date | Auditor | Scope | Summary |
|------|---------|-------|---------|
| 2026-02-02 | Systems Contract Authority | Phase 8 Content Deficit Amendment | Added INV-P8-SEGMENT-EOF-DISTINCT-001 (decoder EOF distinct from segment boundary), INV-P8-CONTENT-DEFICIT-FILL-001 (pad fills EOF-to-boundary gap), INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 (frame_count is planning authority). 9 implementation tasks (P8-PLAN-*, P8-EOF-*, P8-FILL-*), 7 contract tests (P8-TEST-*), 2 integration tests (P8-INT-*). Incident-derived: Black screen incident where decoder EOF caused cascade failure (buffer empty → no TS packets → HTTP timeout → false viewer disconnect → teardown). Root cause: EOF conflated with segment end, no content deficit policy. Creates PHASE8_EXECUTION_PLAN.md and task specs in docs/contracts/tasks/phase8/. |
| 2026-02-02 | Systems Contract Authority | Phase 12 Startup Convergence Amendment | Added INV-SESSION-CREATION-UNGATED-001 (session creation not gated on boundary feasibility) and INV-STARTUP-CONVERGENCE-001 (infeasible boundaries skipped during startup convergence). Amended INV-STARTUP-BOUNDARY-FEASIBILITY-001 to apply to boundary commitment, not session creation. New terminology: Session Creation, Boundary Commitment, Startup Convergence, Converged Session. Added PHASE12.md §8 (Startup Convergence Semantics). 4 implementation tasks (P12-CORE-010–013), 4 test tasks (P12-TEST-009–012). Incident-derived: Core returned 503 on viewer tune-in due to boundary feasibility check, despite content being immediately playable. Root cause: conflation of session creation with boundary commitment. |
| 2026-02-02 | Systems Contract Authority | Phase 12 Terminal Semantics Amendment | Added INV-TERMINAL-SCHEDULER-HALT-001 (intent-absorbing: no scheduling intent after FAILED_TERMINAL) and INV-TERMINAL-TIMER-CLEARED-001 (timers cancelled on terminal entry). Introduced canonical terminology: "fully absorbing" = transition-absorbing + intent-absorbing. Clarified allowed operations in FAILED_TERMINAL (health, metrics, diagnostics). Incident-derived: scheduler continued generating intent after terminal failure, causing spurious log errors. |
| 2026-02-02 | Systems Contract Authority | Phase 12 Creation | Created Phase 12: Live Session Authority & Teardown Semantics. Added 5 invariants: INV-TEARDOWN-STABLE-STATE-001 (teardown deferred in transient states), INV-TEARDOWN-GRACE-TIMEOUT-001 (bounded deferral), INV-TEARDOWN-NO-NEW-WORK-001 (no new work when pending), INV-VIEWER-COUNT-ADVISORY-001 (viewer count advisory during transitions), INV-LIVE-SESSION-AUTHORITY-001 (liveness only in LIVE state). Incident-derived: Core tore down channel during SWITCH_ISSUED causing AIR encoder deadlock and audio queue overflow. 7 implementation tasks (P12-CORE-001–007), 6 test tasks (P12-TEST-001–006). |
| 2026-02-02 | Systems Contract Authority | P11F-007–P11F-009 completion | P11F-007: test_channel_manager_boundary_lifecycle.py (allowed/illegal/terminal-absorbing/LIVE non-absorbing). P11F-008: test_channel_manager_oneshot.py (duplicate suppression, tick guard, exactly-once). P11F-009: test_channel_manager_terminal.py (exception→FAILED_TERMINAL, no re-arm, tick cannot retry, diagnostics). 71 runtime tests pass. Phase 11F complete. |
| 2026-02-02 | Systems Contract Authority | P11F-003–P11F-006 completion | P11F-003: try/except Exception in switch issuance → FAILED_TERMINAL; no retry. P11F-004: _guard_switch_issuance; tick early-return for SWITCH_ISSUED/LIVE/FAILED_TERMINAL. P11F-005: optional event_loop; call_later path when set; Timer fallback. P11F-006: _plan_boundary_ms set/cleared/validated; mismatch → FAILED_TERMINAL. 32 runtime tests passed. |
| 2026-02-02 | Systems Contract Authority | P11F-002 completion | P11F-002 done: BoundaryState enum and _ALLOWED_BOUNDARY_TRANSITIONS; _transition_boundary_state(); all boundary transitions wired (PLANNED→PRELOAD_ISSUED→SWITCH_SCHEDULED→SWITCH_ISSUED→LIVE→PLANNED/NONE). Switch timer moved to after LoadPreview. Illegal transition → FAILED_TERMINAL tested. Unblocks P11F-003, P11F-004, P11F-005, P11F-006. |
| 2026-02-02 | Systems Contract Authority | P11F-001 completion | P11F-001 done: typo `_MIN_PREFEED_LEAD_TIME_MS` → `MIN_PREFEED_LEAD_TIME_MS` verified absent; `channel_manager_launch.py` uses `MIN_PREFEED_LEAD_TIME_MS` only. Tests: test_prefeed_timing, test_clock_driven_switch (9 passed). Unblocks P11F-002. |
| 2026-02-02 | Systems Contract Authority | Boundary Lifecycle Hardening | Added Phase 11F: INV-SWITCH-ISSUANCE-TERMINAL-001 (exception → FAILED_TERMINAL), INV-SWITCH-ISSUANCE-ONESHOT-001 (one-shot issuance), INV-BOUNDARY-LIFECYCLE-001 (state machine), INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 (plan validation). Tightened INV-CONTROL-NO-POLL-001 to forbid tick-based reissuance. Fixed `_MIN_PREFEED_LEAD_TIME_MS` typo. Incident-derived: retry cascade caused negative lead-time violations. |
| 2026-02-02 | Systems Contract Authority | Lead-Time Measurement Basis | Added INV-LEADTIME-MEASUREMENT-001: Prefeed lead time evaluated using issuance timestamp (`issued_at_time_ms`), not AIR receipt time. Receipt-time evaluation makes threshold issuance mathematically impossible under non-zero RPC latency. Proto extended with `issued_at_time_ms` field. |
| 2026-02-02 | Systems Contract Authority | Switch Issuance Deadline | Added INV-SWITCH-ISSUANCE-DEADLINE-001: SwitchToLive issuance MUST be deadline-scheduled and issued no later than `boundary_time - MIN_PREFEED_LEAD_TIME`. Cadence-based detection, tick loops, and jitter padding are forbidden. Derives from LAW-AUTHORITY-HIERARCHY and INV-SWITCH-DEADLINE-AUTHORITATIVE-001. |
| 2026-02-02 | Systems Contract Authority | Startup Feasibility | Added INV-STARTUP-BOUNDARY-FEASIBILITY-001: First scheduled boundary must satisfy `boundary_time >= station_utc + startup_latency + MIN_PREFEED_LEAD_TIME`. Startup latency is a schedule content constraint, not a planning_time offset. Derives from INV-SCHED-PLAN-BEFORE-EXEC-001 and LAW-AUTHORITY-HIERARCHY. Runtime has no legal recovery mechanism for startup infeasibility. |
| 2026-02-02 | Systems Contract Authority | Scheduling Feasibility | Added INV-SCHED-PLAN-BEFORE-EXEC-001: Scheduling feasibility MUST be determined at planning time. Boundaries that cannot satisfy lead-time constraints MUST be rejected during planning, not discovered at runtime. Supports INV-CONTROL-NO-POLL-001 and INV-BOUNDARY-DECLARED-001. Scheduling errors are planning errors. |
| 2026-02-01 | Systems Contract Authority | Authority Hierarchy | **CRITICAL AMENDMENT:** Added LAW-AUTHORITY-HIERARCHY establishing "clock supersedes frame completion for switch execution." Resolved contradiction between clock-based rules (LAW-CLOCK, LAW-SWITCHING) and frame-based rules (LAW-FRAME-EXECUTION, INV-FRAME-001, INV-FRAME-003). Downgraded frame rules from "authority" to "execution precision." Added Authority Model diagram. |
| 2026-02-01 | Systems Contract Authority | Broadcast-Grade Timing | Added 5 invariants (INV-BOUNDARY-TOLERANCE-001, INV-BOUNDARY-DECLARED-001, INV-AUDIO-SAMPLE-CONTINUITY-001, INV-CONTROL-NO-POLL-001, INV-SWITCH-DEADLINE-AUTHORITATIVE-001). Amended LAW-SWITCHING, INV-P10-BACKPRESSURE-SYMMETRIC, INV-P8-SWITCH-TIMING. Promoted INV-P8-SWITCH-TIMING to Layer 2. Defined 5-phase implementation plan (11A-11E). |
