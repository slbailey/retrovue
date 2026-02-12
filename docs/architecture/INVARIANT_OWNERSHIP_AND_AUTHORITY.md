# Invariant Ownership and Authority

**Status:** Canonical
**Scope:** Architectural boundary definition for invariant ownership
**Authority:** Binding — contracts must conform to this document

---

## 1. Purpose

This document defines the ownership boundaries between AIR, Core, and the Protocol interface. Its purpose is to ensure:

- No invariant spans multiple authorities without explicit declaration
- AIR invariants never reference viewers, lifecycle policy, or session creation
- Core responsibilities are clearly separated from broadcast correctness
- Protocol rules govern the command interface, not internal behavior

When an invariant violates these boundaries, it is architecturally invalid and must be corrected.

---

## 2. Authority Domains

### 2.1 AIR (Broadcast Runtime)

AIR is a broadcast engine. It assumes it exists for the duration of a session. It does not know why it exists, when it will cease to exist, or who is observing its output.

**AIR owns:**
- Clock authority (MasterClock is the sole source of "now")
- Timeline authority (TimelineController owns CT mapping)
- Continuous emission (output never stops while session exists)
- Frame selection (ProgramOutput routes pad or real content)
- Codec and mux correctness (decodability, IDR, PCR)
- Backpressure and flow control (producer throttling, buffer equilibrium)
- Pad generation (black video + silence audio, always available)

**AIR assumes:**
- It will be started
- It will be stopped
- Commands will arrive via Protocol
- It has no knowledge of *why* these events occur

**AIR never knows:**
- Viewer count
- Session creation policy
- Teardown reasons
- Schedule generation logic
- Editorial intent

### 2.2 Core (Session Lifecycle & Scheduling)

Core owns all decisions about *whether* a session exists. Core is the authority on schedule, editorial intent, viewer presence, and resource allocation.

**Core owns:**
- Session creation (when to start AIR)
- Session teardown (when to stop AIR)
- Viewer tracking (who is watching, when they leave)
- Schedule generation (what content plays when)
- Playout plan construction (segment boundaries, frame counts)
- Teardown policy (stable state deferral, grace timeouts)
- As-run logging (historical record of what aired)

**Core assumes:**
- AIR will execute commands correctly
- AIR will emit continuous output once started
- AIR will stop when commanded

**Core never owns:**
- Frame timing or pacing
- Codec decisions
- Buffer management
- CT/MT mapping
- Pad emission
- Decodability

### 2.3 Protocol (Command & Deadline Interface)

The Protocol defines how Core commands AIR and how AIR reports status. Protocol rules govern the *interface*, not the internal behavior of either party.

**Protocol owns:**
- Command semantics (StartChannel, StopChannel, legacy preload RPC, legacy switch RPC)
- Deadline parameters (target_boundary_time_ms, issued_at_time_ms)
- Response codes (OK, NOT_READY, PROTOCOL_VIOLATION)
- Lead-time requirements (MIN_PREFEED_LEAD_TIME)
- Clock basis for deadline evaluation

**Protocol defines contracts between Core and AIR:**
- Core issues commands with sufficient lead time
- AIR executes at declared deadlines
- Feasibility is determined at issuance, not at execution
- NOT_READY is a protocol error, not a retry condition

**Protocol never owns:**
- Internal AIR state transitions
- Internal Core scheduling logic
- Viewer-driven decisions
- Broadcast correctness guarantees

---

## 3. Invariant Ownership Rules

### 3.1 Rules AIR May Own

AIR may own invariants concerning:

| Category | Examples |
|----------|----------|
| Clock | MasterClock authority, epoch immutability, CT monotonicity |
| Timeline | CT assignment, segment mapping, producer time-blindness |
| Output | Continuous emission, pad availability, frame cadence |
| Codec | IDR before output, audio house format, video decodability |
| Flow | Backpressure symmetry, buffer equilibrium, decode gating |
| Switching | PTS continuity, no gaps, boundary tolerance |

### 3.2 Rules AIR Is Forbidden From Owning

AIR **must not** own invariants concerning:

| Forbidden Category | Reason |
|--------------------|--------|
| Viewer presence | AIR has no knowledge of viewers |
| Session creation | Core decides when AIR exists |
| Session teardown | Core decides when AIR stops |
| Teardown policy | Stable-state deferral is Core's concern |
| Schedule feasibility | Planning-time decisions belong to Core |
| Editorial intent | What *should* air is Core's domain |
| Observer-gated output | Output is unconditional once session exists |

### 3.3 Rules Core May Own

Core may own invariants concerning:

