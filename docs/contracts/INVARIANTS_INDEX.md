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
| INV-P8-SWITCH-TIMING | Boundary timing tolerance |
| INV-BOUNDARY-* | Broadcast-grade timing |
| INV-AUDIO-SAMPLE-CONTINUITY-001 | Audio continuity |
| INV-SCHED-PLAN-BEFORE-EXEC-001 | Planning-time feasibility |
| INV-STARTUP-BOUNDARY-FEASIBILITY-001 | Startup boundary requirements |
| INV-SWITCH-ISSUANCE-* | Switch issuance rules |
| INV-LEADTIME-MEASUREMENT-001 | Lead-time calculation |
| INV-CONTROL-NO-POLL-001 | No poll semantics |
| INV-SWITCH-DEADLINE-AUTHORITATIVE-001 | Deadline-authoritative switching |

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

---

## Test Coverage Summary

| Layer | Total Rules | With Tests | Coverage |
|-------|-------------|------------|----------|
| Layer 0 (Laws) | 14 | 6 | 43% |
| Layer 1 (Semantic) | 32 | 25 | 78% |
| Layer 2 (Coordination) | 44 | 26 | 59% |
| Layer 3 (Diagnostic) | 5 | 0 | 0% |
| Cross-Domain | 3 | 1 | 33% |
| **Total** | **98** | **58** | **59%** |

---

## Quick Reference

**Looking for a specific invariant?** Use the [CANONICAL_RULE_LEDGER.md](./CANONICAL_RULE_LEDGER.md) and search by Rule ID.

**Need to understand a phase?** See the coordination contract for that phase.

**Want to add a new invariant?** Follow the process in CANONICAL_RULE_LEDGER.md §Maintenance.
