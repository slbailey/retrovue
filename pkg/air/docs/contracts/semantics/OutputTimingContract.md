# OutputTiming Contract

_Related: [OutputContinuity Contract](OutputContinuityContract.md) · [OutputBus & OutputSink Contract](../architecture/OutputBusAndOutputSinkContract.md) · [Playout Engine Contract](PlayoutEngineContract.md) · [Phase contracts](../phases/README.md)_

**Status:** Locked (pre-implementation)  
**Scope:** Air (C++) playout engine runtime — Output layer  
**Audience:** Engine implementers, refactor tools (Cursor), future maintainers

---

## 1. Overview

**OutputTiming** is an Output-layer component responsible for enforcing real-time delivery discipline when providing media to clients.

It ensures that encoded media is not delivered earlier than permitted by real elapsed time, preserving smooth playback and broadcast-grade behavior.

OutputTiming does not define media time, scheduling, or content selection. It only constrains when output data may be emitted.

OutputTiming operates on **already-muxed, timestamped output packets**, not raw frames.

---

## 2. Position in the Architecture

OutputTiming belongs to the **Output** archetype.

```
Input → Playout → OutputContinuity → OutputTiming → OutputSink → Client
```

It operates downstream of timestamp assignment and upstream of I/O.

---

## 3. Responsibilities (Normative)

OutputTiming **MUST**:

- Enforce that output media time does not advance faster than real elapsed time
- Use a local monotonic clock to measure elapsed real time
- Gate packet emission to prevent early delivery
- Establish a timing anchor when output begins or switches live
- Operate transparently to downstream clients

---

## 4. Non-Responsibilities (Normative)

OutputTiming **MUST NOT**:

- Generate, modify, reset, or renumber PTS/DTS/PCR
- Define or own the master media clock
- Consult wall-clock schedule times
- Select content or control preview/live state
- Perform encoding, muxing, or decoding
- Maintain awareness of grid boundaries or program semantics
- Attempt to shape bitrate, smooth jitter, or enforce constant-rate output beyond preventing early delivery

---

## 5. Timing Model

### 5.1 Media Time

- Media intent is expressed exclusively via timestamps (PTS/DTS/PCR)
- Output PTS is continuous and never-ending
- Timestamps are authoritative and immutable

### 5.2 Real Time

- OutputTiming uses a **process-local monotonic clock** (e.g. `std::chrono::steady_clock`) to measure elapsed time
- Absolute wall-clock time is never used
- Only elapsed time is relevant (relative, not absolute)

### 5.3 Timing Anchor

When output begins (or on legacy switch RPC):

- The timing anchor **MUST NOT** be reused across output pacing epochs
- The first emitted packet establishes the timing anchor
- OutputTiming records:
  - **anchor_output_pts**
  - **anchor_wall_elapsed_start**
- These values are internal only and are not encoded into the stream.

### 5.4 Delivery Rule (Invariant)

For any output packet:

```
(packet_pts − anchor_output_pts) ≤ (elapsed_wall_time_since_anchor)
```

If the packet's media time is ahead of elapsed real time, OutputTiming **MUST** delay emission until the invariant is satisfied.

If packets arrive later than permitted by elapsed real time, OutputTiming **MUST** emit them immediately and **MUST NOT** attempt to resynchronize or delay further.

OutputTiming **MUST NOT** drop, duplicate, or reorder packets as part of timing enforcement.

This rule is enforced continuously for the lifetime of the playout epoch.

---

## 6. legacy switch RPC Semantics

On **legacy switch RPC**:

- OutputTiming resets its internal timing anchor
- OutputTiming does not modify output PTS
- OutputTiming does not signal discontinuity to clients
- legacy switch RPC defines a **new output pacing epoch**, not a new media timeline.

---

## 7. Output Continuity Guarantees

Output PTS remains continuous across:

- program boundaries
- grid boundaries
- input source switches

OutputTiming operates purely on relative deltas. No assumptions are made about absolute clock alignment between systems.

---

## 8. Failure Modes Prevented

OutputTiming exists specifically to prevent:

- Startup burst delivery
- Encoder-speed-driven timing
- Client buffer underruns caused by early delivery
- Scaling-induced stutter due to unpaced output
- Accidental coupling between encode speed and playback time

---

## 9. Architectural Invariants

The following must always hold:

1. There is exactly one master media clock
2. OutputTiming enforces but does not own time
3. Output timing discipline exists only at the output boundary
4. No upstream component depends on OutputTiming behavior

---

## 10. Summary (Intent)

OutputTiming ensures that output delivery respects reality without redefining time. It is a **discipline layer**, not a clock, not a scheduler, and not a playout engine.

---

## See Also

- [OutputContinuity Contract](OutputContinuityContract.md) — Timestamp legality and monotonicity; sits upstream of OutputTiming.
- [OutputBus & OutputSink Contract](../architecture/OutputBusAndOutputSinkContract.md) — Output signal path; OutputTiming sits between playout and sink.
- [Playout Engine Contract](PlayoutEngineContract.md) — Control plane integration.
- [Phase contracts](../phases/README.md) — Phase 8 (output, TS, pacing).
