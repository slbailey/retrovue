# OutputContinuity Contract

_Related: [OutputTiming Contract](OutputTimingContract.md) · [OutputBus & OutputSink Contract](OutputBusAndOutputSinkContract.md) · [Playout Engine Contract](PlayoutEngineContract.md)_

**Status:** Locked (pre-implementation)  
**Scope:** Air (C++) playout engine runtime — Output layer  
**Audience:** Engine implementers, refactor tools (Cursor), future maintainers

**Authoritative definition of the output liveness and switching laws** (ProgramOutput never blocks; no gaps, no PTS regression, no silence during switches) **lives in [PlayoutInvariants-BroadcastGradeGuarantees.md](../PlayoutInvariants-BroadcastGradeGuarantees.md).**

---

## 1. Overview

**OutputContinuity** is an Output-layer responsibility that enforces legal timestamp progression on output media streams.

It ensures that timestamps (PTS/DTS) never regress, remain monotonic per stream, and are not corrupted by interleaving, refactors, or stream transitions.

OutputContinuity does not enforce real-time pacing and does not define media time. It only ensures that output timestamps are order-correct and decoder-safe.

**Always-valid output:** The guarantee that the sink always receives valid output (no gaps, freezes, or invalid data) is achieved by **dead-man failsafe** (BlackFrameProducer), not by scheduling logic. When the live producer underruns and Core has not yet commanded the next action, Air switches to an internal BlackFrameProducer until Core reasserts control. That is continuity of *source* (failsafe); OutputContinuity (this contract) is continuity of *timestamps* on whatever source is active.

**Clamp at end PTS:** When a producer reaches its end PTS (or equivalent hard-stop boundary) and Core has not yet issued the next control command, Air MUST NOT emit frames beyond that boundary. Air clamps output for that producer and satisfies always-valid-output by outputting black/silence (BlackFrameProducer or equivalent). This is **failsafe containment**—prefer **bounded silence/black** over **content bleed**—not a scheduling or transition decision. Timestamp continuity (this contract) applies to whatever output is active, including black/silence during containment.

---

## 2. Position in the Architecture

OutputContinuity belongs to the **Output** archetype.

```
Input → Playout → OutputContinuity → OutputTiming → OutputSink → Client
```

It operates downstream of timestamp assignment and upstream of output pacing and I/O.

---

## 3. Responsibilities (Normative)

OutputContinuity **MUST**:

- Enforce monotonic PTS/DTS progression per output stream
- Prevent timestamp regression (backward time jumps)
- Track continuity independently per stream (e.g., audio ≠ video)
- Apply minimal correction when necessary to preserve legality
- Operate transparently to downstream clients

---

## 4. Non-Responsibilities (Normative)

OutputContinuity **MUST NOT**:

- Enforce real-time pacing or delay output
- Consult wall-clock or elapsed time
- Define or own the master media clock
- Reset, renumber, or re-base output PTS
- Signal discontinuities to clients
- Make scheduling or content-selection decisions
- Shape bitrate or manage backpressure

---

## 5. Continuity Model

### 5.1 Per-Stream Tracking

- Continuity is enforced **per output stream**
- Audio and video timestamps are tracked independently
- Interleaving **MUST NOT** cause cross-stream contamination

Example: Video DTS must not be compared against audio DTS. Each stream maintains its own last-seen timestamp.

### 5.2 Legal Timestamp Progression

For each stream:

```
current_pts ≥ last_pts
current_dts ≥ last_dts
```

If a packet violates monotonicity:

- OutputContinuity **MUST** minimally adjust the timestamp forward
- Adjustments must be as small as possible to restore legality
- No additional semantic meaning may be introduced
- OutputContinuity **MUST NOT** adjust timestamps by more than the minimum delta required to restore monotonicity

### 5.3 Scope of Correction

- Corrections are local and minimal
- OutputContinuity exists to preserve legality, not intent
- Timestamp correction must not accumulate policy or pacing logic

---

## 6. Relationship to OutputTiming

- **OutputContinuity** ensures timestamps are legal
- **OutputTiming** ensures timestamps are not delivered early

These responsibilities are orthogonal and **MUST** remain separate.

OutputContinuity **MUST NOT**:

- delay packets
- wait for real time
- coordinate with pacing logic

---

## 7. Output Continuity Guarantees

OutputContinuity guarantees:

- No backward timestamp jumps
- Decoder-safe timestamp ordering
- Stable behavior across:
  - stream interleaving
  - refactors
  - codec changes
  - preview/live switching

OutputContinuity makes no guarantees about playback smoothness or real-time behavior.

---

## 8. Failure Modes Prevented

OutputContinuity exists specifically to prevent:

- DTS/PTS regression caused by interleaved streams
- Timestamp corruption during refactors
- Decoder stalls due to illegal ordering
- Subtle A/V desync caused by shared state
- Reintroduction of single-tracker timestamp bugs

---

## 9. Architectural Invariants

The following must always hold:

1. Continuity enforcement is per stream
2. OutputContinuity does not enforce time, only order
3. OutputContinuity operates exclusively in the Output layer
4. No upstream component depends on OutputContinuity behavior

---

## 10. Summary (Intent)

OutputContinuity ensures that output timestamps remain legal and monotonic without redefining media time or enforcing delivery pace.

It is a **correctness discipline**, not a scheduler, not a clock, and not a pacing mechanism.

---

## See Also

- [OutputTiming Contract](OutputTimingContract.md) — Real-time pacing discipline.
- [OutputBus & OutputSink Contract](OutputBusAndOutputSinkContract.md) — Output signal path.
- [Playout Engine Contract](PlayoutEngineContract.md) — Timestamp assignment and control plane.
- [BlackFrameProducer Contract](BlackFrameProducerContract.md) — Dead-man failsafe for always-valid output (source continuity).