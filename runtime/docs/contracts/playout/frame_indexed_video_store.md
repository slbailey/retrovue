# Contract: Frame-Indexed Video Store (FIVS)

**Classification:** Semantic contract (Layer 1)  
**Parent:** [Frame Selection Alignment](frame_selection_alignment.md) · [INV-HANDOFF-001](../../design/INV-HANDOFF-001-SOURCE-FRAME-TRACE.md)  
**Status:** Contract only — no implementation yet. Tests and implementation must satisfy this contract.

**Methodology:** Contracts define rules → tests enforce rules → implementation satisfies tests.

---

## 1. Purpose

The **Frame-Indexed Video Store (FIVS)** is the component in the playout pipeline that holds decoded video frames and allows them to be retrieved by **source_frame_index** instead of by pop order.

**Responsibilities:**

- **Replaces** the FIFO video buffer: frames are stored and retrieved by index, not by arrival order.
- **Enables** the tick loop to request the exact frame the scheduler has selected for the current output tick.
- **Does not** decide which frame should be emitted; it only stores frames supplied by producers and answers availability/lookup requests.

The **scheduler (tick loop)** is the sole authority for which frame index should be emitted. The store is a passive index: it reports whether a requested frame exists and returns it; it does not advance timeline or choose content. Policy decisions (repeat last frame vs emit PAD when a frame is missing) belong to the tick loop, not to the store.

### Authority Model

The playout system separates responsibilities as follows:

| Component | Responsibility |
|-----------|-----------------|
| **Scheduler (tick loop)** | Determines the authoritative timeline coordinate (selected_src). |
| **Frame Store (FIVS)** | Stores frames indexed by source_frame_index and answers lookup queries. |
| **Producer / Decoder** | Supplies frames to the store. |

- The **scheduler controls time.**
- The **frame store provides indexed access.**
- The **producer supplies frames.**

**No component other than the scheduler may determine which frame index should be emitted.** This prevents future code from accidentally reintroducing FIFO-style behavior.

---

## 2. Definitions

| Term | Definition |
|------|-------------|
| **source_frame_index** | The canonical timeline coordinate for a video frame. A monotonic, segment-relative index assigned when the frame is produced. All frame identity and ordering use this value. |
| **selected_src** | The source_frame_index that the scheduler (tick loop) has determined should be emitted for the current output tick. Computed from wall clock and schedule (e.g. `SourceFrameForTick(output_tick)`). |
| **frame_store** | The Frame-Indexed Video Store: the component that holds frames keyed by source_frame_index and supports lookup by index. |
| **producer** | The component that decodes or generates frames and inserts them into the frame store. May be a file decoder, a programmatic source, or another supplier. |
| **tick loop** | The clock-driven loop that advances output ticks, computes selected_src per tick, requests the corresponding frame from the store, and emits (or applies fallback). |
| **decoder** | The decode path that produces frames; often used interchangeably with “producer” in the context of file-based content. |

**Canonical coordinate:** source_frame_index is the single authoritative identity for a frame in the playout timeline. No other coordinate (PTS, decode order position, buffer slot) defines “which frame” for the purpose of store storage or retrieval.

---

## 3. Core Behavioral Rules

1. **Storage by index**  
   Frames are stored by source_frame_index. Each stored frame is associated with exactly one index at any time.

2. **Out-of-order arrival**  
   Frames may arrive from the producer out of order. The store must accept and retain them by index. Retrieval is by index, not by insertion order.

3. **Retrieval does not remove others**  
   Retrieving a frame for a given index must not remove or invalidate other frames in the store unless an explicit eviction rule applies. (Eviction is defined in Section 7.)

4. **Query by index**  
   The store must support querying whether a specific source_frame_index is present and, if present, returning that frame.

5. **No reordering of indices**  
   The store must not assign or alter source_frame_index. Indices are determined by the producer at insertion. The store does not reorder or reassign indices.

6. **Single frame per index**  
   At any time, at most one frame is stored per source_frame_index. Duplicate indices are handled according to the rules in Section 6 (Decoder Interaction Rules).

7. **Monotonic visibility**  
   Once a frame for index N becomes visible to the store (e.g. after FRAME_STORE_INSERT), a subsequent retrieval request for index N must succeed unless that frame has been explicitly evicted according to Section 7. This prevents frames from “appearing then disappearing” without eviction.

---

## 4. Playout Retrieval Contract

When the tick loop needs a frame for the current tick, it requests the frame for **selected_src** from the store.

**Request:** tick loop requests `frame(selected_src)`.

**Possible outcomes:**

