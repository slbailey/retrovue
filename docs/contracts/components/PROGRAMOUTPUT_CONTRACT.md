# ProgramOutput Contract

**Status:** Canonical
**Layer:** 2.5 (between Phase 9 Bootstrap and Phase 10 Flow Control)
**Scope:** Frame selection, emission dispatch, and non-blocking output guarantee
**Authority:** Refines LAW-OUTPUT-LIVENESS; subordinate to Clock (LAW-CLOCK) and Timeline (LAW-TIMELINE)

---

## 1. Purpose

ProgramOutput is a **pure, non-blocking frame selector and dispatcher**.

Its sole responsibility is to:
1. **Select** the correct frame for the current CT
2. **Emit** a frame (real or pad) on every tick
3. **Never** block, wait, or stall

ProgramOutput is the "broadcast switcher" inside AIR. It does not generate content, schedule boundaries, or manage lifecycle. It selects and forwards.

**Purity requirement:** ProgramOutput must be referentially transparent with respect to CT: given the same CT and buffer state, it produces the same decision. No hidden state, no side effects on selection path.

---

## 2. Authority Boundaries

| Concern | Owner | ProgramOutput Role |
|---------|-------|-------------------|
| Time (CT) | MasterClock / TimelineController | Consumes CT; does not modify |
| Segment ownership | TimelineController | Consumes segment state; does not decide |
| Frame availability | Producers + FrameRingBuffer | Reads buffer; does not manage capacity |
| Output routing | OutputBus | Forwards frames; does not route |
| Sink presence | OutputBus / Core | Unaware; does not query |
| Lifecycle (LIVE/NOT_READY) | Core (ChannelManager) | Emits regardless; does not gate |
| Emission correctness | **ProgramOutput** | **Owns** |

---

## 3. Core Invariants

### PO-001 — Non-Blocking Emission

**Alias of LAW-OUTPUT-LIVENESS**

ProgramOutput MUST emit exactly one frame decision per CT tick. It MUST NOT block, sleep, wait, or retry.

**Clarification:** Emission is a logical decision, not a guarantee of downstream delivery. ProgramOutput decides "this frame for this CT" and forwards to OutputBus. What happens downstream (routing, discard, encoding) is not ProgramOutput's concern.

```
CORRECT:
  CT arrives → select frame → emit → done

FORBIDDEN:
  CT arrives → wait for buffer → wait for producer → wait for sink → emit
```

---

### PO-002 — Selection, Not Scheduling

ProgramOutput does not decide **when** frames are emitted. It only decides **what** frame corresponds to the current CT.

- Scheduling authority: TimelineController
- Selection authority: ProgramOutput
- Emission timing: MasterClock

ProgramOutput has no opinion about whether a frame *should* exist at a given CT. It only answers: "Given this CT, what do I emit?"

---

### PO-003 — Pad Is a First-Class Output

Pad frames (black video + silence audio) are **legal, correct, and expected**.

- Pad emission is a successful output, not an error condition
- Pad is always available; it cannot fail to exist
- Pad selection is a valid answer to "what frame for this CT?"

**Constitutional basis:** LAW-OUTPUT-LIVENESS states "if no content → deterministic pad."

---

### PO-004 — No Sink Awareness

ProgramOutput MUST NOT inspect, query, or depend on sink presence.

- Sink absence affects **routing** (OutputBus), not **selection** (ProgramOutput)
- ProgramOutput emits to OutputBus unconditionally
- If no sink is attached, OutputBus handles discard (legally)

**Ownership clarification:** This invariant aligns with INV-P10-SINK-GATE, which gates **destructive dequeue**, not **emission logic**.

---

### PO-005 — No Readiness Gating

ProgramOutput MUST NOT gate emission on:
- Buffer depth
- Producer readiness
- Audio availability
- Mux state
- Bootstrap completion
- Core LIVE declaration

Readiness is someone else's problem. ProgramOutput emits on schedule, every time.

**Exception:** INV-P10-SINK-GATE permits gating **destructive dequeue** (not emission) until routing target exists. This is buffer protection, not emission suppression.

---

### PO-006 — Destructive Dequeue Rules

ProgramOutput MAY destructively dequeue frames from the active buffer only when:
1. A routing target exists (sink attached), OR
2. An explicit discard policy is active

This prevents buffer drain before routing is established. It does NOT gate emission semantics.

**Anchors:** INV-P10-SINK-GATE

---

### PO-007 — Pad Classification Required

Every emitted pad frame MUST be classified with a PadReason:

| PadReason | Meaning |
|-----------|---------|
| BUFFER_TRULY_EMPTY | Buffer depth is 0, producer is starved |
| PRODUCER_GATED | Producer is blocked at flow control gate |
| CT_SLOT_SKIPPED | Frame exists but CT is in the future |
| FRAME_CT_MISMATCH | Frame CT doesn't match expected output CT |
| CONTENT_DEFICIT_FILL | EOF-to-boundary fill (normal, not violation) |
| UNKNOWN | Fallback for unclassified cases (last resort) |

