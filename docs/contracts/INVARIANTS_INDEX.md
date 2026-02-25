# Invariants Index

**Status:** Canonical navigation
**Purpose:** One-click map of rule families to compiled contract files
**Authority:** Secondary to [CANONICAL_RULE_LEDGER.md](./CANONICAL_RULE_LEDGER.md)

---

## Document Hierarchy

```
CANONICAL_RULE_LEDGER.md          <- Single source of truth (authoritative)
         |
         v
    INVARIANTS_INDEX.md           <- Navigation (this file)
         |
         +-- laws/
         |      +-- BROADCAST_LAWS.md           <- Layer 0: Constitutional (AIR)
         |
         +-- semantics/
         |      +-- PHASE8_SEMANTICS.md         <- Layer 1: Truths about correctness (AIR)
         |
         +-- coordination/                       <- Layer 2: AIR coordination only
         |      +-- PHASE8_COORDINATION.md      <- Write barriers, switches
         |      +-- PHASE9_BOOTSTRAP.md         <- Output bootstrap
         |      +-- PHASE10_FLOW_CONTROL.md     <- Steady-state flow
         |
         +-- components/                        <- Layer 2.5-2.7: Component role specs
         |      +-- PROGRAMOUTPUT_CONTRACT.md   <- Pure selector (2.5)
         |      +-- OUTPUTBUS_CONTRACT.md       <- Non-blocking router (2.6)
         |      +-- SOCKETSINK_CONTRACT.md      <- Non-blocking transport (2.7)
         |
         +-- diagnostics/
         |      +-- DIAGNOSTIC_INVARIANTS.md    <- Layer 3: Logging, drops (AIR)
         |
         +-- historical/
         |      +-- retired_invariants.md       <- Superseded rules
         |
    [Core Contracts - pkg/core/docs/contracts/]
         |
         +-- lifecycle/
                +-- PHASE12_SESSION_TEARDOWN.md <- Core lifecycle (NOT AIR)
                +-- BOUNDARY_LIFECYCLE.md       <- Core boundary + Protocol (NOT AIR)
```

---

## Layer 0 - Constitutional Laws

**Location:** [laws/BROADCAST_LAWS.md](./laws/BROADCAST_LAWS.md)

| Rule Family | Description |
|-------------|-------------|
| LAW-AUTHORITY-HIERARCHY | Clock supersedes frame completion |
| LAW-CLOCK | MasterClock is only source of "now" |
| LAW-TIMELINE | TimelineController owns CT mapping |
| LAW-OUTPUT-LIVENESS | ProgramOutput never blocks |
| LAW-AUDIO-FORMAT | House format enforcement |
| LAW-SWITCHING | No gaps, no PTS regression |
| LAW-VIDEO-DECODABILITY | Every segment starts with IDR |
| LAW-TS-DISCOVERABILITY | TS self-describing to late-joiners; control-plane not media-gated |
| INV-TS-CONTROL-PLANE-CADENCE | PAT/PMT in (T−500ms,T] sliding window; MUST NOT wait on media/CT/buffers |
| LAW-FRAME-EXECUTION | Frame index governs execution precision |
| LAW-OBS-001 through LAW-OBS-005 | Observability requirements |
| LAW-RUNTIME-AUDIO-AUTHORITY | Producer audio authority enforcement |

---

## Layer 1 - Semantic Invariants

**Location:** [semantics/PHASE8_SEMANTICS.md](./semantics/PHASE8_SEMANTICS.md)