| Outcome | Condition | Store behavior | Caller (tick loop) policy |
|---------|-----------|----------------|---------------------------|
| **A. Frame exists** | Store contains a frame for selected_src | Return that frame | Emit the returned frame. |
| **B. Frame missing, earlier frame exists** | Store does not contain selected_src but contains at least one frame with index &lt; selected_src | Report “not present” for selected_src; optionally expose “latest available index” or “has prior” | Caller may **repeat last frame** (hold previous output). |
| **C. Frame missing, no prior frame** | Store does not contain selected_src and no frame with index &lt; selected_src (or store empty) | Report “not present”; no frame to return | Caller emits **PAD** (e.g. black/silence). |

The **store does not decide policy**. It only provides:

- Whether the requested index is present.
- The frame for that index if present.
- Optionally, information that supports “is there any prior frame?” for caller policy (repeat vs PAD). The contract does not require the store to implement policy; it only requires that the store’s responses allow the tick loop to apply the correct policy.

---

## 5. Alignment Invariant

The store must never cause a **future** frame to be emitted. Alignment is enforced by the tick loop using the store’s responses.

**Invariant (FIVS-ALIGN):**

1. **actual_src_emitted ≤ selected_src**  
   For any tick where content is emitted, the source_frame_index of the emitted frame must not exceed the selected_src for that tick.

2. **If a newly emitted frame originates from the store,** its index must equal selected_src.

3. **If the caller repeats a previously emitted frame,** the index of that frame must be ≤ selected_src.

The **store** must only return a frame when the requested index exists and must never return a frame with index &gt; requested_index. The tick loop is responsible for requesting the correct index (selected_src) and for applying repeat/PAD when the frame is missing.

---

## 6. Decoder Interaction Rules

1. **Producers insert by index**  
   Producers (decoders) insert frames into the store with a source_frame_index. The store accepts the frame and associates it with that index.

2. **Duplicate index policy**  
   The implementation must choose either **A. Replace existing frame** or **B. Reject insertion**. The choice must be **deterministic and documented**. If a frame is inserted with a source_frame_index that already exists in the store, the store applies the chosen policy. The store must not retain two distinct frames for the same index. **Tests must validate the chosen policy.** This prevents “sometimes replace” behavior.

3. **No index reordering**  
   The store must not reorder or reassign source_frame_index. The index is determined by the producer at insertion.

4. **Visibility**  
   Once a frame is successfully inserted, it must be available for retrieval by that index until it is evicted (Section 7) or the store is cleared/reset.

---

## 7. Memory and Eviction Guarantees

1. **Bounded retention**  
   The store may retain only a finite number of frames (or a finite index range). Frames outside the retention window may be **evicted**.

2. **Configurable window**  
   The retention window (e.g. “keep indices in [selected_src − back_margin, selected_src + lookahead]” or “keep at most N frames”) must be configurable. Exact parameters are implementation-defined; the contract requires that such a concept exist so that eviction can be constrained.

3. **Eviction safety**  
   Eviction must **never** remove a frame that may still be requested by the scheduler (tick loop). **Eviction must never remove any frame with index ≥ the minimum requestable index provided by the tick loop.** The tick loop must be able to tell the store what that minimum is; otherwise eviction logic becomes guessy. No frame may be evicted if its index could still be selected_src for a current or future tick in the same session. The contract does not specify the eviction algorithm; it only requires that eviction never violates this guarantee.

4. **Eviction order**  
   When eviction is required, frames that are no longer requestable (e.g. indices strictly below the minimum requestable index) may be evicted. The contract does not require a specific eviction strategy (e.g. oldest-first, lowest-index-first); it only requires that the strategy respect the “never remove a frame that may still be requested” rule.

---

## 8. Failure Modes

Required behavior when exceptional conditions occur. Defined as behavior, not implementation.

| Condition | Required behavior |
|-----------|--------------------|
| **Decoder falls behind** | The requested frame (selected_src) is not in the store. Store reports “not present.” Tick loop applies policy (repeat or PAD). Store does not block; it answers from current contents only. |
| **Requested frame does not exist** | Store reports “not present” for that index. No frame returned. No side effect on other stored frames. |
| **Store is empty** | Any request for a specific index returns “not present.” Tick loop applies PAD (or repeat if it has a prior frame from another source). |
| **Duplicate frames arrive** | Same source_frame_index inserted more than once: store applies the defined duplicate-index policy (replace or reject). After the operation, at most one frame exists for that index. No requirement to prefer first or last; policy must be consistent and documented. |
| **Producer stops or errors** | Store does not invent frames. If no new frames are inserted, the store simply has no new indices. Requests for indices never inserted return “not present.” |
| **Eviction required (store full)** | Store evicts only frames that may not be requested (per Section 7). After eviction, insertion of the new frame succeeds. Eviction must not remove the frame at selected_src or any frame that could still become selected_src. |

---

## 9. Observability

The following diagnostics must be available (e.g. logs or metrics) for debugging and validation. The contract does not specify format or transport (e.g. log lines vs Prometheus); only that these events are observable.

