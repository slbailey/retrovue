# Phase 10 Pressure Doctrine

**Layer:** Pressure Doctrine (between Laws and Coordination)
**Status:** Canonical
**Authority:** Defines pressure semantics that all Layer 2 contracts must obey

This doctrine answers: **"What must happen under pressure, no matter how it's implemented?"**

---

## Doctrine Statement

Phase 10 defines the complete and final pressure model for steady-state playout.
All overload, underrun, and backpressure behavior MUST resolve according to this doctrine.
No component may invent alternative recovery, repair, or mitigation strategies.

Phase 10 pressure rules are time-authoritative, slot-based, and directional:

- **Time (CT) always moves forward**
- **Pressure travels upstream only to producers**
- **Transport failures never affect broadcast timing**
- **Pads, not drops, resolve time/content disagreement**

This doctrine closes all ambiguity around "what happens when things go wrong."

---

## Core Principles

### 1. Pressure Terminates at the Producer Decode Gate

All backpressure MUST terminate at producer admission (decode/demux boundary).

- Buffers do not drain to "make room"
- ProgramOutput does not wait
- OutputBus does not signal backpressure
- Transport does not slow time

**Slot-based gating is the only legal pressure mechanism.**

### 2. Time Is Never Backpressured

Clock (CT) advancement is non-negotiable.

- CT never pauses
- CT never rewinds
- CT never waits for content

If content is unavailable or invalid at a CT slot, **pad is emitted**.

### 3. Transport Failure Is Local and Contained

Transport (SocketSink, HTTP fan-out) absorbs its own failure modes.

- Slow or broken clients do not affect AIR timing
- OutputBus always accepts emissions
- Transport may drop bytes freely

**Broadcast correctness is upstream of transport.**

### 4. Pads Are the Only Legal Recovery

When timing and content disagree:

> **Time wins. Content yields via pad.**

Forbidden recovery mechanisms:

- Frame dropping to "catch up"
- Timestamp nudging
- Adaptive speed-up / slow-down
- Silent frame skipping

### 5. Audio and Video Are Gated Symmetrically

Backpressure is applied in time-equivalent units.

- Audio MUST NOT run ahead of video
- Video MUST NOT run ahead of audio
- Audio samples MUST NOT be dropped due to backpressure

**Desync is prevented by gating, not repaired later.**

---

## Phase 10 Overload Behavior Table (Canonical)

This table is authoritative.
**If implementation behavior disagrees with this table, the implementation is wrong.**

| Scenario | Observed Condition | Responsible Component | Required Behavior | Forbidden Behavior |
|----------|-------------------|----------------------|-------------------|-------------------|
| Buffer Full | Buffer at capacity | Producer | Block at decode gate (slot-based) | Draining buffer, dropping frames |
| Buffer Empty | No valid frame at current CT | ProgramOutput | Emit pad (classified reason) | Waiting for producer |
| Sink Slow | Socket/HTTP backpressure | SocketSink | Drop bytes locally | Blocking OutputBus or ProgramOutput |
| Sink Absent | No sink attached | OutputBus | Discard immediately | Buffering, delaying emission |
| Content Unavailable | No valid frame at current CT | ProgramOutput | Emit pad | Speed-up, timestamp repair |
| Audio Missing | No audio for video CT | ProgramOutput | Pad (or stall only per Phase 9 bootstrap rules) | Video-only emission |
| Decode Burst | Disk/GOP burst | Producer | Bounded decode within slot budget | Unbounded queue growth |
| System Overload | CPU saturated | Producer | Natural backpressure via decode gate | Coordinated dropping |
| CT Discontinuity | CT jump detected | Sink (diagnostic) | Reset local timing anchor only | Rewriting CT |

---

## Enforcement Notes

- **ProgramOutput** enforces time authority and pad emission.
- **FrameRingBuffer** enforces capacity and equilibrium.
- **Producers** enforce slot-based decode gating.
- **OutputBus** enforces non-blocking routing.
- **Transport** enforces local failure containment.

No other component may:

- Delay emission
- Invent readiness checks
- Coordinate drops
- Repair timing

---

## Constitutional Closure

Phase 10 pressure doctrine operationalizes:

- `LAW-OUTPUT-LIVENESS`
- `LAW-CLOCK`
- `LAW-AUTHORITY-HIERARCHY`

After Phase 10:

- All stutter is diagnosable
- All drops are attributable
- All timing behavior is predictable

**There are no hidden pressure paths.**

---

## Cross-References

- [BROADCAST_LAWS.md](./laws/BROADCAST_LAWS.md) - Layer 0 Laws
- [PHASE10_FLOW_CONTROL.md](./coordination/PHASE10_FLOW_CONTROL.md) - Layer 2 implementation rules
