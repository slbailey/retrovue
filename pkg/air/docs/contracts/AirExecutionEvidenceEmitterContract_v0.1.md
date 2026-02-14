# AirExecutionEvidenceEmitterContract_v0.1

**Classification:** Contract (AIR Internal + Integration)  
**Owner:** AIR Runtime (PipelineManager / BlockPlan Execution Layer)  
**Enforcement Phase:** During Playout Execution  
**Created:** 2026-02-13  
**Status:** Proposed

---

> **This contract is *authoritative* for how the AIR subsystem emits execution evidence during channel playout.**  
> It legally binds the C++ runtime’s emission logic to deterministic, truthful, and coordinated output at architectural seam boundaries.

**Location:**  
`pkg/air/docs/contracts/AirExecutionEvidenceEmitterContract_v0.1.md`  
(Companion to INV-SEAM and fence invariant contracts.)

---

## 1. Purpose

This contract governs emission by AIR of all execution evidence events required by:

- [AirExecutionEvidenceInterfaceContract_v0.1](coordination/AirExecutionEvidenceInterfaceContract_v0.1.md)
- [ExecutionEvidenceToAsRunMappingContract_v0.1](../core/ExecutionEvidenceToAsRunMappingContract_v0.1.md)

**AIR is the *sole execution truth authority*.**

It ensures that:

- **Evidence is emitted exactly once** at the correct lifecycle boundaries
- **Fence invariants are upheld**
- **Evidence does not drift** relative to wall-clock authority
- **Emission is deterministic and replay-safe**

---

## 2. Emission Authority Boundary

**Evidence emission is restricted to specific AIR runtime transitions:**

| **Lifecycle Moment**            | **Event Type**     |
|----------------------------------|-------------------|
| Block swap committed             | `BLOCK_START`     |
| Segment actually begins emission | `SEGMENT_START` (*optional*) |
| Segment ceases emission          | `SEGMENT_END`     |
| Fence tick closes block          | `BLOCK_FENCE`     |
| Pipeline fatal termination       | `CHANNEL_TERMINATED` |

*No other component may emit evidence events. No synthetic emission paths permitted.*

---

## 3. BLOCK_START Emission Rules

- **AIR-EMIT-001 — Single Emission:**  
  Exactly **one** `BLOCK_START` event MUST be emitted per block activation.<br>
  _Emission timing:_
  - Immediately after `TAKE` commit
  - Before first frame of new block is emitted

- **AIR-EMIT-002 — Fence Consistency:**  
  `swap_tick` and `fence_tick` in `BLOCK_START` MUST match [INV-BLOCK-WALLCLOCK-FENCE-001]: the actual fence tick scheduled for the block.

- **AIR-EMIT-003 — Priming Truth:**  
  `primed_success` MUST *truly* reflect actual priming result, never inferred or “optimistic”.

---

## 4. SEGMENT Emission Rules

- **AIR-EMIT-004 — Segment Identity:**  
  `event_id_ref` MUST match the `EVENT_ID` from TransmissionLog for the segment in execution.  
  _No synthetic or placeholder IDs permitted._

- **AIR-EMIT-005 — No Duplicate SegmentEnd:**  
  Exactly **one** `SEGMENT_END` event MUST be emitted per segment  
  _(unless the segment never emitted frames and was skipped, in which case a `status=SKIPPED` event MUST still be emitted)._

- **AIR-EMIT-006 — Duration Authority:**  
  `actual_duration_ms` MUST be derived from actual frames emitted × frame duration, **not** schedule duration.

---

## 5. BLOCK_FENCE Emission Rules

- **AIR-EMIT-007 — Single Fence:**  
  Exactly **one** `BLOCK_FENCE` event per block, emitted when fence tick fires and output transitions to next block.

- **AIR-EMIT-008 — Frame Count Truth:**  
  `total_frames_emitted` MUST reflect actual output for the block.

- **AIR-EMIT-009 — Early Exhaustion Truth:**  
  `early_exhaustion=true` **only if** content ended before fence, and pad/fallback was required.

- **AIR-EMIT-010 — Truncated by Fence Truth:**  
  `truncated_by_fence=true` **only if** a segment was forcibly cut at the fence.

---

## 6. CHANNEL_TERMINATED Emission Rules

- **AIR-EMIT-011 — Fatal Termination:**  
  If playout pipeline encounters unrecoverable error:  
   - Emit `CHANNEL_TERMINATED` evidence before shutdown if runtime permits.  
   - If crash prevents emission: ChannelManager must detect EOF and handle per [AirExecutionEvidenceInterfaceContract_v0.1].

---

## 7. Ordering and Sequence Integrity

- **AIR-EMIT-012 — Monotonic Sequence:**  
  The `sequence` field MUST increase *strictly* by +1 for each evidence event.

- **AIR-EMIT-013 — No Interleaving:**  
  Evidence **for a single channel** MUST NOT interleave across playout sessions.  
  _i.e., a new `playout_session_id` MUST reset `sequence` to 1._

---

## 8. Timing Authority

- **AIR-EMIT-014 — UTC Truth Source:**  
  All UTC timestamps MUST originate from AIR’s *authoritative output clock* (never from wall/system clock drift).  
  (Use the same clock as fence scheduling.)

- **AIR-EMIT-015 — Fence Alignment:**  
  `actual_end_utc` of `BLOCK_FENCE` MUST equal:  
  _BlockStart UTC_ + _scheduled block duration_ ±1 frame tolerance.

---

## 9. Failure and Edge Case Emission

- **AIR-EMIT-016 — Segment Open at Fence:**  
  If a fence triggers while a segment is active:
    - Emit `SEGMENT_END`:
      - `status=TRUNCATED`
      - `reason=FENCE_TERMINATION`
    - Then emit `BLOCK_FENCE`.

- **AIR-EMIT-017 — Asset Decode Failure:**  
  If decoder fails mid-segment:
    - Emit `SEGMENT_END`:
      - `status=ERROR`
      - `reason=DECODE_ERROR`
    - Continue with fallback logic if defined.

---

## 10. Required AIR Tests

>The following tests MUST exist and pass in `pkg/air` test suite.  
> **These validate correct, legal evidence emission, independent of Core.**

- BlockStart emission test
- Segment emission lifecycle test
- Fence emission correctness test
- Early exhaustion emission test
- Truncated-by-fence emission test
- Fatal termination emission test
- Sequence monotonicity test
- No duplicate SegmentEnd test

---

## 11. Contractual Dependencies

- [AirExecutionEvidenceInterfaceContract_v0.1](./AirExecutionEvidenceInterfaceContract_v0.1.md):  
  Defines the wire-format, machine-parseable evidence protocol.
- [ExecutionEvidenceToAsRunMappingContract_v0.1](../core/ExecutionEvidenceToAsRunMappingContract_v0.1.md):  
  Defines transformation of execution evidence into persistent As-Run artifacts.
- [AsRunLogArtifactContract (v0.2)](../../../docs/contracts/artifacts/AsRunLogArtifactContract.md):  
  Specifies artifact/persistence file format.
- *See also*: INV-SEAM, fence invariants (`INV-BLOCK-WALLCLOCK-FENCE-001`, etc.)

---

**This contract makes AIR runtime fully responsible for correct, deterministic, fence-aligned emission of execution evidence at all legal boundaries.**