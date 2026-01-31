# OutputBus & OutputSink Contract

_Related: [Playout Engine Contract](../semantics/PlayoutEngineContract.md) · [Phase contracts](README.md)_

**Status:** Locked (pre-implementation)  
**Scope:** Air (C++) playout engine runtime  
**Audience:** Engine implementers, refactor tools (Cursor), future maintainers

---

## 1. Purpose

This contract defines the authoritative model for output handling in Air.

Air models output using **broadcast signal concepts**, not transport or threading concepts.

Output is represented as a **bus** (signal path) with one or more **sinks** (consumers).

All previous "stream writer" terminology is explicitly deprecated and must not appear in new code.

---

## 2. Core Definitions (Normative)

### 2.1 OutputBus

**OutputBus** represents the program output signal of a single Air playout session.

OutputBus is a **signal path**, not a transport.

#### OutputBus responsibilities

- Exists for the lifetime of a playout session
- Receives rendered video and audio frames
- Routes frames to currently attached output sinks
- Manages attachment and detachment of sinks
- Is governed by PlayoutControl

#### OutputBus explicitly does NOT:

- Open sockets
- Encode media
- Write bytes
- Own threads
- Know about TCP, UDS, files, or protocols
- Make timing or scheduling decisions

### 2.2 OutputSink

**OutputSink** is a consumer of the OutputBus signal.

An OutputSink converts frames into an external representation (e.g. MPEG-TS over TCP).

#### OutputSink responsibilities

- Accept video and audio frames
- Perform encoding, muxing, and transport
- **Provide jitter protection** (buffering and paced emit) so the emitted stream meets timing and continuity requirements (see §2.3)
- Manage its own internal threads and resources
- Report backpressure or failure to the engine (via defined signals)

#### OutputSink explicitly does NOT:

- Own engine state
- Decide when it may attach or detach
- Know about channels, schedules, or preview/live concepts
- Interact directly with gRPC

### 2.3 Jitter protection (Normative)

The output path **MUST** provide **jitter protection** so that the emitted stream meets timing and continuity requirements.

- **Requirement:** Byte delivery from the output to the transport must be smoothed such that:
  - Bursty or variable-rate input (e.g. from decode or mux) does not cause undue burstiness or gaps in the emitted stream.
  - Downstream timing guarantees (e.g. PCR/PTS monotonicity, continuity counters, decoder buffer constraints) can be met.
- **Placement:** Jitter protection **MUST** be implemented in the **OutputSink**. The bus is a signal path and explicitly does not make timing or scheduling decisions (§2.1); the sink owns encoding, muxing, transport, and internal resources, and is the last point before bytes hit the wire. The sink is therefore the normative place for buffering and paced emit.
- **Scope:** Applies to all output paths. Downstream contracts (e.g. Phase 8.4 persistent TS mux) assume this requirement is satisfied when they specify PCR/PTS monotonicity and stream continuity.

---

## 3. Ownership & Lifecycle (Normative)

### 3.1 Ownership

| Component | Owner |
|-----------|-------|
| OutputBus | PlayoutInstance (inside PlayoutEngine) |
| OutputSink | OutputBus (attached/detached) |
| PlayoutControl | PlayoutInstance |
| gRPC Attach/Detach | Requests only (no ownership) |

**gRPC never owns output state.**

### 3.2 Attachment Model

- OutputBus may have zero or more sinks conceptually
- **Current enforced invariant:** Air allows at most one attached sink per OutputBus
- Policy is enforced by PlayoutControl, not by OutputBus itself

#### Attachment rules (current)

- Attaching a sink when one is already attached:
  - If `replace_existing == true`: detach old sink, then attach new
  - Else: return error
- Detaching a sink leaves OutputBus valid but silent

---

## 4. PlayoutControl Integration (Normative)

All OutputBus attach/detach operations are runtime transitions and must be validated by PlayoutControl.

The control plane enforces:

- Safe attachment timing
- Safe detachment timing
- Prohibition of attach/detach during illegal phases (e.g. stopping)
- Deterministic transition order

**OutputSink implementations must not bypass PlayoutControl.**

OutputBus must not perform attach/detach operations autonomously.

---

## 5. Interface Shape (Non-Normative, Guiding)

These are shape hints, not required signatures.

### OutputBus (conceptual)

- `AttachSink(OutputSink, replace_existing)`
- `DetachSink(force=false)`
- `IsAttached()`
- `OnVideoFrame(frame)`
- `OnAudioFrame(audio)`

### OutputSink (conceptual)

- `Start()`
- `Stop()`
- `ConsumeVideo(frame)`
- `ConsumeAudio(frame)`
- `ReportBackpressure()`

Implementations may vary, but responsibilities must not.

---

## 6. Naming Rules (Strict)

The following terms are **forbidden** in public or runtime-level code:

- `StreamWriter`
- `WriterState`
- `WriterThread`
- `WriteLoop` (unless strictly private to a sink)

Any legacy symbols containing these terms must be encapsulated and not exposed outside a concrete OutputSink.

**Allowed terminology:**

- `OutputBus`
- `OutputSink`
- `Encoder`
- `Mux`
- `Transport`
- `Emit` / `Output` / `Deliver`

---

## 7. Legacy Handling

Existing code previously named `StreamWriterState` is considered:

- Implementation plumbing, not a domain concept

During refactor:

- It must be renamed and encapsulated inside a concrete OutputSink
- No public API or runtime object may expose "writer" semantics

---

## 8. Non-Goals (Explicit)

This contract does NOT define:

- Multi-sink timing arbitration
- Failover behavior
- Redundancy
- Simulcast policy
- Backpressure aggregation semantics

Those may be introduced later without violating this contract.

---

## 9. Invariants (Must Always Hold)

1. Air models output as bus + sinks
2. OutputBus exists independent of attachment
3. gRPC does not own output runtime state
4. PlayoutControl governs output transitions
5. Transport details never leak into engine control logic
6. The OutputSink provides jitter protection (buffering and paced emit) so that the emitted stream meets timing and continuity requirements

---

## 10. Change Control

Any future change that:

- Reintroduces "writer" terminology
- Allows gRPC to own output state
- Collapses bus and sink into one abstraction

**violates this contract** and must be explicitly reviewed.

---

## See Also

- [Playout Engine Contract](../semantics/PlayoutEngineContract.md) — control plane integration
- [Phase contracts](README.md) — Phase 6A, Phase 8