| Rule Family | Description |
|-------------|-------------|
| INV-PACING-* | Frame emission rate and enforcement |
| INV-DECODE-RATE-* | Producer decode rate requirements |
| INV-SEGMENT-CONTENT-* | Segment content requirements |
| INV-P8-001 through INV-P8-012 | Phase 8 timeline invariants |
| INV-P8-OUTPUT-001 | Deterministic output liveness |
| INV-P8-SWITCH-002 | CT/MT segment start mapping |
| INV-P8-AUDIO-CT-001 | Audio PTS derivation |
| INV-P8-SEGMENT-EOF-DISTINCT-001 | EOF vs boundary distinction |
| INV-P8-CONTENT-DEFICIT-FILL-001 | Pad fills content gaps |
| INV-P8-FRAME-COUNT-PLANNING-AUTHORITY-001 | Frame count as planning authority |
| INV-P9-A-OUTPUT-SAFETY | No emission before CT |
| INV-P9-EMISSION-OBLIGATION | Emit frames whose CT arrived |
| INV-P10-REALTIME-THROUGHPUT | Output rate matches target |
| INV-P10-PRODUCER-CT-AUTHORITATIVE | Muxer uses producer CT |
| INV-P10-PCR-PACED-MUX | Time-driven mux loop |
| INV-P10-CONTENT-BLIND | No pixel heuristics |
| INV-P9-SINK-LIVENESS-* | Sink attachment semantics |
| INV-AIR-IDR-BEFORE-OUTPUT | IDR gate at segment start |
| INV-AIR-CONTENT-BEFORE-PAD | Real content before pad |
| INV-AUDIO-HOUSE-FORMAT-001 | House format enforcement |
| INV-FRAME-001 through INV-FRAME-003 | Frame execution rules |
| INV-P10-FRAME-INDEXED-EXECUTION | Frame index tracking |

---

## Layer 2 - Coordination Invariants

### Phase 8 Coordination

**Location:** [coordination/PHASE8_COORDINATION.md](./coordination/PHASE8_COORDINATION.md)

| Rule Family | Description |
|-------------|-------------|
| INV-P8-007 | Write barrier finality |
| INV-P8-SWITCH-* | Switch orchestration |
| INV-P8-SHADOW-* | Shadow decode pacing |
| INV-P8-AUDIO-GATE | Audio gating during shadow |
| INV-P8-SEGMENT-COMMIT* | Segment commit rules |
| INV-P8-EOF-SWITCH | EOF switch completion |
| INV-P8-PREVIEW-EOF | Preview EOF handling |
| INV-P8-SWITCHWATCHER-* | Switch watcher invariants |
| INV-P8-ZERO-FRAME-* | Zero-frame segment handling |
| INV-P8-AV-SYNC | Audio-video sync at switch |
| INV-P8-AUDIO-PRIME-001 | Audio prime sequencing |
| INV-P8-IO-UDS-001 | UDS output constraints |
| INV-P8-SWITCH-TIMING | AIR execution timing tolerance |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | Audio continuity |

### PAD Seam (Big Boy Broadcast Ready)

**Location:** [INVARIANTS.md](./INVARIANTS.md) § INV-PAD-SEAM-AUDIO-READY

| Rule Family | Description |
|-------------|-------------|
| INV-PAD-SEAM-AUDIO-READY | PAD segment audio source non-null, routable, silence pushed before fence; no FENCE_AUDIO_PAD at segment-swap-to-PAD. **Must never be weakened.** |

*Note: Boundary lifecycle and Protocol invariants moved to [BOUNDARY_LIFECYCLE.md](../../pkg/core/docs/contracts/lifecycle/BOUNDARY_LIFECYCLE.md)*

### Phase 9 Bootstrap

**Location:** [coordination/PHASE9_BOOTSTRAP.md](./coordination/PHASE9_BOOTSTRAP.md)

| Rule Family | Description |
|-------------|-------------|
| INV-P9-FLUSH | Shadow frame flush |
| INV-P9-BOOTSTRAP-READY | Bootstrap readiness |
| INV-P9-NO-DEADLOCK | No circular waits |
| INV-P9-WRITE-BARRIER-SYMMETRIC | Symmetric write barriers |
| INV-P9-BOOT-LIVENESS | Sink boot liveness |
| INV-P9-AUDIO-LIVENESS | Audio liveness |
| INV-P9-PCR-AUDIO-MASTER | PCR ownership |
| INV-P9-TS-EMISSION-LIVENESS | TS emission deadline |

### Phase 10 Flow Control

**Location:** [coordination/PHASE10_FLOW_CONTROL.md](./coordination/PHASE10_FLOW_CONTROL.md)

