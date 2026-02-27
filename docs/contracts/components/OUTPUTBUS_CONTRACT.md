# OutputBus Contract

**Status:** Canonical
**Layer:** 2.6 (between ProgramOutput 2.5 and sink behavior)
**Scope:** Routing, sink attachment mechanics, legal discard behavior
**Authority:** Mechanical delivery guarantees only; does not define broadcast correctness (that's Laws + ProgramOutput)

---

## 1. Purpose

OutputBus is a **non-blocking single-sink router with legal discard semantics**.

Its responsibilities:
1. **Accept** frames from ProgramOutput unconditionally
2. **Route** to zero or more sinks (or discard legally)
3. **Provide** mechanical attachment semantics (stable pointer, no races, no blocking)
4. **Never** introduce timing decisions, gating semantics, or lifecycle meaning

OutputBus is plumbing. It moves frames from selection to encoding. It has no opinion about correctness, timing, or broadcast semantics.

---

## 2. Authority Boundaries

### OutputBus Owns (Mechanics Only)

| Concern | OutputBus Role |
|---------|---------------|
| Attach/detach mechanics | Owns — stable pointer semantics |
| Single sink routing | Owns — at most one active sink per channel |
| Legal discard (no sink) | Owns — immediate discard is correct |
| Pointer stability | Owns — no races, no implicit detach |
| Delivery after attach | Owns — immediate handoff, non-blocking |
| Concurrency safety | Owns — thread-safe attach/detach/emit |

### OutputBus Explicitly Does NOT Own

| Concern | Correct Owner | Why OutputBus Must Not Touch |
|---------|---------------|------------------------------|
| Whether AIR exists/starts/stops | Core | Lifecycle is not routing |
| Whether channel is LIVE | Core | LIVE is a lifecycle state |
| Whether emission is "correct" | ProgramOutput + Laws | Correctness is selection, not routing |
| CT policy or pacing | TimelineController / MasterClock | Timing is not routing |
| Buffer drain policy | ProgramOutput | Dequeue gating is selection-side |
| Viewer presence | Core | Routing is viewer-blind |

---

## 3. Core Invariants

### OB-001 — Single Sink Only

At most one sink may be attached at a time.

- Any attempt to attach a second sink is a **protocol error** (Core bug)
- OutputBus does not manage multiple consumers
- Fan-out is an HTTP concern, not an OutputBus concern

```cpp
// ✅ CORRECT: Single sink
void OutputBus::AttachSink(Sink* s) {
    assert(sink_ == nullptr);  // Protocol violation if already attached
    sink_ = s;
}

// ❌ FORBIDDEN: Multiple sinks
std::vector<Sink*> sinks_;  // WRONG — OutputBus is not a fanout
```

---

### OB-002 — Legal Discard When Unattached

If no sink is attached:
- OutputBus **accepts** frames from ProgramOutput
- OutputBus **discards immediately**
- **No buffering** — frames are not queued waiting for a sink
- **No waiting** — OutputBus does not delay hoping a sink will appear
- **No backpressure** — ProgramOutput is never told "slow down"

This is the key invariant that ensures **AIR can exist with zero viewers**.

**Clarification:** Discard is a correct outcome when no routing target exists. It is not an error, not a violation, not a warning condition. This is a **routing absence**, not an emission failure.

**Telemetry:** Increment `frames_discarded_no_sink` counter. Do not log per-frame.

---

### OB-003 — Stable Sink Between Attach/Detach

Once attached:
- **Every frame** is written to the socket
- Errors do **not** trigger implicit detach
- Detach is **explicit** and **Core-owned**

**Forbidden behaviors:**
- No swapping sink behind caller's back
- No implicit detach on errors (log and continue)
- No "auto detach when empty viewers" (Core's decision)
- No "temporary detach for maintenance"

**Model:** Sink attachment controlled entirely by Core. AIR never infers presence, demand, or lifecycle from sink state.

**Anchor:** INV-TS-EMISSION-LIVENESS and INV-SINK-NO-DEADLOCK (sink stability)

---

### OB-004 — No Fan-Out, Ever

OutputBus MUST NOT:
- Duplicate frames to multiple consumers
- Track readers or reader count
- Track backpressure per reader
- Maintain per-consumer state

**Fan-out is strictly an HTTP concern.** The HTTP server may have multiple clients reading from the same MPEG-TS stream. That multiplexing happens at the HTTP layer, not at OutputBus.

OutputBus writes bytes to one socket. Period.

**Architectural boundary:** OutputBus must never be read directly by clients. All fan-out occurs above AIR, via HTTP or equivalent transport. This prevents any "helpful" refactor from reintroducing session tracking or viewer semantics into AIR.

---

### OB-005 — No Timing or Correctness Authority

OutputBus MUST NOT:
- Inspect CT
- Delay writes
- Retry failed writes
- Smooth or pace output
- Gate on readiness
- Interpret whether a frame is "correct"

If bytes arrive, they go out (or get discarded per OB-002). That's it.

**Constitutional basis:** Timing authority belongs to MasterClock and TimelineController. OutputBus is plumbing.

---

## 4. Relationship to ProgramOutput and INV-BUFFER-EQUILIBRIUM

This relationship must be explicit to prevent contamination:

| Concern | Owner |
|---------|-------|
| "What frame corresponds to CT?" | ProgramOutput |
| "Should a frame be emitted even if nothing is ready?" | ProgramOutput (pad) |
| "Should frames be dequeued yet?" | ProgramOutput (INV-BUFFER-EQUILIBRIUM) |
| "Where does the frame go?" | OutputBus |
| "What if nowhere?" | OutputBus discards (OB-002) |
| "Does AIR exist without viewers?" | **Yes** (Core decides lifecycle) |

**No contradictions. No leakage of viewer semantics.**

**Key principle:** OutputBus being sinkless MUST NEVER cause ProgramOutput to "wait."

- ProgramOutput may choose a dequeue policy (per INV-BUFFER-EQUILIBRIUM)
- OutputBus accepts whatever ProgramOutput emits
- If OutputBus has no sink, it discards immediately (OB-002)
- This is correct behavior, not a failure

**Anti-pattern to prevent:**
```cpp
// ❌ FORBIDDEN: Bus state affecting emission
if (output_bus_.HasNoSink()) {
    return;  // WRONG — ProgramOutput must not inspect bus state
}
```

ProgramOutput emits; OutputBus routes or discards. The bus does not signal back "don't emit."

---

## 5. Explicit Non-Responsibilities

**OutputBus MUST NOT:**

| Forbidden Action | Correct Owner |
|-----------------|---------------|
| Decide when to attach/detach sinks | Core (ChannelManager) |
| Signal "readiness" to upstream | (nobody — no readiness gating) |
| Interpret frame content | (nobody at this layer) |
| Negotiate formats with sinks | EncoderPipeline / Sink |
| Track viewer count | Core |
| Decide LIVE state | Core |
| Backpressure ProgramOutput | (forbidden — non-blocking) |

---

## 6. Failure Semantics

| Condition | Action | Classification |
|-----------|--------|----------------|
| No sink attached | Discard frame immediately | Legal (OB-002) |
| Sink delivery fails | Log, continue emitting | Sink-local error |
| Sink slow | Handoff returns immediately | Sink's problem |
| AttachSink during emit | Thread-safe completion | No race |
| DetachSink during emit | Thread-safe completion | No dangling pointer |

**No failures propagate upstream.** OutputBus absorbs delivery issues; ProgramOutput is never affected. Core decides whether to detach a failing sink.

---

## 7. Test Obligations

| Test ID | Requirement |
|---------|-------------|
| T-OB-001 | `Emit()` never blocks (time-bounded, e.g., < 1ms) |
| T-OB-002 | With no sink, `Emit()` returns success + increments discard metric |
| T-OB-003 | Attach → frames observed by sink; Detach → frames stop |
| T-OB-004 | No internal queuing: frame count in == frame count out (or discarded) |
| T-OB-005 | Concurrent attach/detach/emit is race-free |
| T-OB-006 | Errors at sink do not cause implicit detach |

---

## 8. Derivation Notes

| This Contract | Derives From | Relationship |
|---------------|--------------|--------------|
| OB-001 | LAW-OUTPUT-LIVENESS | **Supports** — non-blocking preserves liveness |
| OB-002 | INV-TS-EMISSION-LIVENESS, INV-SINK-NO-DEADLOCK | **Anchors** — pre-attach discard semantics |
| OB-003 | INV-TS-EMISSION-LIVENESS, INV-SINK-NO-DEADLOCK | **Anchors** — post-attach delivery + stability |
| OB-004 | BROADCAST_CONSTITUTION §5.3 | **Refines** — no buffering at routing layer |
| OB-005 | LAW-CLOCK, LAW-TIMELINE | **Subordinate** — no timing authority |

---

## Cross-References

- [PROGRAMOUTPUT_CONTRACT.md](./PROGRAMOUTPUT_CONTRACT.md) — Upstream: frame selection
- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) — LAW-OUTPUT-LIVENESS
- [BROADCAST_CONSTITUTION.MD](../../architecture/BROADCAST_CONSTITUTION.MD) — §5.3 OutputBus role, §6 Sink Attachment Rule