| Event | When | Purpose |
|-------|------|---------|
| **FRAME_STORE_INSERT** | A frame is successfully inserted (index, and optionally size/count). | Confirm producer is supplying frames and at which indices. |
| **FRAME_STORE_HIT** | A request for frame(index) succeeds. | Confirm alignment and that the tick loop is receiving the requested frame. |
| **FRAME_STORE_MISS** | A request for frame(index) is made and the frame is not present. | Detect underflow, decoder lag, or eviction issues. |
| **FRAME_STORE_EVICT** | A frame is evicted (index, and optionally reason/window). | Verify eviction only removes safe indices; diagnose capacity pressure. |
| **FRAME_STORE_LOOKAHEAD** | On request or periodically: requested index and highest available index (e.g. `requested=150 max_available=172`). | Diagnose decode-behind: how far ahead the decoder is relative to what the tick loop needs. |

Optional: **FRAME_STORE_DUPLICATE** (or equivalent) when the duplicate-index policy is triggered (replace or reject), to distinguish from normal insert.

Observability must not alter the semantics of the store (e.g. logging must not change hit/miss behavior).

---

## 10. Required Tests

The following contract tests must exist. Each test must correspond to a rule or invariant in this document. Tests prove compliance; implementation must satisfy the tests.

| Test | Rule / invariant | Description |
|------|-------------------|-------------|
| **test_retrieve_exact_frame** | §3 Storage by index; §4 Outcome A | Request frame(selected_src) when that index is stored; store returns that frame and no other. |
| **test_retrieve_missing_frame** | §4 Outcomes B, C | Request frame(selected_src) when index is not present; store reports not present; no frame returned. |
| **test_no_future_frame_emission** | §5 FIVS-ALIGN | For a request frame(selected_src), the store never returns a frame with index &gt; selected_src. Tick loop test: actual_src_emitted ≤ selected_src for every tick. |
| **test_decoder_ahead_frames_available** | §3 Out-of-order; §4 | Producer inserts frames for indices ahead of current selected_src; store retains them; request for selected_src when present returns correct frame. |
| **test_decoder_behind_frame_missing** | §8 Decoder falls behind | selected_src is beyond the highest index in the store; request returns not present; tick loop can apply repeat or PAD. |
| **test_out_of_order_insert_retrieve** | §3 Out-of-order arrival | Insert frames in non-sequential order; retrieve by index; each retrieval returns the frame for that index. |
| **test_retrieval_does_not_remove_others** | §3 Retrieval does not remove others | Insert frames at indices A, B, C; retrieve B; A and C remain available for retrieval (unless eviction applies). |
| **test_duplicate_index_policy** | §6 Duplicate index policy | Insert two frames with same index; after policy applied, at most one frame for that index; behavior consistent with documented policy. |
| **test_eviction_never_removes_requestable** | §7 Eviction safety | Configure store with finite capacity; cause eviction; verify no evicted frame has index ≥ minimum requestable (e.g. selected_src − back_margin). |
| **test_retrieve_after_eviction_boundary** | §7 Eviction safety | Insert frames [100..200]; set selected_src = 150; evict frames &lt; 140. Verify: frame 150 still retrievable; frame 140 retrievable; frame 139 not retrievable. Protects the eviction boundary. |
| **test_store_empty_returns_not_present** | §8 Store is empty | Store has no frames; any request returns not present. |
| **test_observability_events** | §9 Observability | For insert, hit, miss, evict, lookahead (and optionally duplicate), trigger the condition and verify the corresponding diagnostic is emitted. |

---

## Summary: Invariants the Implementation Must Satisfy

1. **FIVS-ALIGN:** actual_src_emitted ≤ selected_src; newly emitted frame from store has index == selected_src; repeated frame has index ≤ selected_src. The store only returns a frame when the requested index exists and never returns a frame with index &gt; requested_index.

2. **Storage by index:** Frames are stored and retrieved only by source_frame_index; one logical frame per index.

3. **Out-of-order:** Frames may be inserted in any order; retrieval is by index only.

4. **Retrieval non-destructive:** Retrieving one index does not remove other frames except where eviction applies.

5. **Eviction safety:** Eviction never removes a frame that may still be requested by the tick loop.

6. **No policy in store:** The store reports presence/absence and returns frames; it does not decide repeat vs PAD.

7. **Duplicate policy:** Implementation chooses either replace or reject; choice is deterministic and documented; tests validate the chosen policy.

8. **Observability:** FRAME_STORE_INSERT, FRAME_STORE_HIT, FRAME_STORE_MISS, FRAME_STORE_EVICT, FRAME_STORE_LOOKAHEAD (and optionally duplicate) are emitted as specified.

Implementation and data structures (e.g. map, sliding window, lock discipline) are out of scope for this contract; they must be chosen so that all of the above invariants and tests are satisfied.