| Rule Family | Description |
|-------------|-------------|
| INV-P10-BACKPRESSURE-SYMMETRIC | Symmetric backpressure |
| INV-P10-PRODUCER-THROTTLE | Producer throttling |
| INV-P10-BUFFER-EQUILIBRIUM | Buffer depth stability |
| INV-P10-NO-SILENCE-INJECTION | Disable silence injection |
| INV-P10-SINK-GATE | Sink attachment gate (flow control, not observer-gated) |
| INV-OUTPUT-READY-BEFORE-LIVE | **(Core-owned)** Output observable before LIVE |
| INV-SWITCH-READINESS | Switch readiness (diagnostic) |
| INV-SWITCH-SUCCESSOR-EMISSION | Successor emission (diagnostic) |
| RULE-P10-DECODE-GATE | Slot-based decode gating |
| INV-P10-AUDIO-VIDEO-GATE | Audio-video gate timing |

### Phase 12 Teardown (Core Lifecycle — NOT AIR)

**Location:** [/pkg/core/docs/contracts/lifecycle/PHASE12_SESSION_TEARDOWN.md](../../pkg/core/docs/contracts/lifecycle/PHASE12_SESSION_TEARDOWN.md)

**Ownership:** These are Core lifecycle invariants. AIR does not "enter teardown" — AIR receives StopChannel. Teardown policy, viewer tracking, and session lifecycle are exclusively Core concerns.

| Rule Family | Description |
|-------------|-------------|
| INV-TEARDOWN-* | Teardown semantics (Core) |
| INV-VIEWER-COUNT-ADVISORY-001 | Viewer count advisory (Core) |
| INV-LIVE-SESSION-AUTHORITY-001 | Live session definition (Core) |
| INV-TERMINAL-* | Terminal state semantics (Core) |
| INV-SESSION-CREATION-UNGATED-001 | Ungated session creation (Core) |
| INV-STARTUP-CONVERGENCE-001 | Startup convergence (Core) |

### Boundary Lifecycle (Core + Protocol — NOT AIR)

**Location:** [/pkg/core/docs/contracts/lifecycle/BOUNDARY_LIFECYCLE.md](../../pkg/core/docs/contracts/lifecycle/BOUNDARY_LIFECYCLE.md)

**Ownership:** These are Core lifecycle and Protocol interface invariants. AIR does not define, plan, or manage boundary lifecycle states. AIR receives boundary declarations via Protocol and executes them.

| Rule Family | Description |
|-------------|-------------|
| INV-BOUNDARY-TOLERANCE-001 | Timing tolerance (Protocol) |
| INV-BOUNDARY-DECLARED-001 | Boundary declaration (Protocol) |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Deadline authority (Protocol) |
| INV-LEADTIME-MEASUREMENT-001 | Lead-time basis (Protocol) |
| INV-CONTROL-NO-POLL-001 | No-poll semantics (Protocol) |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Planning-time feasibility (Core) |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | Startup boundary (Core) |
| INV-SWITCH-ISSUANCE-* | Issuance rules (Core) |
| INV-BOUNDARY-LIFECYCLE-001 | Lifecycle state machine (Core) |
| INV-BOUNDARY-DECLARED-MATCHES-PLAN-001 | Plan conformance (Core) |

---

## Layer 2.5 - Component Contracts

Component contracts define the role, authority boundaries, and invariants for specific AIR components.

### ProgramOutput Contract

**Location:** [components/PROGRAMOUTPUT_CONTRACT.md](./components/PROGRAMOUTPUT_CONTRACT.md)

**Role:** Pure, non-blocking frame selector and dispatcher. Refines LAW-OUTPUT-LIVENESS.

| Invariant | Description |
|-----------|-------------|
| PO-001 | Non-blocking emission (alias of LAW-OUTPUT-LIVENESS) |
| PO-002 | Selection, not scheduling |
| PO-003 | Pad is first-class output |
| PO-004 | No sink awareness |
| PO-005 | No readiness gating |
| PO-006 | Destructive dequeue rules (anchors INV-P10-SINK-GATE) |
| PO-007 | Pad classification required |
| PO-008 | No timing repairs |