**Anchors:** INV-P10-PAD-REASON (Layer 3 diagnostic)

---

### PO-008 — No Timing Repairs

ProgramOutput MUST NOT:
- Adjust CT
- Skip CT slots
- Reschedule frames
- "Catch up" after missed slots
- Delay emission to wait for "better" frames

**If time and content disagree, time wins.**

CT is authoritative. If the expected frame doesn't exist or doesn't match, emit pad. Never delay the clock.

**Constitutional basis:** LAW-AUTHORITY-HIERARCHY — "Clock authority supersedes frame completion."

---

## 4. Explicit Non-Responsibilities

**ProgramOutput MUST NOT:**

| Forbidden Action | Correct Owner |
|-----------------|---------------|
| Detect underrun or overrun | FrameRingBuffer / Flow Control |
| Decide switch timing | TimelineController / Core |
| Inject silence | MpegTSOutputSink (Phase 9 bootstrap only) |
| Negotiate formats | EncoderPipeline |
| Interpret transport PTS | MpegTSOutputSink |
| Wait for "better" frames | (nobody — forbidden) |
| Retry missed output opportunities | (nobody — forbidden) |
| Query viewer count | (nobody in AIR — Core only) |
| Decide LIVE state | Core (ChannelManager) |

### Forbidden Anti-Patterns (Visual Landmines)

```cpp
// ❌ FORBIDDEN: Sink-gated emission
if (!sink_attached_) return;  // WRONG — emit regardless

// ❌ FORBIDDEN: Blocking on buffer
if (buffer_.empty()) {
    wait_for_frame();  // WRONG — emit pad immediately
}

// ❌ FORBIDDEN: Readiness gating
if (!bootstrap_ready_ || !producer_ready_) {
    return;  // WRONG — emit pad, don't gate
}

// ❌ FORBIDDEN: Timing repairs
if (frame.ct < current_ct_) {
    skip_frame();  // WRONG — log mismatch, emit pad
    catch_up();    // WRONG — never catch up
}

// ❌ FORBIDDEN: Retry logic
while (!emit_succeeded) {
    retry();  // WRONG — emit once, succeed or pad
}
```

**If you see any of these patterns in ProgramOutput, the code is wrong.**

---

## 5. Failure Semantics

| Condition | Action | Classification |
|-----------|--------|----------------|
| No frame at CT | Emit pad | BUFFER_TRULY_EMPTY |
| Frame CT mismatch | Emit pad + log | FRAME_CT_MISMATCH |
| Buffer empty | Emit pad | BUFFER_TRULY_EMPTY |
| Producer gated | Emit pad | PRODUCER_GATED |
| Sink missing | Emit (OutputBus discards) | (not ProgramOutput's concern) |
| Content deficit (EOF before boundary) | Emit pad | CONTENT_DEFICIT_FILL |

**No retries. No delays. No repairs.**

---

## 7. Derivation Notes

| This Contract | Derives From | Relationship |
|---------------|--------------|--------------|
| PO-001 | LAW-OUTPUT-LIVENESS | **Alias** |
| PO-002 | LAW-TIMELINE | **Refines** — selection vs scheduling split |
| PO-003 | LAW-OUTPUT-LIVENESS | **Refines** — pad semantics |
| PO-004 | BROADCAST_CONSTITUTION §6 | **Refines** — sink irrelevance |
| PO-005 | LAW-OUTPUT-LIVENESS | **Operationalizes** — no gating |
| PO-006 | INV-P10-SINK-GATE | **Anchors** |
| PO-007 | INV-P10-PAD-REASON | **Anchors** |
| PO-008 | LAW-AUTHORITY-HIERARCHY | **Operationalizes** — clock wins |

---

## 8. Test Obligations

| Invariant | Test Requirement |
|-----------|-----------------|
| PO-001 | Verify emission occurs every CT tick regardless of buffer state |
| PO-003 | Verify pad emission is classified as success, not error |
| PO-004 | Verify no sink queries in selection path |
| PO-006 | Verify dequeue blocked until routing target exists |
| PO-007 | Verify all pad emissions include PadReason |
| PO-008 | Verify no CT adjustments or delays in selection path |

---

## Cross-References

- [BROADCAST_LAWS.md](../laws/BROADCAST_LAWS.md) — LAW-OUTPUT-LIVENESS, LAW-AUTHORITY-HIERARCHY
- [BROADCAST_CONSTITUTION.MD](../../architecture/BROADCAST_CONSTITUTION.MD) — §5.2 ProgramOutput role
- [CANONICAL_RUNTIME_DATAFLOW.MD](../../architecture/CANONICAL_RUNTIME_DATAFLOW.MD) — §3.4 FrameSelection
- [PHASE10_FLOW_CONTROL.md](../coordination/PHASE10_FLOW_CONTROL.md) — INV-P10-SINK-GATE
- [DIAGNOSTIC_INVARIANTS.md](../diagnostics/DIAGNOSTIC_INVARIANTS.md) — INV-P10-PAD-REASON