| Category | Examples |
|----------|----------|
| Lifecycle | Session creation, teardown, stable-state deferral |
| Scheduling | Plan generation, boundary feasibility, lead-time calculation |
| Viewers | Viewer count, tune-in/tune-out handling |
| Teardown | Grace timeout, deferred teardown, terminal states |
| Protocol compliance | Issuance deadlines, one-shot semantics |

### 3.4 Rules Core Is Forbidden From Owning

Core **must not** own invariants concerning:

| Forbidden Category | Reason |
|--------------------|--------|
| Frame timing | AIR owns real-time execution |
| Mux correctness | AIR owns codec and transport |
| Buffer management | AIR owns flow control |
| CT/MT mapping | AIR owns timeline authority |
| Pad emission | AIR owns continuous output |
| Decodability | AIR owns codec constraints |

### 3.5 Rules Protocol May Own

Protocol may own invariants concerning:

| Category | Examples |
|----------|----------|
| Command format | Required fields, parameter semantics |
| Deadline semantics | target_boundary_time_ms interpretation |
| Feasibility basis | Lead-time measurement, issued_at_time_ms |
| Response codes | NOT_READY, PROTOCOL_VIOLATION meanings |
| Clock basis | Which clock is authoritative for deadlines |

### 3.6 Rules Protocol Is Forbidden From Owning

Protocol **must not** own invariants concerning:

| Forbidden Category | Reason |
|--------------------|--------|
| Internal AIR state | Protocol sees commands and responses only |
| Internal Core logic | Protocol sees issuance, not scheduling |
| Broadcast correctness | That's AIR's domain |
| Lifecycle policy | That's Core's domain |

---

## 4. Examples of Correct Ownership

### 4.1 Pad Emission

**Owner:** AIR

Pad (black video + silence audio) is first-class content. It is always available. When real content is unavailable, ProgramOutput selects pad. This decision is made solely on content availability, never on viewer presence or session policy.

**Correct invariant:** "If no content → deterministic pad (black + silence)"

**Why AIR:** Continuous emission is a broadcast guarantee. AIR does not know if anyone is watching. It emits regardless.

### 4.2 Clock Authority

**Owner:** AIR

MasterClock is the sole source of "now" for all playout decisions. No other component may define wall-clock time for timeline, pacing, or deadline evaluation within AIR.

**Correct invariant:** "MasterClock is the only source of 'now'"

**Why AIR:** Clock authority is fundamental to broadcast correctness. Core commands *when* to switch (via Protocol deadline), but AIR's internal clock governs execution.

### 4.3 Sink Attachment

**Owner:** AIR (attachment mechanics), Core (attachment timing)

Sink attachment is a mechanical operation within AIR. The decision of *when* to attach a sink is Core's responsibility (via AttachStream command). Once attached, AIR delivers frames unconditionally.

AIR does not delay, pace, or condition frame emission based on sink presence; absence of a sink results in legal discard.

**Correct invariant (AIR):** "Post-attach delivery: after AttachSink, all frames reach sink until DetachSink"

**Correct invariant (Core):** "Sink attachment timing is orthogonal to broadcast correctness"

**Why split:** AIR owns the mechanics of delivery. Core owns the decision to attach. Neither owns the other's domain.

### 4.4 Session Teardown

**Owner:** Core

Session teardown is a lifecycle decision. Core decides when AIR stops based on viewer count, resource policy, or explicit operator action. AIR does not know why it is being stopped.

**Correct invariant:** "Teardown deferred in transient boundary states"

**Why Core:** This invariant concerns *when* to stop AIR, not *how* AIR behaves. AIR simply stops when commanded.

---

## 5. Examples of Invalid / Mixed Ownership

### 5.1 Viewer-Driven Gating in AIR

**Invalid:** "AIR must not emit frames until a viewer is present"

**Violation:** AIR has no knowledge of viewers. This invariant requires AIR to track observer presence, violating the boundary.

**Correction:** If such gating is needed, Core must implement it by delaying AttachStream or StartChannel. AIR emits unconditionally once started.

### 5.2 Sink-Readiness as a Broadcast Condition

**Invalid:** "Broadcast correctness requires sink to be attached"

**Violation:** Broadcast correctness is defined by continuous emission, not by observation. A broadcast is correct even if no one is watching.

**Correction:** Sink attachment is orthogonal to broadcast correctness. AIR emits to OutputBus regardless. If no sink is attached, frames are discarded (legally). Broadcast correctness is preserved.

### 5.3 Output Gating Based on Observer Presence

**Invalid:** "ProgramOutput must wait until sink is attached before consuming frames"

**Violation:** This makes output contingent on observer presence. It inverts the broadcast model.

**Correction:** INV-P10-SINK-GATE exists for *flow control* (preventing buffer drain before routing is possible), not for observer-gated semantics. The invariant must be understood as a flow control mechanism, not a visibility gate. Frames flow regardless of whether anyone observes them.