### OutputBus Contract

**Location:** [components/OUTPUTBUS_CONTRACT.md](./components/OUTPUTBUS_CONTRACT.md)

**Role:** Single-sink byte router. Mechanical delivery only. No fan-out.

| Invariant | Description |
|-----------|-------------|
| OB-001 | Single sink only (second attach = protocol error) |
| OB-002 | Legal discard when unattached (AIR can exist with zero viewers) |
| OB-003 | Stable sink between attach/detach (errors don't detach) |
| OB-004 | No fan-out, ever (HTTP handles multiplexing) |
| OB-005 | No timing or correctness authority |

### SocketSink Contract

**Location:** [components/SOCKETSINK_CONTRACT.md](./components/SOCKETSINK_CONTRACT.md)

**Role:** Non-blocking byte consumer. Transport layer, outside broadcast semantics.

| Invariant | Description |
|-----------|-------------|
| SS-001 | Non-blocking ingress (HARD LAW — violation = LAW-OUTPUT-LIVENESS breach) |
| SS-002 | Local backpressure absorption (never propagate upstream) |
| SS-003 | Bounded memory (no unbounded queues) |
| SS-004 | Best-effort delivery (no retries, no repair) |
| SS-005 | Failure is local (errors don't detach, don't affect AIR) |
| SS-006 | No timing authority (no sleep, no pacing, no batching) |

---

## Layer 3 - Diagnostic Invariants

**Location:** [diagnostics/DIAGNOSTIC_INVARIANTS.md](./diagnostics/DIAGNOSTIC_INVARIANTS.md)

| Rule Family | Description |
|-------------|-------------|
| INV-P8-WRITE-BARRIER-DIAG | Write barrier logging |
| INV-P8-AUDIO-PRIME-STALL | Audio prime stall logging |
| INV-P10-FRAME-DROP-POLICY | Frame drop logging |
| INV-P10-PAD-REASON | Pad reason classification |
| INV-NO-PAD-WHILE-DEPTH-HIGH | Violation detection |

---

## Historical

**Location:** [../historical/retired_invariants.md](../historical/retired_invariants.md)

Superseded rules from RULE_HARVEST and audit amendments.

---

## Cross-Domain Rules

**Location:** [CANONICAL_RULE_LEDGER.md](./CANONICAL_RULE_LEDGER.md) (Cross-Domain section)

| Rule | Description |
|------|-------------|
| RULE-CANONICAL-GATING | Only canonical assets scheduled |
| RULE-CORE-RUNTIME-READONLY | Config tables immutable at runtime |
| RULE-CORE-PLAYLOG-AUTHORITY | Only ScheduleService writes playlog |

**Operational promise (Core + AIR):** [docs/contracts/core/RunwayMinContract_v0.1.md](./core/RunwayMinContract_v0.1.md)

| Rule | Description |
|------|-------------|
| INV-RUNWAY-MIN-001 | When queue_depth >= 3, AIR must not enter PADDED_GAP due to "no next block" except when ScheduleService returns None (true planning gap) |

---

## Test Coverage Summary

| Layer | Total Rules | With Tests | Coverage |
|-------|-------------|------------|----------|
| Layer 0 (Laws) | 15 | 6 | 40% |
| Layer 1 (Semantic) | 33 | 25 | 76% |
| Layer 2 (Coordination) | 44 | 26 | 59% |
| Layer 3 (Diagnostic) | 5 | 0 | 0% |
| Cross-Domain | 3 | 1 | 33% |
| **Total** | **100** | **58** | **58%** |

---

## Quick Reference

**Looking for a specific invariant?** Use the [CANONICAL_RULE_LEDGER.md](./CANONICAL_RULE_LEDGER.md) and search by Rule ID.

**Need to understand a phase?** See the coordination contract for that phase.

**Want to add a new invariant?** Follow the process in CANONICAL_RULE_LEDGER.md §Maintenance.