### 5.4 Viewer Count in AIR Logs

**Invalid:** "AIR logs viewer count on frame emission"

**Violation:** AIR has no knowledge of viewers. Any such logging requires information AIR must not possess.

**Correction:** Viewer-correlated logging belongs to Core's as-run log, not AIR's telemetry.

### 5.5 Teardown Policy in AIR

**Invalid:** "AIR defers stop until boundary state is stable"

**Violation:** Teardown policy is Core's domain. AIR stops when commanded. The stability check belongs in Core.

**Correction:** INV-TEARDOWN-STABLE-STATE-001 is correctly owned by Core (ChannelManager). AIR's StopChannel handler executes immediately.

### 5.6 Schedule Feasibility Validation in AIR

**Invalid:** "AIR validates that frame_count >= slot_duration × fps"

**Violation:** Schedule feasibility is a planning-time concern owned by Core. AIR must not validate schedule correctness.

**Correction:** INV-SEGMENT-CONTENT-001 is Core-only. AIR consumes frame_count as planning authority without validation. If actual frames < frame_count at runtime, AIR fills with pad (INV-P8-CONTENT-DEFICIT-FILL-001). AIR adapts; AIR does not validate.

### 5.7 LIVE State Declaration in AIR

**Invalid:** "AIR decides when channel enters LIVE state"

**Violation:** LIVE is a Core lifecycle state. AIR has no concept of "live" vs "not live" — it emits continuously once started.

**Correction:** INV-OUTPUT-READY-BEFORE-LIVE is owned by Core (ChannelManager). AIR exposes readiness signals (buffer depth, sink status). Core queries these signals and decides LIVE. AIR never autonomously declares or transitions to LIVE.

---

## 6. Boundary Cases Requiring Explicit Declaration

Some invariants legitimately span domains. These must be explicitly declared as **cross-domain** with clear ownership of each component.

### 6.1 Deadline-Authoritative Switching

**Protocol:** Declares that `target_boundary_time_ms` is the authoritative deadline.

**Core:** Issues legacy switch RPC with deadline parameter, ensures lead-time feasibility.

**AIR:** Executes switch at declared deadline ± 1 frame, uses safety rails if not ready.

**Declaration:** INV-SWITCH-DEADLINE-AUTHORITATIVE-001 is a **Protocol invariant** that imposes obligations on both Core (issuance) and AIR (execution).

### 6.2 Lead-Time Feasibility

**Protocol:** Declares that `issued_at_time_ms` is the measurement basis.

**Core:** Computes issuance time to satisfy MIN_PREFEED_LEAD_TIME.

**AIR:** Evaluates lead time using `issued_at_time_ms`, not receipt time.

**Declaration:** INV-LEADTIME-MEASUREMENT-001 is a **Protocol invariant** with obligations on both parties.

---

## 7. Enforcement Rule

**If an invariant violates ownership boundaries, it must be moved or split.**

Specifically:

1. **AIR invariants referencing viewers:** Must be moved to Core or deleted.

2. **AIR invariants referencing lifecycle policy:** Must be moved to Core.

3. **Core invariants referencing frame timing:** Must be moved to AIR or Protocol.

4. **Protocol invariants with internal behavior requirements:** Must be split into Protocol (interface) and domain (implementation) components.

5. **Invariants with ambiguous ownership:** Must be explicitly declared as cross-domain with clear per-domain obligations.

**Contracts must conform to this document.** An invariant that violates these boundaries is architecturally invalid, regardless of its operational utility. The invariant must be corrected, not the boundary.

Architectural convenience is not justification for ownership violation.

---

## 8. Summary Table

| Domain | Owns | Forbidden |
|--------|------|-----------|
| **AIR** | Clock, timeline, emission, codec, flow, switching | Viewers, lifecycle, teardown policy, schedule, editorial |
| **Core** | Lifecycle, schedule, viewers, teardown, protocol compliance | Frame timing, mux, buffers, CT/MT, pad, decodability |
| **Protocol** | Command format, deadlines, feasibility basis, response codes | Internal state, broadcast correctness, lifecycle policy |

---

## 9. Cross-References

- [BROADCAST_CONSTITUTION.MD](./BROADCAST_CONSTITUTION.MD) — Prime directive and authority hierarchy
- [CANONICAL_RUNTIME_DATAFLOW.MD](./CANONICAL_RUNTIME_DATAFLOW.MD) — Runtime model
- [CANONICAL_RULE_LEDGER.md](../contracts/CANONICAL_RULE_LEDGER.md) — All active invariants
- [CLAUDE.md](../../CLAUDE.md) — System-level component responsibilities
- [Core Lifecycle Contracts](../../pkg/core/docs/contracts/lifecycle/) — Core-owned lifecycle invariants (teardown, sessions, viewers)
